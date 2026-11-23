"""FFmpeg access. The app ships its own static ffmpeg (imageio-ffmpeg), so users install nothing."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import numpy as np

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # don't flash a console window on Windows
# Video work runs below normal priority so the app (and the rest of the computer) stays responsive while clips
# are being made: it still uses every idle core, it just steps aside when something you're doing needs the CPU.
_LOW = 0x00004000 if sys.platform == "win32" else 0  # BELOW_NORMAL_PRIORITY_CLASS
_FLAGS = _NO_WINDOW | _LOW


def _lower_priority() -> None:  # runs in the child on Mac and Linux, before FFmpeg starts
    try:
        os.nice(10)
    except OSError:
        pass


_PRE = None if sys.platform == "win32" else _lower_priority
SPAWN = {"creationflags": _FLAGS, "preexec_fn": _PRE}  # for any other FFmpeg call: no console window, low priority


class FFmpegError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    env = os.environ.get("CLIPPR_FFMPEG")
    if env and Path(env).exists():
        return env
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        found = shutil.which("ffmpeg")
        if found:
            return found
    raise FFmpegError("FFmpeg is missing from this installation")


def run(args: list[str], timeout: float = 3600, cwd: Path | None = None) -> str:
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", *args]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_FLAGS, preexec_fn=_PRE, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise FFmpegError("Video processing took too long and was stopped")
    err = p.stderr.decode("utf-8", "replace")
    if p.returncode != 0:
        raise FFmpegError("FFmpeg failed: " + " ".join(err.strip().splitlines()[-3:])[:400])
    return err


@dataclass
class MediaInfo:
    duration: float | None
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool


def probe(path: Path) -> MediaInfo:
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-i", str(path)]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=_FLAGS, preexec_fn=_PRE)
    except subprocess.TimeoutExpired:
        raise FFmpegError(f"Reading {path.name} took over a minute (the file may be damaged or on a slow drive)")
    text = p.stderr.decode("utf-8", "replace")
    dur = None
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    w = h = None
    fps = None
    vm = re.search(r"Stream #.*?Video:.*?(\d{2,5})x(\d{2,5})", text)
    if vm:
        w, h = int(vm[1]), int(vm[2])
    fm = re.search(r"Video:.*?(\d+(?:\.\d+)?) fps", text) or re.search(r"Video:.*?(\d+(?:\.\d+)?) tbr", text)
    if fm:
        fps = float(fm[1])
        if fps > 240:  # bogus container timebase, not a real frame rate
            fps = None
    return MediaInfo(dur, w, h, fps, bool(re.search(r"Stream #.*?Audio:", text)))


def decode_audio_chunks(path: Path, sample_rate: int, chunk_seconds: float = 120) -> Iterator[np.ndarray]:
    """Stream mono float32 audio without loading hours of audio into memory."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path),
           "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-"]
    errors = tempfile.TemporaryFile()  # a file, not a pipe: a chatty error log can't fill it and stall FFmpeg
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors, creationflags=_FLAGS, preexec_fn=_PRE)
    n = int(sample_rate * chunk_seconds) * 2
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(n)
            if not buf:
                break
            yield np.frombuffer(buf[: len(buf) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    finally:
        proc.stdout.close() if proc.stdout else None
        proc.wait(timeout=30)
    if proc.returncode not in (0, None):
        errors.seek(0)
        err = errors.read().decode("utf-8", "replace")
        errors.close()
        raise FFmpegError("Couldn't read audio: " + err.strip()[-300:])
    errors.close()
