"""Obsidian as Vyral's memory: a readable, editable copy of what it learned from your clips, and your own rules.

An Obsidian vault is just a folder of Markdown notes on this computer, so nothing goes over the internet and no
plugin is needed. Vyral only ever reads and writes inside the vault's Vyral/ folder:
- Vyral/Learned/<date> <source>.md: one note per clip you sent to learn from (style.py), with what was measured;
- Vyral/Playbook.md: what your clips do in each situation (laugh, shock, anger, fear, hype, plain), rewritten on
  every sync, except the "## My rules" section, which is yours and is never touched.

Rules in "## My rules", one per line (anything else in the section is ignored):
    - laugh: sound=vine_boom, zoom=on, headline=off
    - shock: hook=on
    - any: max_length=60
Situations: any, laugh, shock, anger, fear, hype, plain ("any" applies to every clip; the clip's own situation
wins). Keys: hook, headline, sfx, zoom, captions (on/off), sound (a sound's name, or off), length (seconds more or
less than your usual, -30 to 30), max_length (seconds, 10 to 600). They win over your learned style and the
tuner when a clip is pre-edited (preedit.apply, through `force`).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from .models import Setting

log = logging.getLogger("clippr.obsidian")
KEY = "obsidian"
SITUATIONS = ("laugh", "shock", "anger", "fear", "hype", "plain")
MY_RULES = "## My rules"
RULES_HELP = ("<!-- One rule per line, like:\n- laugh: sound=vine_boom, zoom=on, headline=off\n- shock: hook=on\n- any: max_length=60\n"
              "Situations: any, laugh, shock, anger, fear, hype, plain. Keys: hook, headline, sfx, zoom, captions (on/off), "
              "sound (a sound's name or off), length (seconds more or less than usual), max_length (seconds). -->")
ON = {"on": True, "yes": True, "true": True, "off": False, "no": False, "false": False}
RULE = re.compile(r"^\s*[-*]\s*(\w+)\s*:\s*(.+?)\s*$")


# ---------- the vault ----------
def check_vault(path: str) -> Path:
    """The vault folder, or ValueError saying what's wrong with the path."""
    p = Path(path.strip().strip('"').strip("'")).expanduser()
    if not str(p).strip() or not p.is_absolute():
        raise ValueError("Paste the full path of your vault folder, like /Users/you/Documents/My vault")
    if not p.is_dir():
        raise ValueError(f"There's no folder at {p}")
    if not (p / ".obsidian").is_dir():
        raise ValueError(f"{p} isn't an Obsidian vault (it has no .obsidian folder). Open it in Obsidian once, or pick the vault's own folder.")
    return p.resolve()


def _base(vault: str) -> Path | None:
    """The vault's Vyral/ folder, made if needed, or None when the vault is gone or Vyral/ points outside it."""
    try:
        root = check_vault(vault)
        base = root / "Vyral"
        base.mkdir(exist_ok=True)
        base = base.resolve()
        return base if base.is_relative_to(root) else None
    except (ValueError, OSError) as e:
        log.warning("Obsidian vault unavailable: %s", e)
        return None


def inside(base: Path, rel: str) -> Path:
    """base/rel, refusing anything that ends up outside base (.., absolute paths, links out)."""
    p = (base / rel).resolve()
    if not p.is_relative_to(base):
        raise ValueError(f"refusing to touch {rel}: outside the vault's Vyral folder")
    return p


def _vault(s: Session) -> str:
    from .api.system import load_settings
    return load_settings(s).obsidian.vault


def state(s: Session) -> dict:
    r = s.get(Setting, KEY)
    return dict(r.value) if r else {}


def _save(s: Session, value: dict) -> None:
    r = s.get(Setting, KEY)
    if r:
        r.value = value
    else:
        s.add(Setting(key=KEY, value=value))


# ---------- notes ----------
def _front(text: str) -> dict:
    """The --- frontmatter of a note Vyral wrote (one `key: json value` per line), or {}."""
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, _, v = line.partition(":")
        try:
            out[k.strip()] = json.loads(v.strip())
        except ValueError:
            out[k.strip()] = v.strip()
    return out


def _name(example: dict) -> str:
    src = re.sub(r"^https?://(www\.)?", "", example["url"])
    src = re.sub(r"[^\w .-]+", " ", src).strip()[:60].strip(" .") or "clip"
    return f"{(example.get('at') or '')[:10] or 'undated'} {src}.md"


def situation(text: str) -> str:
    from .titles import _mood
    return _mood(text or "")


