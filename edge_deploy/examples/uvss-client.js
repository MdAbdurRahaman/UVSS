/*!
 * uvss-client.js — drop-in client for the UVSS edge service.
 *
 * Handles the WebSocket lifecycle (including reconnection), prefixes relative
 * media URLs with the service origin, and exposes the session controls.
 *
 *   const uvss = new UvssClient("http://192.168.1.50:8000");
 *   uvss.on("person", (p) => console.log(p.identity, p.images));
 *   uvss.connect();
 *   document.querySelector("#feed").src = uvss.streamUrl();
 *
 * No dependencies. Works as a <script> tag, CommonJS or ES module.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.UvssClient = factory();
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  class UvssClient {
    /**
     * @param {string} baseUrl e.g. "http://192.168.1.50:8000".
     *                         Defaults to the page's own origin.
     * @param {object} [opts]  { autoReconnect=true, maxBackoff=8000 }
     */
    constructor(baseUrl, opts = {}) {
      this.base = (baseUrl || window.location.origin).replace(/\/+$/, "");
      this.autoReconnect = opts.autoReconnect !== false;
      this.maxBackoff = opts.maxBackoff || 8000;

      this._handlers = Object.create(null);
      this._ws = null;
      this._backoff = 1000;
      this._closedByUs = false;

      this.status = null;      // last status payload
      this.session = null;     // active session, or null
      this.persons = new Map();// identity -> person
    }

    // ---------------------------------------------------------- events --
    /** Events: status, person, started, stopped, open, close, error */
    on(event, fn) {
      (this._handlers[event] = this._handlers[event] || []).push(fn);
      return this;
    }

    off(event, fn) {
      const list = this._handlers[event];
      if (list) this._handlers[event] = list.filter((f) => f !== fn);
      return this;
    }

    _emit(event, payload) {
      (this._handlers[event] || []).forEach((fn) => {
        try { fn(payload); } catch (err) { console.error("[uvss]", err); }
      });
    }

    // ------------------------------------------------------------- urls --
    /** MJPEG live feed — assign straight to an <img> src. */
    streamUrl() { return `${this.base}/api/stream`; }

    /** Turn a relative path from the API into a loadable absolute URL. */
    url(path) {
      if (!path) return null;
      return /^https?:\/\//i.test(path) ? path : this.base + path;
    }

    /** Absolute {crop, full} URLs for one image entry. */
    imageUrls(image) {
      if (!image) return { crop: null, full: null, score: 0 };
      return {
        crop: this.url(image.crop),
        full: this.url(image.full),
        score: image.score,
      };
    }

    // -------------------------------------------------------- websocket --
    connect() {
      this._closedByUs = false;
      const wsBase = this.base.replace(/^http/i, "ws");
      let ws;
      try {
        ws = new WebSocket(`${wsBase}/ws`);
      } catch (err) {
        this._emit("error", err);
        this._scheduleReconnect();
        return this;
      }
      this._ws = ws;

      ws.onopen = () => {
        this._backoff = 1000;
        this._emit("open");
      };

      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }

        if (msg.type === "status") {
          this.status = msg.status;
          this.session = msg.status.session;
          this._emit("status", msg.status);
        } else if (msg.type === "session_started") {
          this.persons.clear();
          this.session = msg.session;
          this._emit("started", msg.session);
        } else if (msg.type === "session_stopped") {
          this.session = null;
          this._emit("stopped", msg.session);
        } else if (msg.type === "person") {
          this.persons.set(msg.person.identity, msg.person);
          this._emit("person", msg.person);
        }
      };

      ws.onerror = (err) => this._emit("error", err);
      ws.onclose = () => {
        this._emit("close");
        if (!this._closedByUs) this._scheduleReconnect();
      };
      return this;
    }

    disconnect() {
      this._closedByUs = true;
      if (this._ws) { try { this._ws.close(); } catch {} }
      this._ws = null;
    }

    _scheduleReconnect() {
      if (!this.autoReconnect) return;
      setTimeout(() => this.connect(), this._backoff);
      this._backoff = Math.min(this._backoff * 1.6, this.maxBackoff);
    }

    // ---------------------------------------------------------- control --
    async _post(path, trigger) {
      const res = await fetch(
        `${this.base}${path}?trigger=${encodeURIComponent(trigger)}`,
        { method: "POST" });
      return res.json();
    }

    /** Begin a session. `trigger` is a label stored with it. */
    start(trigger = "ui") { return this._post("/api/session/start", trigger); }

    /** End the running session. */
    stop(trigger = "ui") { return this._post("/api/session/stop", trigger); }

    /** Full state, without waiting for the next WebSocket tick. */
    async getStatus() {
      const r = await fetch(`${this.base}/api/status`);
      return r.json();
    }

    /** Active session plus completed history. */
    async getSessions() {
      const r = await fetch(`${this.base}/api/sessions`);
      return r.json();
    }

    /** Playable/downloadable clip URL for a session id. */
    clipUrl(sessionId) { return `${this.base}/clips/${sessionId}.mp4`; }

    // ----------------------------------------------------------- helpers --
    /** True when inference is running on a GPU. */
    isGpu() {
      const p = (this.status && this.status.providers) || [];
      return p.some((x) => /CUDA|Dml|CoreML/i.test(x));
    }

    /** Subjects sorted best-first. */
    people() {
      return [...this.persons.values()]
        .sort((a, b) => b.best_score - a.best_score);
    }
  }

  return UvssClient;
}));
