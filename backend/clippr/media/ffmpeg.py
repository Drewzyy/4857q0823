"""FFmpeg access. The app ships its own static ffmpeg (imageio-ffmpeg), so users install nothing."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import numpy as np

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # don't flash a console window on Windows


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
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW, cwd=cwd)
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
    p = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=_NO_WINDOW)
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
    fm = re.search(r"Video:.*?(\d+(?:\.\d+)?) fps", text)
    if fm:
        fps = float(fm[1])
    return MediaInfo(dur, w, h, fps, bool(re.search(r"Stream #.*?Audio:", text)))


def decode_audio_chunks(path: Path, sample_rate: int, chunk_seconds: float = 120) -> Iterator[np.ndarray]:
    """Stream mono float32 audio without loading hours of audio into memory."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path),
           "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
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
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        raise FFmpegError("Couldn't read audio: " + err.strip()[-300:])
