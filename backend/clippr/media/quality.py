"""The quality check on every finished video, after the safety check and before review: is the file itself good
enough to post as it is?

One FFmpeg pass over the video (blackdetect, freezedetect, the loudness meter) plus its header:
- the right size for the page (1080x1920 and so on) and about the length the edit says;
- sound present, at a sensible loudness (Vyral evens it to -14 LUFS, TikTok's target; far off means something broke);
- no black stretch over a second and no frozen picture over six seconds (a broken source or a bad cut; a few seconds
  of a still image, like a tweet on screen, is normal in reaction streams);
- not a near-empty file (Vyral encodes at constant quality, so a low bitrate on its own just means a still shot).
A video that fails is held back from review and from Muse with the reason; re-rendering checks it again.
"""
from __future__ import annotations

import re
from pathlib import Path

from .ffmpeg import FFmpegError, probe, run

MIN_MBPS = 1.0  # Vyral encodes at constant quality, so a still shot can be small and still sharp; under this, it broke


def check(path: Path, width: int, height: int, duration: float) -> dict:
    problems: list[str] = []
    try:
        info = probe(path)
        err = run(["-i", str(path), "-vf", "blackdetect=d=1:pix_th=0.10,freezedetect=n=0.003:d=6", "-af", "ebur128",
                   "-f", "null", "-"], timeout=600)
    except FFmpegError as e:
        return {"status": "fail", "problems": [f"couldn't read the video ({e})"]}
    if (info.width, info.height) != (width, height):
        problems.append(f"it's {info.width}x{info.height}, not {width}x{height}")
    if duration and info.duration and abs(info.duration - duration) > max(1.0, duration * 0.05):
        problems.append(f"it runs {info.duration:.1f} s instead of {duration:.1f} s")
    if not info.has_audio:
        problems.append("there's no sound")
    blacks = [float(b) - float(a) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]
    if blacks:
        problems.append(f"{sum(blacks):.1f} s of black picture")
    freezes = [float(x) for x in re.findall(r"lavfi\.freezedetect\.freeze_duration: ([\d.]+)", err)]
    if freezes:
        problems.append(f"the picture freezes for {max(freezes):.1f} s")
    loud = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    lufs = float(loud[-1]) if loud else None
    if info.has_audio and (lufs is None or not -20 <= lufs <= -9):
        problems.append(f"the sound level is off ({lufs if lufs is not None else 'silent'} LUFS; it should be near -14)")
    size = path.stat().st_size
    mbps = size * 8 / max(info.duration or duration or 1, 0.1) / 1e6
    if mbps < MIN_MBPS:
        problems.append(f"the file is nearly empty ({mbps:.1f} Mbps)")
    return {"status": "fail" if problems else "pass", "problems": problems,
            "measures": {"lufs": lufs, "mbps": round(mbps, 1), "duration": info.duration, "size": [info.width, info.height]}}
