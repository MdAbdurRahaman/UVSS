/* UVSS edge dashboard.
 *
 * Two channels from the server:
 *   /api/stream  MJPEG, rendered straight into <img>
 *   /ws          JSON events: status ticks, session start/stop, new persons
 *
 * The WebSocket auto-reconnects, because an edge box on a wall display must
 * survive the server restarting without someone walking over to hit F5.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const el = {
    state: $("pill-state"), model: $("pill-model"), accel: $("pill-accel"),
    fps: $("pill-fps"), infer: $("pill-infer"), conn: $("pill-conn"),
    detectHint: $("detect-hint"),
    overlay: $("video-overlay"), rec: $("rec-badge"),
    btnStart: $("btn-start"), btnStop: $("btn-stop"),
    metaId: $("meta-id"), metaElapsed: $("meta-elapsed"),
    metaFrames: $("meta-frames"), metaTrigger: $("meta-trigger"),
    people: $("people"), peopleEmpty: $("people-empty"),
    personCount: $("person-count"),
    clipPanel: $("clip-panel"), clipPlayer: $("clip-player"),
    clipHint: $("clip-hint"), clipDownload: $("clip-download"),
    history: $("history"),
    lightbox: $("lightbox"), lightboxImg: $("lightbox-img"),
    lightboxCap: $("lightbox-caption"), lightboxClose: $("lightbox-close"),
    lbCrop: $("lb-crop"), lbFull: $("lb-full"),
    lightboxDownload: $("lightbox-download"),
    toast: $("toast"),
  };

  let active = false;
  let startedAt = null;
  const persons = new Map();   // key -> person payload

  // ---------------------------------------------------------------- toast --
  let toastTimer = null;
  function toast(msg, isError = false) {
    el.toast.textContent = msg;
    el.toast.classList.toggle("err", !!isError);
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.toast.hidden = true; }, 3200);
  }

  // ------------------------------------------------------------- controls --
  async function post(path, trigger) {
    try {
      const r = await fetch(`${path}?trigger=${encodeURIComponent(trigger)}`,
                            { method: "POST" });
      const data = await r.json();
      if (!data.ok) toast(data.reason || "request refused", true);
      return data;
    } catch (err) {
      toast(`request failed: ${err}`, true);
      return null;
    }
  }

  const startSession = () => { if (!active) post("/api/session/start", "manual-key"); };
  const stopSession  = () => { if (active)  post("/api/session/stop",  "manual-key"); };

  el.btnStart.addEventListener("click", startSession);
  el.btnStop.addEventListener("click", stopSession);

  // Debug hotkeys: S = start, X = stop. Ignored while typing in a field.
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || e.metaKey || e.ctrlKey) return;
    const k = e.key.toLowerCase();
    if (k === "s") { e.preventDefault(); startSession(); }
    else if (k === "x") { e.preventDefault(); stopSession(); }
    else if (k === "escape") closeLightbox();
  });

  // ------------------------------------------------------------ rendering --
  function setActive(on, session) {
    active = on;
    el.btnStart.disabled = on;
    el.btnStop.disabled = !on;
    el.overlay.hidden = on;
    el.rec.classList.toggle("on", on);
    el.state.textContent = on ? "RECORDING" : "IDLE";
    el.state.className = "pill " + (on ? "live" : "idle");

    if (on && session) {
      startedAt = Date.now();
      el.metaId.textContent = session.id;
      el.metaTrigger.textContent = session.trigger || "—";
    } else if (!on) {
      startedAt = null;
    }
  }

  function renderPersons() {
    const list = [...persons.values()].sort((a, b) => b.best_score - a.best_score);
    el.personCount.textContent = list.length;

    if (!list.length) {
      el.people.innerHTML = "";
      el.people.appendChild(el.peopleEmpty);
      el.peopleEmpty.hidden = false;
      return;
    }
    el.peopleEmpty.hidden = true;

    const tile = (p, img, i, kind) => {
      const url = kind === "full" ? img.full : img.crop;
      if (!url) return `<div class="shot empty-shot"></div>`;
      const cap = `${p.class_name} #${p.identity} — rank ${i + 1} · Q ${img.score}`;
      return `
        <div class="shot" data-crop="${img.crop}" data-full="${img.full || ""}"
             data-kind="${kind}" data-cap="${cap}">
          <img src="${url}" alt="" loading="lazy">
          <span class="rank">${i + 1}</span>
        </div>`;
    };

    el.people.innerHTML = list.map((p) => {
      const imgs = p.images || [];
      const pad = Math.max(0, 5 - imgs.length);
      const blanks = Array.from({ length: pad },
                                () => `<div class="shot empty-shot"></div>`).join("");
      const crops = imgs.map((im, i) => tile(p, im, i, "crop")).join("") + blanks;
      const fulls = imgs.map((im, i) => tile(p, im, i, "full")).join("") + blanks;
      return `
        <div class="person">
          <div class="person-head">
            <span class="person-id">#${p.identity}</span>
            <span class="person-class">${p.class_name}</span>
            <span class="person-score">best Q ${p.best_score.toFixed(3)}</span>
          </div>
          <div class="row-label">cropped</div>
          <div class="shots">${crops}</div>
          <div class="row-label">whole frame</div>
          <div class="shots">${fulls}</div>
        </div>`;
    }).join("");

    el.people.querySelectorAll(".shot[data-crop]").forEach((node) => {
      node.addEventListener("click", () =>
        openLightbox(node.dataset.crop, node.dataset.full,
                     node.dataset.cap, node.dataset.kind));
    });
  }

  function renderHistory(history) {
    if (!history || !history.length) return;
    el.history.innerHTML = history.map((s) => `
      <div class="hist-item" data-id="${s.id}" data-clip="${s.clip_url || ""}">
        <span class="hist-when">${s.started_at || s.id}</span>
        <span class="hist-stats">${s.person_count} subj · ${s.duration}s</span>
      </div>`).join("");

    el.history.querySelectorAll(".hist-item").forEach((node) => {
      node.addEventListener("click", () => {
        const clip = node.dataset.clip;
        if (!clip) { toast("no clip recorded for that session"); return; }
        showClip(clip, node.dataset.id);
      });
    });
  }

  function showClip(url, id) {
    el.clipPanel.hidden = false;
    el.clipPlayer.src = url;
    el.clipDownload.href = url;
    el.clipDownload.setAttribute("download", `${id}.mp4`);
    el.clipHint.textContent = id;
    el.clipPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // ------------------------------------------------------------ lightbox --
  let lbCrop = "", lbFull = "", lbKind = "crop";

  function paintLightbox() {
    const url = lbKind === "full" && lbFull ? lbFull : lbCrop;
    el.lightboxImg.src = url;
    el.lbCrop.classList.toggle("active", lbKind === "crop");
    el.lbFull.classList.toggle("active", lbKind === "full");
    el.lbFull.disabled = !lbFull;
    el.lightboxDownload.href = url;
  }

  function openLightbox(crop, full, caption, kind = "crop") {
    lbCrop = crop || "";
    lbFull = full || "";
    lbKind = (kind === "full" && lbFull) ? "full" : "crop";
    el.lightboxCap.textContent = caption || "";
    paintLightbox();
    el.lightbox.hidden = false;
  }

  function closeLightbox() { el.lightbox.hidden = true; el.lightboxImg.src = ""; }

  el.lbCrop.addEventListener("click", () => { lbKind = "crop"; paintLightbox(); });
  el.lbFull.addEventListener("click", () => {
    if (lbFull) { lbKind = "full"; paintLightbox(); }
  });
  el.lightboxClose.addEventListener("click", closeLightbox);
  el.lightbox.addEventListener("click", (e) => {
    if (e.target === el.lightbox) closeLightbox();
  });

  // -------------------------------------------------------------- status --
  function applyStatus(st) {
    el.model.textContent = st.model || "—";
    el.fps.textContent = `${st.fps} FPS`;
    el.infer.textContent = `${st.infer_ms} ms`;

    const prov = (st.providers || []).join(", ");
    const gpu = /CUDA|Dml/i.test(prov);
    el.accel.textContent = gpu ? "GPU" : "CPU";
    el.accel.className = "pill " + (gpu ? "good" : "dim");

    el.detectHint.textContent = "detecting: " +
      (Array.isArray(st.classes) ? st.classes.join(", ") : st.classes);

    if (st.error) toast(st.error, true);

    const s = st.session;
    if (s && !active) {
      setActive(true, s);
      persons.clear();
      (s.persons || []).forEach((p) => persons.set(p.identity, p));
      renderPersons();
    } else if (!s && active) {
      setActive(false, null);
    }
    if (s) {
      el.metaFrames.textContent = s.frames;
      el.metaId.textContent = s.id;
      el.metaTrigger.textContent = s.trigger || "—";
    }
    renderHistory(st.history);
  }

  // Local ticker so elapsed time is smooth between 1 Hz status pushes.
  setInterval(() => {
    if (active && startedAt) {
      el.metaElapsed.textContent =
        ((Date.now() - startedAt) / 1000).toFixed(1) + " s";
    }
  }, 100);

  // ------------------------------------------------------------ websocket --
  let ws = null, retry = 1000;

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
      retry = 1000;
      el.conn.textContent = "connected";
      el.conn.className = "pill good";
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }

      if (msg.type === "status") {
        applyStatus(msg.status);
      } else if (msg.type === "session_started") {
        persons.clear();
        renderPersons();
        setActive(true, msg.session);
        el.clipPanel.hidden = true;
        toast(`session started (${msg.session.trigger})`);
      } else if (msg.type === "session_stopped") {
        setActive(false, null);
        const s = msg.session;
        toast(`session stopped — ${s.person_count} subject(s), ${s.duration}s`);
        if (s.clip_url) showClip(s.clip_url, s.id);
      } else if (msg.type === "person") {
        persons.set(msg.person.identity, msg.person);
        renderPersons();
      }
    };

    const drop = () => {
      el.conn.textContent = "reconnecting…";
      el.conn.className = "pill dim";
      // Back off to 8 s so a server restart doesn't get hammered.
      setTimeout(connect, retry);
      retry = Math.min(retry * 1.6, 8000);
    };
    ws.onclose = drop;
    ws.onerror = () => { try { ws.close(); } catch {} };
  }

  connect();

  // If the MJPEG stream drops (server restart), nudge it back.
  const stream = $("stream");
  stream.addEventListener("error", () => {
    setTimeout(() => { stream.src = "/api/stream?t=" + Date.now(); }, 1500);
  });
})();