def learned_note(example: dict) -> str:
    """One learned clip as a note: frontmatter of what was measured, then the same in words."""
    f = example["features"]
    mood = situation(example.get("title") or "")
    front = {"url": example["url"], "learned": example.get("at"), "situation": mood, "views": example.get("views"),
             **{k: f.get(k) for k in ("length", "hook", "cuts_per_min", "layout", "captions", "headline", "sfx", "sound", "zooms", "peak_share", "tail")},
             "hashtags": example.get("hashtags") or [], "song": example.get("song")}
    edits = [f"Opens on the climax for {f['hook']:g} s (a hook)" if f.get("hook") else "No hook: starts at the start",
             f"{f.get('zooms') or 0} zoom-ins", f"{f.get('cuts_per_min', 0):g} cuts a minute", f"Layout: {f.get('layout')}"]
    sfx = (f"{f['sfx']} sound effects" + (f", mostly {f['sound']}" if f.get("sound") else " (not one of Vyral's sounds)")) if f.get("sfx") else "No sound effects"
    peak = f", the big moment {round(f['peak_share'] * 100)}% of the way in" if f.get("peak_share") is not None else ""
    lines = ["---", *(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()), "---", "",
             f"# {example.get('title') or example['url']}", "", f"Source: {example['url']}", "",
             f"**Situation:** {mood}", f"**Length:** {f.get('length', 0):g} s{peak}",
             f"**Views:** {example['views']:,}" if example.get("views") else "**Views:** unknown", "",
             "## Edits", *(f"- {x}" for x in edits), "", "## Sound", f"- {sfx}",
             *([f"- Song: {example['song']}"] if example.get("song") else []), "", "## Text",
             f"- Headline at the top for {f['headline']:g} s" if f.get("headline") else "- No headline",
             f"- Captions: {'yes' if f.get('captions') else 'no'}",
             *([f"- Post text: {example['title']}"] if example.get("title") else []),
             *([f"- Hashtags: {' '.join(example['hashtags'])}"] if example.get("hashtags") else []), ""]
    return "\n".join(lines)


def write_learned(base: Path, example: dict) -> Path | None:
    if not example.get("features"):
        return None
    p = inside(base, "Learned/" + _name(example))
    p.parent.mkdir(exist_ok=True)
    p.write_text(learned_note(example), encoding="utf-8")
    return p


def read_learned(base: Path) -> list[dict]:
    """Every Learned note's frontmatter (yours to edit, e.g. a situation), skipping any that can't be read."""
    out = []
    folder = inside(base, "Learned")
    for p in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            front = _front(inside(base, f"Learned/{p.name}").read_text(encoding="utf-8"))
            if front.get("url"):
                out.append(front)
        except (OSError, ValueError) as e:
            log.warning("skipped note %s: %s", p.name, e)
    return out


# ---------- the playbook ----------
def parse_rules(text: str) -> tuple[dict, list[str]]:
    """({situation: force}, warnings) from the "## My rules" section of the playbook."""
    from .media import sfx
    m = re.search(r"^## My rules[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    rules: dict[str, dict] = {}
    warnings: list[str] = []
    for line in re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).splitlines() if m else []:
        r = RULE.match(line)
        if not r:
            continue
        where, body = r.group(1).lower(), r.group(2)
        if where not in ("any", *SITUATIONS):
            warnings.append(f"Unknown situation \"{where}\" in: {line.strip()}")
            continue
        out = rules.setdefault(where, {})
        for part in filter(None, (x.strip() for x in body.split(","))):
            k, _, v = (x.strip().lower() for x in part.partition("="))
            if k in ("hook", "headline", "sfx", "zoom", "captions") and v in ON:
                out[k] = ON[v]
            elif k == "sound" and v in ("off", "none"):
                out["sfx"] = False
            elif k == "sound" and sfx.is_sound_name(v):
                out.update(sound=v, sfx=True)
            elif k in ("length", "max_length") and re.fullmatch(r"[+-]?\d+(\.\d+)?", v) and (
                    -30 <= float(v) <= 30 if k == "length" else 10 <= float(v) <= 600):
                out[k] = float(v)
            else:
                warnings.append(f"Ignored \"{part}\" ({where}): " + (f"no sound named {v}" if k == "sound" else "not a key and value Vyral knows"))
    return {k: v for k, v in rules.items() if v}, warnings


