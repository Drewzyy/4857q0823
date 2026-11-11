"""Dead air is found and cut out; captions move with the cut."""
from clippr.media import deadair
from clippr.media.ffmpeg import probe, run
from clippr.media.render import OutputFormat, render


def _clip(tmp):
    """2s tone, 4s silence, 2s tone."""
    src = tmp / "s.mp4"
    run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=8",
         "-f", "lavfi", "-i", "sine=f=440:d=2", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=4", "-f", "lavfi", "-i", "sine=f=440:d=2",
         "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]", "-map", "0:v", "-map", "[a]", "-t", "8",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)])
    return src


def test_silence_is_found_and_cut(tmp_path):
    src = _clip(tmp_path)
    gaps = deadair.detect(src, 0, 8)
    assert len(gaps) == 1 and 2.0 <= gaps[0][0] <= 2.5 and 5.5 <= gaps[0][1] <= 6.0
    out = render(src, tmp_path / "o.mp4", OutputFormat(360, 640, 30), duration=8, gaps=deadair.relative(gaps, 0, 8))
    assert 4.0 < probe(out).duration < 5.0


def test_never_cut_too_short():
    rel = [(1.0, 3.0)]
    assert deadair.removed_before(5, rel) == 2 and deadair.removed_before(2, rel) == 1
    assert deadair.inside(2, rel) and not deadair.inside(3, rel)


def test_cuts_and_dead_air_merge():
    rel = deadair.relative([[2, 5], [4, 6], [10, 11]], 1, 8)
    assert rel == [(1.0, 5.0)]  # [2,5] and [4,6] merge; [10,11] is past the 8 s cut


def test_cuts_keep_audio_and_video_in_sync_on_uneven_frame_rates(tmp_path):
    """Twitch and Kick footage often has uneven frame timing; cutting used to leave the video seconds short."""
    import re
    import subprocess
    from clippr.media.ffmpeg import ffmpeg_exe
    src = tmp_path / "vfr.mp4"
    run(["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=60:duration=12", "-f", "lavfi", "-i", "sine=f=440:d=12",
         "-vf", "select='not(eq(mod(n,7),3))'", "-fps_mode", "vfr", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(src)])
    out = render(src, tmp_path / "o.mp4", OutputFormat(180, 320, 30), duration=12, gaps=[(2.0, 4.0), (6.0, 7.5)])

    def seconds(stream):
        e = subprocess.run([ffmpeg_exe(), "-i", str(out), "-map", stream, "-f", "null", "-"], capture_output=True, text=True).stderr
        h, m, sec = re.findall(r"time=(\d+):(\d+):([\d.]+)", e)[-1]
        return int(h) * 3600 + int(m) * 60 + float(sec)
    assert abs(seconds("0:v") - 8.5) < 0.15 and abs(seconds("0:a") - 8.5) < 0.15
