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
           overlay_dir: Path | None = None, zoom: float = 1.0, pan: tuple[float, float] = (0.5, 0.5), speed: float = 1.0,
           video_height: float = 0.0, cam: list[float] | None = None) -> Path:
    """overlay_dir: folder prepared by overlay.prepare() holding overlay.ass + fonts (text burned in).
    video_height: how much of the frame's height the sharp video fills (0.45 = 45%). A wide stream is trimmed at
    the sides (where pan says) to get there; 0 or anything below the stream's full-width height keeps it whole."""
    src, out = src.resolve(), out.resolve()
    info = probe(src)
    # Keep the stream's real frame rate (e.g. 60 or 59.94), capped at what platforms accept. If the
    # stream doesn't report one, aim for the cap rather than risk throwing frames away.
    fps = min(info.fps, fmt.max_fps) if info.fps else fmt.max_fps
    W, H = fmt.width, fmt.height
    bw, bh = W // 4 // 2 * 2, H // 4 // 2 * 2
    # Width/height of the area the video fills. Never wider than the stream itself: asking for less height than
    # the full-width stream has just shows the whole stream, never trimmed at the top and bottom.
    stream = info.width / info.height if info.width and info.height else 16 / 9
    box = min(W / (H * video_height), stream) if video_height > 0 else stream
    if cam and H > W:  # stacked (vertical outputs only): content on top, facecam underneath, no blurred background
        from .facecam import CAM_SHARE
        hb = int(H * CAM_SHARE) // 2 * 2
        ht = H - hb
        cx, cy, cw, ch = cam
        vf = (
            f"[0:v]setpts=PTS/{speed:.4f},fps={fps:.3f},split=2[a][c];"
            f"[a]crop=w='min(iw,ih*{W / ht:.4f})':h='min(ih,iw/{W / ht:.4f})':x='(iw-ow)*{pan[0]:.4f}':y='(ih-oh)*{pan[1]:.4f}',"
            f"scale={W}:{ht}:flags=lanczos,setsar=1[t];"
            f"[c]crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{cx:.4f}:ih*{cy:.4f},scale={W}:{hb}:flags=lanczos,setsar=1[m];"
            f"[t][m]vstack,setsar=1"
            + (",ass=overlay.ass:fontsdir=fonts" if overlay_dir else "")
            + ",format=yuv420p[v]"
        )
    else:
        vf = None
    vf = vf or (
        # Editor zoom/pan crops the source; speed retimes it. Both are no-ops at their defaults.
        f"[0:v]crop=iw/{zoom:.4f}:ih/{zoom:.4f}:(iw-iw/{zoom:.4f})*{pan[0]:.4f}:(ih-ih/{zoom:.4f})*{pan[1]:.4f},"
        f"setpts=PTS/{speed:.4f},fps={fps:.3f},split=2[bg][fg];"
        # Blur at quarter size then scale up: same look as a full-size blur, many times faster.
        f"[bg]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},gblur=sigma=10,"
        f"scale={W}:{H}:flags=bicubic,eq=brightness=-0.12:saturation=1.15[b];"
        f"[fg]crop=w='min(iw,ih*{box:.4f})':h='min(ih,iw/{box:.4f})':x='(iw-ow)*{pan[0]:.4f}':y='(ih-oh)*{pan[1]:.4f}',"
        f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[f];"
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
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]  # input option: limits source time, so speed changes the output length
    args += ["-i", str(src)]
    args += ["-filter_complex", vf, "-map", "[v]"]
    if info.has_audio:
        args += ["-map", "0:a:0", "-af", (f"atempo={speed:.4f}," if abs(speed - 1) > 1e-3 else "") + "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    args += [*vcodec, "-preset", os.environ.get("CLIPPR_RENDER_PRESET", "medium"), "-maxrate", maxrate, "-bufsize", f"{fmt.bitrate_mbps * 3:.1f}M",
             "-movflags", "+faststart", str(out)]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.mp4")
    args[-1] = str(tmp)
    run(args, cwd=overlay_dir)
    tmp.replace(out)
    return out
