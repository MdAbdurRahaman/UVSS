#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
src/detector.py
===============
Face detection front-end with two interchangeable backends behind one API:

    OnnxBackend         — pure onnxruntime. No torch import. Preferred.
    UltralyticsBackend  — .pt weights through the Ultralytics API.

Both return the same `Detections` object, so `tracker.py`, `quality.py` and the
GUI never care which one is active.

Standalone use::

    python src/detector.py --model models/best.onnx --source 0
    python src/detector.py --model models/best.pt --source path/to/image.jpg
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

# Allow `python src/detector.py` as well as `from src.detector import ...`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.utils import (default_class_names, letterbox,
                           load_inference_config, nms, scale_boxes, xywh2xyxy)
else:
    from .utils import (default_class_names, letterbox, load_inference_config,
                        nms, scale_boxes, xywh2xyxy)


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #
@dataclass
class Detections:
    """Per-frame detections in original-image pixel coordinates."""
    boxes: np.ndarray = field(                       # (N, 4) float32 xyxy
        default_factory=lambda: np.zeros((0, 4), dtype=np.float32))
    scores: np.ndarray = field(                      # (N,) float32
        default_factory=lambda: np.zeros((0,), dtype=np.float32))
    class_ids: np.ndarray = field(                   # (N,) int32 — always 0
        default_factory=lambda: np.zeros((0,), dtype=np.int32))
    inference_ms: float = 0.0

    def __len__(self) -> int:
        return int(self.boxes.shape[0])

    def __bool__(self) -> bool:
        return len(self) > 0

    def filter_by_conf(self, threshold: float) -> "Detections":
        keep = self.scores >= float(threshold)
        return Detections(self.boxes[keep], self.scores[keep],
                          self.class_ids[keep], self.inference_ms)

    def areas(self) -> np.ndarray:
        if len(self) == 0:
            return np.zeros((0,), dtype=np.float32)
        w = np.clip(self.boxes[:, 2] - self.boxes[:, 0], 0, None)
        h = np.clip(self.boxes[:, 3] - self.boxes[:, 1], 0, None)
        return (w * h).astype(np.float32)


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class _BaseBackend:
    name = "base"

    def __init__(self, weights: Path, imgsz: int = 640) -> None:
        self.weights = Path(weights)
        self.imgsz = int(imgsz)

    num_classes = 1

    def infer(self, frame: np.ndarray, conf: float, iou: float,
              max_det: int, classes: set[int] | None = None) -> Detections:
        raise NotImplementedError

    def close(self) -> None:
        pass


