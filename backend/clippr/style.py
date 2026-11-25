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
- sound effects: sudden short loud hits over the talking (rough: a scream can look like one), and which of Vyral's
  sounds it is when one matches;
- zoom-ins: the picture suddenly scaling up within a shot.
Clips with more views count for more (their views are read from the post when it's learned). Transitions and
sounds that aren't in Vyral's library aren't recognized.

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


def _sfx(path: Path, dur: float) -> list[float]:
    """When short loud hits stand out over the talking: a rough list of sound effects (seconds into the clip)."""
    from .grade import loudness
    try:
        db = loudness(path, 0, dur)
    except FFmpegError:
        return []
    hits, i = [], 20
    talking, loudest = float(np.median(db)), float(np.percentile(db, 95))
    while i < len(db) - 8:
        base = float(np.median(db[i - 20:i]))
        # Over ongoing talk (not a word starting after a pause), sudden, louder than the talking ever gets, gone in half a second.
        if base > talking - 4 and db[i] - base > 12 and db[i] > loudest + 4 and float(db[i + 4:i + 8].mean()) - base < 4:
            hits.append(round(i * 0.1, 1))
            i += 10
        i += 1
    return hits


def _shape(samples: np.ndarray) -> np.ndarray:
    """A sound's spectrum in 32 bands (log), for telling sounds apart regardless of how loud they are."""
    spec = np.abs(np.fft.rfft(samples * np.hanning(len(samples)))) + 1e-9
    bands = np.array_split(np.log(spec[: len(spec) // 2]), 32)
    v = np.array([b.mean() for b in bands])
    v -= v.mean()
    return v / (np.linalg.norm(v) + 1e-9)


def _audio(path: Path, start: float, secs: float) -> np.ndarray:
    import subprocess
    from .media.ffmpeg import SPAWN, ffmpeg_exe
    p = subprocess.run([ffmpeg_exe(), "-v", "error", "-ss", f"{max(start, 0):.2f}", "-t", f"{secs:.2f}", "-i", str(path),
                        "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, timeout=60, **SPAWN)
    return np.frombuffer(p.stdout, np.float32)


def _which_sound(path: Path, hits: list[float], tmp: Path) -> str | None:
    """Which of Vyral's sound effects your clip uses, matched by the shape of its sound, or None."""
    from .media import sfx
    if not hits:
        return None
    lib = {}
    for name in sfx.SOUNDS:
        x = _audio(sfx.path(name, tmp / "sfx"), 0, 0.6)
        if len(x) > 1000:
            lib[name] = _shape(x)
    votes: dict[str, int] = {}
    for t in hits:
        x = _audio(path, t - 0.05, 0.6)
        if len(x) < 1000 or not lib:
            continue
        name, score = max(((n, float(_shape(x) @ v)) for n, v in lib.items()), key=lambda z: z[1])
        if score > 0.85:
            votes[name] = votes.get(name, 0) + 1
    return max(votes, key=votes.get) if votes else None


def _grew(a: np.ndarray, b: np.ndarray) -> bool:
    """Whether frame b is frame a punched in: a magnified copy of a (1.1 to 1.4 times, around the middle) matches b
    much better than a itself does. A cut matches neither; movement in the picture doesn't match the magnified copy."""
    import cv2
    a, b = a.astype(np.float32), b.astype(np.float32)
    same = float(np.abs(b - a).mean())
    if same < 4:  # nothing changed
        return False
    h, w = a.shape
    for s in (1.1, 1.2, 1.3, 1.4):
        cw, ch = int(w / s), int(h / s)
        x, y = (w - cw) // 2, (h - ch) // 2
        zoomed = cv2.resize(a[y:y + ch, x:x + cw], (w, h), interpolation=cv2.INTER_LINEAR)
        if float(np.abs(b - zoomed).mean()) < 0.5 * same:
            return True
    return False


def _zooms(path: Path) -> int:
    """Punch-ins: the picture (or one panel of a stacked layout) suddenly magnified within one shot, counted once each."""
    import subprocess
    from .media.ffmpeg import SPAWN, ffmpeg_exe
    w, h, fps = 180, 320, 4
    p = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True, timeout=600, **SPAWN)
    frames = np.frombuffer(p.stdout, np.uint8)[: (len(p.stdout) // (w * h)) * w * h].reshape(-1, h, w)
    found, last = 0, -9.0
    for k in range(1, len(frames)):
        t = k / fps
        if t - last < 1.5:
            continue
        a, b = frames[k - 1], frames[k]
        if _grew(a, b) or _grew(a[: h // 2], b[: h // 2]) or _grew(a[h // 2:], b[h // 2:]) or _grew(a[h // 3:], b[h // 3:]):
            found += 1
            last = t
    return found


def analyze(path: Path) -> dict:
    """What one clip's edit looks like, measured."""
    dur = probe(path).duration or 0.0
    tmp = Path(tempfile.mkdtemp(prefix="vyral-style-"))
    try:
        cuts = _cuts(path)
        hits = _sfx(path, dur)
        return {"length": round(dur, 1), "hook": _hook(path, dur), "cuts_per_min": round(len(cuts) / max(dur / 60, 0.25), 1),
                "layout": _layout(path, dur, tmp), "captions": bool(onscreen.has_captions(path, 0, dur)),
                "headline": _headline(path, dur, tmp), "sfx": len(hits), "sound": _which_sound(path, hits, tmp),
                "zooms": _zooms(path)}
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


def _weight(e: dict) -> float:
    """Clips that did better count more: 1 for a clip with no known views, up to about 7 for a million."""
    return 1.0 + float(np.log10(1 + e["views"])) if e.get("views") else 1.0


def _wmedian(pairs: list[tuple[float, float]]) -> float:
    pairs = sorted(pairs)
    half, run_ = sum(w for _, w in pairs) / 2, 0.0
    for v, w in pairs:
        run_ += w
        if run_ >= half:
            return v
    return pairs[-1][0]


def _wquant(pairs: list[tuple[float, float]], q: float) -> float:
    pairs = sorted(pairs)
    total, run_ = sum(w for _, w in pairs), 0.0
    for v, w in pairs:
        run_ += w
        if run_ >= q * total:
            return v
    return pairs[-1][0]


def profile_of(examples: list[dict]) -> dict | None:
    """Your style from the measured clips, the ones with more views counting more."""
    ex = [e for e in examples if e.get("features")]
    if len(ex) < MIN_EXAMPLES:
        return None
    ws = [(e["features"], _weight(e)) for e in ex]
    total = sum(w for _, w in ws)
    rate = lambda ok: round(sum(w for f, w in ws if ok(f)) / total, 2)  # noqa: E731
    hooks = [(f["hook"], w) for f, w in ws if f["hook"]]
    heads = [(f["headline"], w) for f, w in ws if f["headline"]]
    layouts = {k: round(sum(w for f, w in ws if f["layout"] == k), 2) for k in LAYOUTS}
    sounds: dict[str, float] = {}
    for f, w in ws:
        if f.get("sound"):
            sounds[f["sound"]] = sounds.get(f["sound"], 0) + w
    lengths = [(f["length"], w) for f, w in ws]
    return {"examples": len(ex), "weight": round(total, 1), "length": _wmedian(lengths), "length_low": _wquant(lengths, 0.2),
            "length_high": _wquant(lengths, 0.8), "hook_rate": rate(lambda f: f["hook"]),
            "hook_seconds": _wmedian(hooks) if hooks else 0.0, "cuts_per_min": _wmedian([(f["cuts_per_min"], w) for f, w in ws]),
            "layout": max(layouts, key=layouts.get), "layouts": layouts, "captions_rate": rate(lambda f: f["captions"]),
            "headline_rate": rate(lambda f: f["headline"]), "headline_seconds": _wmedian(heads) if heads else 0.0,
            "sfx_rate": rate(lambda f: f["sfx"]), "sound": max(sounds, key=sounds.get) if sounds else None,
            "zoom_rate": rate(lambda f: f.get("zooms"))}


def current(s: Session) -> dict | None:
    """Your learned style, or None until enough clips are measured (then Vyral's defaults apply)."""
    return _row(s).get("profile")


def view(s: Session) -> dict:
    row = _row(s)
    return {"examples": row.get("examples", [])[::-1], "profile": row.get("profile"), "needed": MIN_EXAMPLES}


def add(s: Session, url: str, features: dict | None, error: str | None = None, views: int | None = None) -> dict | None:
    row = _row(s)
    ex = [e for e in row.get("examples", []) if e["url"] != url]
    ex.append({"url": url, "at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "features": features, "error": error,
               "views": views})
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
    try:  # how many people watched it: the clips that did better count more in your style
        views = ctx.fetcher.post_details(url).views
    except Exception:
        views = None
    with ctx.db.session() as s:
        profile = add(s, url, feats, err, views)
    return {"features": feats, "error": err, "profile": profile, "views": views}
