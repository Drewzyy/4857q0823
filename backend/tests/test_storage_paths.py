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


def _base(monkeypatch, tmp_path):
    monkeypatch.delenv("CLIPPR_DATA_DIR", raising=False)
    monkeypatch.setenv("CLIPPR_BASE_DATA_DIR", str(tmp_path / "appdata" / "Vyral"))
    return tmp_path / "appdata" / "Vyral"


def test_data_folder_follows_the_location_file_and_env_wins(monkeypatch, tmp_path):
    from clippr import config
    base = _base(monkeypatch, tmp_path)
    assert config.default_data_dir() == base
    config.write_location({"path": str(tmp_path / "D" / "Vyral")})
    assert config.location_file() == tmp_path / "appdata" / "Vyral-location.json"
    assert config.default_data_dir() == tmp_path / "D" / "Vyral"
    config.location_file().write_text("not json")
    assert config.default_data_dir() == base  # a broken file never loses the data folder
    monkeypatch.setenv("CLIPPR_DATA_DIR", str(tmp_path / "env"))
    assert config.default_data_dir() == tmp_path / "env"


def test_move_at_startup_copies_checks_repoints_and_removes_the_old_folder(monkeypatch, tmp_path):
    import sqlite3

    from clippr import config
    old = _base(monkeypatch, tmp_path)
    (old / "media" / "c1").mkdir(parents=True)
    (old / "media" / "c1" / "clip.mp4").write_bytes(b"v" * 1000)
    con = sqlite3.connect(old / "clippr.db")
    con.execute("CREATE TABLE outputs (file_path TEXT, meta TEXT)")
    con.execute("INSERT INTO outputs VALUES (?, ?)", (str(old / "media" / "c1" / "clip.mp4"), '{"n": 1}'))
    con.commit()
    con.close()
    new = tmp_path / "D" / "Vyral"
    config.write_location({"path": str(new), "move_from": str(old)})
    assert config.default_data_dir() == old  # not moved yet
    config.apply_pending_move()
    assert (new / "media" / "c1" / "clip.mp4").read_bytes() == b"v" * 1000 and not old.exists()
    assert config.read_location() == {"path": str(new), "moved_from": str(old)}
    assert config.default_data_dir() == new
    con = sqlite3.connect(new / "clippr.db")
    assert con.execute("SELECT file_path FROM outputs").fetchone()[0] == str(new / "media" / "c1" / "clip.mp4")
    con.close()


def test_failed_move_keeps_the_old_folder_and_reports_it(monkeypatch, tmp_path):
    import shutil

    from clippr import config
    old = _base(monkeypatch, tmp_path)
    old.mkdir(parents=True)
    (old / "clippr.db").write_bytes(b"x")
    config.write_location({"path": str(tmp_path / "D"), "move_from": str(old)})
    monkeypatch.setattr(shutil, "copytree", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    config.apply_pending_move()
    assert (old / "clippr.db").exists() and config.default_data_dir() == old
    assert "disk full" in config.read_location()["error"]


def test_move_validation(client, monkeypatch, tmp_path):
    from clippr import config
    _base(monkeypatch, tmp_path)
    data = Path(client.get("/api/storage/location").json()["data_dir"])
    for bad, why in (("relative/dir", "full folder path"), (str(data / "inside"), "inside")):
        r = client.post("/api/storage/move", json={"path": bad})
        assert r.status_code == 422 and why in r.json()["error"]["message"]
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert client.post("/api/storage/move", json={"path": str(blocker / "sub")}).status_code == 422
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10, 10, 1))
    r = client.post("/api/storage/move", json={"path": str(tmp_path / "small")})
    assert r.status_code == 422 and "Not enough room" in r.json()["error"]["message"]
    monkeypatch.undo()
    _base(monkeypatch, tmp_path)
    busy = tmp_path / "D"
    busy.mkdir()
    (busy / "other.txt").write_text("x")
    r = client.post("/api/storage/move", json={"path": str(busy)})
    assert r.json()["path"] == str(busy / "Vyral")  # a folder with other things in it gets a Vyral folder inside
    assert config.read_location() == {"path": str(busy / "Vyral"), "move_from": str(data)}
    assert client.get("/api/storage/location").json()["pending"] == str(busy / "Vyral")
    monkeypatch.setenv("CLIPPR_DATA_DIR", str(data))
    assert client.post("/api/storage/move", json={"path": str(tmp_path / "x")}).status_code == 409
