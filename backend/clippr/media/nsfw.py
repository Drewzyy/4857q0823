"""Nudity and sexual content in the picture: every clip's frames are looked at before it can be reviewed or posted.

Uses Yahoo's open_nsfw model (BSD 2-clause, see models/OPEN_NSFW-LICENSE.txt). It scores how likely a picture is to
be pornographic or sexually explicit, run here on this computer through OpenCV (already part of Vyral). It's a
filter, not a judge: it can miss things (a small corner of the screen, a fast cut) and can be fooled by a lot of
skin (a pool stream), so a clear result quarantines the clip and a borderline one sends it to a person.

Frames: one every 1.5 seconds across the clip (at most 40), each looked at whole and as a centre square, so a
webcam or a game window in the middle of a wide stream is seen close up too.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

from .ffmpeg import SPAWN, FFmpegError, ffmpeg_exe

log = logging.getLogger("clippr.nsfw")
MODELS = Path(__file__).parent / "models"
EVERY = 1.5
MOST = 40
FAIL, FAIL_ONCE, REVIEW = 0.85, 0.95, 0.6  # nudity likelihood: in 2+ frames / in any frame / worth a look
_local = threading.local()


def _net():
    if getattr(_local, "net", None) is None:
        import cv2
        _local.net = cv2.dnn.readNetFromCaffe(str(MODELS / "open_nsfw.prototxt"), str(MODELS / "open_nsfw.caffemodel"))
    return _local.net


def score_image(bgr: np.ndarray) -> float:
    """0..1: how likely this picture is sexually explicit. bgr: an image as OpenCV reads it."""
    import cv2
    img = cv2.resize(bgr, (256, 256), interpolation=cv2.INTER_AREA)[16:240, 16:240]
    net = _net()
    net.setInput(cv2.dnn.blobFromImage(img, 1.0, (224, 224), (104, 117, 123), swapRB=False))
    return float(net.forward()[0][1])


def _frames(path: Path, start: float, dur: float):
    """(seconds into the clip, frame) every EVERY seconds, 640 wide, read straight from FFmpeg."""
    import subprocess
    n = max(1, min(MOST, int(dur / EVERY)))
    step = dur / n
    for i in range(n):
        t = start + (i + 0.5) * step
        p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path),
                            "-frames:v", "1", "-vf", "scale=640:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, timeout=60, **SPAWN)
        if p.returncode != 0 or not p.stdout:
            continue
        import cv2
        frame = cv2.imdecode(np.frombuffer(p.stdout, np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            yield t - start, frame


def scan(path: Path, start: float, dur: float) -> dict:
    """{"max": highest score, "at": seconds into the clip, "hits": frames over FAIL, "level": fail | review | pass}."""
    worst, at, hits = 0.0, None, 0
    try:
        for t, frame in _frames(path, start, dur):
            h, w = frame.shape[:2]
            side = min(h, w)
            middle = frame[(h - side) // 2:(h + side) // 2, (w - side) // 2:(w + side) // 2]
            s = max(score_image(frame), score_image(middle))
            hits += s >= FAIL
            if s > worst:
                worst, at = s, round(t, 1)
    except (FFmpegError, OSError, Exception) as e:  # never blocks a clip silently: an unreadable picture goes to a person
        log.warning("picture check failed for %s: %s", path.name, e)
        return {"max": None, "at": None, "hits": 0, "level": "review", "error": str(e)[:200]}
    level = "fail" if hits >= 2 or worst >= FAIL_ONCE else "review" if worst >= REVIEW else "pass"
    return {"max": round(worst, 3), "at": at, "hits": int(hits), "level": level}
