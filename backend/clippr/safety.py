"""The pre-post safety check. Runs on every clip before it can be reviewed or posted; separate from the virality
grade, and it comes first: a clip that fails is quarantined and never offered for review or posted.

Built from TikTok's Community Guidelines (Safety and Civility: violent behaviors, hate speech, harassment;
Mental and Behavioral Health: suicide and self-harm; Sensitive and Mature Themes: sexual activity and nudity,
shocking and graphic content; Regulated Goods and Commercial Activities: drugs, weapons; Integrity and
Authenticity: intellectual property, unoriginal content) and Instagram's Community Guidelines and Recommendations
Guidelines (nudity, graphic violence, hate speech, bullying and harassment, regulated goods, intellectual property).

What it checks, all on this computer:
- the streamer's clip permission (off: out, same as a fail);
- what's said (the transcript), the headline, the titles and the source post's caption, against the categories
  below and your blocklist in Settings;
- the game: GTA and similar games get stricter checks, and games on your blocklist are out;
- re-uploads: a clip with no transformation (no captions, no headline) of someone else's post goes to review.
What it can't check here, so a person (or Muse) must look before approving: the picture itself (nudity, gore,
weapons on screen) and whether music in the clip is copyrighted. Those are listed on every result as not checked,
and a clip is never auto-posted on the strength of this check alone.

Results: "fail" (quarantined: never reviewed, never posted, stays failed through edits and re-renders),
"review" (something borderline or uncertain: only a person or Muse can approve it, never auto-posted) or "pass".
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# category: (fails outright, needs review). Whole words or phrases, case-insensitive.
CATEGORIES: dict[str, tuple[list[str], list[str]]] = {
    "sexual content and nudity": (["sex tape", "porn", "pornhub", "onlyfans", "nudes", "blowjob", "handjob", "sex act", "having sex",
                                   "strip club", "stripper", "lap dance", "naked", "nude"], ["sexy", "horny", "booty", "twerk"]),
    "sexualized minors": (["underage", "minor nude", "jailbait", "child porn"], []),
    "graphic violence and gore": (["gore", "decapitat", "beheading", "dismember", "torture", "execution", "executed him", "blood everywhere"],
                                  ["blood", "stabbed", "shot him", "killed him", "murder"]),
    "threats": (["i will kill you", "i'm gonna kill you", "im gonna kill you", "i'll kill you", "shoot up", "bomb threat"], ["kill you"]),
    "self-harm": (["kill yourself", "kys", "suicide", "cut myself", "self harm", "self-harm"], ["want to die", "end it all"]),
    "hate speech": (["heil hitler", "white power", "gas the"], ["racist"]),
    "harassment": (["doxx", "dox him", "dox her", "home address is"], ["ugly ass", "fat ass"]),
    "drugs": (["selling drugs", "drug deal", "plug me", "cocaine", "meth", "heroin", "fentanyl", "snorting", "crack pipe"],
              ["weed", "edible", "high as", "smoking", "blunt", "xan", "percs", "lean"]),
    "weapons used to threaten": (["point the gun at", "pulled a gun", "gun to his head", "gun to her head"], ["gun", "glock", "knife"]),
    "illegal activity": (["robbing", "rob a", "shoplift", "steal a car", "swatting", "swatted"], ["stole", "cops"]),
}
# Games where the scenes above happen on screen often enough that what's said is the only warning: stricter.
HIGH_RISK_GAMES = re.compile(r"\b(gta|grand theft auto|red dead|cyberpunk|hitman|mafia|saints row|the last of us|mortal kombat|outlast)\b", re.I)
HIGH_RISK_SCENES = ["strip club", "stripper", "lap dance", "prostitute", "hooker", "torture", "execute", "execution", "beat her",
                    "kidnap", "hostage", "snort", "cocaine"]
NOT_CHECKED = ["the picture itself (nudity, gore, weapons on screen): look before approving",
               "copyrighted music: there's no local music fingerprinting"]


def _compile(terms: list[str]) -> re.Pattern | None:
    terms = [t.strip() for t in terms if t and t.strip()]
    if not terms:
        return None
    return re.compile(r"(?<![\w'])(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")", re.I)


def _when(words: list[dict], phrase: str) -> float | None:
    """Seconds into the clip where a phrase is said (its first word), if it's in the transcript."""
    first = phrase.split()[0].lower()
    for w in words:
        if first in w["text"].lower():
            return round(float(w["start"]), 2)
    return None


def check(*, permission: bool | None, words: list[dict], texts: list[str], game: str = "", reupload_untransformed: bool = False,
          blocklist: dict | None = None, previous: dict | None = None) -> dict:
    """The safety result for one clip. words: the transcript ({start, end, text}, seconds into the clip); texts: the
    headline, titles and captions shown or posted with it."""
    flags: list[dict] = []

    def flag(category: str, level: str, reason: str, at: float | None = None, confidence: float = 0.9) -> None:
        flags.append({"category": category, "level": level, "reason": reason, "at": at, "confidence": confidence})

    if permission is False:
        flag("creator rights", "fail", "You haven't confirmed permission to clip this streamer", confidence=1.0)
    elif permission is None:
        flag("creator rights", "review", "No streamer is linked to this clip, so permission to clip them isn't confirmed", confidence=0.5)
    said = " ".join(w["text"] for w in words)
    shown = " \n ".join(t for t in texts if t)
    for where, text in (("said", said), ("shown", shown)):
        for category, (hard, soft) in CATEGORIES.items():
            for level, terms in (("fail", hard), ("review", soft)):
                rx = _compile(terms)
                for m in rx.finditer(text) if rx else ():
                    flag(category, level, f"“{m.group(0)}” {where}", _when(words, m.group(0)) if where == "said" else None,
                         0.85 if level == "fail" else 0.5)
                    break
    bl = blocklist or {}
    for key, label in (("banned_words", "your banned words"), ("banned_scenes", "your banned scenes")):
        rx = _compile(bl.get(key) or [])
        for text, where in ((said, "said"), (shown, "shown")):
            m = rx.search(text) if rx else None
            if m:
                flag("blocklist", "fail", f"“{m.group(0)}” {where} (on {label})", _when(words, m.group(0)) if where == "said" else None, 1.0)
    if game:
        if any(g.strip() and g.strip().lower() in game.lower() for g in bl.get("banned_games") or []):
            flag("blocklist", "fail", f"{game} is on your banned games", confidence=1.0)
        if HIGH_RISK_GAMES.search(game):
            rx = _compile(HIGH_RISK_SCENES)
            m = rx.search(f"{said}\n{shown}") if rx else None
            if m:
                flag("high-risk game scene", "fail", f"{game}: “{m.group(0)}”", _when(words, m.group(0)), 0.8)
            else:
                flag("high-risk game", "review", f"{game} often shows scenes that get accounts flagged; check the picture", confidence=0.4)
    if reupload_untransformed:
        flag("unoriginal content", "review", "Someone else's post with no captions or headline added: reads as a straight re-upload", confidence=0.6)
    if previous and previous.get("status") == "fail":  # quarantine sticks: edits and re-renders never release it
        flags += [f for f in previous.get("flags", []) if f["level"] == "fail" and f not in flags]
    status = "fail" if any(f["level"] == "fail" for f in flags) else "review" if flags else "pass"
    return {"status": status, "flags": flags, "not_checked": NOT_CHECKED,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
