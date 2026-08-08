#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
web/server.py
=============
Edge service: camera -> detection -> web dashboard.

Runs on the edge computer and serves a browser dashboard showing

  * the live video feed
  * a recorded clip for each START -> STOP session
  * every person detected in that session, with their best 5 images

START/STOP come from HTTP endpoints, so the trigger source is pluggable:
a ROS node, a GPIO sensor, a PLC, or the keyboard (for debugging) all POST to
the same place. The service itself has no ROS dependency.

Design notes
------------
* The camera thread runs ALWAYS so the live feed works while idle; detection,
  tracking and clip recording only run while a session is active.
* A ring buffer holds the last few seconds of frames. A physical trigger always
  fires slightly *after* the interesting moment starts, so the clip is written
  with that pre-roll prepended.
* Video is streamed as MJPEG (`multipart/x-mixed-replace`). It needs no
  signalling, no codecs and no plugins — an `<img>` tag renders it. WebRTC would
  cut latency further at a large complexity cost; on a LAN edge box that trade
  is not worth it.
* State changes and new detections are pushed over a WebSocket rather than
  polled, so the dashboard updates the instant something happens.

Run
---
    python web/server.py
    python web/server.py --host 0.0.0.0 --port 8000 --source 0
    python web/server.py --model models/coco/yolov8n-coco.onnx --classes person
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Two supported layouts:
#   training project : <root>/web/server.py   with <root>/src/
#   deployed package : <root>/server.py       with <root>/src/
# Detect which by looking for src/ next to the script before going up a level.
_HERE = Path(__file__).resolve().parent
ROOT = _HERE if (_HERE / "src").is_dir() else _HERE.parent
IS_PACKAGE = (_HERE / "src").is_dir()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np


def _fatal(msg: str, hint: str = "") -> None:
    print(f"\n[x] {msg}", file=sys.stderr)
    if hint:
        print(f"    {hint}", file=sys.stderr)
    sys.exit(1)


try:
    import cv2
except ImportError:
    _fatal("OpenCV is not installed.", "pip install opencv-python")

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                                   StreamingResponse)
    from fastapi.staticfiles import StaticFiles
except ImportError:
    _fatal("FastAPI is not installed.",
           "pip install fastapi uvicorn[standard]")

try:
    import uvicorn
except ImportError:
    _fatal("uvicorn is not installed.", "pip install uvicorn[standard]")

from src.detector import FaceDetector
from src.quality import BestImageGallery
from src.tracker import FaceTracker
from src.utils import (box_iou, color_for_id, find_default_model,
                       list_available_models, load_inference_config,
                       open_camera, resolve_class_group)

# --------------------------------------------------------------------------- #
SESSIONS_DIR = ROOT / ("sessions" if IS_PACKAGE else "web_sessions")
STATIC_DIR = _HERE / "static"
JPEG_QUALITY = 80
RING_SECONDS = 3.0          # pre-roll kept before a START trigger

# Which browser origins may call this API. "*" is the sane default for a
# private edge device on a closed network; narrow it with --cors-origins when
# the box is reachable from somewhere less trusted.
CORS_ORIGINS: list[str] = ["*"]


# --------------------------------------------------------------------------- #
# Session bookkeeping
# --------------------------------------------------------------------------- #
@dataclass
class PersonRecord:
    """One tracked subject in a session, with its best images."""
    track_id: int
    identity: str
    class_name: str
    # One entry per kept shot: {"crop": url, "full": url|None, "score": float}
    images: list[dict] = field(default_factory=list)
    best_score: float = 0.0
    first_seen: float = 0.0
    last_seen: float = 0.0

    def to_json(self) -> dict:
        return {
            "track_id": self.track_id,
            "identity": self.identity,
            "class_name": self.class_name,
            "images": self.images,
            "best_score": round(self.best_score, 3),
            "first_seen": round(self.first_seen, 2),
            "last_seen": round(self.last_seen, 2),
        }


