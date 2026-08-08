#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
src/tracker.py
==============
Multi-object tracking for faces.

Primary   : ``supervision.ByteTrack`` — battle-tested, handles occlusion well.
Fallback  : ``SimpleSortTracker`` — a dependency-free IoU + constant-velocity
            SORT-lite so the GUI keeps working if `supervision` is absent or its
            API shifts under us.

Both are wrapped by `FaceTracker`, which takes a `Detections` object from
`detector.py` and returns `TrackedDetections` (the same boxes plus a
`track_ids` array).
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.detector import Detections
    from src.utils import box_iou, load_inference_config
else:
    from .detector import Detections
    from .utils import box_iou, load_inference_config


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #
@dataclass
class TrackedDetections:
    """Detections plus a persistent identity per box."""
    boxes: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 4), dtype=np.float32))
    scores: np.ndarray = field(
        default_factory=lambda: np.zeros((0,), dtype=np.float32))
    track_ids: np.ndarray = field(
        default_factory=lambda: np.zeros((0,), dtype=np.int32))

    def __len__(self) -> int:
        return int(self.boxes.shape[0])

    def __bool__(self) -> bool:
        return len(self) > 0

    def __iter__(self):
        """Yield (box, score, track_id) triples."""
        for i in range(len(self)):
            yield self.boxes[i], float(self.scores[i]), int(self.track_ids[i])


# --------------------------------------------------------------------------- #
# SORT-lite fallback
# --------------------------------------------------------------------------- #
class _Track:
    """One tracked face: box, velocity, age and hit bookkeeping."""

    __slots__ = ("track_id", "box", "velocity", "score", "age",
                 "hits", "time_since_update")

    def __init__(self, track_id: int, box: np.ndarray, score: float) -> None:
        self.track_id = int(track_id)
        self.box = box.astype(np.float32).copy()
        self.velocity = np.zeros(4, dtype=np.float32)
        self.score = float(score)
        self.age = 0
        self.hits = 1
        self.time_since_update = 0

    def predict(self) -> np.ndarray:
        """Constant-velocity extrapolation, damped so drift stays bounded."""
        self.box = self.box + self.velocity
        self.velocity *= 0.85
        self.age += 1
        self.time_since_update += 1
        return self.box

    def update(self, box: np.ndarray, score: float) -> None:
        box = box.astype(np.float32)
        # Exponential-moving-average velocity — cheap and stable at 30 fps.
        self.velocity = 0.5 * self.velocity + 0.5 * (box - self.box)
        self.box = box
        self.score = float(score)
        self.hits += 1
        self.time_since_update = 0


class SimpleSortTracker:
    """
    SORT without the Kalman filter: greedy/Hungarian IoU association plus
    constant-velocity prediction. Accurate enough for face tracking at 30 fps and
    has no dependency beyond numpy (scipy is used when available).
    """

    def __init__(self, iou_threshold: float = 0.3, max_age: int = 45,
                 min_hits: int = 2, score_threshold: float = 0.30) -> None:
        self.iou_threshold = float(iou_threshold)
        self.max_age = int(max_age)
        self.min_hits = int(min_hits)
        self.score_threshold = float(score_threshold)
        self._tracks: list[_Track] = []
        self._next_id = 1
        self._frame = 0

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1
        self._frame = 0

    def update(self, boxes: np.ndarray, scores: np.ndarray) -> TrackedDetections:
        self._frame += 1

        keep = scores >= self.score_threshold
        boxes = boxes[keep]
        scores = scores[keep]

        for t in self._tracks:
            t.predict()

        matches, unmatched_det = self._associate(boxes)

        for det_idx, trk_idx in matches:
            self._tracks[trk_idx].update(boxes[det_idx], float(scores[det_idx]))

        for det_idx in unmatched_det:
            self._tracks.append(_Track(self._next_id, boxes[det_idx],
                                       float(scores[det_idx])))
            self._next_id += 1

        self._tracks = [t for t in self._tracks
                        if t.time_since_update <= self.max_age]

        out_boxes, out_scores, out_ids = [], [], []
        for t in self._tracks:
            # Report a track only while it is currently observed, and only once
            # it has been confirmed (or immediately, early in the sequence).
            if t.time_since_update > 0:
                continue
            if t.hits < self.min_hits and self._frame > self.min_hits:
                continue
            out_boxes.append(t.box)
            out_scores.append(t.score)
            out_ids.append(t.track_id)

        if not out_boxes:
            return TrackedDetections()
        return TrackedDetections(
            np.asarray(out_boxes, dtype=np.float32),
            np.asarray(out_scores, dtype=np.float32),
            np.asarray(out_ids, dtype=np.int32),
        )

    def _associate(self, boxes: np.ndarray) -> tuple[list[tuple[int, int]], list[int]]:
        """Match detections to tracks by IoU. Returns (matches, unmatched_dets)."""
        if len(boxes) == 0:
            return [], []
        if not self._tracks:
            return [], list(range(len(boxes)))

        track_boxes = np.asarray([t.box for t in self._tracks], dtype=np.float32)
        iou = box_iou(boxes, track_boxes)          # (n_det, n_trk)

        matches: list[tuple[int, int]] = []
        try:
            from scipy.optimize import linear_sum_assignment

            rows, cols = linear_sum_assignment(-iou)
            for r, c in zip(rows, cols):
                if iou[r, c] >= self.iou_threshold:
                    matches.append((int(r), int(c)))
        except ImportError:
            # Greedy fallback: repeatedly take the highest remaining IoU pair.
            work = iou.copy()
            while True:
                r, c = np.unravel_index(np.argmax(work), work.shape)
                if work[r, c] < self.iou_threshold:
                    break
                matches.append((int(r), int(c)))
                work[r, :] = -1.0
                work[:, c] = -1.0
                if (work < 0).all():
                    break

        matched_dets = {r for r, _ in matches}
        unmatched = [i for i in range(len(boxes)) if i not in matched_dets]
        return matches, unmatched

    @property
    def active_track_count(self) -> int:
        return sum(1 for t in self._tracks if t.time_since_update == 0)