class OnnxBackend(_BaseBackend):
    """
    ONNX Runtime backend.

    YOLO11 exports a single output of shape ``(1, 4 + nc, num_anchors)``. For our
    single-class model that is ``(1, 5, 8400)`` at 640 px: rows 0-3 are cx,cy,w,h
    in *letterboxed* pixels and row 4 is the class score. Decoding therefore is:
    transpose -> threshold -> xywh2xyxy -> NMS -> un-letterbox.

    Exports made with ``nms=True`` instead emit ``(1, N, 6)`` = xyxy,conf,cls;
    that layout is detected and handled too.
    """

    name = "onnxruntime"

    def __init__(self, weights: Path, imgsz: int = 640,
                 providers: list[str] | None = None) -> None:
        super().__init__(weights, imgsz)
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "onnxruntime is required for .onnx models. "
                "Install it with: pip install onnxruntime"
            ) from exc

        if providers is None:
            available = ort.get_available_providers()
            preferred = ["CUDAExecutionProvider", "DmlExecutionProvider",
                         "CoreMLExecutionProvider", "CPUExecutionProvider"]
            providers = [p for p in preferred if p in available] or available

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.log_severity_level = 3   # errors only

        self.session = ort.InferenceSession(str(self.weights),
                                            sess_options=opts,
                                            providers=providers)
        self.providers = self.session.get_providers()

        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        # Static exports carry a fixed spatial size; honour it over the config.
        shape = inp.shape
        if len(shape) == 4 and isinstance(shape[2], int) and shape[2] > 0:
            self.imgsz = int(shape[2])
        self.output_names = [o.name for o in self.session.get_outputs()]

        # Infer the class count from the output shape: (1, 4+nc, anchors) for a
        # raw head, or (1, N, 6) for an end-to-end export.
        self.num_classes = 1
        try:
            shape = self.session.get_outputs()[0].shape
            if len(shape) == 3 and isinstance(shape[1], int) \
                    and isinstance(shape[2], int):
                nc = (min(shape[1], shape[2]) - 4
                      if shape[1] != 6 else 1)
                if nc >= 1:
                    self.num_classes = int(nc)
        except Exception:  # noqa: BLE001 — dynamic shapes; fall back to 1
            pass

    def infer(self, frame: np.ndarray, conf: float, iou: float,
              max_det: int, classes: set[int] | None = None) -> Detections:
        import time

        padded, ratio, pad = letterbox(frame, self.imgsz)
        # BGR HWC uint8 -> RGB CHW float32 [0,1], batched.
        blob = padded[:, :, ::-1].transpose(2, 0, 1)
        blob = np.ascontiguousarray(blob, dtype=np.float32) / 255.0
        blob = blob[None]

        t0 = time.perf_counter()
        outputs = self.session.run(self.output_names, {self.input_name: blob})
        ms = (time.perf_counter() - t0) * 1000.0

        out = np.asarray(outputs[0])
        boxes, scores, class_ids = self._decode(out, conf, iou, max_det,
                                                classes)
        boxes = scale_boxes(boxes, ratio, pad, frame.shape[:2])
        return Detections(boxes.astype(np.float32),
                          scores.astype(np.float32),
                          class_ids.astype(np.int32), ms)

    def _decode(self, out: np.ndarray, conf: float, iou: float, max_det: int,
                classes: set[int] | None = None,
                imgsz: int | None = None
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Decode a YOLO head into (boxes_xyxy, scores, class_ids).

        Class ids come from `argmax` over the class scores, NOT a hardcoded
        zero — that is what lets a multi-class model (e.g. COCO-80) report real
        labels instead of calling every car a "face".
        """
        empty = (np.zeros((0, 4), np.float32), np.zeros((0,), np.float32),
                 np.zeros((0,), np.int32))
        if out.ndim == 3:
            out = out[0]
        if out.size == 0:
            return empty

        # --- Layout A: end-to-end export, (N, 6) = x1,y1,x2,y2,conf,cls ------
        if out.ndim == 2 and out.shape[1] == 6 and out.shape[0] != 6:
            keep = out[:, 4] >= conf
            if classes is not None:
                keep &= np.isin(out[:, 5].astype(np.int32), list(classes))
            sel = out[keep]
            if sel.size == 0:
                return empty
            order = sel[:, 4].argsort()[::-1][:max_det]
            return (sel[order, :4].astype(np.float32),
                    sel[order, 4].astype(np.float32),
                    sel[order, 5].astype(np.int32))

        # --- Layout B: raw head, (4+nc, num_anchors) -> transpose ------------
        if out.shape[0] < out.shape[1]:
            out = out.T                                   # (num_anchors, 4+nc)

        if out.shape[1] < 5:
            return empty

        cls_scores = out[:, 4:]
        if cls_scores.shape[1] == 1:
            scores = cls_scores[:, 0]
            class_ids = np.zeros(len(scores), dtype=np.int32)
        else:
            class_ids = cls_scores.argmax(axis=1).astype(np.int32)
            scores = cls_scores.max(axis=1)

        keep = scores >= conf
        if classes is not None:
            keep &= np.isin(class_ids, list(classes))
        if not keep.any():
            return empty

        xywh = out[keep, :4].astype(np.float32)

        # Two export conventions exist. Ultralytics emits box coordinates in
        # LETTERBOXED PIXELS (0..imgsz); some community re-exports emit
        # NORMALISED coordinates (0..1). Treating normalised output as pixels
        # collapses every box to [0,0,0,0] once the letterbox is undone, so
        # detect which convention this model uses and rescale when needed.
        size = float(imgsz if imgsz is not None else self.imgsz)
        if xywh.size and float(np.abs(xywh).max()) <= 2.0:
            xywh = xywh * size

        boxes = xywh2xyxy(xywh)
        scores = scores[keep].astype(np.float32)
        class_ids = class_ids[keep]

        # Class-aware NMS: offset boxes per class so a person standing in front
        # of a car does not suppress the car.
        if class_ids.max(initial=0) > 0:
            offset = class_ids.astype(np.float32) * 8192.0
            idx = nms(boxes + offset[:, None], scores, iou_threshold=iou,
                      max_det=max_det)
        else:
            idx = nms(boxes, scores, iou_threshold=iou, max_det=max_det)
        return boxes[idx], scores[idx], class_ids[idx]


class UltralyticsBackend(_BaseBackend):
    """Ultralytics backend — handles .pt, and also .onnx/.engine via its loader."""

    name = "ultralytics"

    def __init__(self, weights: Path, imgsz: int = 640,
                 device: Any = None) -> None:
        super().__init__(weights, imgsz)
        try:
            from ultralytics import YOLO
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "ultralytics is required for .pt models. "
                "Install it with: pip install ultralytics"
            ) from exc

        self.model = YOLO(str(self.weights))
        self.device = device
        if device is None:
            try:
                import torch
                self.device = 0 if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"

        names = getattr(self.model, "names", None)
        self.num_classes = len(names) if names else 1
        self.model_names = (list(names.values()) if isinstance(names, dict)
                            else list(names) if names else None)

    def infer(self, frame: np.ndarray, conf: float, iou: float,
              max_det: int, classes: set[int] | None = None) -> Detections:
        import time

        t0 = time.perf_counter()
        results = self.model.predict(frame, imgsz=self.imgsz, conf=float(conf),
                                     iou=float(iou), max_det=int(max_det),
                                     classes=sorted(classes) if classes else None,
                                     device=self.device, verbose=False)
        ms = (time.perf_counter() - t0) * 1000.0

        if not results:
            return Detections(inference_ms=ms)
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return Detections(inference_ms=ms)

        boxes = r.boxes.xyxy.cpu().numpy().astype(np.float32)
        scores = r.boxes.conf.cpu().numpy().astype(np.float32)
        cls = r.boxes.cls.cpu().numpy().astype(np.int32)
        return Detections(boxes, scores, cls, ms)


# --------------------------------------------------------------------------- #
# Public facade
# --------------------------------------------------------------------------- #
class FaceDetector:
    """
    Backend-agnostic face detector.

        det = FaceDetector("models/best.onnx")
        result = det.detect(frame)          # -> Detections

    The backend is chosen from the file extension. `.onnx` goes to onnxruntime
    unless `prefer_ultralytics=True`, because that avoids importing torch.
    """

    def __init__(self, weights: str | Path, imgsz: int | None = None,
                 conf: float | None = None, iou: float | None = None,
                 max_det: int | None = None, device: Any = None,
                 prefer_ultralytics: bool = False,
                 classes: Iterable[int] | None = None) -> None:
        cfg = load_inference_config()

        self.weights = Path(weights)
        if not self.weights.exists():
            raise FileNotFoundError(f"Model file not found: {self.weights}")

        self.imgsz = int(imgsz if imgsz is not None else cfg["imgsz"])
        self.conf = float(conf if conf is not None else cfg["conf_threshold"])
        self.iou = float(iou if iou is not None else cfg["iou_threshold"])
        self.max_det = int(max_det if max_det is not None
                           else cfg["max_detections"])

        suffix = self.weights.suffix.lower()
        if suffix == ".onnx" and not prefer_ultralytics:
            try:
                self.backend: _BaseBackend = OnnxBackend(self.weights, self.imgsz)
            except RuntimeError:
                # onnxruntime missing — Ultralytics can still load ONNX.
                self.backend = UltralyticsBackend(self.weights, self.imgsz, device)
        else:
            self.backend = UltralyticsBackend(self.weights, self.imgsz, device)

        # A static ONNX export may override the requested size.
        self.imgsz = self.backend.imgsz

        # --- class metadata -------------------------------------------------
        self.num_classes = int(getattr(self.backend, "num_classes", 1) or 1)
        names = getattr(self.backend, "model_names", None)
        self.class_names: list[str] = (
            list(names) if names and len(names) == self.num_classes
            else default_class_names(self.num_classes))
        self.classes: set[int] | None = set(classes) if classes else None

    # -- properties ---------------------------------------------------------
    @property
    def backend_name(self) -> str:
        return self.backend.name

    @property
    def providers(self) -> list[str]:
        return list(getattr(self.backend, "providers", []))

    @property
    def is_multiclass(self) -> bool:
        return self.num_classes > 1

    def class_name(self, class_id: int) -> str:
        """Human-readable label for a class id."""
        if 0 <= int(class_id) < len(self.class_names):
            return self.class_names[int(class_id)]
        return f"class {int(class_id)}"

    def set_classes(self, classes: Iterable[int] | None) -> None:
        """Restrict detection to these class ids (None = all)."""
        self.classes = set(classes) if classes else None

    def describe(self) -> str:
        extra = f" [{', '.join(self.providers)}]" if self.providers else ""
        kind = ("1 class (face)" if self.num_classes == 1
                else f"{self.num_classes} classes")
        return (f"{self.weights.name} via {self.backend_name}"
                f"{extra} @ {self.imgsz}px, {kind}")

    # -- inference ----------------------------------------------------------
    def detect(self, frame: np.ndarray, conf: float | None = None,
               iou: float | None = None,
               classes: Iterable[int] | None = None) -> Detections:
        """Run detection on one BGR frame."""
        if frame is None or frame.size == 0:
            return Detections()
        wanted = set(classes) if classes else self.classes
        return self.backend.infer(
            frame,
            conf=float(self.conf if conf is None else conf),
            iou=float(self.iou if iou is None else iou),
            max_det=self.max_det,
            classes=wanted,
        )

    def detect_tiled(self, frame: np.ndarray, conf: float | None = None,
                     iou: float | None = None,
                     classes: Iterable[int] | None = None,
                     grid: tuple[int, int] = (2, 2), overlap: float = 0.25,
                     include_full: bool = True) -> Detections:
        """
        Scale-invariant detection by slicing the frame into overlapping tiles.

        A detector always resizes its input to `imgsz` (640 here), so an object
        occupying 5 % of a 1280x720 frame arrives as ~30 px — often too small to
        recognise. Running each tile separately means that same object arrives
        at 2-3x the pixels, while the full-frame pass still catches objects too
        large to fit in one tile. Merging both makes detection far less
        sensitive to how near or far the subject is.

        This is the standard "slicing aided hyper inference" trick. Cost is
        roughly (tiles + 1) x a normal frame, so it is opt-in.

        `overlap` is the fractional overlap between neighbouring tiles; it stops
        an object landing exactly on a seam from being cut in half.
        """
        if frame is None or frame.size == 0:
            return Detections()

        conf_v = float(self.conf if conf is None else conf)
        iou_v = float(self.iou if iou is None else iou)
        wanted = set(classes) if classes else self.classes

        h, w = frame.shape[:2]
        rows, cols = max(1, int(grid[0])), max(1, int(grid[1]))
        overlap = float(np.clip(overlap, 0.0, 0.9))

        # Tile size chosen so that `cols` tiles with `overlap` cover the width.
        tile_w = int(round(w / (cols - (cols - 1) * overlap))) if cols > 1 else w
        tile_h = int(round(h / (rows - (rows - 1) * overlap))) if rows > 1 else h
        step_x = int(round(tile_w * (1.0 - overlap))) if cols > 1 else w
        step_y = int(round(tile_h * (1.0 - overlap))) if rows > 1 else h

        boxes: list[np.ndarray] = []
        scores: list[np.ndarray] = []
        cls: list[np.ndarray] = []
        total_ms = 0.0

        if include_full:
            full = self.detect(frame, conf=conf_v, iou=iou_v, classes=wanted)
            total_ms += full.inference_ms
            if len(full):
                boxes.append(full.boxes)
                scores.append(full.scores)
                cls.append(full.class_ids)

        for r in range(rows):
            for c in range(cols):
                x0 = min(c * step_x, max(w - tile_w, 0))
                y0 = min(r * step_y, max(h - tile_h, 0))
                x1 = min(x0 + tile_w, w)
                y1 = min(y0 + tile_h, h)
                if x1 - x0 < 16 or y1 - y0 < 16:
                    continue

                sub = frame[y0:y1, x0:x1]
                res = self.detect(sub, conf=conf_v, iou=iou_v, classes=wanted)
                total_ms += res.inference_ms
                if not len(res):
                    continue
                shifted = res.boxes.copy()
                shifted[:, [0, 2]] += x0
                shifted[:, [1, 3]] += y0
                boxes.append(shifted)
                scores.append(res.scores)
                cls.append(res.class_ids)

        if not boxes:
            return Detections(inference_ms=total_ms)

        all_boxes = np.concatenate(boxes).astype(np.float32)
        all_scores = np.concatenate(scores).astype(np.float32)
        all_cls = np.concatenate(cls).astype(np.int32)

        # Class-aware NMS across the union: the same object seen in the
        # full-frame pass and in two tiles must collapse to one box.
        if all_cls.max(initial=0) > 0:
            offset = all_cls.astype(np.float32) * 8192.0
            keep = nms(all_boxes + offset[:, None], all_scores,
                       iou_threshold=iou_v, max_det=self.max_det)
        else:
            keep = nms(all_boxes, all_scores, iou_threshold=iou_v,
                       max_det=self.max_det)

        return Detections(all_boxes[keep], all_scores[keep], all_cls[keep],
                          total_ms)

    def warmup(self, runs: int = 2) -> None:
        """Run a couple of dummy inferences so the first real frame is not slow."""
        dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        for _ in range(max(1, runs)):
            try:
                self.detect(dummy)
            except Exception:  # noqa: BLE001 — warm-up must never be fatal
                break

    def close(self) -> None:
        self.backend.close()

    def __enter__(self) -> "FaceDetector":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# --------------------------------------------------------------------------- #
# CLI smoke test
# --------------------------------------------------------------------------- #
def _main() -> int:
    import argparse

    import cv2

    from src.utils import FPSMeter, draw_detections, draw_hud, find_default_model

    p = argparse.ArgumentParser(description="Detector smoke test.")
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--source", type=str, default="0",
                   help="webcam index, image path or video path")
    p.add_argument("--conf", type=float, default=0.35)
    p.add_argument("--iou", type=float, default=0.45)
    args = p.parse_args()

    model = Path(args.model) if args.model else find_default_model()
    if model is None:
        print("[x] No model found. Train and export one first, or pass --model.")
        return 1

    det = FaceDetector(model, conf=args.conf, iou=args.iou)
    print(f"[+] {det.describe()}")
    det.warmup()

    # Still image
    src = args.source
    if not src.isdigit() and Path(src).suffix.lower() in (".jpg", ".jpeg", ".png",
                                                          ".bmp"):
        frame = cv2.imread(src)
        if frame is None:
            print(f"[x] Could not read {src}")
            return 1
        res = det.detect(frame)
        print(f"[+] {len(res)} face(s) in {res.inference_ms:.1f} ms")
        draw_detections(frame, res.boxes, res.scores)
        out = Path(src).with_name(Path(src).stem + "_detected.jpg")
        cv2.imwrite(str(out), frame)
        print(f"[+] Wrote {out}")
        return 0

    # Live / video
    cap = cv2.VideoCapture(int(src) if src.isdigit() else src)
    if not cap.isOpened():
        print(f"[x] Could not open source {src}")
        return 1
    fps = FPSMeter()
    print("[i] Press q to quit.")
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        res = det.detect(frame)
        draw_detections(frame, res.boxes, res.scores)
        draw_hud(frame, [f"FPS {fps.tick():.1f}",
                         f"faces {len(res)}",
                         f"{res.inference_ms:.1f} ms",
                         det.backend_name])
        cv2.imshow("detector", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
