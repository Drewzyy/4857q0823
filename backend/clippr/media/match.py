"""Find where a short clip came from inside a long stream, using audio.

Clippers almost always keep the streamer's original audio (often with music or effects on top),
so audio alignment is the most reliable signal. The reference is split into segments, each
segment is located with normalized cross-correlation over band-energy features, and the
segments that agree give the start and end in the stream. Jump cuts are handled because each
segment is located independently; the clip is rebuilt from the continuous original span.
Nothing below the confidence threshold is reported as a match.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .ffmpeg import decode_audio_chunks

SR = 8000
WIN = 512
HOP = 320  # 40 ms -> 25 feature frames per second
FPS = SR / HOP
BANDS = 16


def _band_matrix() -> np.ndarray:
    freqs = np.fft.rfftfreq(WIN, 1 / SR)
    edges = np.geomspace(150, 3800, BANDS + 1)
    m = np.zeros((len(freqs), BANDS), dtype=np.float32)
    for b in range(BANDS):
        m[(freqs >= edges[b]) & (freqs < edges[b + 1]), b] = 1.0
    return m


_BAND = _band_matrix()
_WINDOW = np.hanning(WIN).astype(np.float32)


def _frames_to_features(samples: np.ndarray) -> np.ndarray:
    n = 1 + (len(samples) - WIN) // HOP if len(samples) >= WIN else 0
    if n <= 0:
        return np.zeros((0, BANDS), dtype=np.float32)
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(samples[idx] * _WINDOW, axis=1)).astype(np.float32)
    return np.log1p(spec @ _BAND * 50.0)


def _highpass(feats: np.ndarray, width: int = 25) -> np.ndarray:
    """Remove slow loudness/EQ changes so only the moment-to-moment pattern is compared."""
    if len(feats) == 0:
        return feats
    k = np.ones(width, dtype=np.float32) / width
    smooth = np.stack([np.convolve(feats[:, b], k, mode="same") for b in range(feats.shape[1])], axis=1)
    return (feats - smooth).astype(np.float32)


def extract_features(path: Path) -> np.ndarray:
    parts, carry = [], np.zeros(0, dtype=np.float32)
    for chunk in decode_audio_chunks(path, SR):
        data = np.concatenate([carry, chunk])
        n = 1 + (len(data) - WIN) // HOP if len(data) >= WIN else 0
        if n > 0:
            parts.append(_frames_to_features(data[: (n - 1) * HOP + WIN]))
            carry = data[n * HOP:]
        else:
            carry = data
    feats = np.concatenate(parts) if parts else np.zeros((0, BANDS), dtype=np.float32)
    return _highpass(feats)


def _ncc(ref: np.ndarray, hay: np.ndarray) -> np.ndarray:
    """Mean over bands of normalized cross-correlation of ref (L x B) at every offset in hay (N x B)."""
    L, N = len(ref), len(hay)
    if N < L or L == 0:
        return np.zeros(0)
    out = np.zeros(N - L + 1)
    nfft = 1 << int(np.ceil(np.log2(N + L)))
    used = 0
    for b in range(ref.shape[1]):
        r = ref[:, b].astype(np.float64)
        r = r - r.mean()
        rn = np.linalg.norm(r)
        if rn < 1e-9:
            continue
        r /= rn
        h = hay[:, b].astype(np.float64)
        num = np.fft.irfft(np.fft.rfft(h, nfft) * np.conj(np.fft.rfft(r, nfft)), nfft)[: N - L + 1]
        c1 = np.concatenate([[0.0], np.cumsum(h)])
        c2 = np.concatenate([[0.0], np.cumsum(h * h)])
        s1 = c1[L:] - c1[:-L]
        s2 = c2[L:] - c2[:-L]
        den = np.sqrt(np.maximum(s2 - s1 * s1 / L, 1e-12))
        out += num / den
        used += 1
    return out / max(used, 1)


def _locate(seg: np.ndarray, hay: np.ndarray, chunk: int = 45000) -> tuple[int, float, float]:
    """Best offset, its score and how far it stands out (z-score), scanning hay in chunks."""
    L = len(seg)
    best_off, best, all_scores = -1, -1.0, []
    start = 0
    while start < len(hay) - L + 1:
        part = hay[start: start + chunk + L - 1]
        c = _ncc(seg, part)
        if len(c):
            i = int(np.argmax(c))
            if c[i] > best:
                best, best_off = float(c[i]), start + i
            all_scores.append(c[:: max(1, len(c) // 4000)])
        start += chunk
    if best_off < 0:
        return -1, 0.0, 0.0
    sample = np.concatenate(all_scores)
    z = (best - float(sample.mean())) / (float(sample.std()) + 1e-9)
    return best_off, best, z


@dataclass
class MatchResult:
    start: float  # seconds in the stream
    end: float
    confidence: float  # 0..1


def find_in_stream(ref: np.ndarray, hay: np.ndarray, *, seg_seconds: float = 6.0, min_score: float = 0.45,
                   min_z: float = 7.0, pad: float = 0.5) -> MatchResult | None:
    seg = int(seg_seconds * FPS)
    if len(ref) < int(2 * FPS) or len(hay) < len(ref):
        return None
    if len(ref) < seg:
        seg = len(ref)
    starts = list(range(0, len(ref) - seg + 1, seg)) or [0]
    hits = []
    for s in starts:
        off, score, z = _locate(ref[s: s + seg], hay)
        if off >= 0 and score >= min_score and z >= min_z:
            hits.append((s, off, score))
    if not hits:
        return None
    # Keep segments whose stream positions belong together (within 3 minutes of the median).
    med = float(np.median([o for _, o, _ in hits]))
    near = [h for h in hits if abs(h[1] - med) <= 180 * FPS]
    if len(near) < max(1, int(np.ceil(len(starts) * 0.34))):
        return None
    begin = min(o for _, o, _ in near) / FPS
    end = max(o + seg for _, o, _ in near) / FPS
    # Extend to cover reference audio before the first and after the last matched segment.
    first_s = min(s for s, _, _ in near)
    last_s = max(s for s, _, _ in near)
    begin -= first_s / FPS
    end += (len(ref) - (last_s + seg)) / FPS
    conf = float(np.mean([sc for _, _, sc in near])) * len(near) / len(starts)
    return MatchResult(max(0.0, begin - pad), min(len(hay) / FPS, end + pad), round(min(1.0, conf), 3))


def save_features(feats: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, feats.astype(np.float16))


def load_features(path: Path) -> np.ndarray:
    return np.load(path).astype(np.float32)
