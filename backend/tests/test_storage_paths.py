"""Where saved videos and new clips go when the user picks their own folders."""
from pathlib import Path

from clippr.models import Clip, ClipOutput
from test_mcp import _clip


def test_relative_or_unwritable_folders_are_rejected(client, tmp_path):
    for key in ("save_folder", "media_folder"):
        assert client.put("/api/settings", json={"storage": {key: "videos/here"}}).status_code == 422
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    r = client.put("/api/settings", json={"storage": {"save_folder": str(blocker / "sub")}})
    assert r.status_code == 422 and "can't write" in r.json()["error"]["message"]
    assert client.get("/api/settings").json()["storage"]["save_folder"] == ""


def test_save_to_computer_uses_the_chosen_folder(env, tmp_path):
    ctx, client, fake = env
    cid, _, _ = _clip(ctx, client, fake)
    with ctx.db.session() as s:
        oid = s.query(ClipOutput).filter_by(clip_id=cid).first().id
    chosen = tmp_path / "my" / "videos"
    assert client.put("/api/settings", json={"storage": {"save_folder": str(chosen)}}).status_code == 200
    saved = Path(client.post(f"/api/outputs/{oid}/save").json()["path"])
    assert saved.parent == chosen and saved.exists()


def test_new_clips_are_kept_in_the_chosen_folder(env, tmp_path):
    ctx, client, fake = env
    chosen = tmp_path / "clip-disk"
    assert client.put("/api/settings", json={"storage": {"media_folder": str(chosen)}}).status_code == 200
    cid, _, _ = _clip(ctx, client, fake)
    with ctx.db.session() as s:
        clip = s.get(Clip, cid)
        files = [Path(o.file_path) for o in s.query(ClipOutput).filter_by(clip_id=cid) if o.file_path]
    assert files and all(chosen in f.parents for f in files) and chosen in Path(clip.files_dir).parents


def test_choose_folder_opens_the_computers_own_picker(env, monkeypatch):
    import subprocess
    ctx, c, fake = env
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="/Users/me/Clips/\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert c.post("/api/pick-folder").json() == {"path": "/Users/me/Clips"}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="User canceled"))
    assert c.post("/api/pick-folder").json() == {"path": None}  # cancelled: nothing changes

    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(subprocess, "run", missing)
    r = c.post("/api/pick-folder")
    assert r.status_code == 501 and "Type the folder" in r.json()["error"]["message"]
