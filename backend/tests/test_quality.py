"""The quality check on every finished video, and broken videos held back from review and Muse."""
from clippr.media.ffmpeg import run
from clippr.media.quality import check
from clippr.media.render import OutputFormat, render


def test_good_videos_pass_and_broken_ones_say_why(tmp_path):
    run(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=8", "-f", "lavfi", "-i", "sine=f=300:d=8",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(tmp_path / "src.mp4")])
    good = render(tmp_path / "src.mp4", tmp_path / "good.mp4", OutputFormat(540, 960, 30), duration=8, use_hardware=False)
    assert check(good, 540, 960, 8)["status"] == "pass"
    run(["-f", "lavfi", "-i", "color=c=black:size=540x960:rate=30:duration=4", "-t", "4", "-c:v", "libx264", "-preset", "ultrafast",
         str(tmp_path / "bad.mp4")])
    bad = check(tmp_path / "bad.mp4", 1080, 1920, 8)
    text = " ".join(bad["problems"])
    assert bad["status"] == "fail" and "1080x1920" in text and "4.0 s instead of 8.0 s" in text and "no sound" in text and "black" in text


def test_a_failed_video_is_held_back(env):
    from fastapi.testclient import TestClient
    from clippr import mcp
    from clippr.models import ClipOutput
    from test_mcp import _call, _clip
    ctx, c, fake = env
    cid, tt, yt = _clip(ctx, c, fake)
    outs = c.get("/api/clips").json()[0]["outputs"]
    assert all(o["quality"]["status"] == "pass" for o in outs), [o["quality"] for o in outs]  # real renders pass
    with ctx.db.session() as s:
        o = s.query(ClipOutput).filter(ClipOutput.destination_id == tt).one()
        o.quality = {"status": "fail", "problems": ["2.0 s of black picture"]}
    mc, tok = TestClient(mcp.create_app(ctx)), mcp.token(ctx)
    assert all(o["destination"]["id"] != tt for x in _call(mc, tok, "list_ready_clips")[1] for o in x["outputs"])
    err, msg = _call(mc, tok, "approve_clip", clip_id=cid, destination_id=tt, watched=True)
    assert err and "quality check" in msg and "black picture" in msg
