# UVSS Edge Service

Self-contained detection service for an edge computer. Copy this folder across,
install, run, and point your own frontend at it.

**No dependency on the training project** — just Python and a few pip packages.

---

## What it does

* Streams live video from a camera
* On a **START** signal: begins AI detection and records a clip
* Detects each person (or vehicle), tracks them, and keeps their **best 5
  images** — a cropped view *and* the whole frame with boxes drawn
* On **STOP**: finalises the clip and results
* START/STOP come from HTTP, so a ROS node, a sensor, a GPIO pin or a button in
  your UI can all drive it

---

## 1. Install

**Windows**

```
install.bat
```

**Linux**

```bash
chmod +x install.sh run.sh
./install.sh
```

Needs **Python 3.10–3.12**. The installer creates a `.venv` and pulls the
dependencies. On Windows it also swaps in DirectML for GPU inference (roughly
5× faster than CPU; works on any DirectX 12 GPU with no CUDA setup).

For an NVIDIA box on Linux:

```bash
./.venv/bin/python -m pip uninstall -y onnxruntime
./.venv/bin/python -m pip install onnxruntime-gpu
```

---

## 2. Run

```
run.bat                 (Windows)
./run.sh                (Linux)
```

Then check it is alive:

```
http://localhost:8000/api/status
```

A reference dashboard is served at `http://localhost:8000` — useful for
verifying the camera before you wire up your own page.

### Common options

```bash
run.bat --source 1                       # second camera
run.bat --source rtsp://cam/stream       # IP camera
run.bat --classes Vehicles               # cars/trucks/buses/motorcycles/bicycles
run.bat --classes all
run.bat --conf 0.25 --top-k 8
run.bat --port 9000
run.bat --cors-origins http://my-site:3000
```

---

## 3. Wire up your frontend

**Start here: [INTEGRATION.md](INTEGRATION.md)** — step-by-step for connecting
an existing website, with React / Vue / plain-HTML snippets and the gotchas
(HTTPS mixed content, CORS, firewall).

**[API.md](API.md)** is the full endpoint reference.

The short version:

```html
<!-- live video: no player library needed -->
<img id="feed" src="http://EDGE_IP:8000/api/stream">

<script src="examples/uvss-client.js"></script>
<script>
  const uvss = new UvssClient("http://EDGE_IP:8000");

  uvss.on("status",  s => { /* fps, gpu, camera health */ });
  uvss.on("person",  p => { /* p.images -> [{crop, full, score}] */ });
  uvss.on("stopped", s => { /* s.clip_url -> the recorded clip */ });

  uvss.connect();
  uvss.start("ui");   // or POST /api/session/start from anywhere
</script>
```

`examples/integration-example.html` is a complete working page you can open
directly and crib from.

CORS is open by default so a page on any origin can call the service. Restrict
it with `--cors-origins` once you know where your frontend is hosted.

---

## 4. Triggering from ROS / a sensor

```bash
# ROS 2 (source your ROS setup first) — std_msgs/Bool: True=start, False=stop
python ros_bridge.py --mode ros2 --topic /uvss/session_active

# ROS 1
python ros_bridge.py --mode ros1 --topic /uvss/session_active

# Raspberry Pi GPIO, HIGH = active
python ros_bridge.py --mode gpio --pin 17

# Serial device emitting START / STOP lines
python ros_bridge.py --mode serial --port /dev/ttyUSB0

# No hardware yet — toggles every 15 s so you can watch it work
python ros_bridge.py --mode test
```

Add `--server http://EDGE_IP:8000` if the bridge runs on a different machine.

Or skip the bridge entirely — anything that can POST works:

```bash
curl -X POST "http://EDGE_IP:8000/api/session/start?trigger=radar"
```

---

## 5. Output on disk

```
sessions/
└── 20260806_125205_09ba/
    ├── clip.mp4              includes ~3 s recorded BEFORE the trigger
    ├── session.json
    └── images/
        └── person_1/
            ├── crop/  q0.724_f45.jpg  …   subject cut out
            └── full/  q0.724_f45.jpg  …   whole frame, boxes drawn
```

Filenames encode quality and frame number — sort descending for best-first.
Images are written as they are captured, so a crash never loses what was
already seen.

---

## 6. Folder contents

| Path | What it is |
| --- | --- |
| `server.py` | The service |
| `src/` | Detector, tracker, quality scoring |
| `models/` | The ONNX model it runs |
| `configs/` | Thresholds and tuning |
| `static/` | Reference dashboard (optional) |
| `examples/` | JS client + working integration page |
| `ros_bridge.py` | ROS / GPIO / serial trigger bridge |
| `API.md` | **Full API contract** |
| `sessions/` | Output, created at runtime |

---

## 7. Troubleshooting

**Camera blank** — another process holds it. Check `/api/status` for `camera_ok`
and `error`.

**Frontend gets CORS errors** — start with
`--cors-origins http://your-frontend-origin`, or leave the default `*`.

**Low FPS** — check `providers` in `/api/status`. If there is no `Dml` or `CUDA`
entry it is running on CPU; install `onnxruntime-directml` (or
`onnxruntime-gpu`). Also try `--width 960 --height 540`.

**Clip missing** — the console logs a VideoWriter failure. The service uses
`mp4v`, which every OpenCV build supports.

**Nothing detected** — check the `classes` field in `/api/status`, and lower
`--conf` for distant subjects.
