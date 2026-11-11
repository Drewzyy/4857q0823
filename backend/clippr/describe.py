"""Ready-to-paste titles and captions for each platform. Deterministic: only facts we have (the source
post's own words and hashtags, the creator, the stream date, your page settings), never invented."""
from __future__ import annotations

import re
from datetime import datetime

LIMITS = {"tiktok": 2200, "instagram": 2200, "youtube": 5000, "facebook": 5000}
# 3 to 5 specific hashtags beat 20 generic ones (TikTok's own guidance as relayed by creator playbooks; the
# platforms read the caption for topic). Generic reach tags say nothing about the clip, so they're left out.
MAX_TAGS = {"instagram": 5, "tiktok": 5, "youtube": 5, "facebook": 5}
GENERIC_TAGS = {"#fyp", "#foryou", "#foryoupage", "#fy", "#fypシ", "#viral", "#viralvideo", "#trending", "#xyzbca", "#explore", "#explorepage"}
BRAND_TAG = "#vyralclips"
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


def stream_date_line(when: datetime | None) -> str:
    if not when:
        return ""
    d = when.astimezone()
    return f"Streamed {d:%b} {d.day}, {d.year}"


def _tags(original: list[str], page: list[str], platform: str) -> list[str]:
    tags, seen = [], set()
    extra = [BRAND_TAG] + (["#shorts"] if platform == "youtube" else [])
    for t in [*page, *original, *extra]:  # the page's own tags first: the user picked them for this page
        t = t.strip()
        if not t:
            continue
        t = t if t.startswith("#") else f"#{t}"
        if t.lower() in GENERIC_TAGS:
            continue
        if t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    limit = MAX_TAGS.get(platform, 5)
    if len(tags) > limit:  # always keep #vyralclips (and #shorts on YouTube) when trimming
        keep = [t.lower() for t in extra]
        tags = [t for t in tags if t.lower() not in keep][: limit - len(extra)] + extra
    return tags


def game_tag(game: str) -> str:
    """'Grand Theft Auto VI' -> '#GrandTheftAutoVI'. Empty for categories that aren't a game."""
    if not game or game.lower() in NOT_GAMES:
        return ""
    return "#" + "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", game))


def build(platform: str, source_title: str, creator: str | None, settings: dict, stream_date: datetime | None = None,
          game: str = "") -> tuple[str, str]:
    """Returns (title, description). Title is YouTube's separate title; elsewhere it leads the caption. The game
    goes in as words (captions are what Instagram and TikTok search reads) and as one specific hashtag."""
    title = clean_title(source_title, creator)
    parts = [title] if platform != "youtube" else []
    if settings.get("default_caption"):
        parts.append(settings["default_caption"].strip())
    playing = game if game_tag(game) else ""
    info = "\n".join(x for x in [f"Streamer: {creator}" if creator else "", f"Game: {playing}" if playing else "",
                                 stream_date_line(stream_date)] if x)
    if info:
        parts.append(info)
    parts.append(" ".join(_tags([game_tag(game)] + original_hashtags(source_title), settings.get("hashtags") or [], platform)))
    desc = "\n\n".join(p for p in parts if p)
    return title, desc[: LIMITS.get(platform, 2200)]
