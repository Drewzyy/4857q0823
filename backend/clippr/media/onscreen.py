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

SAMPLES = 14  # captions pause when nobody talks: more frames so short silences don't hide them
WIDTH = 640


def _lines(gray, band_from: float = 0.22, band_to: float = 0.95) -> list[tuple[int, int, int, int]]:
    """Text-line boxes (x, y, w, h) in a band of one frame (by default from a fifth of the way down, where TikTok-style
    captions sit, to the bottom), centered ones only."""
    import cv2
    h, w = gray.shape
    top = int(h * band_from)
    band = gray[top:int(h * band_to)]
    grad = cv2.morphologyEx(band, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    _, bw = cv2.threshold(grad, 110, 255, cv2.THRESH_BINARY)  # caption text has hard, high-contrast edges (an outline)
    # Long straight edges (the picture's own stripes, borders, UI panels) aren't letters. Left in, they run through a
    # caption and merge it into one shape too tall to be text, so busy footage hid its captions (the double captions).
    import numpy as np
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(w * 0.09)))))
    hori = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, w // 5), 1)))
    bw = cv2.subtract(bw, cv2.dilate(cv2.bitwise_or(vert, hori), np.ones((3, 3), np.uint8)))
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
            if len(hits) < len(frames) * 0.35:
                continue
            # ...and whose words change from frame to frame: captions. The same words throughout is a title or a logo.
            # Compared on the text's own hard edges only, so moving footage behind a fixed title doesn't count as change.
            y0, y1, x0, x1 = max(0, int(mid - 0.035 * h)), int(mid + 0.035 * h), int(frames[0][0].shape[1] * 0.12), int(frames[0][0].shape[1] * 0.88)
            masks = []
            for g, b in hits:  # each frame's own text line only: the picture around it would make any two frames look alike
                m = cv2.morphologyEx(g[y0:y1, x0:x1], cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 110
                keep = np.zeros_like(m)
                keep[:, max(0, b[0] - x0 - 4):max(0, b[0] + b[2] - x0 + 4)] = True
                masks.append(m & keep)
            overlap = [float((a & b).sum()) / max(1.0, float((a | b).sum())) for a, b in zip(masks, masks[1:])]
            # Each frame's own text line only: a fixed title overlaps itself almost fully (0.9 to 1) from frame to frame,
            # changing captions about half (the same capital letters on the same baseline) or less.
            if overlap and float(np.median(overlap)) < 0.75:
                return True
    return False
