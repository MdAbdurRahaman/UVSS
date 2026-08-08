"""
UVSS vehicle face detection — inference package.

    from src.detector import FaceDetector, Detections
    from src.tracker import FaceTracker, TrackedDetections
    from src.quality import BestFaceGallery, score_face

Submodules import their heavy dependencies lazily, so importing this package
does not pull in torch/onnxruntime until a detector is actually constructed.
"""

__version__ = "1.0.0"

__all__ = [
    "detector",
    "tracker",
    "quality",
    "utils",
]
