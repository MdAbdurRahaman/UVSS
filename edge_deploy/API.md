# UVSS Edge Service — API reference

Everything your frontend needs. The service is plain HTTP + WebSocket, so it
works with React, Vue, Angular, or a hand-written page.

Base URL below is assumed to be `http://EDGE_IP:8000`.

---

## Quick shape of it

| What you want | How |
| --- | --- |
| Live video | `<img src="http://EDGE_IP:8000/api/stream">` |
| Start / stop detection | `POST /api/session/start` · `/api/session/stop` |
| Live status + detections | WebSocket `ws://EDGE_IP:8000/ws` |
| Detected people + images | From the WebSocket, or `GET /api/status` |
| Recorded clip | `GET /clips/{session_id}.mp4` |

CORS is enabled (`*` by default), so a page served from any origin can call
this. Lock it down with `--cors-origins http://your-site` in production.

---

## 1. Live video

```html
<img id="feed" src="http://EDGE_IP:8000/api/stream" alt="live">
```

That is the whole integration. The endpoint returns
`multipart/x-mixed-replace`, an MJPEG stream the browser renders natively — no
player library, no WebRTC signalling, no codec setup.

The stream runs whether or not a session is active. While a session runs, boxes
and labels are drawn on it and a red `REC` marker appears.

If the service restarts, the `<img>` errors — reload it:

```js
feed.addEventListener("error", () => {
  setTimeout(() => { feed.src = "http://EDGE_IP:8000/api/stream?t=" + Date.now(); }, 1500);
});
```

---

## 2. Start / stop a session

A session is one START→STOP cycle. Detection, best-image capture and clip
recording all happen only inside one.

```
POST /api/session/start?trigger=<label>
POST /api/session/stop?trigger=<label>
```

`trigger` is a free-text label stored with the session so you can tell later
what started it (`ros`, `radar`, `manual`, `gate-sensor`…).

```js
await fetch("http://EDGE_IP:8000/api/session/start?trigger=ui", { method: "POST" });
```

**Response**

```json
{
  "ok": true,
  "session": {
    "id": "20260806_125205_09ba",
    "started_at": "2026-08-06T12:52:05",
    "trigger": "ui",
    "active": true,
    "frames": 0,
    "person_count": 0,
    "persons": []
  }
}
```

On refusal (a session is already running, or none is running to stop):

```json
{ "ok": false, "reason": "a session is already running" }
```

> The clip includes ~3 s recorded **before** the start signal. A physical
> trigger always fires slightly late, so a ring buffer keeps the approach.

---

## 3. Live events (WebSocket)

```js
const ws = new WebSocket("ws://EDGE_IP:8000/ws");
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  switch (msg.type) {
    case "status":           /* every 1 s */            break;
    case "session_started":  /* someone hit START */    break;
    case "session_stopped":  /* clip + results ready */ break;
    case "person":           /* a subject's images changed */ break;
  }
};
```

### `status` — pushed once per second

```json
{
  "type": "status",
  "status": {
    "camera_ok": true,
    "error": null,
    "fps": 28.4,
    "infer_ms": 7.2,
    "detections": 2,
    "model": "yolov8n-coco.onnx",
    "backend": "onnxruntime",
    "providers": ["DmlExecutionProvider", "CPUExecutionProvider"],
    "classes": ["person"],
    "conf": 0.35,
    "session": { /* the active session, or null */ },
    "history": [ /* recent completed sessions */ ]
  }
}
```

`providers` containing `Dml` or `CUDA` means it is running on the GPU.

### `person` — a subject was detected or improved

```json
{
  "type": "person",
  "session_id": "20260806_125205_09ba",
  "person": {
    "track_id": 1,
    "identity": "1",
    "class_name": "person",
    "best_score": 0.724,
    "first_seen": 1.2,
    "last_seen": 6.8,
    "images": [
      {
        "crop":  "/session-files/20260806_125205_09ba/images/person_1/crop/q0.724_f45.jpg",
        "full":  "/session-files/20260806_125205_09ba/images/person_1/full/q0.724_f45.jpg",
        "score": 0.724
      }
    ]
  }
}
```

