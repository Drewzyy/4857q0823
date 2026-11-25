"""Your style, learned from the clips you send: Vyral watches each one and measures how it's edited, then cuts new
clips the same way.

Every link you post in the Discord inbox (and any you add in Settings > Muse & posting > Your style) is downloaded
and measured, on this computer:
- length;
- the hook: whether the clip opens on a few seconds that come back later (the climax first), and how long it is;
- cuts: how often the picture jumps (scene changes a minute);
- the layout: facecam on top and the game under it, two people one above the other, the streamer's face filling
  the frame, or the whole picture;
- captions: whether it has them;
- the headline: whether there's a line of text at the top at the start, and how long it stays;
- sound effects: sudden short loud hits over the talking (a rough count: a scream can look like one).
Zoom-ins and transitions aren't measured: telling a zoom from the camera moving needs more than these checks.

Once 3 clips are in, your style takes over from Vyral's defaults: new clips (and waiting ones, when you press
Apply) get your usual length range, a hook only if most of yours have one and as long as yours are, a headline only
if most of yours have one and for as long, sound effects only if most of yours have them, your usual layout, and
captions if most of yours have them. Settings lists every measured clip and what was learned, and Reset forgets it.
This is learning by measuring, not a neural network: it copies what can be measured and counted, not taste.
"""
from __future__ import annotations

import logging
import re
import shutil
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from .media import facecam, match, onscreen
from .media.ffmpeg import FFmpegError, probe, run
from .models import Setting

log = logging.getLogger("clippr.style")
KEY = "style"
MIN_EXAMPLES = 3
KEEP = 200
LAYOUTS = ("stacked", "two", "face", "full")


# ---------- measuring one clip ----------
def _cuts(path: Path) -> list[float]:
    err = run(["-i", str(path), "-vf", "select='gt(scene,0.32)',showinfo", "-an", "-f", "null", "-"], timeout=600)
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", err)]


def _hook(path: Path, dur: float) -> float:
    """Seconds of the opening that come back later in the clip (the climax shown first), or 0."""
    if dur < 15:
        return 0.0
    feats = match.extract_features(path)
    fps = match.FPS
    for secs in (6.0, 5.0, 4.0, 3.0, 2.0):
        ref, hay = feats[: int(secs * fps)], feats[int((secs + 2) * fps):]
        if len(hay) > len(ref) and match.find_in_stream(ref, hay, seg_seconds=secs, pad=0.0):
            return secs
    return 0.0


def _grab(path: Path, t: float, tmp: Path, gray: bool):
    import cv2
    out = tmp / f"g{t:.2f}.png"
    try:
        run(["-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=540:-2" + (",format=gray" if gray else ""), str(out)], timeout=60)
    except FFmpegError:
        return None
    return cv2.imread(str(out), cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)


def _split_row(gray) -> float | None:
    """Where a picture is split into a top and a bottom panel (as a share of the height), or None."""
    import cv2
    h = gray.shape[0]
    edges = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)).mean(axis=1)
    lo, hi = int(h * 0.25), int(h * 0.62)
    row = lo + int(np.argmax(edges[lo:hi]))
    return row / h if edges[row] > 4 * float(np.median(edges)) + 8 else None


def _layout(path: Path, dur: float, tmp: Path) -> str:
    times = [dur * (i + 0.5) / 8 for i in range(8)]
    splits, faces_top, faces_bottom, big = [], 0, 0, 0
    for t in times:
        img = _grab(path, t, tmp, gray=False)
        if img is None:
            continue
        import cv2
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        split = _split_row(gray)
        splits.append(split)
        h, w = gray.shape
        for x, y, fw, fh in facecam._faces(img):
            cy = (y + fh / 2) / h
            if fw / w > 0.3:
                big += 1
            if split is not None:
                faces_top += cy < split
                faces_bottom += cy > split
    n = len(splits) or 1
    stacked = sum(1 for x in splits if x is not None) >= n * 0.6
    if stacked and faces_top >= n * 0.4 and faces_bottom >= n * 0.4:
        return "two"
    if stacked:
        return "stacked"
    return "face" if big >= n * 0.5 else "full"


def _headline(path: Path, dur: float, tmp: Path) -> float:
    """How long a line of text sits at the top from the start (seconds), 0 if none, the whole clip if it stays."""
    first, seen = None, 0.0
    for t in (0.8, 1.8, 3, 4.5, 6, 8, 10, 13, 16, 20, 25, 30, 40, 50, 60):
        if t >= dur:
            break
        g = _grab(path, t, tmp, gray=True)
        if g is None:
            continue
        lines = onscreen._lines(g, 0.03, 0.34)
        if first is None:
            if lines:
                first, seen = lines[0], t
            elif t > 2:
                return 0.0  # nothing at the top in the first two seconds: no headline
            continue
        if not any(abs(b[1] - first[1]) < 0.04 * g.shape[0] for b in lines):
            return seen  # gone
        seen = t
    return round(dur, 1) if first is not None else 0.0


