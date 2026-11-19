"""The MCP bridge for Muse, review and approval, the safety check, routing by kind, and Muse marking what it posted."""
import json
import socket
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from clippr import mcp, safety
from clippr.fetch import RemotePost
from clippr.models import AuditLog, Clip, ClipOutput
from fakes import drain
from test_pipeline import setup_accounts


def _clip(ctx, c, fake):
    """A real clip through the real pipeline (fake TikTok/Twitch underneath)."""
    _, sid, tt, yt = setup_accounts(c)
    fake.posts = [RemotePost("old1", "https://www.tiktok.com/@a.clips/video/old1", "old")]
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("new1", "https://www.tiktok.com/@a.clips/video/new1", "Streamer A couldn't believe what chat did #fyp"), *fake.posts]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    cid = c.get("/api/clips").json()[0]["id"]
    with ctx.db.session() as s:  # the fake stream is quiet test audio: give it a passing grade, as a real clip would earn
        clip = s.get(Clip, cid)
        clip.grade = {**(clip.grade or {}), "score": 70, "tier": "B"}
    return cid, tt, yt


def _rpc(mc, method, params=None, token=None, mid=1):
    r = mc.post("/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}},
                headers={"Authorization": f"Bearer {token}", "Host": "127.0.0.1:47821"})
    return r


def _call(mc, tok, name, **args):
    r = _rpc(mc, "tools/call", {"name": name, "arguments": args}, tok).json()["result"]
    return r["isError"], (json.loads(r["content"][0]["text"]) if not r["isError"] else r["content"][0]["text"])


def test_safety_check_rules():
    w = lambda *t: [{"start": i * 0.5, "end": i * 0.5 + 0.4, "text": x} for i, x in enumerate(t)]  # noqa: E731
    assert safety.check(permission=True, words=w("no", "way", "bro"), texts=["Lacy lost it"])["status"] == "pass"
    r = safety.check(permission=False, words=[], texts=[])
    assert r["status"] == "fail" and r["flags"][0]["category"] == "creator rights"
    r = safety.check(permission=True, words=w("we", "went", "to", "the", "strip", "club"), texts=[], game="Grand Theft Auto V")
    assert r["status"] == "fail" and any(f["category"] == "high-risk game scene" and f["at"] == 2.0 for f in r["flags"])
    assert safety.check(permission=True, words=w("nice", "drive"), texts=[], game="Grand Theft Auto V")["status"] == "review"  # uncertain is never a pass
    assert safety.check(permission=True, words=w("he", "smoked", "weed"), texts=[])["status"] == "review"
    assert safety.check(permission=True, words=[], texts=["bad word"], blocklist={"banned_words": ["bad word"]})["status"] == "fail"
    assert safety.check(permission=True, words=[], texts=[], game="Valorant", blocklist={"banned_games": ["valorant"]})["status"] == "fail"
    # Quarantine sticks: editing the words out doesn't release it.
    failed = safety.check(permission=True, words=w("kill", "yourself"), texts=[])
    assert failed["status"] == "fail" and safety.check(permission=True, words=[], texts=[], previous=failed)["status"] == "fail"
    assert safety.check(permission=True, words=w("cp", "is", "high"), texts=[])["status"] == "pass"  # gaming slang, not a flag


def test_pages_get_clips_of_their_kind(env):
    ctx, c, fake = env
    a = c.post("/api/streamers", json={"name": "Pod", "links": ["https://www.twitch.tv/pod"], "permission": True, "kind": "podcast"}).json()
    pods = c.post("/api/destinations", json={"platform": "instagram", "display_name": "Pods", "handle": "@vyralpods", "creator_ids": [a["id"]]}).json()
    clips = c.post("/api/destinations", json={"platform": "tiktok", "display_name": "Clips", "handle": "@vyralclips19", "creator_ids": [a["id"]]}).json()
    assert c.get("/api/destinations").json() and pods["settings"]["content_kinds"] == ["podcast"] and clips["settings"]["content_kinds"] == ["regular"]
    from clippr.routing import for_kind, pages_for
    with ctx.db.session() as s:
        pages = pages_for(s, {a["id"]})  # every page of the streamer; the clip's kind then picks among them
        assert [d.id for d in for_kind(pages, "podcast", "podcast")] == [pods["id"]]  # a podcast clip: only the podcast page
        assert [d.id for d in for_kind(pages, "regular", "podcast")] == [clips["id"]]  # detected as a regular clip


