#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
src/quality.py
==============
Face quality scoring and best-face selection.

Score components (each normalised to 0-1, then weighted):

    sharpness   variance of the Laplacian, normalised by crop area so a large
                blurry face cannot out-score a small crisp one
    size        face area relative to a reference size — bigger faces carry more
                recognisable detail
    confidence  the detector's own score
    frontality  a cheap proxy from the box aspect ratio plus left/right
                intensity symmetry; a profile face is asymmetric and narrow

`BestFaceGallery` keeps the top-K crops per track ID, with a minimum-improvement
rule and a cooldown so a static subject does not churn the gallery every frame.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.utils import (DEFAULT_SAVE_DIR, ROOT, crop_face, imwrite_unicode,
                           load_inference_config, timestamp_slug)
else:
    from .utils import (DEFAULT_SAVE_DIR, ROOT, crop_face, imwrite_unicode,
                        load_inference_config, timestamp_slug)


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
# Reference face size in pixels at which the `size` component saturates to 1.0.
# 160 px is roughly where face-recognition models stop gaining accuracy.
REFERENCE_FACE_PX = 160.0

# Laplacian variance considered "perfectly sharp" after area normalisation.
SHARPNESS_SATURATION = 900.0

# --- appearance matching ---------------------------------------------------
# Trackers like ByteTrack/BoT-SORT associate on motion and IoU only. When two
# people cross, the boxes overlap and identities can swap, so one track ends up
# holding crops of two different individuals. A cheap banded colour histogram
# separates them well (measured on real crops: same person >= 0.77, different
# people <= 0.55), so it is used as a guard: a crop that does not look like the
# identity it was assigned to starts a NEW gallery identity instead of
# polluting the existing one.
APPEARANCE_BANDS = 3          # head / torso / legs
APPEARANCE_H_BINS = 16
APPEARANCE_S_BINS = 8


