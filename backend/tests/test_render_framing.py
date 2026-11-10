import numpy as np
import subprocess

from clippr.media.ffmpeg import ffmpeg_exe, probe, run
from clippr.media.render import OutputFormat, render


def _sharp_rows(path, w=270, h=480):
    """Share of the frame's rows that hold the sharp video (the blurred background has almost no detail)."""
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-ss", "1", "-i", str(path), "-frames:v", "1", "-vf", f"scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(h, w).astype(int)
    detail = np.abs(np.diff(f, axis=1)).mean(axis=1)
    return float((detail > 1.2).mean())


def test_video_height_makes_the_stream_fill_more_of_the_frame(tmp_path):
    src = tmp_path / "stream.mp4"
    run(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=2", "-c:v", "libx264", "-preset", "ultrafast", str(src)])
    fmt = OutputFormat(540, 960, 30)
    whole = _sharp_rows(render(src, tmp_path / "a.mp4", fmt, video_height=0))
    zoomed = _sharp_rows(render(src, tmp_path / "b.mp4", fmt, video_height=0.6))
    assert 0.27 < whole < 0.37  # a 16:9 stream across the full width: about a third of the height
    assert 0.55 < zoomed < 0.65
    smaller = _sharp_rows(render(src, tmp_path / "c.mp4", fmt, video_height=0.2))  # less than full width: whole stream, uncut
    assert abs(smaller - whole) < 0.03


def test_thumbnail_is_saved_and_embedded(tmp_path):
    from clippr.media.ffmpeg import ffmpeg_exe
    from clippr.media.render import thumbnail
    import subprocess
    src = tmp_path / "v.mp4"
    run(["-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30:duration=2", "-c:v", "libx264", "-preset", "ultrafast", str(src)])
    jpg = thumbnail(src, 1.0)
    assert jpg.exists() and jpg.stat().st_size > 1000
    info = subprocess.run([ffmpeg_exe(), "-i", str(src)], capture_output=True, text=True).stderr
    assert "attached pic" in info and probe(src).duration > 1.5
    assert thumbnail(src, 99).exists()  # past the end falls back to the last frame
    info = subprocess.run([ffmpeg_exe(), "-i", str(src)], capture_output=True, text=True).stderr
    assert info.count("attached pic") == 1  # a new cover replaces the old one
