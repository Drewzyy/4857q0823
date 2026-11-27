"""Obsidian memory: connecting a vault, notes written there, the playbook, and your rules applied to clips."""
import numpy as np
import pytest

from clippr import obsidian, preedit, style
from clippr.media.overlay import Word
from clippr.schemas import ClipEdit

FEATS = {"length": 42.0, "hook": 3.0, "cuts_per_min": 2.0, "layout": "stacked", "captions": True, "headline": 4.0,
         "sfx": 1, "sound": "boom", "zooms": 2, "peak_share": 0.7, "tail": 6.0}


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "My vault"
    (v / ".obsidian").mkdir(parents=True)
    return v


def test_connect_validates(client, vault, tmp_path):
    (tmp_path / "plain").mkdir()
    for bad in ("", "relative/path", str(tmp_path / "missing"), str(tmp_path / "plain")):
        r = client.post("/api/obsidian/connect", json={"path": bad})
        assert r.status_code == 422, bad
    assert "isn't an Obsidian vault" in client.post("/api/obsidian/connect", json={"path": str(tmp_path / "plain")}).json()["error"]["message"]
    r = client.post("/api/obsidian/connect", json={"path": f'"{vault}"'}).json()
    assert r["connected"] and r["name"] == "My vault" and r["synced"] and not r["error"]
    assert (vault / "Vyral" / "Playbook.md").exists()
    assert not client.post("/api/obsidian/disconnect").json()["connected"]


def test_learned_note_playbook_and_rules(client, ctx, vault):
    client.post("/api/obsidian/connect", json={"path": str(vault)})
    with ctx.db.session() as s:
        style.add(s, "https://www.tiktok.com/@me/video/1", FEATS, views=12000, hashtags=["#kai"], title="he was laughing so hard lmao")
    obsidian.learned(ctx, "https://www.tiktok.com/@me/video/1", "")
    notes = list((vault / "Vyral" / "Learned").glob("*.md"))
    assert len(notes) == 1 and "/" not in notes[0].name
    text = notes[0].read_text()
    front = obsidian._front(text)
    assert front["situation"] == "laugh" and front["sound"] == "boom" and front["views"] == 12000
    assert "2 zoom-ins" in text and "mostly boom" in text and "Headline at the top for 4 s" in text
    (vault / "Vyral" / "Learned" / "broken.md").write_text("---\nnot: [valid\n")  # no url: skipped, never fatal
    book = vault / "Vyral" / "Playbook.md"
    book.write_text(book.read_text().replace("## My rules", "old summary\n## My rules\n- laugh: sound=ding, zoom=off, headline=off\n"
                                             "- any: max_length=60, wobble=yes\n- party: hook=on\n- shock: sound=nope", 1))
    r = client.post("/api/obsidian/sync").json()
    assert r["notes"] == 1 and r["rules"] == {"laugh": {"sound": "ding", "sfx": True, "zoom": False, "headline": False}, "any": {"max_length": 60.0}}
    assert len(r["warnings"]) == 3
    again = book.read_text()
    assert "## Laugh (1 clip)" in again and "old summary" not in again and "- laugh: sound=ding" in again
    with ctx.db.session() as s:
        assert obsidian.force(s)["situations"]["laugh"]["sound"] == "ding"


def test_rules_applied_by_situation():
    words = [Word(i * 0.5, i * 0.5 + 0.4, w) for i, w in enumerate("lmao he fell off the chair haha".split())]
    db = np.full(900, -30.0)
    db[300:320] = -5.0
    rules = {"situations": {"laugh": {"sound": "ding", "sfx": True, "zoom": False, "captions": False}, "shock": {"hook": True},
                            "any": {"max_length": 40.0}}}
    e = preedit.apply(ClipEdit(start=0, end=90).model_dump(), words, db, "x", sound=False, force=rules)
    assert e["sounds"][0]["name"] == "ding" and not e.get("punch") and e["captions"] is False
    assert e["end"] - e["start"] <= 40.0 and e["trial"]["situation"] == "laugh"
    plain = preedit.apply(ClipEdit(start=0, end=90).model_dump(), [], db, "x", sound=False, force=rules)
    assert not plain["sounds"] and plain["trial"]["situation"] == "plain"


def test_paths_stay_inside(tmp_path, vault):
    base = obsidian._base(str(vault))
    with pytest.raises(ValueError):
        obsidian.inside(base, "../escape.md")
    with pytest.raises(ValueError):
        obsidian.inside(base, "/etc/passwd")
    p = obsidian.write_learned(base, {"url": "https://x.com/../../../etc/a", "at": "2026-11-01", "features": FEATS})
    assert p.is_relative_to(base / "Learned")


def test_vault_gone_is_harmless(ctx, vault):
    import shutil
    from clippr.api.system import put_settings
    with ctx.db.session() as s:
        put_settings({"obsidian": {"vault": str(vault)}}, s)
    shutil.rmtree(vault)
    with ctx.db.session() as s:
        assert obsidian.force(s) == {}
        assert "error" in obsidian.sync(s)
        assert obsidian.view(s)["error"]