def _sfx(path: Path, dur: float) -> int:
    """Short loud hits well above the talking around them: a rough count of sound effects."""
    from .grade import loudness
    try:
        db = loudness(path, 0, dur)
    except FFmpegError:
        return 0
    hits, i = 0, 20
    talking, loudest = float(np.median(db)), float(np.percentile(db, 95))
    while i < len(db) - 8:
        base = float(np.median(db[i - 20:i]))
        # Over ongoing talk (not a word starting after a pause), sudden, louder than the talking ever gets, gone in half a second.
        if base > talking - 4 and db[i] - base > 12 and db[i] > loudest + 4 and float(db[i + 4:i + 8].mean()) - base < 4:
            hits += 1
            i += 10
        i += 1
    return hits


def analyze(path: Path) -> dict:
    """What one clip's edit looks like, measured."""
    dur = probe(path).duration or 0.0
    tmp = Path(tempfile.mkdtemp(prefix="vyral-style-"))
    try:
        cuts = _cuts(path)
        return {"length": round(dur, 1), "hook": _hook(path, dur), "cuts_per_min": round(len(cuts) / max(dur / 60, 0.25), 1),
                "layout": _layout(path, dur, tmp), "captions": bool(onscreen.has_captions(path, 0, dur)),
                "headline": _headline(path, dur, tmp), "sfx": _sfx(path, dur)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- the profile ----------
def _row(s: Session) -> dict:
    r = s.get(Setting, KEY)
    return dict(r.value) if r else {"examples": []}


def _save(s: Session, value: dict) -> None:
    r = s.get(Setting, KEY)
    if r:
        r.value = value
    else:
        s.add(Setting(key=KEY, value=value))


def profile_of(examples: list[dict]) -> dict | None:
    fs = [e["features"] for e in examples if e.get("features")]
    if len(fs) < MIN_EXAMPLES:
        return None
    lengths = sorted(f["length"] for f in fs)
    q = lambda p: lengths[min(len(lengths) - 1, int(p * (len(lengths) - 1) + 0.5))]  # noqa: E731
    hooks = [f["hook"] for f in fs if f["hook"]]
    heads = [f["headline"] for f in fs if f["headline"]]
    layouts = {k: sum(1 for f in fs if f["layout"] == k) for k in LAYOUTS}
    return {"examples": len(fs), "length": statistics.median(lengths), "length_low": q(0.2), "length_high": q(0.8),
            "hook_rate": round(len(hooks) / len(fs), 2), "hook_seconds": statistics.median(hooks) if hooks else 0.0,
            "cuts_per_min": statistics.median(f["cuts_per_min"] for f in fs),
            "layout": max(layouts, key=layouts.get), "layouts": layouts,
            "captions_rate": round(sum(f["captions"] for f in fs) / len(fs), 2),
            "headline_rate": round(len(heads) / len(fs), 2), "headline_seconds": statistics.median(heads) if heads else 0.0,
            "sfx_rate": round(sum(1 for f in fs if f["sfx"]) / len(fs), 2)}


def current(s: Session) -> dict | None:
    """Your learned style, or None until enough clips are measured (then Vyral's defaults apply)."""
    return _row(s).get("profile")


def view(s: Session) -> dict:
    row = _row(s)
    return {"examples": row.get("examples", [])[::-1], "profile": row.get("profile"), "needed": MIN_EXAMPLES}


def add(s: Session, url: str, features: dict | None, error: str | None = None) -> dict | None:
    row = _row(s)
    ex = [e for e in row.get("examples", []) if e["url"] != url]
    ex.append({"url": url, "at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "features": features, "error": error})
    row["examples"] = ex[-KEEP:]
    row["profile"] = profile_of(row["examples"])
    _save(s, row)
    return row["profile"]


def forget(s: Session, url: str | None = None) -> None:
    row = _row(s)
    row["examples"] = [e for e in row.get("examples", []) if url and e["url"] != url]
    row["profile"] = profile_of(row["examples"])
    _save(s, row)


def learn(ctx, url: str) -> dict:
    """Download a clip you made (or like) and add how it's edited to your style."""
    with ctx.db.session() as s:
        if any(e["url"] == url and e.get("features") for e in _row(s).get("examples", [])):
            return {"skipped": "already learned"}
    work = Path(tempfile.mkdtemp(prefix="vyral-learn-"))
    try:
        video = ctx.fetcher.download_post(url, work)
        feats = analyze(Path(video))
        err = None
    except Exception as e:  # a private or deleted post: kept in the list with why, never stops the inbox
        log.warning("couldn't learn from %s: %s", url, e)
        feats, err = None, str(e)[:200]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with ctx.db.session() as s:
        profile = add(s, url, feats, err)
    return {"features": feats, "error": err, "profile": profile}