def test_muse_reviews_approves_and_posts_and_marks_posted(env, tmp_path):
    ctx, c, fake = env
    cid, tt, yt = _clip(ctx, c, fake)
    mc = TestClient(mcp.create_app(ctx))
    tok = mcp.token(ctx)

    # Locked down: wrong token, wrong host.
    assert _rpc(mc, "tools/list", token="nope").status_code == 401
    assert mc.post("/mcp", json={}, headers={"Authorization": f"Bearer {tok}", "Host": "evil.com"}).status_code == 421
    init = _rpc(mc, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "inspector"}}, tok).json()
    assert init["result"]["serverInfo"]["name"] == "vyral" and "tools" in init["result"]["capabilities"]
    names = {t["name"] for t in _rpc(mc, "tools/list", token=tok).json()["result"]["tools"]}
    assert names == {"list_ready_clips", "get_clip", "list_sources", "list_destinations", "list_funnel_routes", "list_clips_for_review",
                     "review_clip", "update_clip", "approve_clip", "reject_clip", "get_posting_package", "mark_posted",
                     "get_safety_check", "list_quarantined_clips", "list_campaigns"}

    err, ready = _call(mc, tok, "list_ready_clips")
    assert not err and ready[0]["clip_id"] == cid and ready[0]["safety"] in ("pass", "review")
    assert all(Path(o["file_path"]).exists() for o in ready[0]["outputs"])
    _, queue = _call(mc, tok, "list_clips_for_review")
    assert [x["clip_id"] for x in queue] == [cid]
    _, rv = _call(mc, tok, "review_clip", clip_id=cid)
    assert rv["transcript"] and rv["hook_text"] and rv["trim"]["end"] > rv["trim"]["start"]
    assert {r["destination_id"] for r in _call(mc, tok, "list_funnel_routes")[1]} == {tt, yt}

    # Edit: caption on one page, trim and headline (re-renders without transcribing again).
    calls = ctx.transcriber.calls
    err, up = _call(mc, tok, "update_clip", clip_id=cid, destination_id=tt, caption="Streamer A lost it #streamera #gaming",
                    hook_text="Streamer A couldn't believe it", trim_start=rv["trim"]["start"] + 0.5, trim_end=rv["trim"]["end"])
    assert not err and "caption" in up["changed"], up
    drain(ctx)
    assert ctx.transcriber.calls == calls  # the transcript is reused
    _, after = _call(mc, tok, "review_clip", clip_id=cid)
    assert after["hook_text"] == "Streamer A couldn't believe it" and abs(after["trim"]["start"] - rv["trim"]["start"] - 0.5) < 0.01

    # Approve needs watching; one page at a time; and doesn't post by itself.
    err, msg = _call(mc, tok, "approve_clip", clip_id=cid, watched=True)
    assert err and "Say which page" in msg
    err, msg = _call(mc, tok, "approve_clip", clip_id=cid, destination_id=tt, watched=False)
    assert err and "Watch the video" in msg
    err, ok = _call(mc, tok, "approve_clip", clip_id=cid, destination_id=tt, watched=True)
    assert not err and ok["review"] == "approved"
    out = next(o for o in c.get("/api/clips").json()[0]["outputs"] if o["destination"]["id"] == tt)
    assert out["review"] == "approved" and out["reviewed_by"] == "muse"  # shows in the app
    with ctx.db.session() as s:
        assert s.query(AuditLog).filter(AuditLog.action == "output.approved").one().details["by"] == "muse"
        assert not s.query(ClipOutput).filter(ClipOutput.status == "uploaded").count()  # approving posts nothing
    err, pkg = _call(mc, tok, "get_posting_package", clip_id=cid, destination_id=tt)
    assert not err and Path(pkg["video_path"]).exists() and pkg["caption"] == "Streamer A lost it #streamera #gaming"
    assert pkg["destination"]["handle"] == "@streamera.tt" and pkg["duration"] > 5 and pkg["aspect_ratio"] == "1080:1920"
    err, rej = _call(mc, tok, "reject_clip", clip_id=cid, destination_id=yt, reason="Weak on YouTube")
    assert not err and rej[0]["review"] == "rejected"

    # mark_posted: only an approved video, only a link on that page's platform.
    err, msg = _call(mc, tok, "mark_posted", clip_id=cid, destination_id=yt, post_url="https://www.youtube.com/shorts/abc123")
    assert err and "Approve it first" in msg
    err, msg = _call(mc, tok, "mark_posted", clip_id=cid, destination_id=tt, post_url="https://www.instagram.com/reel/abc/")
    assert err and "isn't a Tiktok link" in msg
    err, msg = _call(mc, tok, "mark_posted", clip_id=cid, destination_id=tt, post_url="http://www.tiktok.com/@vyralclips19/video/9")
    assert err
    err, done = _call(mc, tok, "mark_posted", clip_id=cid, destination_id=tt, post_url="https://www.tiktok.com/@vyralclips19/video/9")
    assert not err and done["status"] == "uploaded" and done["post_url"].endswith("/video/9")
    out = next(o for o in c.get("/api/clips").json()[0]["outputs"] if o["destination"]["id"] == tt)
    assert out["status"] == "uploaded" and out["post_url"].endswith("/video/9")  # shows in the app
    with ctx.db.session() as s:
        assert s.query(AuditLog).filter(AuditLog.action == "clip.post_linked").one().details["by"] == "muse"
        assert s.query(ClipOutput).filter(ClipOutput.post_url.isnot(None)).one().uploaded_at

    assert tok not in json.dumps([_rpc(mc, "tools/call", {"name": n, "arguments": {"clip_id": cid, "destination_id": tt}}, tok).json()
                                  for n in ("get_clip", "review_clip", "list_destinations")])


