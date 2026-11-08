"""Synthetic but realistic-ish test media: speech-like audio, clips with jump cuts and music."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from clippr.media.ffmpeg import run

SR = 16000


def speechlike(seconds: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * SR), dtype=np.float32)
    t = 0
    while t < len(out):
        n = int(rng.uniform(0.06, 0.35) * SR)
        if rng.random() < 0.18:
            t += n  # pause
            continue
        tt = np.arange(n) / SR
        f0 = rng.uniform(90, 260)
        sig = sum(np.sin(2 * np.pi * f0 * k * tt) / k for k in range(1, 8))
        sig = sig + rng.normal(0, 0.3, n) * (rng.random() < 0.3)
        env = np.hanning(n) * rng.uniform(0.2, 1.0)
        seg = (sig * env).astype(np.float32)[: len(out) - t]
        out[t: t + len(seg)] += seg
        t += n
    return out / (np.abs(out).max() + 1e-9) * 0.8


def music(seconds: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * SR), dtype=np.float32)
    beat = int(0.5 * SR)
    for i in range(0, len(out), beat):
        tt = np.arange(min(beat, len(out) - i)) / SR
        chord = sum(np.sin(2 * np.pi * f * tt) for f in rng.choice([220, 262, 330, 392, 440, 523], 3))
        out[i: i + len(tt)] = chord * np.exp(-tt * 3)
    return out / (np.abs(out).max() + 1e-9) * 0.8


def write_wav(path: Path, x: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def make_stream_and_clip(d: Path, stream_s: float = 1200, at: float = 754.0, clip_s: float = 30.0, *, video: bool = False):
    """Returns (stream_path, clip_path). The clip has a 3 s jump cut, music at -8 dB, lower volume, AAC."""
    stream = speechlike(stream_s, 1)
    a, cut_from, cut_to, b = at, at + 12, at + 15, at + clip_s + 3
    clip = np.concatenate([stream[int(a * SR): int(cut_from * SR)], stream[int(cut_to * SR): int(b * SR)]])
    clip = clip * 0.6 + music(len(clip) / SR, 7) * 0.24
    sw, cw = write_wav(d / "stream.wav", stream), write_wav(d / "clip.wav", clip)
    if video:
        sp, cp = d / "stream.mp4", d / "clip.mp4"
        run(["-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={stream_s}", "-i", str(sw),
             "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-c:a", "aac", "-b:a", "96k", str(sp)])
        run(["-f", "lavfi", "-i", f"testsrc=size=720x1280:rate=30:duration={len(clip) / SR}", "-i", str(cw),
             "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-c:a", "aac", "-b:a", "96k", str(cp)])
    else:
        sp, cp = d / "stream.m4a", d / "clip.m4a"
        run(["-i", str(sw), "-c:a", "aac", "-b:a", "64k", str(sp)])
        run(["-i", str(cw), "-c:a", "aac", "-b:a", "96k", str(cp)])
    return sp, cp