@dataclass
class Session:
    """One START -> STOP cycle."""
    id: str
    started_at: float
    trigger: str                       # who started it
    stopped_at: float | None = None
    stop_trigger: str | None = None
    clip_path: Path | None = None
    frames: int = 0
    persons: dict[int, PersonRecord] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        end = self.stopped_at if self.stopped_at is not None else time.time()
        return max(end - self.started_at, 0.0)

    @property
    def active(self) -> bool:
        return self.stopped_at is None

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "started_at": datetime.fromtimestamp(self.started_at).isoformat(
                timespec="seconds"),
            "stopped_at": (datetime.fromtimestamp(self.stopped_at).isoformat(
                timespec="seconds") if self.stopped_at else None),
            "trigger": self.trigger,
            "stop_trigger": self.stop_trigger,
            "duration": round(self.duration, 1),
            "active": self.active,
            "frames": self.frames,
            "clip_url": (f"/clips/{self.id}.mp4"
                         if self.clip_path and self.clip_path.exists() else None),
            "person_count": len(self.persons),
            "persons": [p.to_json() for p in sorted(
                self.persons.values(), key=lambda x: -x.best_score)],
        }


# --------------------------------------------------------------------------- #
# The edge engine
# --------------------------------------------------------------------------- #
class EdgeEngine:
    """
    Camera capture + inference + session recording, on one worker thread.

    Thread-safety: `_lock` guards everything the web layer reads (latest frame,
    current session, stats). The web layer never mutates engine state directly —
    it calls start_session()/stop_session(), which take the same lock.
    """

    def __init__(self, model: Path, source: Any = 0, conf: float = 0.35,
                 iou: float = 0.45, classes: set[int] | None = None,
                 top_k: int = 5, width: int = 1280, height: int = 720) -> None:
        self.source = source
        self.width, self.height = width, height
        self.conf, self.iou = conf, iou

        cfg = load_inference_config()
        self.detector = FaceDetector(model, conf=conf, iou=iou)
        self.detector.set_classes(classes)
        self.tracker_cfg = cfg.get("tracker", {})
        self.quality_cfg = dict(cfg.get("quality", {}))
        self.quality_cfg["top_k_per_track"] = int(top_k)

        self.tracker: FaceTracker | None = None
        self.gallery: BestImageGallery | None = None

        # `_lock` guards shared state and is held only for quick assignments.
        # Clip writing is disk I/O, so it gets its own lock — holding `_lock`
        # across a VideoWriter.write() would stall every API call for the
        # duration of the write, once per frame.
        self._lock = threading.Lock()
        self._writer_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._latest_jpeg: bytes | None = None
        self._latest_raw: np.ndarray | None = None
        self._ring: deque[np.ndarray] = deque(maxlen=1)
        self._writer: Any = None
        self._fps = 0.0
        self._infer_ms = 0.0
        self._frame_index = 0
        self._live_detections = 0
        self._camera_ok = False
        self._error: str | None = None

        self.session: Session | None = None
        self.history: list[Session] = []

        # Filled in by the app so the worker can push events to browsers.
        self.event_sink: Any = None

        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="EdgeEngine")
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._close_writer()

    # -- public state -------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            s = self.session
            return {
                "camera_ok": self._camera_ok,
                "error": self._error,
                "fps": round(self._fps, 1),
                "infer_ms": round(self._infer_ms, 1),
                "detections": self._live_detections,
                "model": self.detector.weights.name,
                "backend": self.detector.backend_name,
                "providers": self.detector.providers,
                "classes": (sorted(self.detector.class_name(c)
                                   for c in self.detector.classes)
                            if self.detector.classes else "all"),
                "conf": round(self.conf, 2),
                "session": s.to_json() if s else None,
                "history": [h.to_json() for h in reversed(self.history[-20:])],
            }

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    # -- session control ----------------------------------------------------
    def start_session(self, trigger: str = "manual") -> dict:
        with self._lock:
            if self.session is not None:
                return {"ok": False, "reason": "a session is already running",
                        "session": self.session.to_json()}

        # Build the per-session objects BEFORE taking the lock. Constructing a
        # FaceTracker imports supervision/trackers on first use, which can take
        # seconds — doing that under `_lock` would stall the camera thread and
        # every API call with it.
        sid = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + \
            uuid.uuid4().hex[:4]
        sess = Session(id=sid, started_at=time.time(), trigger=trigger)
        sdir = SESSIONS_DIR / sid
        (sdir / "images").mkdir(parents=True, exist_ok=True)
        sess.clip_path = sdir / "clip.mp4"

        # Fresh tracker + gallery per session so IDs restart at 1 and one
        # session's subjects never leak into the next.
        tracker = FaceTracker(config=self.tracker_cfg)
        gallery = BestImageGallery(config=self.quality_cfg)
        gallery.enable_autosave(out_dir=sdir / "images", session_subdir=False)

        with self._lock:
            if self.session is not None:      # raced with another START
                return {"ok": False, "reason": "a session is already running",
                        "session": self.session.to_json()}
            self.tracker = tracker
            self.gallery = gallery

            fps = self._fps if self._fps > 1 else 20.0
            preroll = list(self._ring)
            if preroll:
                h, w = preroll[-1].shape[:2]
            elif self._latest_raw is not None:
                h, w = self._latest_raw.shape[:2]
            else:
                h, w = self.height, self.width

            self.session = sess
            self._frame_index = 0

        # Opening the writer and flushing the pre-roll are disk I/O — do them
        # outside `_lock` so the camera thread is not blocked meanwhile.
        self._open_writer(sess.clip_path, fps, (w, h))
        for frame in preroll:
            if frame.shape[1] == w and frame.shape[0] == h:
                self._write_frame(frame)
                sess.frames += 1

        self._emit({"type": "session_started", "session": sess.to_json()})
        return {"ok": True, "session": sess.to_json()}

    def stop_session(self, trigger: str = "manual") -> dict:
        with self._lock:
            sess = self.session
            if sess is None:
                return {"ok": False, "reason": "no session is running"}
            sess.stopped_at = time.time()
            sess.stop_trigger = trigger
            self._close_writer()
            if self.gallery is not None:
                try:
                    self.gallery._write_summary()
                except Exception:  # noqa: BLE001
                    pass
            self.session = None
            self.history.append(sess)
            self.tracker = None
            self.gallery = None

        self._save_session_json(sess)
        self._emit({"type": "session_stopped", "session": sess.to_json()})
        return {"ok": True, "session": sess.to_json()}

    # -- worker -------------------------------------------------------------
    def _run(self) -> None:
        cap = None
        try:
            cap = self._open_source()
            if cap is None:
                with self._lock:
                    self._error = f"could not open source: {self.source}"
                return
            with self._lock:
                self._camera_ok = True

            times: deque[float] = deque(maxlen=30)
            last = time.perf_counter()

            while not self._stop.is_set():
                got, frame = cap.read()
                if not got or frame is None:
                    time.sleep(0.02)
                    continue

                now = time.perf_counter()
                times.append(now - last)
                last = now
                fps = len(times) / max(sum(times), 1e-6)

                with self._lock:
                    self._fps = fps
                    if self._ring.maxlen != max(int(fps * RING_SECONDS), 5):
                        self._ring = deque(self._ring,
                                           maxlen=max(int(fps * RING_SECONDS), 5))
                    self._ring.append(frame.copy())
                    active = self.session is not None

                annotated = frame
                if active:
                    annotated = self._process(frame)

                ok_, buf = cv2.imencode(
                    ".jpg", annotated,
                    [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                if ok_:
                    with self._lock:
                        self._latest_jpeg = buf.tobytes()
                        self._latest_raw = annotated

        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"
            import traceback
            traceback.print_exc()
        finally:
            if cap is not None:
                cap.release()
            self._close_writer()

    def _open_source(self):
        src = self.source
        if isinstance(src, int) or (isinstance(src, str) and str(src).isdigit()):
            return open_camera(int(src), self.width, self.height)
        cap = cv2.VideoCapture(str(src))
        return cap if cap.isOpened() else None

    def _process(self, frame: np.ndarray) -> np.ndarray:
        """Detect + track + collect best images, and record the clip frame."""
        det = self.detector.detect(frame, conf=self.conf, iou=self.iou)
        with self._lock:
            tracker, gallery, sess = self.tracker, self.gallery, self.session
        if tracker is None or gallery is None or sess is None:
            return frame

        tracked = tracker.update(det)
        class_ids = self._recover_class_ids(tracked, det)

        self._frame_index += 1
        scores = gallery.update(frame, tracked, self._frame_index,
                                class_ids=class_ids,
                                class_names=self.detector.class_names)

        annotated = self._annotate(frame, tracked, scores, class_ids)

        # Give each newly-kept record the annotated whole frame it came from,
        # so every best shot has both a crop and a full view with boxes drawn.
        gallery.attach_context(annotated, self._frame_index)

        with self._lock:
            self._infer_ms = det.inference_ms
            self._live_detections = len(tracked)
            sess.frames += 1
        self._write_frame(annotated)      # disk I/O, outside `_lock`

        self._sync_persons(sess, gallery)
        return annotated

    @staticmethod
    def _recover_class_ids(tracked: Any, det: Any) -> np.ndarray:
        """Trackers drop class ids; re-attach them by IoU to the detections."""
        n = len(tracked)
        if n == 0 or len(det) == 0:
            return np.zeros(n, dtype=np.int32)
        try:
            iou = box_iou(np.asarray(tracked.boxes, dtype=np.float32),
                          np.asarray(det.boxes, dtype=np.float32))
            return np.asarray(det.class_ids, dtype=np.int32)[iou.argmax(axis=1)]
        except Exception:  # noqa: BLE001
            return np.zeros(n, dtype=np.int32)

    def _annotate(self, frame: np.ndarray, tracked: Any, scores: list[float],
                  class_ids: np.ndarray) -> np.ndarray:
        out = frame.copy()
        multiclass = self.detector.is_multiclass
        for i in range(len(tracked)):
            x1, y1, x2, y2 = (int(v) for v in tracked.boxes[i][:4])
            tid = int(tracked.track_ids[i])
            cid = int(class_ids[i]) if i < len(class_ids) else 0
            colour = color_for_id(cid if multiclass else tid)
            cv2.rectangle(out, (x1, y1), (x2, y2), colour, 2)

            bits = []
            if multiclass:
                bits.append(self.detector.class_name(cid))
            bits.append(f"#{tid}")
            bits.append(f"{float(tracked.scores[i]):.2f}")
            if i < len(scores):
                bits.append(f"Q{scores[i]:.2f}")
            label = "  ".join(bits)

            (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                             0.5, 1)
            ty = y1 - 6 if y1 - th - base - 6 > 0 else y2 + th + base + 6
            cv2.rectangle(out, (x1, ty - th - base - 2), (x1 + tw + 8, ty + 2),
                          colour, -1)
            cv2.putText(out, label, (x1 + 4, ty - base),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (10, 10, 10), 1,
                        cv2.LINE_AA)

        cv2.putText(out, "REC", (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 0, 255), 2, cv2.LINE_AA)
        cv2.circle(out, (100, 27), 8, (0, 0, 255), -1)
        return out

    def _sync_persons(self, sess: Session, gallery: BestImageGallery) -> None:
        """Mirror the gallery into the session and push changes to browsers."""
        changed = []
        now = time.time()
        for gid in gallery.track_ids():
            recs = gallery.get(gid)
            if not recs:
                continue
            def _url(path: Path | None) -> str | None:
                if path is None:
                    return None
                try:
                    return ("/session-files/"
                            + path.relative_to(SESSIONS_DIR).as_posix())
                except ValueError:
                    return None

            urls = []
            for rec in recs:
                crop_url = _url(rec.saved_path)
                if crop_url is None:
                    continue
                urls.append({"crop": crop_url,
                             "full": _url(rec.saved_full_path),
                             "score": round(rec.score, 3)})

            person = sess.persons.get(gid)
            if person is None:
                person = PersonRecord(track_id=gid,
                                      identity=gallery.label_for(gid),
                                      class_name=recs[0].class_name,
                                      first_seen=now - sess.started_at)
                sess.persons[gid] = person
            if urls != person.images or recs[0].score != person.best_score:
                person.images = urls
                person.best_score = recs[0].score
                person.last_seen = now - sess.started_at
                changed.append(person)

        for p in changed:
            self._emit({"type": "person", "person": p.to_json(),
                        "session_id": sess.id})

    # -- clip writing -------------------------------------------------------
    def _open_writer(self, path: Path, fps: float, size: tuple[int, int]) -> None:
        with self._writer_lock:
            self._close_writer_locked()
            w, h = size
            # mp4v is universally available in OpenCV builds; avc1/H.264 often
            # is not, and a silent VideoWriter failure produces a 0-byte clip.
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(path), fourcc,
                                     max(float(fps), 5.0), (w, h))
            if not writer.isOpened():
                print(f"  [!] could not open clip writer for {path}")
                writer = None
            self._writer = writer

    def _write_frame(self, frame: np.ndarray) -> None:
        with self._writer_lock:
            if self._writer is None:
                return
            try:
                self._writer.write(frame)
            except Exception:  # noqa: BLE001
                pass

    def _close_writer_locked(self) -> None:
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:  # noqa: BLE001
                pass
            self._writer = None

    def _close_writer(self) -> None:
        with self._writer_lock:
            self._close_writer_locked()

    def _save_session_json(self, sess: Session) -> None:
        try:
            path = SESSIONS_DIR / sess.id / "session.json"
            path.write_text(json.dumps(sess.to_json(), indent=2),
                            encoding="utf-8")
        except OSError:
            pass

    # -- events -------------------------------------------------------------
    def _emit(self, payload: dict) -> None:
        if self.event_sink is not None:
            try:
                self.event_sink(payload)
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- #
# Web layer
# --------------------------------------------------------------------------- #
class Hub:
    """Fan-out of engine events to every connected browser."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def _send(self, payload: dict) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def publish(self, payload: dict) -> None:
        """Called from the worker THREAD; hops onto the asyncio loop."""
        if self.loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send(payload), self.loop)
        except Exception:  # noqa: BLE001
            pass


def build_app(engine: EdgeEngine) -> FastAPI:
    hub = Hub()
    engine.event_sink = hub.publish

    # Lifespan rather than the deprecated @app.on_event hooks, which FastAPI
    # will remove. The camera thread starts once the loop exists, because the
    # hub needs a running loop to marshal worker events onto.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        hub.loop = asyncio.get_running_loop()
        engine.start()
        try:
            yield
        finally:
            engine.shutdown()

    app = FastAPI(title="UVSS Edge Detection", lifespan=lifespan)

    # CORS: the dashboard bundled here is served from the same origin, but the
    # whole point of this service is that ANY frontend can drive it — typically
    # one served from a different host or port. Without this, the browser
    # blocks every fetch()/WebSocket from that page.
    try:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    except ImportError:
        pass

    # ---- pages ----
    @app.get("/", response_class=HTMLResponse)
    async def index() -> Any:
        page = STATIC_DIR / "index.html"
        if not page.exists():
            return HTMLResponse("<h1>static/index.html is missing</h1>",
                                status_code=500)
        return HTMLResponse(page.read_text(encoding="utf-8"))

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)),
                  name="static")
    app.mount("/session-files", StaticFiles(directory=str(SESSIONS_DIR)),
              name="session-files")

    # ---- live video ----
    @app.get("/api/stream")
    async def stream() -> Any:
        boundary = "frame"

        async def gen():
            while True:
                jpeg = engine.latest_jpeg()
                if jpeg is not None:
                    yield (b"--" + boundary.encode() + b"\r\n"
                           b"Content-Type: image/jpeg\r\n"
                           b"Content-Length: " + str(len(jpeg)).encode() +
                           b"\r\n\r\n" + jpeg + b"\r\n")
                await asyncio.sleep(0.03)          # ~30 fps cap

        return StreamingResponse(
            gen(),
            media_type=f"multipart/x-mixed-replace; boundary={boundary}")

    # ---- control ----
    # NOTE: these are plain `def`, not `async def`, on purpose. They acquire a
    # threading.Lock shared with the camera worker, and a blocking call inside
    # an `async def` handler stalls the whole event loop — which would freeze
    # the MJPEG stream and every WebSocket at the same time. Declaring them
    # `def` makes FastAPI run them in a threadpool instead.
    @app.post("/api/session/start")
    def session_start(trigger: str = "manual") -> Any:
        return JSONResponse(engine.start_session(trigger))

    @app.post("/api/session/stop")
    def session_stop(trigger: str = "manual") -> Any:
        return JSONResponse(engine.stop_session(trigger))

    @app.get("/api/status")
    def status() -> Any:
        return JSONResponse(engine.status())

    @app.get("/api/sessions")
    def sessions() -> Any:
        return JSONResponse({
            "active": engine.session.to_json() if engine.session else None,
            "history": [s.to_json() for s in reversed(engine.history)],
        })

    @app.get("/clips/{session_id}.mp4")
    async def clip(session_id: str) -> Any:
        path = SESSIONS_DIR / session_id / "clip.mp4"
        if not path.exists():
            return JSONResponse({"error": "clip not found"}, status_code=404)
        return FileResponse(path, media_type="video/mp4",
                            filename=f"{session_id}.mp4")

    # ---- events ----
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await hub.connect(ws)
        # engine.status() takes the worker's lock, so run it off the event loop.
        get_status = lambda: asyncio.to_thread(engine.status)  # noqa: E731
        try:
            await ws.send_json({"type": "status", "status": await get_status()})
            while True:
                # Periodic status keeps FPS/detection counters live even when
                # nothing else is happening, and doubles as a keepalive.
                await asyncio.sleep(1.0)
                await ws.send_json({"type": "status",
                                    "status": await get_status()})
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            hub.disconnect(ws)

    return app


# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="UVSS edge detection service + web dashboard.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--host", default="0.0.0.0",
                   help="0.0.0.0 exposes it on the network (default)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--source", default="0",
                   help="camera index, video file or RTSP URL")
    p.add_argument("--model", default=None,
                   help="path to a .onnx/.pt model (default: auto-discover)")
    p.add_argument("--classes", default="person",
                   help="'person', 'Vehicles', 'all', or comma-separated names")
    p.add_argument("--conf", type=float, default=0.35)
    p.add_argument("--iou", type=float, default=0.45)
    p.add_argument("--top-k", type=int, default=1,
                   help="best images kept per subject (1 best face crop + full frame)")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--cors-origins", default="*",
                   help="comma-separated origins allowed to call the API, "
                        "e.g. http://my-site:3000 (default: * )")
    return p.parse_args()


def resolve_classes(spec: str, detector_names: list[str]) -> set[int] | None:
    spec = (spec or "").strip()
    if not spec or spec.lower() == "all":
        return None
    group = resolve_class_group(spec, detector_names)
    if group:
        return group
    lower = [n.lower() for n in detector_names]
    out: set[int] = set()
    for tok in spec.split(","):
        tok = tok.strip().lower()
        if not tok:
            continue
        if tok.isdigit():
            out.add(int(tok))
        elif tok in lower:
            out.add(lower.index(tok))
        else:
            print(f"  [!] unknown class '{tok}' — ignored")
    return out or None


def main() -> int:
    global CORS_ORIGINS
    args = parse_args()
    CORS_ORIGINS = [o.strip() for o in args.cors_origins.split(",") if o.strip()] \
        or ["*"]

    model = Path(args.model) if args.model else None
    if model is not None and not model.is_absolute():
        model = ROOT / model
    if model is None:
        model = find_default_model()
    if model is None:
        available = list_available_models()
        model = available[0] if available else None
    if model is None:
        _fatal("No model found.",
               "Train one, or pass --model models/coco/yolov8n-coco.onnx")

    print("\n" + "=" * 70)
    print("UVSS EDGE DETECTION SERVICE")
    print("=" * 70)

    probe = FaceDetector(model)
    classes = resolve_classes(args.classes, probe.class_names)
    shown = (", ".join(sorted(probe.class_name(c) for c in classes))
             if classes else "all classes")
    print(f"  model    : {probe.describe()}")
    print(f"  detecting: {shown}")
    print(f"  source   : {args.source}")
    print(f"  best-K   : {args.top_k} images per subject")
    del probe

    source: Any = int(args.source) if str(args.source).isdigit() else args.source
    engine = EdgeEngine(model, source=source, conf=args.conf, iou=args.iou,
                        classes=classes, top_k=args.top_k,
                        width=args.width, height=args.height)
    app = build_app(engine)

    shown_host = "localhost" if args.host in ("0.0.0.0", "") else args.host
    print(f"\n  dashboard: http://{shown_host}:{args.port}")
    if args.host == "0.0.0.0":
        print(f"  on the LAN: http://<this-machine-ip>:{args.port}")
    print(f"\n  triggers:")
    print(f"    POST http://{shown_host}:{args.port}/api/session/start?trigger=ros")
    print(f"    POST http://{shown_host}:{args.port}/api/session/stop?trigger=ros")
    print(f"    or press S / X in the dashboard\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
