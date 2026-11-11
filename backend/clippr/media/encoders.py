"""Pick the fastest video encoder that works on this computer.

Hardware encoders (Apple VideoToolbox on Macs; NVIDIA, Intel or AMD on Windows) render several times faster than
the processor. Each is tried once with a tiny test encode, because being listed doesn't mean the graphics card or
its driver supports it. The processor encoder (libx264/libx265) always works and is the fallback.
"""
from __future__ import annotations

import logging
import os
import sys
import threading

from .ffmpeg import FFmpegError, run

log = logging.getLogger("clippr.encoders")

_lock = threading.Lock()
_found: dict[str, str | None] = {}

CANDIDATES = {
    "h264": {"darwin": ["h264_videotoolbox"], "win32": ["h264_nvenc", "h264_qsv", "h264_amf"]},
    "h265": {"darwin": ["hevc_videotoolbox"], "win32": ["hevc_nvenc", "hevc_qsv", "hevc_amf"]},
}


def _works(name: str) -> bool:
    try:
        run(["-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:duration=0.5", "-pix_fmt", "yuv420p", "-c:v", name, "-f", "null", "-"], timeout=30)
        return True
    except FFmpegError:
        return False


def hardware(codec: str) -> str | None:
    """The working hardware encoder for h264/h265 here, or None. Checked once per run."""
    with _lock:
        if codec not in _found:
            _found[codec] = next((n for n in CANDIDATES[codec].get(sys.platform, []) if _works(n)), None)
            log.info("%s hardware encoder: %s", codec, _found[codec] or "none, using the processor")
        return _found[codec]


def args(codec: str, bitrate_mbps: float, use_hardware: bool = True) -> list[str]:
    """Encoder arguments for a finished clip: high quality, capped near the platform's bitrate."""
    hw = hardware(codec) if use_hardware else None
    peak = f"{bitrate_mbps * 1.5:.1f}M"
    # No reordered (B) frames: they start the video track a few frames late and rely on a correction (an edit list)
    # that some players and uploads ignore, so the sound ran ahead of the picture.
    no_reorder = ["-bf", "0"]
    if hw and "videotoolbox" in hw:
        return ["-c:v", hw, "-b:v", f"{bitrate_mbps:.1f}M", "-maxrate", peak, "-allow_sw", "1", *no_reorder] + (["-tag:v", "hvc1"] if codec == "h265" else [])
    if hw and "nvenc" in hw:
        return ["-c:v", hw, "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", f"{bitrate_mbps:.1f}M", "-maxrate", peak, *no_reorder]
    if hw and "qsv" in hw:
        return ["-c:v", hw, "-preset", "medium", "-global_quality", "20", "-maxrate", peak, *no_reorder]
    if hw and "amf" in hw:
        return ["-c:v", hw, "-quality", "quality", "-rc", "vbr_peak", "-b:v", f"{bitrate_mbps:.1f}M", "-maxrate", peak, *no_reorder]
    # Processor: "faster" is several times quicker than "medium" for a barely visible difference at this quality.
    # The processor too: no reordered frames, so the picture starts exactly with the sound in every player (a
    # touch more bitrate, made up for with slightly higher quality settings).
    soft = ["-c:v", "libx265", "-crf", "19", "-tag:v", "hvc1"] if codec == "h265" else ["-c:v", "libx264", "-crf", "16", "-profile:v", "high"]
    return soft + no_reorder + ["-maxrate", peak, "-bufsize", f"{bitrate_mbps * 3:.1f}M"]


def software_preset() -> list[str]:
    return ["-preset", os.environ.get("CLIPPR_RENDER_PRESET", "faster")]