def playbook(notes: list[dict], mine: str) -> str:
    """Playbook.md: per situation, what your learned clips usually do, then your rules section untouched."""
    out = ["# Vyral playbook", "", "Written by Vyral from your Learned notes on every sync. Everything above \"My rules\" is rewritten;",
           "write your own rules under \"My rules\" and Vyral uses them when it makes clips.", ""]
    for mood in SITUATIONS:
        ns = [n for n in notes if n.get("situation") == mood]
        if not ns:
            continue
        rate = lambda k: round(100 * sum(1 for n in ns if n.get(k)) / len(ns))  # noqa: E731
        sounds = sorted({n["sound"] for n in ns if n.get("sound")}, key=lambda x: -sum(1 for n in ns if n.get("sound") == x))
        lens = sorted(float(n.get("length") or 0) for n in ns)
        layouts = [n.get("layout") for n in ns if n.get("layout")]
        out += [f"## {mood.capitalize()} ({len(ns)} clip{'s' if len(ns) != 1 else ''})",
                f"- Length: usually about {lens[len(lens) // 2]:g} s",
                f"- Hook (climax first): {rate('hook')}% of clips", f"- Zoom-ins: {rate('zooms')}% of clips",
                f"- Sound effects: {rate('sfx')}% of clips" + (f", mostly {', '.join(sounds[:2])}" if sounds else ""),
                f"- Headline at the top: {rate('headline')}%, captions: {rate('captions')}%",
                f"- Layout: mostly {max(set(layouts), key=layouts.count)}" if layouts else "- Layout: unknown", ""]
    if len(out) == 5:
        out += ["No learned clips yet. Send clips to learn from (Discord inbox or Settings > Your style) and they show up here.", ""]
    return "\n".join(out) + (mine.rstrip() + "\n" if mine else f"{MY_RULES}\n\n{RULES_HELP}\n\n")


def _mine(text: str) -> str:
    m = re.search(r"^## My rules.*", text, re.S | re.M)
    return m.group(0) if m else ""


def sync(s: Session) -> dict:
    """Write the missing Learned notes, rewrite the playbook (keeping your rules) and read your rules."""
    from . import style
    vault = _vault(s)
    if not vault:
        return {"skipped": "not connected"}
    st = state(s)
    base = _base(vault)
    if base is None:
        st.update(error="The vault folder can't be found. Is it moved or renamed? Connect it again.", rules={})
        _save(s, st)
        return {"error": st["error"]}
    try:
        notes = read_learned(base)
        have = {n["url"] for n in notes}
        for e in style._row(s).get("examples", []):
            if e.get("features") and e["url"] not in have and write_learned(base, e):
                notes.append(_front(learned_note(e)))
        book = inside(base, "Playbook.md")
        old = book.read_text(encoding="utf-8") if book.exists() else ""
        mine = _mine(old)
        book.write_text(playbook(notes, mine), encoding="utf-8")
        rules, warnings = parse_rules(mine)
    except (OSError, ValueError) as e:
        log.warning("Obsidian sync failed: %s", e)
        st.update(error=f"Couldn't write to the vault: {e}")
        _save(s, st)
        return {"error": st["error"]}
    st.update(error=None, rules=rules, warnings=warnings, notes=len(notes), synced=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    _save(s, st)
    return {"notes": len(notes), "rules": len(rules), "warnings": len(warnings)}


def force(s: Session) -> dict:
    """Your rules for preedit.apply's `force` ({"situations": {...}}), read fresh from the vault, or {} (never raises)."""
    try:
        vault = _vault(s)
        base = _base(vault) if vault else None
        if base is None:
            return {}
        book = inside(base, "Playbook.md")
        rules = parse_rules(book.read_text(encoding="utf-8"))[0] if book.exists() else {}
        return {"situations": rules} if rules else {}
    except Exception:
        log.exception("couldn't read the Obsidian rules")
        return {}


def learned(ctx, url: str, title: str) -> None:
    """After style.py learned a clip: its note in the vault, when one is connected (never fails the learning)."""
    from . import style
    try:
        with ctx.db.session() as s:
            vault = _vault(s)
            base = _base(vault) if vault else None
            e = next((x for x in style._row(s).get("examples", []) if x["url"] == url), None)
        if base and e:
            write_learned(base, {**e, "title": e.get("title") or title})
    except Exception:
        log.exception("couldn't write the Obsidian note for %s", url)


def view(s: Session) -> dict:
    vault = _vault(s)
    st = state(s)
    return {"connected": bool(vault), "vault": vault, "name": Path(vault).name if vault else None, "notes": st.get("notes", 0),
            "synced": st.get("synced"), "error": st.get("error"), "warnings": st.get("warnings", []),
            "rules": st.get("rules", {})}
