#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
src/utils.py
============
Shared helpers for the inference stack: project paths, config loading, model
discovery, letterboxing, NMS, box maths, drawing and an FPS meter.

Nothing here imports torch — the GUI can run on an ONNX-only install.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

# --------------------------------------------------------------------------- #
# Project paths
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
CONFIG_PATH = ROOT / "configs" / "train_config.yaml"
DATASETS_DIR = ROOT / "datasets"
DEFAULT_SAVE_DIR = ROOT / "best_faces"

MODEL_EXTS = (".onnx", ".pt", ".torchscript")


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
DEFAULT_INFERENCE: dict[str, Any] = {
    "conf_threshold": 0.35,
    "iou_threshold": 0.45,
    "imgsz": 640,
    "max_detections": 100,
    "tracker": {
        "type": "bytetrack",
        "track_activation_threshold": 0.30,
        "lost_track_buffer": 45,
        "minimum_matching_threshold": 0.85,
        "frame_rate": 30,
    },
    "quality": {
        "top_k_per_track": 5,
        "weights": {"sharpness": 0.35, "size": 0.25,
                    "confidence": 0.25, "frontality": 0.15},
        "min_face_px": 40,
        "min_improvement": 0.02,
        "cooldown_frames": 3,
        "save_dir": "best_images",
        "crop_margin": 0.20,
        "appearance_split": True,
        "appearance_threshold": 0.62,
    },
}


def load_inference_config(path: Path | None = None) -> dict[str, Any]:
    """Read the `inference:` block of train_config.yaml, merged over defaults."""
    import copy

    cfg = copy.deepcopy(DEFAULT_INFERENCE)
    path = path or CONFIG_PATH
    if not path.exists():
        return cfg
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:  # noqa: BLE001 — a missing/broken config must not crash the GUI
        return cfg

    user = data.get("inference", {}) or {}

    def merge(base: dict, over: dict) -> dict:
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                merge(base[k], v)
            else:
                base[k] = v
        return base

    return merge(cfg, user)


# --------------------------------------------------------------------------- #
# Model discovery
# --------------------------------------------------------------------------- #
# Smallest plausible model file. Anything below this is a truncated or
# interrupted download, not a model — auto-loading it produces a confusing
# "Protobuf parsing failed" dialog at startup instead of a clean "no model yet".
MIN_MODEL_BYTES = 256 * 1024


def is_usable_model(path: Path) -> bool:
    """True if `path` looks like a real, complete model file."""
    try:
        return (path.is_file()
                and path.suffix.lower() in MODEL_EXTS
                and path.stat().st_size >= MIN_MODEL_BYTES)
    except OSError:
        return False


