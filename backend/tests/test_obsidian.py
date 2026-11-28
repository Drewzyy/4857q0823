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


def test_review_notes_go_to_the_vault_and_the_playbook_keeps_my_rules(client, ctx, vault, tmp_path):
    from datetime import datetime
    from clippr import obsidian, posting, tuner
    from clippr.models import ClipOutput, Setting
    from test_screen import _clip
    client.post("/api/obsidian/connect", json={"path": str(vault)})
    book = vault / "Vyral" / "Playbook.md"
    book.write_text(book.read_text().replace("## My rules", "## My rules\n- laugh: zoom=off", 1))
    mine = obsidian._mine(book.read_text())
    _clip(ctx, tmp_path, n=1)
    with ctx.db.session() as s:
        oid = s.query(ClipOutput).first().id
        posting.reject(s, oid, "you", "too short, no context")
    month = vault / "Vyral" / "Feedback" / f"{datetime.now().astimezone():%Y-%m}.md"
    text = month.read_text()
    assert "Clip 0" in text and "Page: My page" in text and "rejected by you" in text and "too short, no context" in text
    assert "min seconds 35 to 38" in text
    pb = book.read_text()
    assert "## What your reviews taught" in pb and "min seconds: 38" in pb and "too short, no context (1)" in pb
    assert obsidian._mine(pb).rstrip() == mine.rstrip() and pb.index("## What your reviews taught") < pb.index("## My rules")
    with ctx.db.session() as s:  # a tuner winner: the section is regenerated, once, with My rules kept
        s.merge(Setting(key="tuned", value={"best": {}, "results": {}}))
        s.flush()
        orig = tuner._scores
        tuner._scores = lambda s, since: [({"hook": True}, 1.0)] * 6 + [({"hook": False}, 0.0)] * 6
        try:
            tuner.learn(s)
        finally:
            tuner._scores = orig
    pb = book.read_text()
    assert pb.count("## What your reviews taught") == 1 and "Climax first (hook): True" in pb and obsidian._mine(pb).rstrip() == mine.rstrip()
    r = client.post("/api/obsidian/sync").json()  # a full sync keeps the section too
    assert r["rules"] == {"laugh": {"zoom": False}} and "## What your reviews taught" in book.read_text()


def test_feedback_without_a_vault_is_skipped_quietly(client, ctx, tmp_path):
    from clippr import obsidian, posting
    from clippr.models import ClipOutput
    from test_screen import _clip
    _clip(ctx, tmp_path, n=1)
    with ctx.db.session() as s:
        posting.reject(s, s.query(ClipOutput).first().id, "you", "boring")  # not connected: nothing written, no error
        obsidian.feedback(s, title="x", page="y", decision="z", note="n")
        obsidian.write_taught(s)
    gone = tmp_path / "gone vault"
    (gone / ".obsidian").mkdir(parents=True)
    client.post("/api/obsidian/connect", json={"path": str(gone)})
    import shutil
    shutil.rmtree(gone)
    with ctx.db.session() as s:  # connected, then the vault went away
        posting.reject(s, s.query(ClipOutput).first().id, "you", "too long")
    assert not gone.exists()
