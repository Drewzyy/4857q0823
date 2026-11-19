"""Captions already burned into the footage: when the stream (or the post it came from) shows its own captions,
Vyral's word-by-word captions would sit on top of them, so they're left off for that clip.

A caption is a wide line of text, centered, in the middle or lower part of the picture, that changes as people
talk. Found on a handful of frames with OpenCV's text-edge trick (gradient, then joining letters into lines); a
logo, a game's fixed on-screen display or a chat box at the side doesn't count, because it doesn't change or
isn't centered.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from .ffmpeg import FFmpegError, run

SAMPLES = 8
WIDTH = 640


def _lines(gray) -> list[tuple[int, int, int, int]]:
    """Text-line boxes (x, y, w, h) in the middle-to-bottom band of one frame, centered ones only."""
    import cv2
    h, w = gray.shape
    top = int(h * 0.42)
    band = gray[top:int(h * 0.95)]
    grad = cv2.morphologyEx(band, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    _, bw = cv2.threshold(grad, 110, 255, cv2.THRESH_BINARY)  # caption text has hard, high-contrast edges (an outline)
    joined = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, w // 40), 3)))
    parts = []
    for c in cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, bw_, bh = cv2.boundingRect(c)
        if 0.02 * h < bh < 0.12 * h and bw_ > 0.03 * w:
            parts.append([x, y, x + bw_, y + bh])
    # Words of one line can come out as separate boxes: join boxes at the same height.
    parts.sort(key=lambda p: (p[1], p[0]))
    rows: list[list[int]] = []
    for p in parts:
        r = next((r for r in rows if abs((r[1] + r[3]) / 2 - (p[1] + p[3]) / 2) < 0.02 * h), None)
        if r:
            r[0], r[1], r[2], r[3] = min(r[0], p[0]), min(r[1], p[1]), max(r[2], p[2]), max(r[3], p[3])
        else:
            rows.append(list(p))
    found = []
    for x0, y0, x1, y1 in rows:
        bw_, bh = x1 - x0, y1 - y0
        density = float((bw[y0:y1, x0:x1] > 0).mean())
        if bw_ > 0.1 * w and bw_ / bh > 2.5 and 0.1 < density < 0.85 and abs((x0 + x1) / 2 - w / 2) < 0.15 * w:
            found.append((x0, y0 + top, bw_, bh))
    return found


def has_captions(src: Path, start: float, dur: float) -> bool:
    """Whether this stretch of footage already shows captions."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False
    frames = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(SAMPLES):
            out = Path(tmp) / f"c{i}.png"
            try:
                run(["-ss", f"{start + dur * (i + 0.5) / SAMPLES:.3f}", "-i", str(src), "-frames:v", "1", "-vf", f"scale={WIDTH}:-2,format=gray", str(out)], timeout=60)
            except FFmpegError:
                continue
            g = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
            if g is not None:
                frames.append((g, _lines(g)))
    if len(frames) < SAMPLES * 0.6:
        return False
    h = frames[0][0].shape[0]
    # The text line that sits at the same height on most frames...
    for _, boxes in frames:
        for x, y, w, bh in boxes:
            mid = y + bh / 2
            at = [next((b for b in bx if abs(b[1] + b[3] / 2 - mid) < 0.04 * h), None) for _, bx in frames]
            hits = [(g, b) for (g, _), b in zip(frames, at) if b]
            if len(hits) < len(frames) * 0.5:
                continue
            # ...and whose words change from frame to frame: captions. The same words throughout is a title or a logo.
            # Compared on the text's own hard edges only, so moving footage behind a fixed title doesn't count as change.
            y0, y1, x0, x1 = max(0, int(mid - 0.035 * h)), int(mid + 0.035 * h), int(frames[0][0].shape[1] * 0.12), int(frames[0][0].shape[1] * 0.88)
            masks = [cv2.morphologyEx(g[y0:y1, x0:x1], cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 110 for g, _ in hits]
            overlap = [float((a & b).sum()) / max(1.0, float((a | b).sum())) for a, b in zip(masks, masks[1:])]
            # Measured on real clips: a fixed title overlaps itself 0.6 to 0.95 from frame to frame, captions 0.1 to 0.45.
            if overlap and float(np.median(overlap)) < 0.45:
                return True
    return False