# --------------------------------------------------------------------------- #
# supervision.ByteTrack wrapper
# --------------------------------------------------------------------------- #
class _ByteTrackWrapper:
    """
    Adapter around ``supervision.ByteTrack``.

    supervision renamed ByteTrack's constructor arguments between releases
    (`track_thresh`/`track_buffer`/`match_thresh` became
    `track_activation_threshold`/`lost_track_buffer`/`minimum_matching_threshold`),
    so the kwargs are filtered against the live signature rather than pinned.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        import supervision as sv

        self.sv = sv
        self.impl = "supervision.ByteTrack"

        # supervision deprecated `sv.ByteTrack` in 0.28 and removes it in 0.30;
        # the successor is `ByteTrackTracker` in the separate `trackers`
        # package, whose `update_with_detections` is renamed to `update`.
        # Prefer it when present so this keeps working after the removal.
        try:
            from trackers import ByteTrackTracker  # type: ignore

            self.tracker = ByteTrackTracker(
                track_activation_threshold=float(
                    cfg.get("track_activation_threshold", 0.30)),
                lost_track_buffer=int(cfg.get("lost_track_buffer", 45)),
                minimum_matching_threshold=float(
                    cfg.get("minimum_matching_threshold", 0.85)),
                frame_rate=int(cfg.get("frame_rate", 30)),
            )
            self.impl = "trackers.ByteTrackTracker"
            return
        except ImportError:
            pass
        except Exception:  # noqa: BLE001 — signature drift; fall back below
            pass

        wanted = {
            "track_activation_threshold": float(cfg.get("track_activation_threshold", 0.30)),
            "lost_track_buffer": int(cfg.get("lost_track_buffer", 45)),
            "minimum_matching_threshold": float(cfg.get("minimum_matching_threshold", 0.85)),
            "frame_rate": int(cfg.get("frame_rate", 30)),
            # legacy names, kept so old supervision releases also get values
            "track_thresh": float(cfg.get("track_activation_threshold", 0.30)),
            "track_buffer": int(cfg.get("lost_track_buffer", 45)),
            "match_thresh": float(cfg.get("minimum_matching_threshold", 0.85)),
        }
        try:
            params = set(inspect.signature(sv.ByteTrack.__init__).parameters)
            kwargs = {k: v for k, v in wanted.items() if k in params}
        except (TypeError, ValueError):
            kwargs = {}

        try:
            self.tracker = sv.ByteTrack(**kwargs)
        except TypeError:
            self.tracker = sv.ByteTrack()

    def reset(self) -> None:
        if hasattr(self.tracker, "reset"):
            self.tracker.reset()

    def _advance(self, det):
        """Call whichever update method this implementation exposes."""
        fn = getattr(self.tracker, "update_with_detections", None)
        if fn is None:
            fn = self.tracker.update           # trackers.ByteTrackTracker
        return fn(det)

    def update(self, boxes: np.ndarray, scores: np.ndarray) -> TrackedDetections:
        sv = self.sv
        if len(boxes) == 0:
            # ByteTrack still needs a tick so lost tracks age out correctly.
            try:
                self._advance(sv.Detections.empty())
            except Exception:  # noqa: BLE001 — older releases reject empty input
                pass
            return TrackedDetections()

        det = sv.Detections(
            xyxy=boxes.astype(np.float32),
            confidence=scores.astype(np.float32),
            class_id=np.zeros(len(boxes), dtype=int),
        )
        tracked = self._advance(det)

        if tracked is None or len(tracked) == 0:
            return TrackedDetections()

        ids = tracked.tracker_id
        if ids is None:
            ids = np.arange(len(tracked), dtype=np.int32)
        conf = tracked.confidence
        if conf is None:
            conf = np.ones(len(tracked), dtype=np.float32)

        # ByteTrack can emit predicted tracks with a null id; drop those.
        valid = np.array([i is not None for i in ids], dtype=bool)
        if not valid.all():
            return TrackedDetections(
                tracked.xyxy[valid].astype(np.float32),
                np.asarray(conf, dtype=np.float32)[valid],
                np.asarray(ids, dtype=object)[valid].astype(np.int32),
            )

        return TrackedDetections(
            tracked.xyxy.astype(np.float32),
            np.asarray(conf, dtype=np.float32),
            np.asarray(ids, dtype=np.int32),
        )


# --------------------------------------------------------------------------- #
# Public facade
# --------------------------------------------------------------------------- #
class FaceTracker:
    """
    Tracker facade.

        tracker = FaceTracker()                # bytetrack if available
        tracked = tracker.update(detections)   # -> TrackedDetections

    `backend_name` reports which implementation actually loaded, so the GUI can
    show it and the user is never guessing.
    """

    def __init__(self, tracker_type: str | None = None,
                 config: dict[str, Any] | None = None) -> None:
        cfg = config if config is not None else \
            load_inference_config().get("tracker", {})
        self.config = dict(cfg)
        requested = (tracker_type or cfg.get("type", "bytetrack")).lower()
        self.requested_type = requested

        self.backend: Any = None
        self.backend_name = "none"

        if requested == "bytetrack":
            try:
                self.backend = _ByteTrackWrapper(self.config)
                self.backend_name = self.backend.impl
            except Exception as exc:  # noqa: BLE001 — missing/changed supervision
                self._warn = (f"ByteTrack unavailable ({type(exc).__name__}: "
                              f"{exc}) — using the built-in SORT-lite tracker")
                print(f"  [!] {self._warn}")

        if self.backend is None:
            self.backend = SimpleSortTracker(
                iou_threshold=1.0 - float(self.config.get(
                    "minimum_matching_threshold", 0.85)) + 0.15,
                max_age=int(self.config.get("lost_track_buffer", 45)),
                min_hits=2,
                score_threshold=float(self.config.get(
                    "track_activation_threshold", 0.30)),
            )
            self.backend_name = "SimpleSort"

    def update(self, detections: Detections | TrackedDetections) -> TrackedDetections:
        """Advance the tracker by one frame."""
        boxes = np.asarray(detections.boxes, dtype=np.float32)
        scores = np.asarray(detections.scores, dtype=np.float32)
        if boxes.ndim != 2 or boxes.shape[0] == 0:
            boxes = np.zeros((0, 4), dtype=np.float32)
            scores = np.zeros((0,), dtype=np.float32)
        try:
            return self.backend.update(boxes, scores)
        except Exception as exc:  # noqa: BLE001 — never kill the video loop
            print(f"  [!] Tracker error ({type(exc).__name__}: {exc}) — "
                  f"passing detections through untracked")
            return TrackedDetections(
                boxes, scores,
                np.full(len(boxes), -1, dtype=np.int32))

    def reset(self) -> None:
        """Clear all tracks — call this when the video source changes."""
        try:
            self.backend.reset()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("Tracker self-test: a box drifting right across 10 frames "
          "should hold a single ID.\n")

    tracker = FaceTracker()
    print(f"  backend: {tracker.backend_name}\n")

    for f in range(10):
        x = 100 + f * 12
        boxes = np.array([[x, 100, x + 80, 200]], dtype=np.float32)
        scores = np.array([0.9], dtype=np.float32)
        out = tracker.update(Detections(boxes, scores,
                                        np.zeros(1, dtype=np.int32)))
        ids = out.track_ids.tolist() if len(out) else []
        print(f"  frame {f:>2}  box x={x:<4}  ids={ids}")

    print("\n  (a single stable ID from ~frame 1 onward is correct)")