def find_default_model(models_dir: Path | None = None) -> Path | None:
    """
    Pick a model to load at startup.

    Preference order — ONNX beats PyTorch because the GUI then needs no torch:
        models/best.onnx > models/best.pt > any *.onnx > any *.pt
        > newest runs/train/*/weights/best.pt

    Truncated files are skipped (see `MIN_MODEL_BYTES`).
    """
    models_dir = models_dir or MODELS_DIR
    if models_dir.exists():
        for name in ("best.onnx", "best.pt", "last.onnx", "last.pt"):
            p = models_dir / name
            if is_usable_model(p):
                return p
        for ext in (".onnx", ".pt"):
            hits = sorted(p for p in models_dir.glob(f"*{ext}")
                          if is_usable_model(p))
            if hits:
                return hits[0]

    runs = ROOT / "runs" / "train"
    if runs.exists():
        hits = sorted((p for p in runs.glob("*/weights/best.pt")
                       if is_usable_model(p)),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if hits:
            return hits[0]
    return None


def list_available_models(models_dir: Path | None = None) -> list[Path]:
    """Every loadable model file the project knows about, newest first."""
    models_dir = models_dir or MODELS_DIR
    out: list[Path] = []
    if models_dir.exists():
        out += [p for p in models_dir.iterdir() if is_usable_model(p)]
        # Subfolders too, so alternative models (e.g. models/coco/) are
        # selectable in the GUI. `find_default_model` deliberately does NOT
        # look here, so dropping a COCO model in cannot shadow best.onnx.
        for sub in sorted(p for p in models_dir.iterdir() if p.is_dir()):
            out += [p for p in sorted(sub.iterdir()) if is_usable_model(p)]
    runs = ROOT / "runs" / "train"
    if runs.exists():
        out += [p for p in runs.glob("*/weights/*.pt") if is_usable_model(p)]
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            uniq.append(p)
    uniq.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return uniq


# --------------------------------------------------------------------------- #
# Pre-processing
# --------------------------------------------------------------------------- #
def letterbox(image: np.ndarray, new_shape: int | tuple[int, int] = 640,
              color: tuple[int, int, int] = (114, 114, 114),
              scaleup: bool = True) -> tuple[np.ndarray, float, tuple[float, float]]:
    """
    Resize with unchanged aspect ratio, padding to `new_shape`.

    Returns (padded_image, ratio, (pad_w, pad_h)). The pad values are the
    *left/top* padding, which is what `scale_boxes` needs to invert the mapping.
    """
    import cv2

    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    h, w = image.shape[:2]
    r = min(new_shape[0] / h, new_shape[1] / w)
    if not scaleup:
        r = min(r, 1.0)

    new_unpad = (int(round(w * r)), int(round(h * r)))
    dw = (new_shape[1] - new_unpad[0]) / 2.0
    dh = (new_shape[0] - new_unpad[1]) / 2.0

    if (w, h) != new_unpad:
        image = cv2.resize(image, new_unpad, interpolation=cv2.INTER_LINEAR)

    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    image = cv2.copyMakeBorder(image, top, bottom, left, right,
                               cv2.BORDER_CONSTANT, value=color)
    return image, r, (dw, dh)


def scale_boxes(boxes: np.ndarray, ratio: float, pad: tuple[float, float],
                orig_shape: tuple[int, int]) -> np.ndarray:
    """Map xyxy boxes from letterboxed space back to original image space."""
    if boxes.size == 0:
        return boxes
    out = boxes.astype(np.float32).copy()
    out[:, [0, 2]] -= pad[0]
    out[:, [1, 3]] -= pad[1]
    out /= max(ratio, 1e-9)
    h, w = orig_shape[:2]
    out[:, [0, 2]] = out[:, [0, 2]].clip(0, w - 1)
    out[:, [1, 3]] = out[:, [1, 3]].clip(0, h - 1)
    return out


# --------------------------------------------------------------------------- #
# Box maths
# --------------------------------------------------------------------------- #
def xywh2xyxy(x: np.ndarray) -> np.ndarray:
    """(cx, cy, w, h) -> (x1, y1, x2, y2)."""
    y = np.empty_like(x, dtype=np.float32)
    half_w = x[..., 2] / 2.0
    half_h = x[..., 3] / 2.0
    y[..., 0] = x[..., 0] - half_w
    y[..., 1] = x[..., 1] - half_h
    y[..., 2] = x[..., 0] + half_w
    y[..., 3] = x[..., 1] + half_h
    return y


def box_iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU between two sets of xyxy boxes -> (len(a), len(b))."""
    if a.size == 0 or b.size == 0:
        return np.zeros((len(a), len(b)), dtype=np.float32)
    a = a.astype(np.float32)
    b = b.astype(np.float32)

    area_a = np.clip(a[:, 2] - a[:, 0], 0, None) * np.clip(a[:, 3] - a[:, 1], 0, None)
    area_b = np.clip(b[:, 2] - b[:, 0], 0, None) * np.clip(b[:, 3] - b[:, 1], 0, None)

    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:4], b[None, :, 2:4])
    wh = np.clip(rb - lt, 0, None)
    inter = wh[..., 0] * wh[..., 1]

    union = area_a[:, None] + area_b[None, :] - inter
    return inter / np.maximum(union, 1e-9)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float = 0.45,
        max_det: int = 300) -> np.ndarray:
    """
    Greedy non-maximum suppression. Returns the kept indices, score-descending.

    Uses cv2.dnn.NMSBoxes when OpenCV is importable (C++ speed), else a vectorised
    numpy fallback.
    """
    if boxes.size == 0:
        return np.empty((0,), dtype=np.int32)

    try:
        import cv2

        wh_boxes = boxes.copy().astype(np.float32)
        wh_boxes[:, 2] -= wh_boxes[:, 0]
        wh_boxes[:, 3] -= wh_boxes[:, 1]
        idx = cv2.dnn.NMSBoxes(wh_boxes.tolist(), scores.astype(np.float32).tolist(),
                               score_threshold=0.0, nms_threshold=float(iou_threshold))
        if idx is None or len(idx) == 0:
            return np.empty((0,), dtype=np.int32)
        return np.asarray(idx, dtype=np.int32).reshape(-1)[:max_det]
    except Exception:  # noqa: BLE001 — fall through to the numpy implementation
        pass

    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0 and len(keep) < max_det:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        ious = box_iou(boxes[i:i + 1], boxes[order[1:]])[0]
        order = order[1:][ious <= iou_threshold]
    return np.asarray(keep, dtype=np.int32)


def expand_box(box: Sequence[float], margin: float, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    """Grow an xyxy box by `margin` (fraction of its size), clipped to `shape`."""
    x1, y1, x2, y2 = box[:4]
    w = x2 - x1
    h = y2 - y1
    x1 -= w * margin / 2.0
    x2 += w * margin / 2.0
    y1 -= h * margin / 2.0
    y2 += h * margin / 2.0
    ih, iw = shape[:2]
    return (max(0, int(x1)), max(0, int(y1)),
            min(iw, int(x2)), min(ih, int(y2)))


def crop_face(frame: np.ndarray, box: Sequence[float],
              margin: float = 0.2) -> np.ndarray | None:
    """Crop an (optionally expanded) face region. None if the crop is degenerate."""
    x1, y1, x2, y2 = expand_box(box, margin, frame.shape[:2])
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    crop = frame[y1:y2, x1:x2]
    return crop if crop.size else None


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
# Standard COCO-80 class names, in model output order. Needed so a general
# purpose COCO checkpoint renders real labels ("person", "car") instead of the
# meaningless "0" a single-class model would produce.
COCO_NAMES: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag",
    "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
)


# Named groups of classes that are useful to select together. Defined by NAME
# rather than index so they work with any model whose classes are named this
# way, not just stock COCO.
#
# "Vehicles" is deliberately GROUND vehicles only — aeroplanes and boats are
# excluded, since this project watches roads.
# `person` is deliberately NOT part of any group and has no group of its own —
# people and vehicles are always selected separately.
CLASS_GROUPS: dict[str, tuple[str, ...]] = {
    "Vehicles": ("car", "motorcycle", "bus", "truck", "bicycle"),
}


def resolve_class_group(name: str,
                        class_names: Sequence[str]) -> set[int] | None:
    """
    Class ids for a named group, or None if the group is unknown/empty.

    Members the model does not have are silently skipped, so a group still
    works on a model with a reduced label set.
    """
    members = CLASS_GROUPS.get(name)
    if not members:
        return None
    lower = [n.lower() for n in class_names]
    ids = {lower.index(m) for m in members if m in lower}
    return ids or None


def group_members(name: str, class_names: Sequence[str]) -> list[str]:
    """The group's members that this model actually has, in output order."""
    ids = resolve_class_group(name, class_names)
    if not ids:
        return []
    return [class_names[i] for i in sorted(ids)]


def available_groups(class_names: Sequence[str],
                     min_members: int = 2) -> list[str]:
    """Groups worth offering for this model (those with enough members)."""
    return [g for g in CLASS_GROUPS
            if len(group_members(g, class_names)) >= min_members]


def default_class_names(num_classes: int) -> list[str]:
    """
    Best-guess class names for a model with `num_classes` outputs.

        1  -> our single-class face detector
        80 -> a stock COCO checkpoint
        else -> generic placeholders
    """
    if num_classes <= 1:
        return ["face"]
    if num_classes == len(COCO_NAMES):
        return list(COCO_NAMES)
    return [f"class {i}" for i in range(num_classes)]


# Distinct, colour-blind-friendly-ish BGR palette for track IDs.
PALETTE: tuple[tuple[int, int, int], ...] = (
    (56, 168, 0), (0, 165, 255), (255, 128, 0), (180, 60, 220),
    (0, 220, 220), (200, 90, 90), (60, 200, 255), (140, 200, 60),
    (255, 100, 180), (90, 140, 255), (0, 200, 120), (200, 200, 60),
)


def color_for_id(track_id: int) -> tuple[int, int, int]:
    """Stable colour per track ID."""
    return PALETTE[int(track_id) % len(PALETTE)]


def draw_detections(frame: np.ndarray, boxes: np.ndarray,
                    scores: np.ndarray | None = None,
                    track_ids: np.ndarray | None = None,
                    quality: np.ndarray | None = None,
                    thickness: int = 2, font_scale: float = 0.5) -> np.ndarray:
    """Draw boxes with `ID n | conf | Q score` labels. Mutates and returns frame."""
    import cv2

    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = [int(v) for v in box[:4]]
        tid = int(track_ids[i]) if track_ids is not None and i < len(track_ids) else -1
        color = color_for_id(tid) if tid >= 0 else (0, 200, 0)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

        parts: list[str] = []
        if tid >= 0:
            parts.append(f"ID {tid}")
        if scores is not None and i < len(scores):
            parts.append(f"{float(scores[i]):.2f}")
        if quality is not None and i < len(quality):
            parts.append(f"Q{float(quality[i]):.2f}")
        if not parts:
            continue
        label = " | ".join(parts)

        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                         font_scale, 1)
        ly = max(y1, th + base + 2)
        cv2.rectangle(frame, (x1, ly - th - base - 2), (x1 + tw + 4, ly),
                      color, -1)
        cv2.putText(frame, label, (x1 + 2, ly - base),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), 1,
                    cv2.LINE_AA)
    return frame