Each entry has **two images**:

* `crop` — the subject cut out of the frame
* `full` — the whole frame with bounding boxes drawn

Up to 5 per subject (configurable with `--top-k`), best first. Prefix the paths
with the service origin to load them.

`identity` is the display label. Usually it equals `track_id`, but if the
tracker swaps two people mid-session, an appearance check splits them and you
get `"1"` and `"1b"` — so one card never mixes two people.

### `session_stopped`

```json
{
  "type": "session_stopped",
  "session": {
    "id": "20260806_125205_09ba",
    "duration": 10.5,
    "frames": 210,
    "person_count": 2,
    "clip_url": "/clips/20260806_125205_09ba.mp4",
    "persons": [ /* full list with images */ ]
  }
}
```

**Reconnect on drop** — an edge display must survive a service restart:

```js
function connect() {
  const ws = new WebSocket("ws://EDGE_IP:8000/ws");
  ws.onmessage = handle;
  ws.onclose = () => setTimeout(connect, 2000);
}
```

---

## 4. REST endpoints

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/status` | Same object as the `status` event |
| `GET` | `/api/sessions` | `{ active, history[] }` |
| `POST` | `/api/session/start?trigger=x` | `{ ok, session }` |
| `POST` | `/api/session/stop?trigger=x` | `{ ok, session }` |
| `GET` | `/api/stream` | MJPEG video |
| `GET` | `/clips/{id}.mp4` | Recorded clip |
| `GET` | `/session-files/...` | Saved images |

Polling `/api/status` works if you would rather not use the WebSocket, but you
lose the instant push when a person appears.

---

## 5. Triggering from ROS or a sensor

Anything that can make an HTTP POST can drive this:

```bash
curl -X POST "http://EDGE_IP:8000/api/session/start?trigger=radar"
```

`ros_bridge.py` ships with the package and converts a topic or pin into those
calls (`std_msgs/Bool`: True = start, False = stop):

```bash
python ros_bridge.py --mode ros2 --topic /uvss/session_active --server http://EDGE_IP:8000
python ros_bridge.py --mode ros1 --topic /uvss/session_active
python ros_bridge.py --mode gpio --pin 17
python ros_bridge.py --mode serial --port /dev/ttyUSB0 --baud 115200
python ros_bridge.py --mode test          # no hardware; toggles on a timer
```

It debounces and only acts on state *changes*, so a chattering sensor cannot
spam the API.

---

## 6. Drop-in client

`examples/uvss-client.js` wraps all of the above:

```html
<script src="uvss-client.js"></script>
<script>
const uvss = new UvssClient("http://EDGE_IP:8000");

uvss.on("status",  (s) => { /* fps, gpu, camera health */ });
uvss.on("person",  (p) => { /* render p.images: {crop, full, score} */ });
uvss.on("started", (s) => { /* show REC */ });
uvss.on("stopped", (s) => { /* play s.clip_url */ });

uvss.connect();
document.querySelector("#feed").src = uvss.streamUrl();

uvss.start("ui");
uvss.stop("ui");
</script>
```

It handles reconnection, URL prefixing and error reporting. See
`examples/integration-example.html` for a working page.

---

## 7. On-disk layout

```
sessions/
└── 20260806_125205_09ba/
    ├── clip.mp4
    ├── session.json
    └── images/
        └── person_1/
            ├── crop/  q0.724_f45.jpg   ...
            └── full/  q0.724_f45.jpg   ...
```

Filenames encode quality and frame number, so sorting descending gives
best-first. Images are written the moment they are captured, not at session
end — if the service dies mid-run, what it already saw is on disk.

---

## 8. Server options

```bash
python server.py --help

--host 0.0.0.0            # reachable on the LAN (default)
--port 8000
--source 0                # camera index, file, or rtsp:// URL
--model models/best.onnx
--classes person          # or Vehicles, all, or car,truck
--conf 0.35
--top-k 5                 # best images per subject
--width 1280 --height 720
--cors-origins http://your-site:3000
```
