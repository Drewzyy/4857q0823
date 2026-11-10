"""Facecam detection and the stacked layout."""
from pathlib import Path

from clippr.media import facecam
from clippr.media.ffmpeg import probe, run
from clippr.media.render import OutputFormat, render

FACE = Path(__file__).parent / "fixtures" / "face.jpg"


def _stream(tmp: Path, corner: bool) -> Path:
    """A 1280x720 'game' with the face pasted small in the bottom-right corner, or big in the middle."""
    src = tmp / "stream.mp4"
    face = "scale=200:-2" if corner else "scale=-2:600"
    pos = "W-w-30:H-h-30" if corner else "(W-w)/2:(H-h)/2"
    run(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=3", "-loop", "1", "-i", str(FACE),
         "-filter_complex", f"[1:v]{face}[f];[0:v][f]overlay={pos}:shortest=1", "-t", "3",
         "-c:v", "libx264", "-preset", "ultrafast", str(src)])
    return src


def test_corner_face_is_a_facecam(tmp_path):
    cam = facecam.detect(_stream(tmp_path, True), 0, 3, 16 / 9, 1080 / 768)
    assert cam is not None
    x, y, w, h = cam
    assert x > 0.6 and y > 0.4 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.0001 and y + h <= 1.0001


def test_face_in_the_middle_keeps_normal_framing(tmp_path):
    assert facecam.detect(_stream(tmp_path, False), 0, 3, 16 / 9, 1080 / 768) is None


def test_a_face_seen_once_is_not_a_facecam():
    frames = [[(10, 10, 40, 40)]] + [[] for _ in range(7)]
    assert facecam.pick(frames, 640, 360) is None


def test_cam_box_stays_inside_the_frame():
    x, y, w, h = facecam.cam_box((0.97, 0.97, 0.15), 16 / 9, 1080 / 768)
    assert x + w <= 1.0001 and y + h <= 1.0001 and x >= 0 and y >= 0


def test_stacked_render_is_full_vertical(tmp_path):
    src = _stream(tmp_path, True)
    out = render(src, tmp_path / "out.mp4", OutputFormat(540, 960, 30), cam=[0.7, 0.5, 0.3, 0.45])
    info = probe(out)
    assert (info.width, info.height) == (540, 960)
