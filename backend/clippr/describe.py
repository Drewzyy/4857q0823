"""Ready-to-paste titles and captions for each platform: the clip's title (titles.py), your page's extra line and
a few specific hashtags."""
from __future__ import annotations

import re

LIMITS = {"tiktok": 2200, "instagram": 2200, "youtube": 5000, "facebook": 5000}
# 3 to 5 specific hashtags beat 20 generic ones (TikTok's own guidance as relayed by creator playbooks; the
# platforms read the caption for topic). Generic reach tags say nothing about the clip, so they're left out.
MAX_TAGS = {"instagram": 6, "tiktok": 6, "youtube": 6, "facebook": 6}
DEFAULT_TAGS = ["#fyp", "#funny"]  # yours: @lacy #lacy #gta6 #fyp #funny #core
# Taken out of a source post's own tags (Vyral adds #fyp itself, once).
GENERIC_TAGS = {"#fyp", "#foryou", "#foryoupage", "#fy", "#fypシ", "#viral", "#viralvideo", "#trending", "#xyzbca", "#explore", "#explorepage"}
NOT_GAMES = {"just chatting", "irl", "talk shows & podcasts", "music", "art", "special events", "pools, hot tubs, and beaches", "asmr", "sports"}


def clean_title(text: str, creator: str | None) -> str:
    """The post's words without hashtags, @mentions and links."""
    t = re.sub(r"#[\w.]+|@[\w.]+", " ", text or "")
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -|·:")
    if not t:
        t = f"{creator} moment" if creator else "Stream moment"
    return t[:100].rstrip()


def original_hashtags(text: str) -> list[str]:
    return re.findall(r"#[\w]+", text or "")


def _tags(first: list[str], page: list[str], original: list[str], platform: str) -> list[str]:
    tags, seen = [], set()
    extra = ["#shorts"] if platform == "youtube" else []
    for t in [*first, *page, *[x for x in original if x.lower() not in GENERIC_TAGS], *extra]:
        t = t.strip()
        if not t or t == "#":
            continue
        t = t if t.startswith("#") else f"#{t}"
        if t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    limit = MAX_TAGS.get(platform, 6)
    if len(tags) > limit:  # always keep #shorts on YouTube when trimming
        tags = [t for t in tags if t.lower() not in extra][: limit - len(extra)] + extra
    return tags


def game_tag(game: str) -> str:
    """'Grand Theft Auto VI' -> '#GrandTheftAutoVI'. Empty for categories that aren't a game."""
    if not game or game.lower() in NOT_GAMES:
        return ""
    return "#" + "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", game))


def has_tag(text: str, tag: str) -> bool:
    return bool(re.search(rf"{re.escape(tag)}(?!\w)", text, re.I))


def has_name(text: str, name: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I))


def clean_list(items: list[str], hashtags: bool = False) -> list[str]:
    """For a list typed by the user: trimmed, no blanks, and hashtags that start with # and are one word."""
    items = [x.strip() for x in items if x.strip()]
    if any(len(x) > 60 for x in items):
        raise ValueError("Each one must be 60 characters or fewer")
    if hashtags:
        items = [x if x.startswith("#") else f"#{x}" for x in items]
        if not all(re.fullmatch(r"#\w+", x) for x in items):
            raise ValueError("Hashtags can only use letters, numbers and _")
    return items


def apply_rules(caption: str, rules: dict | None, platform: str = "", title: str = "") -> str:
    """Make a caption follow rules ({hashtags, mention, extra}): a missing extra line and a missing name ("With Lacy")
    go after the text, a missing hashtag joins the hashtag line. What's already there is left alone, and if the
    caption is too long for the platform the text is cut, never the rules. `title` counts as where a name can be said."""
    rules = rules or {}
    body, _, tail = caption.rstrip().rpartition("\n")
    if not tail.lstrip().startswith(("#", "@")):  # the tag line: hashtags, or the streamer's @ then hashtags
        body, tail = caption.rstrip(), ""
    body = body.rstrip()
    seen = f"{caption}\n{title}"
    add = [x for x in [rules.get("extra", "").strip()] if x and x.lower() not in seen.lower()]
    names = [n for n in rules.get("mention") or [] if not has_name(seen, n)]
    if names:
        add.append("With " + ", ".join(names))
    tail = " ".join([tail, *(h for h in rules.get("hashtags") or [] if not has_tag(caption, h))]).strip()
    end = "\n\n".join(p for p in [*add, tail] if p)
    limit = LIMITS.get(platform, 2200)
    return "\n\n".join(p for p in [body[: max(0, limit - len(end) - 2)], end] if p)[:limit]


def handle(name: str) -> str:
    """'Jason Levine' -> 'jasonlevine': how a streamer is tagged."""
    return re.sub(r"[^\w]", "", (name or "").lower())


def build(platform: str, title: str, tags_from: str, settings: dict, game: str = "", rules: dict | None = None,
          streamer: str = "") -> tuple[str, str]:
    """(title, caption). The caption is nearly empty on purpose, the way you post: the page's own line if it has
    one, then the streamer's @ and the hashtags (the streamer, the game, #fyp, #funny, the page's own, then the
    source post's). It never repeats the title or the headline on the video, and has no emoji. YouTube shows
    the title separately. streamer: the streamer's handle (their stream channel name), for @ and #."""
    who = handle(streamer)
    # learned_tags: the hashtags your own clips use most (style.py), right after #fyp #funny.
    tags = _tags([f"#{who}" if who else "", game_tag(game).lower(), *DEFAULT_TAGS, *(settings.get("learned_tags") or [])],
                 settings.get("hashtags") or [],
                 original_hashtags(tags_from), platform)
    parts = [settings.get("default_caption", "").strip(), " ".join(([f"@{who}"] if who and platform != "youtube" else []) + tags)]
    desc = "\n\n".join(p for p in parts if p)
    return title[:100], apply_rules(desc[: LIMITS.get(platform, 2200)], rules, platform, title)
