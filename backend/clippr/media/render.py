"""Render the final upload-ready video: sharp centered footage over a blurred, darkened copy."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .ffmpeg import probe, run


@dataclass(frozen=True)
class OutputFormat:
    width: int = 1080
    height: int = 1920
    max_fps: int = 60
    codec: str = "h264"  # h264 | h265
    bitrate_mbps: float = 12

    @classmethod
    def from_settings(cls, fmt: dict) -> "OutputFormat":
        w, h = (int(x) for x in str(fmt.get("resolution", "1080x1920")).split("x"))
        return cls(w, h, int(fmt.get("fps", 60)), fmt.get("codec", "h264"), float(fmt.get("bitrate_mbps", 12)))

    @property
    def key(self) -> str:
        return f"{self.width}x{self.height}_{self.max_fps}_{self.codec}_{int(self.bitrate_mbps)}"


def render(src: Path, out: Path, fmt: OutputFormat, *, start: float | None = None, duration: float | None = None,
           overlay_dir: Path | None = None) -> Path:
    """overlay_dir: folder prepared by overlay.prepare() holding overlay.ass + fonts (text burned in)."""
    src, out = src.resolve(), out.resolve()
    info = probe(src)
    fps = min(info.fps or 30, fmt.max_fps)
    W, H = fmt.width, fmt.height
    vf = (
        f"[0:v]fps={fps:g},split=2[bg][fg];"
        f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40,eq=brightness=-0.12:saturation=1.15[b];"
        f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[f];"
        f"[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1"
        + (",ass=overlay.ass:fontsdir=fonts" if overlay_dir else "")
        + ",format=yuv420p[v]"
    )
    # High-quality constant-quality encode, capped so platforms don't re-compress it harder.
    maxrate = f"{fmt.bitrate_mbps * 1.5:.1f}M"
    vcodec = ["-c:v", "libx265", "-crf", "20", "-tag:v", "hvc1"] if fmt.codec == "h265" else ["-c:v", "libx264", "-crf", "17", "-profile:v", "high"]
    args = []
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(src)]
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]
    args += ["-filter_complex", vf, "-map", "[v]"]
    if info.has_audio:
        args += ["-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    args += [*vcodec, "-preset", os.environ.get("CLIPPR_RENDER_PRESET", "medium"), "-maxrate", maxrate, "-bufsize", f"{fmt.bitrate_mbps * 3:.1f}M",
             "-movflags", "+faststart", str(out)]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.mp4")
    args[-1] = str(tmp)
    run(args, cwd=overlay_dir)
    tmp.replace(out)
    return out