def draw_hud(frame: np.ndarray, lines: Iterable[str],
             origin: tuple[int, int] = (10, 10)) -> np.ndarray:
    """Draw a translucent multi-line status panel in the top-left corner."""
    import cv2

    lines = list(lines)
    if not lines:
        return frame

    pad = 8
    fs = 0.55
    sizes = [cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)[0] for t in lines]
    w = max(s[0] for s in sizes) + pad * 2
    lh = max(s[1] for s in sizes) + 8
    h = lh * len(lines) + pad

    x, y = origin
    panel = frame[y:y + h, x:x + w]
    if panel.size:
        overlay = panel.copy()
        overlay[:] = (25, 25, 25)
        cv2.addWeighted(overlay, 0.55, panel, 0.45, 0, panel)

    for i, text in enumerate(lines):
        cv2.putText(frame, text, (x + pad, y + pad + lh * (i + 1) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (235, 235, 235), 1,
                    cv2.LINE_AA)
    return frame


# --------------------------------------------------------------------------- #
# Timing
# --------------------------------------------------------------------------- #
class FPSMeter:
    """Rolling-window FPS estimate — steadier than an instantaneous 1/dt."""

    def __init__(self, window: int = 30) -> None:
        self._times: deque[float] = deque(maxlen=int(window))
        self._last = time.perf_counter()

    def tick(self) -> float:
        now = time.perf_counter()
        self._times.append(now - self._last)
        self._last = now
        return self.fps

    @property
    def fps(self) -> float:
        if not self._times:
            return 0.0
        mean = sum(self._times) / len(self._times)
        return 1.0 / mean if mean > 1e-9 else 0.0

    def reset(self) -> None:
        self._times.clear()
        self._last = time.perf_counter()


class Timer:
    """Context manager measuring a block in milliseconds."""

    def __init__(self) -> None:
        self.ms = 0.0
        self._t0 = 0.0

    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        self.ms = (time.perf_counter() - self._t0) * 1000.0


# --------------------------------------------------------------------------- #
# Camera discovery
# --------------------------------------------------------------------------- #
def enumerate_cameras(max_index: int = 6) -> list[int]:
    """
    Probe camera indices 0..max_index-1 and return those that open and yield a
    frame.

    On Windows this uses the DirectShow backend explicitly — the default MSMF
    backend spends seconds timing out on absent devices.
    """
    import sys

    import cv2

    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
    found: list[int] = []
    for i in range(max_index):
        cap = None
        try:
            cap = cv2.VideoCapture(i, backend)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    found.append(i)
        except Exception:  # noqa: BLE001 — a bad index must not stop the scan
            pass
        finally:
            if cap is not None:
                cap.release()
    return found


def open_camera(index: int, width: int = 1280, height: int = 720,
                fps: int = 30):
    """Open a camera with sane defaults and a small buffer (low latency)."""
    import sys

    import cv2

    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
    cap = cv2.VideoCapture(int(index), backend)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(int(index))     # retry with the default backend
    if not cap.isOpened():
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
    cap.set(cv2.CAP_PROP_FPS, int(fps))
    # A 1-frame buffer keeps the displayed frame current instead of replaying a
    # backlog when inference is slower than capture.
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:  # noqa: BLE001 — unsupported on some backends
        pass
    return cap


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
def imwrite_unicode(path: Path, image: np.ndarray, quality: int = 95) -> bool:
    """
    cv2.imwrite fails on non-ASCII Windows paths. Encode in memory and use
    numpy's tofile, which goes through Python's Unicode-aware file API.
    """
    import cv2

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ext = path.suffix if path.suffix else ".jpg"
        params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)] \
            if ext.lower() in (".jpg", ".jpeg") else []
        success, buf = cv2.imencode(ext, image, params)
        if not success:
            return False
        buf.tofile(str(path))
        return True
    except Exception:  # noqa: BLE001
        return False


def imread_unicode(path: Path) -> np.ndarray | None:
    """Unicode-safe counterpart of imwrite_unicode."""
    import cv2

    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        return None


def timestamp_slug() -> str:
    """Filesystem-safe timestamp, e.g. 20260803_142530."""
    return time.strftime("%Y%m%d_%H%M%S")