def test_quarantined_clips_never_reach_review(env):
    ctx, c, fake = env
    cid, tt, _ = _clip(ctx, c, fake)
    with ctx.db.session() as s:
        clip = s.get(Clip, cid)
        clip.words = [{"start": 1.0, "end": 1.4, "text": "kys"}]
    ctx.pipeline.check_safety(cid)
    mc, tok = TestClient(mcp.create_app(ctx)), mcp.token(ctx)
    assert _call(mc, tok, "list_ready_clips")[1] == [] and _call(mc, tok, "list_clips_for_review")[1] == []
    q = _call(mc, tok, "list_quarantined_clips")[1]
    assert q[0]["clip_id"] == cid and q[0]["flags"][0]["at"] == 1.0
    err, msg = _call(mc, tok, "approve_clip", clip_id=cid, destination_id=tt, watched=True)
    assert err and "Quarantined" in msg
    err, msg = _call(mc, tok, "update_clip", clip_id=cid, trim_start=0.5)  # re-rendering doesn't release it
    assert err and "Quarantined" in msg
    assert c.post(f"/api/outputs/{c.get('/api/clips').json()[0]['outputs'][0]['id']}/review", json={"decision": "approve", "watched": True}).status_code == 409


def test_auto_post_is_off_and_locked_until_five_reviewed_posts(env):
    ctx, c, fake = env
    cid, tt, _ = _clip(ctx, c, fake)
    assert c.get(f"/api/destinations").json()[0]["settings"]["auto_post"] is False
    r = c.patch(f"/api/destinations/{tt}", json={"settings": {"auto_post": True}})
    assert r.status_code == 409 and "after 5 reviewed posts" in r.json()["error"]["message"]


def test_mcp_server_binds_localhost_and_fails_loudly_when_the_port_is_taken(env, caplog):
    ctx, c, fake = env
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    port = busy.getsockname()[1]
    c.put("/api/settings", json={"posting": {"mcp_port": port}})
    server = mcp.Server(ctx)
    server.start()
    assert not server.state()["running"] and "already in use" in server.state()["error"]
    assert any("MCP server not started" in r.message for r in caplog.records)
    busy.close()
    server.start()
    try:
        assert server.state()["running"]
        r = httpx.post(f"http://127.0.0.1:{port}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                       headers={"Authorization": f"Bearer {mcp.token(ctx)}"}, timeout=10)
        assert r.json()["result"] == {}
    finally:
        server.stop()
    bridge = c.get("/api/bridge").json()
    assert bridge["mcp"]["url"] == f"http://127.0.0.1:{port}/mcp"


def test_listen_address_is_this_computer_or_tailscale_only(env):
    ctx, c, fake = env
    ok = lambda host: c.put("/api/settings", json={"posting": {"mcp_host": host}}).status_code  # noqa: E731
    assert ok("100.115.250.79") == 200  # Tailscale (100.64.0.0/10)
    assert c.get("/api/bridge").json()["mcp"]["url"].startswith("http://100.115.250.79:")
    assert ok("127.0.0.1") == 200
    for bad in ("0.0.0.0", "192.168.1.5", "8.8.8.8", "100.115.250.79:47821", "47821.5", "localhost"):
        assert ok(bad) == 422, bad
    r = c.put("/api/settings", json={"posting": {"mcp_port": 47821.5}})
    assert r.status_code == 422


def test_token_lives_in_a_private_file_not_the_keychain(env):
    import os
    import stat
    ctx, c, fake = env
    t = mcp.token(ctx)
    path = ctx.config.data_dir / mcp.TOKEN_FILE
    assert path.read_text() == t and mcp.token(ctx) == t  # made once, then reused
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600  # only your user can read it
    assert ctx.secrets.get("mcp") is None  # nothing in the keychain to prompt for after an update
