"""Find a streamer's facecam: a small face that stays in one corner or edge while other content fills the screen.

When one is found the clip is laid out stacked: the content on top, the facecam scaled up underneath. A face in
the middle of the frame or filling much of it is the streamer just talking to camera, so the normal framing stays.
Detection is OpenCV's YuNet face model (bundled, MIT licensed; handles turned and partly covered faces), with
the older Haar model as a fallback, on a dozen frames. No network, about a second per clip. When it misses, the
user marks the facecam in the editor once per streamer.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from .ffmpeg import FFmpegError, run

log = logging.getLogger("clippr.facecam")

SAMPLES = 12
SAMPLE_WIDTH = 960  # facecams are small: enough pixels for a face a few percent of the frame wide
MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
CAM_SHARE = 0.4  # share of the output height the facecam panel takes in the stacked layout


def _faces(img) -> list[tuple[int, int, int, int]]:
    import cv2
    h, w = img.shape[:2]
    if MODEL.exists() and hasattr(cv2, "FaceDetectorYN"):
        try:
            det = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), 0.55, 0.3, 50)
            _, found = det.detect(img)
            return [tuple(int(v) for v in f[:4]) for f in (found if found is not None else [])]
        except cv2.error:
            log.exception("YuNet failed; using the older face model")
    model = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    found = model.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(max(16, h // 40),) * 2)
    return [tuple(int(v) for v in f) for f in found]


def pick(frames: list[list[tuple[int, int, int, int]]], width: int, height: int) -> tuple[float, float, float] | None:
    """The facecam's face as (center x, center y, face width), all as shares of the frame, or None.

    It counts only if the same small, off-center face shows up in about a third of the sampled frames or more."""
    cands = []
    for faces in frames:
        for x, y, w, h in faces:
            cx, cy, fw = (x + w / 2) / width, (y + h / 2) / height, w / width
            small = fw < 0.22
            off_center = abs(cx - 0.5) > 0.18 or abs(cy - 0.5) > 0.2
            if small and off_center:
                cands.append((cx, cy, fw))
    best, support = None, 0
    for c in cands:
        near = [d for d in cands if abs(d[0] - c[0]) < 0.06 and abs(d[1] - c[1]) < 0.08]
        if len(near) > support:
            best, support = near, len(near)
    if not best or support < max(2, len(frames) * 0.35):  # the streamer can look away or duck out of frame
        return None
    n = len(best)
    return sum(d[0] for d in best) / n, sum(d[1] for d in best) / n, sum(d[2] for d in best) / n


def cam_box(face: tuple[float, float, float], stream_aspect: float, panel_aspect: float) -> list[float]:
    """The area of the source (x, y, w, h as shares) shown in the facecam panel: the face with room around it,
    shaped like the panel and kept inside the frame."""
    cx, cy, fw = face
    w = min(1.0, fw * 3.2)
    h = w * stream_aspect / panel_aspect
    if h > 1:
        h, w = 1.0, panel_aspect / stream_aspect
    x = min(max(cx - w / 2, 0), 1 - w)
    y = min(max(cy - h * 0.45, 0), 1 - h)
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def sample(src: Path, start: float, dur: float) -> tuple[list[list[tuple[int, int, int, int]]], tuple[int, int] | None]:
    """Faces in a dozen frames spread over the cut, and the frame size they were found at."""
    try:
        import cv2
    except ImportError:
        return [], None
    frames: list = []
    size = None
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(SAMPLES):
            t = start + dur * (i + 0.5) / SAMPLES
            out = Path(tmp) / f"f{i}.jpg"
            try:
                run(["-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-vf", f"scale={SAMPLE_WIDTH}:-2", "-q:v", "3", str(out)], timeout=60)
            except FFmpegError:
                continue
            img = cv2.imread(str(out))
            if img is None:
                continue
            size = img.shape[1], img.shape[0]
            frames.append(_faces(img))
    return frames, size


def detect(src: Path, start: float, dur: float, stream_aspect: float, panel_aspect: float,
           sampled: tuple | None = None) -> list[float] | None:
    """The facecam's box in the source for this cut, or None if there isn't one (or it couldn't be checked)."""
    frames, size = sampled or sample(src, start, dur)
    if not frames or not size:
        return None
    face = pick(frames, *size)
    log.info("facecam %s in %d frames", "found" if face else "not found", len(frames))
    return cam_box(face, stream_aspect, panel_aspect) if face else None


def subject_pan(frames: list, size: tuple[int, int] | None, crop_share: float) -> float | None:
    """Where to point a narrow crop (crop_share of the width) so the main person stays in it, as pan_x 0..1, or
    None to keep it centered. One position for the whole clip, never following the face around (steady beats
    jittery: the approach the most-used open-source clippers settled on). The main person is the biggest face
    seen in at least a third of the frames; a crowd or nobody keeps the center."""
    if not frames or not size or crop_share >= 0.98:
        return None
    w = size[0]
    biggest = []
    for faces in frames:
        if faces:
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            if fw / w >= 0.04:  # big enough to be the subject, not a face in the background
                biggest.append((x + fw / 2) / w)
    if len(biggest) < max(2, len(frames) / 3):
        return None
    cx = sorted(biggest)[len(biggest) // 2]
    if max(biggest) - min(biggest) > 0.5:  # people on both sides: no single framing keeps them all
        return None
    return round(min(1.0, max(0.0, (cx - crop_share / 2) / (1 - crop_share))), 3)