def appearance_signature(crop: np.ndarray) -> np.ndarray | None:
    """Unit-norm banded HSV colour histogram. None if the crop is unusable."""
    import cv2

    if crop is None or crop.size == 0 or min(crop.shape[:2]) < 8:
        return None
    try:
        resized = cv2.resize(crop, (64, 128), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        step = hsv.shape[0] // APPEARANCE_BANDS
        parts = []
        for b in range(APPEARANCE_BANDS):
            band = hsv[b * step:(b + 1) * step]
            hist = cv2.calcHist([band], [0, 1], None,
                                [APPEARANCE_H_BINS, APPEARANCE_S_BINS],
                                [0, 180, 0, 256])
            cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
            parts.append(hist.flatten())
        vec = np.concatenate(parts).astype(np.float32)
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 1e-6 else None
    except Exception:  # noqa: BLE001 — never break the video loop
        return None


def appearance_similarity(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """Cosine similarity of two unit-norm signatures, 0..1."""
    if a is None or b is None:
        return 1.0            # unknown -> do not split
    return float(np.clip(np.dot(a, b), 0.0, 1.0))


def laplacian_sharpness(gray: np.ndarray) -> float:
    """Variance of the Laplacian — the standard no-reference blur metric."""
    import cv2

    if gray is None or gray.size == 0:
        return 0.0
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def sharpness_score(crop: np.ndarray) -> float:
    """
    Normalised sharpness in 0-1.

    Raw Laplacian variance scales with resolution, so a 300x300 crop always beats
    a 60x60 crop of the same subject. Rescaling every crop to a fixed 96x96 first
    removes that bias and makes the metric comparable across face sizes.
    """
    import cv2

    if crop is None or crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    if min(gray.shape[:2]) < 8:
        return 0.0
    gray = cv2.resize(gray, (96, 96), interpolation=cv2.INTER_AREA)
    var = laplacian_sharpness(gray)
    return float(np.clip(var / SHARPNESS_SATURATION, 0.0, 1.0))


def size_score(box: Sequence[float],
               reference_px: float = REFERENCE_FACE_PX) -> float:
    """Normalised face size in 0-1, saturating at `reference_px`."""
    x1, y1, x2, y2 = box[:4]
    side = float(np.sqrt(max(x2 - x1, 0.0) * max(y2 - y1, 0.0)))
    return float(np.clip(side / reference_px, 0.0, 1.0))


def frontality_score(crop: np.ndarray, box: Sequence[float]) -> float:
    """
    Cheap frontality proxy in 0-1, no landmark model required.

    Two signals, averaged:
      * aspect ratio — a frontal face box is roughly 0.75-0.95 wide-over-tall;
        profiles are noticeably narrower.
      * left/right symmetry — a frontal face has similar mean intensity and
        gradient energy in its two halves; a profile does not.
    """
    import cv2

    x1, y1, x2, y2 = box[:4]
    w = max(x2 - x1, 1.0)
    h = max(y2 - y1, 1.0)
    ar = w / h
    # Peak at ar == 0.85, decaying either side.
    ar_score = float(np.exp(-((ar - 0.85) ** 2) / (2 * 0.22 ** 2)))

    sym_score = 0.5
    if crop is not None and crop.size and min(crop.shape[:2]) >= 16:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        gray = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
        left = gray[:, :32].astype(np.float32)
        right = np.fliplr(gray[:, 32:]).astype(np.float32)

        # Intensity symmetry
        diff = np.abs(left - right).mean()
        intensity_sym = float(np.clip(1.0 - diff / 60.0, 0.0, 1.0))

        # Gradient-energy symmetry — robust to lighting falloff across the face
        gl = float(np.abs(cv2.Sobel(left, cv2.CV_32F, 1, 0, ksize=3)).mean())
        gr = float(np.abs(cv2.Sobel(right, cv2.CV_32F, 1, 0, ksize=3)).mean())
        grad_sym = float(min(gl, gr) / max(max(gl, gr), 1e-6))

        sym_score = 0.5 * intensity_sym + 0.5 * grad_sym

    return float(np.clip(0.5 * ar_score + 0.5 * sym_score, 0.0, 1.0))


def score_detection(crop: np.ndarray, box: Sequence[float], confidence: float,
                    weights: dict[str, float] | None = None,
                    use_frontality: bool = True
                    ) -> tuple[float, dict[str, float]]:
    """
    Composite quality score for one detection crop.

    ``use_frontality`` should be False for non-face classes: the frontality
    proxy assumes a roughly symmetric, face-shaped subject, so applying it to a
    car or a chair injects noise rather than signal. When it is dropped the
    remaining weights are renormalised, so scores stay comparable in 0-1.

    Returns ``(score, components)``.
    """
    w = {"sharpness": 0.35, "size": 0.25, "confidence": 0.25, "frontality": 0.15}
    if weights:
        w.update({k: float(v) for k, v in weights.items() if k in w})

    components = {
        "sharpness": sharpness_score(crop),
        "size": size_score(box),
        "confidence": float(np.clip(confidence, 0.0, 1.0)),
    }
    if use_frontality:
        components["frontality"] = frontality_score(crop, box)
    else:
        w = {k: v for k, v in w.items() if k != "frontality"}

    total = sum(w.values()) or 1.0
    score = sum(components[k] * w[k] for k in components) / total
    return float(np.clip(score, 0.0, 1.0)), components


# Backwards-compatible alias — the project was face-only before multi-class
# model support was added.
def score_face(crop: np.ndarray, box: Sequence[float], confidence: float,
               weights: dict[str, float] | None = None
               ) -> tuple[float, dict[str, float]]:
    """Face-specific wrapper around :func:`score_detection`."""
    return score_detection(crop, box, confidence, weights, use_frontality=True)


# --------------------------------------------------------------------------- #
# Gallery
# --------------------------------------------------------------------------- #
@dataclass
class DetectionRecord:
    """One kept crop for one track."""
    track_id: int
    crop: np.ndarray
    score: float
    confidence: float
    box: tuple[float, float, float, float]
    frame_index: int
    components: dict[str, float] = field(default_factory=dict)
    class_id: int = 0
    class_name: str = "face"
    saved_path: Path | None = None      # crop file, when auto-save is on
    identity: str = ""                  # display label, e.g. "10" or "10b"
    signature: np.ndarray | None = None  # appearance descriptor
    # The whole frame this crop came from, kept as encoded JPEG bytes rather
    # than a raw array: a 1280x720 BGR frame is ~2.7 MB, and holding one per
    # kept record would run to hundreds of MB across several subjects.
    full_jpeg: bytes | None = None
    saved_full_path: Path | None = None

    @property
    def size_px(self) -> tuple[int, int]:
        h, w = self.crop.shape[:2]
        return (w, h)

    def summary(self) -> str:
        c = self.components
        front = (f"front={c['frontality']:.2f}  " if "frontality" in c else "")
        return (f"id {self.identity or self.track_id}  [{self.class_name}]  "
                f"Q={self.score:.3f}  conf={self.confidence:.2f}  "
                f"sharp={c.get('sharpness', 0):.2f}  "
                f"size={c.get('size', 0):.2f}  {front}"
                f"{self.size_px[0]}x{self.size_px[1]}px  frame {self.frame_index}")


# Backwards-compatible alias.
FaceRecord = DetectionRecord


class BestImageGallery:
    """
    Keeps the top-K highest-quality crops per track ID, for ANY detected class.

        gallery = BestImageGallery(top_k=5)
        gallery.update(frame, tracked, frame_index, class_names=det.class_names)
        paths = gallery.save_all()

    Originally face-only; generalised when multi-class (COCO) models were added,
    so "best faces" became "best images". Face-specific scoring (frontality) is
    applied only to detections whose class is actually `face`.

    Two guards stop the gallery churning on a stationary subject:
      * `min_improvement` — a new crop must beat the *worst kept* crop by this
        margin before it displaces it.
      * `cooldown_frames` — at most one accepted crop per track per N frames.
    """

    def __init__(self, top_k: int | None = None,
                 weights: dict[str, float] | None = None,
                 min_face_px: int | None = None,
                 min_improvement: float | None = None,
                 cooldown_frames: int | None = None,
                 crop_margin: float | None = None,
                 save_dir: str | Path | None = None,
                 config: dict[str, Any] | None = None) -> None:
        cfg = config if config is not None else \
            load_inference_config().get("quality", {})

        self.top_k = int(top_k if top_k is not None
                         else cfg.get("top_k_per_track", 1))
        self.weights = dict(weights if weights is not None
                            else cfg.get("weights", {}))
        self.min_face_px = int(min_face_px if min_face_px is not None
                               else cfg.get("min_face_px", 40))
        self.min_improvement = float(min_improvement if min_improvement is not None
                                     else cfg.get("min_improvement", 0.02))
        self.cooldown_frames = int(cooldown_frames if cooldown_frames is not None
                                   else cfg.get("cooldown_frames", 3))
        self.crop_margin = float(crop_margin if crop_margin is not None
                                 else cfg.get("crop_margin", 0.20))

        raw_dir = save_dir if save_dir is not None else \
            cfg.get("save_dir", "best_images")
        d = Path(raw_dir)
        self.save_dir = d if d.is_absolute() else (ROOT / d)

        # Keyed by GALLERY id, not raw track id: one track can spawn several
        # gallery identities if the tracker swaps people mid-sequence.
        self._faces: dict[int, list[DetectionRecord]] = {}
        self._last_accept: dict[int, int] = {}
        self._considered = 0
        self._accepted = 0

        # --- identity bookkeeping ------------------------------------------
        self.appearance_split = bool(cfg.get("appearance_split", True))
        self.appearance_threshold = float(cfg.get("appearance_threshold", 0.62))
        self._gid_track: dict[int, int] = {}      # gallery id -> track id
        self._gid_label: dict[int, str] = {}      # gallery id -> display label
        self._track_gids: dict[int, list[int]] = {}
        self._next_gid = 1
        self.splits = 0                            # how many times we split

        # --- auto-save -----------------------------------------------------
        self.autosave_dir: Path | None = None
        self._autosave_writes = 0
        self._autosave_quality = 95

    # -- introspection ------------------------------------------------------
    @property
    def track_count(self) -> int:
        return len(self._faces)

    @property
    def face_count(self) -> int:
        return sum(len(v) for v in self._faces.values())

    @property
    def stats(self) -> dict[str, int]:
        return {"tracks": self.track_count, "faces": self.face_count,
                "considered": self._considered, "accepted": self._accepted}

    def track_ids(self) -> list[int]:
        """Gallery identity ids (one track may have produced several)."""
        return sorted(self._faces)

    def label_for(self, gid: int) -> str:
        """Display label for a gallery identity, e.g. '10' or '10b'."""
        return self._gid_label.get(int(gid), str(gid))

    def get_by_track(self, track_id: int) -> list[DetectionRecord]:
        """
        Every kept record for a raw TRACK id, across all identities it produced.

        `get()` takes a gallery-identity id; this takes the tracker's id, which
        is usually what callers have. If the appearance guard split the track,
        this returns the union.
        """
        out: list[DetectionRecord] = []
        for gid in self._track_gids.get(int(track_id), []):
            out.extend(self._faces.get(gid, []))
        out.sort(key=lambda r: r.score, reverse=True)
        return out

    # -- identity resolution ------------------------------------------------
    def _new_identity(self, track_id: int) -> int:
        gid = self._next_gid
        self._next_gid += 1
        siblings = self._track_gids.setdefault(track_id, [])
        # First identity for a track keeps the plain number; later ones get a
        # suffix, so "10" and "10b" are visibly the same track split in two.
        label = str(track_id) if not siblings else \
            f"{track_id}{chr(ord('a') + len(siblings))}"
        siblings.append(gid)
        self._gid_track[gid] = track_id
        self._gid_label[gid] = label
        return gid

    def _resolve_identity(self, track_id: int,
                          signature: np.ndarray | None) -> int:
        """
        Map a (track_id, appearance) pair to a gallery identity.

        Reuses the track's existing identity when the crop looks like it, and
        otherwise starts a new one — which is what stops an ID switch from
        merging two people into a single folder.
        """
        siblings = self._track_gids.get(track_id, [])
        if not siblings:
            return self._new_identity(track_id)

        if not self.appearance_split or signature is None:
            return siblings[0]

        best_gid, best_sim = None, -1.0
        for gid in siblings:
            for rec in self._faces.get(gid, []):
                sim = appearance_similarity(signature, rec.signature)
                if sim > best_sim:
                    best_sim, best_gid = sim, gid

        if best_gid is not None and best_sim >= self.appearance_threshold:
            return best_gid
        if best_gid is None:               # no stored signatures yet
            return siblings[0]

        self.splits += 1
        return self._new_identity(track_id)

    def get(self, track_id: int) -> list[DetectionRecord]:
        """Kept faces for one track, best first."""
        return list(self._faces.get(int(track_id), []))

    def best_per_track(self) -> list[DetectionRecord]:
        """The single best crop for each track, best track first."""
        out = [v[0] for v in self._faces.values() if v]
        out.sort(key=lambda r: r.score, reverse=True)
        return out

    def all_records(self) -> list[DetectionRecord]:
        out: list[DetectionRecord] = []
        for recs in self._faces.values():
            out.extend(recs)
        out.sort(key=lambda r: (r.track_id, -r.score))
        return out

    # -- ingestion ----------------------------------------------------------
    def update(self, frame: np.ndarray, tracked: Any, frame_index: int = 0,
               class_ids: Any = None,
               class_names: Sequence[str] | None = None) -> list[float]:
        """
        Score every tracked detection in this frame and keep the good ones.

        `class_ids` / `class_names` are optional; without them everything is
        treated as the single `face` class, which is exactly the old behaviour.

        Returns the per-detection quality scores in the same order as `tracked`,
        so the caller can render them on the boxes.
        """
        scores: list[float] = []
        if frame is None or frame.size == 0 or tracked is None or len(tracked) == 0:
            return scores

        boxes = np.asarray(tracked.boxes, dtype=np.float32)
        confs = np.asarray(tracked.scores, dtype=np.float32)
        tids = np.asarray(tracked.track_ids, dtype=np.int32)

        if class_ids is None:
            class_ids = getattr(tracked, "class_ids", None)
        cids = (np.asarray(class_ids, dtype=np.int32)
                if class_ids is not None else np.zeros(len(boxes), dtype=np.int32))

        for i in range(len(boxes)):
            box = boxes[i]
            conf = float(confs[i]) if i < len(confs) else 0.0
            tid = int(tids[i]) if i < len(tids) else -1
            cid = int(cids[i]) if i < len(cids) else 0
            cname = (class_names[cid] if class_names and 0 <= cid < len(class_names)
                     else ("face" if cid == 0 and not class_names else f"class {cid}"))

            crop = crop_face(frame, box, self.crop_margin)
            if crop is None:
                scores.append(0.0)
                continue

            # Frontality assumes a face-shaped, roughly symmetric subject.
            score, components = score_detection(
                crop, box, conf, self.weights,
                use_frontality=(cname.lower() == "face"))
            scores.append(score)
            self._considered += 1

            if tid < 0:
                continue  # untracked detection — nothing stable to file it under
            if min(crop.shape[0], crop.shape[1]) < self.min_face_px:
                continue

            # Appearance guard: decide WHICH gallery identity this crop belongs
            # to before the cooldown check, so a swapped-in person is not
            # silently dropped by the previous person's cooldown.
            sig = appearance_signature(crop) if self.appearance_split else None
            gid = self._resolve_identity(tid, sig)

            if frame_index - self._last_accept.get(gid, -10 ** 9) < self.cooldown_frames:
                continue

            record = DetectionRecord(
                track_id=tid, crop=crop.copy(), score=score, confidence=conf,
                box=(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
                frame_index=int(frame_index), components=components,
                class_id=cid, class_name=cname,
                identity=self._gid_label.get(gid, str(tid)), signature=sig)
            if self._insert(record, gid):
                self._last_accept[gid] = frame_index
                self._accepted += 1

        return scores

    # -- auto-save ----------------------------------------------------------
    def enable_autosave(self, out_dir: str | Path | None = None,
                        session_subdir: bool = True,
                        jpeg_quality: int = 95) -> Path:
        """
        Write every kept crop to disk the moment it is accepted.

        The folder is kept in SYNC with the gallery: when a better crop pushes
        a worse one out of a track's top-K, the displaced file is deleted. So
        the directory always holds exactly "the best K per subject", not every
        crop that was ever briefly good enough.

        Returns the session directory.
        """
        base = Path(out_dir) if out_dir is not None else self.save_dir
        if not base.is_absolute():
            base = ROOT / base
        if session_subdir:
            base = base / f"session_{timestamp_slug()}"
        base.mkdir(parents=True, exist_ok=True)

        self.autosave_dir = base
        self._autosave_quality = int(jpeg_quality)

        # Flush anything already collected before auto-save was switched on.
        for recs in self._faces.values():
            for rec in recs:
                if rec.saved_path is None:
                    self._autosave_write(rec)
        self._write_summary()
        return base

    def disable_autosave(self) -> None:
        self.autosave_dir = None

    def attach_context(self, annotated: np.ndarray, frame_index: int,
                       jpeg_quality: int = 90) -> int:
        """
        Attach the ANNOTATED full frame to records captured on `frame_index`.

        Called after drawing, because the boxes carry the quality scores that
        `update()` produces — so the full view cannot be built until update()
        has already run. Every record accepted on this frame shares one encoded
        copy, so a frame containing four subjects is encoded once, not四 times.

        Returns how many records were given a context frame.
        """
        if annotated is None or annotated.size == 0:
            return 0

        pending = [rec for recs in self._faces.values() for rec in recs
                   if rec.frame_index == frame_index and rec.full_jpeg is None]
        if not pending:
            return 0

        import cv2

        try:
            ok, buf = cv2.imencode(".jpg", annotated,
                                   [int(cv2.IMWRITE_JPEG_QUALITY),
                                    int(jpeg_quality)])
            if not ok:
                return 0
            encoded = buf.tobytes()
        except Exception:  # noqa: BLE001
            return 0

        for rec in pending:
            rec.full_jpeg = encoded
            if self.autosave_dir is not None:
                self._autosave_write_full(rec)
        return len(pending)

    def _record_dir(self, record: DetectionRecord) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in record.class_name)
        ident = "".join(c if c.isalnum() else "_"
                        for c in (record.identity or str(record.track_id)))
        return (self.autosave_dir or self.save_dir) / f"{safe}_{ident}"

    @staticmethod
    def _stem(record: DetectionRecord) -> str:
        # Name by score then frame: stable for the life of the record (rank
        # would churn as better crops arrive), and a descending name sort is a
        # descending quality sort.
        return f"q{record.score:.3f}_f{record.frame_index}"

    def _autosave_write(self, record: DetectionRecord) -> None:
        """Write the CROP. The annotated full frame follows in attach_context."""
        if self.autosave_dir is None:
            return
        path = self._record_dir(record) / "crop" / f"{self._stem(record)}.jpg"
        if imwrite_unicode(path, record.crop, self._autosave_quality):
            record.saved_path = path
            self._autosave_writes += 1
        if record.full_jpeg is not None:
            self._autosave_write_full(record)

    def _autosave_write_full(self, record: DetectionRecord) -> None:
        """Write the annotated whole frame this crop came from."""
        if self.autosave_dir is None or record.full_jpeg is None:
            return
        path = self._record_dir(record) / "full" / f"{self._stem(record)}.jpg"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(record.full_jpeg)
            record.saved_full_path = path
        except OSError:
            pass

    @staticmethod
    def _autosave_remove(record: DetectionRecord) -> None:
        """Delete both files when a record is displaced from the top-K."""
        for attr in ("saved_path", "saved_full_path"):
            path = getattr(record, attr, None)
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            setattr(record, attr, None)

    def _write_summary(self) -> None:
        if self.autosave_dir is None:
            return
        try:
            by_class: dict[str, int] = {}
            for rec in self.all_records():
                by_class[rec.class_name] = by_class.get(rec.class_name, 0) + 1
            breakdown = "   ".join(f"{k}: {v}" for k, v in sorted(by_class.items()))
            lines = [f"UVSS best-image auto-save — {timestamp_slug()}",
                     f"tracks: {self.track_count}   images: {self.face_count}",
                     f"by class: {breakdown or 'none'}",
                     f"considered: {self._considered}   accepted: {self._accepted}",
                     ""]
            for rec in self.all_records():
                lines.append("  " + rec.summary())
            (self.autosave_dir / "summary.txt").write_text(
                "\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass

    def _insert(self, record: DetectionRecord, gid: int | None = None) -> bool:
        """Insert into an identity's top-K list. Returns True if it was kept."""
        if gid is None:                       # direct call (tests, legacy)
            gid = self._resolve_identity(record.track_id, record.signature)
            record.identity = self._gid_label.get(gid, str(record.track_id))
        bucket = self._faces.setdefault(gid, [])

        if len(bucket) < self.top_k:
            bucket.append(record)
            bucket.sort(key=lambda r: r.score, reverse=True)
            self._autosave_write(record)
            self._after_insert()
            return True

        worst = bucket[-1]
        if record.score < worst.score + self.min_improvement:
            return False

        self._autosave_remove(worst)      # keep the folder in sync
        bucket[-1] = record
        bucket.sort(key=lambda r: r.score, reverse=True)
        self._autosave_write(record)
        self._after_insert()
        return True

    def _after_insert(self) -> None:
        # Refresh the manifest periodically rather than on every write — it is
        # small, but this runs at frame rate.
        if self.autosave_dir is not None and self._autosave_writes % 10 == 0:
            self._write_summary()

    # -- persistence --------------------------------------------------------
    def save_all(self, out_dir: str | Path | None = None,
                 session_subdir: bool = True,
                 jpeg_quality: int = 95) -> list[Path]:
        """
        Write every kept crop to disk as
        ``<out>/<session>/track_<id>/rank<k>_q<score>_f<frame>.jpg``.

        Also writes a `summary.txt` per session. Returns the written paths.
        """
        base = Path(out_dir) if out_dir is not None else self.save_dir
        if not base.is_absolute():
            base = ROOT / base
        if session_subdir:
            base = base / f"session_{timestamp_slug()}"

        written: list[Path] = []
        if not self._faces:
            return written

        for gid in sorted(self._faces):
            records = self._faces[gid]
            if not records:
                continue
            # Group by class + identity so a mixed session stays navigable.
            cname = records[0].class_name
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in cname)
            ident = "".join(c if c.isalnum() else "_"
                            for c in (records[0].identity or str(gid)))
            tdir = base / f"{safe}_{ident}"
            for rank, rec in enumerate(records, 1):
                name = (f"rank{rank}_q{rec.score:.3f}"
                        f"_c{rec.confidence:.2f}_f{rec.frame_index}.jpg")
                if imwrite_unicode(tdir / "crop" / name, rec.crop, jpeg_quality):
                    written.append(tdir / "crop" / name)
                # The annotated whole frame, when one was attached.
                if rec.full_jpeg is not None:
                    full = tdir / "full" / name
                    try:
                        full.parent.mkdir(parents=True, exist_ok=True)
                        full.write_bytes(rec.full_jpeg)
                        written.append(full)
                    except OSError:
                        pass

        try:
            by_class: dict[str, int] = {}
            for rec in self.all_records():
                by_class[rec.class_name] = by_class.get(rec.class_name, 0) + 1
            breakdown = "   ".join(f"{k}: {v}" for k, v in sorted(by_class.items()))
            lines = [f"UVSS best-image export — {timestamp_slug()}",
                     f"tracks: {self.track_count}   images: {self.face_count}",
                     f"by class: {breakdown or 'none'}",
                     f"considered: {self._considered}   accepted: {self._accepted}",
                     ""]
            for rec in self.all_records():
                lines.append("  " + rec.summary())
            (base / "summary.txt").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
        except OSError:
            pass

        return written

    def clear(self, delete_saved: bool = False) -> None:
        """
        Drop everything from memory.

        `delete_saved` also removes the auto-saved files. Default False: the
        point of auto-save is that clearing the live view never destroys what is
        already on disk.
        """
        if delete_saved:
            for recs in self._faces.values():
                for rec in recs:
                    self._autosave_remove(rec)
        self._faces.clear()
        self._last_accept.clear()
        self._gid_track.clear()
        self._gid_label.clear()
        self._track_gids.clear()
        self._next_gid = 1
        self.splits = 0
        self._considered = 0
        self._accepted = 0
        self._write_summary()

    def record_at(self, x: int, y: int) -> DetectionRecord | None:
        """
        The record whose tile contains (x, y) in the last `make_track_sheet`
        image, or None. Lets a GUI turn a click into the crop that was clicked.
        """
        for x0, y0, x1, y1, tid, rank in getattr(self, "last_sheet_layout", []):
            if x0 <= x < x1 and y0 <= y < y1:
                recs = self.get(tid)
                if 1 <= rank <= len(recs):
                    return recs[rank - 1]
        return None

    def make_track_sheet(self, thumb: int = 96, gutter: int = 46,
                         max_per_track: int | None = None) -> np.ndarray | None:
        """
        One row per tracked subject, showing that subject's best crops.

        Row 0 is person 1's top-K, row 1 is person 2's top-K, and so on — which
        is what you actually want to eyeball when several people are in frame.
        The left gutter labels each row. Rows are padded to equal width so the
        result is a single image the GUI can scroll.
        """
        import cv2

        tids = self.track_ids()
        if not tids:
            return None

        k = max_per_track or self.top_k
        widest = max(min(len(self.get(t)), k) for t in tids) or 1

        # Records where each tile landed, so a GUI can turn a click into the
        # record it belongs to: (x0, y0, x1, y1, track_id, rank).
        self.last_sheet_layout: list[tuple[int, int, int, int, int, int]] = []

        rows = []
        row_top = 0
        for tid in tids:
            recs = self.get(tid)[:k]
            if not recs:
                continue

            label = np.zeros((thumb, gutter, 3), dtype=np.uint8)
            label[:] = (32, 34, 38)
            cv2.putText(label, f"#{self.label_for(tid)}", (3, thumb // 2 - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1,
                        cv2.LINE_AA)
            cv2.putText(label, recs[0].class_name[:6], (4, thumb // 2 + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 200, 150), 1,
                        cv2.LINE_AA)
            tiles = [label]

            for rank, rec in enumerate(recs, 1):
                t = cv2.resize(rec.crop, (thumb, thumb),
                               interpolation=cv2.INTER_AREA)
                cv2.rectangle(t, (0, 0), (thumb - 1, thumb - 1),
                              (70, 70, 70), 1)
                cv2.putText(t, f"{rank}", (4, 15), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (0, 255, 0), 1, cv2.LINE_AA)
                cv2.putText(t, f"{rec.score:.2f}", (4, thumb - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1,
                            cv2.LINE_AA)
                x0 = gutter + (rank - 1) * thumb
                self.last_sheet_layout.append(
                    (x0, row_top, x0 + thumb, row_top + thumb, tid, rank))
                tiles.append(t)

            # Pad short rows so every row is the same width.
            while len(tiles) - 1 < widest:
                tiles.append(np.zeros((thumb, thumb, 3), dtype=np.uint8))
            rows.append(np.hstack(tiles))
            row_top += thumb + 3          # tile height + separator

        if not rows:
            return None

        sep = np.zeros((3, rows[0].shape[1], 3), dtype=np.uint8)
        stacked: list[np.ndarray] = []
        for i, row in enumerate(rows):
            if i:
                stacked.append(sep)
            stacked.append(row)
        return np.vstack(stacked)

    def make_contact_sheet(self, thumb: int = 96, per_row: int = 8,
                           records: Iterable[DetectionRecord] | None = None) -> np.ndarray | None:
        """Tile the best crops into one image — one tile per track by default."""
        import cv2

        recs = list(records) if records is not None else self.best_per_track()
        if not recs:
            return None

        multiclass = len({r.class_name for r in recs}) > 1
        tiles = []
        for r in recs:
            t = cv2.resize(r.crop, (thumb, thumb), interpolation=cv2.INTER_AREA)
            cv2.rectangle(t, (0, 0), (thumb - 1, thumb - 1), (60, 60, 60), 1)
            top = (f"{r.class_name[:8]} {r.track_id}" if multiclass
                   else f"{r.track_id}")
            cv2.putText(t, top, (3, 14), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (0, 255, 0), 1, cv2.LINE_AA)
            cv2.putText(t, f"{r.score:.2f}", (3, thumb - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1,
                        cv2.LINE_AA)
            tiles.append(t)

        rows = []
        for i in range(0, len(tiles), per_row):
            row = tiles[i:i + per_row]
            while len(row) < per_row:
                row.append(np.zeros((thumb, thumb, 3), dtype=np.uint8))
            rows.append(np.hstack(row))
        return np.vstack(rows)


# Backwards-compatible alias — this class was face-only before multi-class
# model support was added.
BestFaceGallery = BestImageGallery


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import cv2

    print("Quality self-test: a sharp synthetic crop should out-score a blurred "
          "copy of itself.\n")

    rng = np.random.default_rng(0)
    sharp = rng.integers(0, 255, (120, 100, 3), dtype=np.uint8)
    cv2.rectangle(sharp, (20, 20), (80, 100), (255, 255, 255), -1)
    cv2.circle(sharp, (40, 50), 6, (0, 0, 0), -1)
    cv2.circle(sharp, (62, 50), 6, (0, 0, 0), -1)
    blurred = cv2.GaussianBlur(sharp, (15, 15), 0)

    box = (0.0, 0.0, 100.0, 120.0)
    for label, img in (("sharp", sharp), ("blurred", blurred)):
        s, comp = score_face(img, box, 0.9)
        parts = "  ".join(f"{k}={v:.3f}" for k, v in comp.items())
        print(f"  {label:<8} score={s:.3f}   {parts}")

    print("\nGallery test — 12 crops of one track, top 5 kept:")
    gallery = BestFaceGallery(top_k=5, cooldown_frames=0)

    class _T:
        def __init__(self, b, s, i):
            self.boxes, self.scores, self.track_ids = b, s, i

        def __len__(self):
            return len(self.boxes)

    frame = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    for f in range(12):
        k = 1 + 2 * (f % 6)
        frame_f = cv2.GaussianBlur(frame, (k, k), 0)
        gallery.update(
            frame_f,
            _T(np.array([[100, 100, 220, 250]], np.float32),
               np.array([0.9], np.float32),
               np.array([7], np.int32)),
            frame_index=f,
        )
    print(f"  stats: {gallery.stats}")
    for rec in gallery.get(7):
        print("   ", rec.summary())
