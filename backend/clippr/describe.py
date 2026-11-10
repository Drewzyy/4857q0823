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


def build(platform: str, source_title: str, creator: str | None, settings: dict, stream_date: datetime | None = None) -> tuple[str, str]:
    """Returns (title, description). Title is YouTube's separate title; elsewhere it leads the caption."""
    title = clean_title(source_title, creator)
    parts = [title] if platform != "youtube" else []
    if settings.get("default_caption"):
        parts.append(settings["default_caption"].strip())
    info = "\n".join(x for x in [f"Streamer: {creator}" if creator else "", stream_date_line(stream_date)] if x)
    if info:
        parts.append(info)
    parts.append(" ".join(_tags(original_hashtags(source_title), settings.get("hashtags") or [], platform)))
    desc = "\n\n".join(p for p in parts if p)
    return title, desc[: LIMITS.get(platform, 2200)]
