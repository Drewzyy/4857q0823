"""Ready-to-paste titles and captions for each platform. Deterministic: it only uses facts we
have (the source post's own words, the creator, your destination defaults), never invents events."""
from __future__ import annotations

import re

LIMITS = {"tiktok": 2200, "instagram": 2200, "youtube": 5000, "facebook": 5000}
MAX_TAGS = {"instagram": 30, "tiktok": 30, "youtube": 15, "facebook": 30}


def clean_title(text: str, creator: str | None) -> str:
    t = re.sub(r"#[\w.]+|@[\w.]+", " ", text or "")
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -|·:")
    if not t:
        t = f"{creator} moment" if creator else "Stream moment"
    return t[:100].rstrip()


def _tags(raw: list[str], platform: str, creator: str | None) -> list[str]:
    tags, seen = [], set()
    extra = [f"#{re.sub(r'[^A-Za-z0-9_]', '', creator)}"] if creator and re.sub(r"[^A-Za-z0-9_]", "", creator) else []
    if platform == "youtube":
        extra.append("#shorts")
    for t in [*raw, *extra]:
        t = t.strip()
        if not t:
            continue
        t = t if t.startswith("#") else f"#{t}"
        if t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    return tags[: MAX_TAGS.get(platform, 30)]


def build(platform: str, source_title: str, creator: str | None, settings: dict) -> tuple[str, str]:
    """Returns (title, description). Title matters for YouTube; elsewhere it leads the caption."""
    title = clean_title(source_title, creator)
    parts = [title] if platform != "youtube" else []
    if settings.get("default_caption"):
        parts.append(settings["default_caption"].strip())
    if creator:
        parts.append(f"Streamer: {creator}")
    tags = _tags(settings.get("hashtags") or [], platform, creator)
    if tags:
        parts.append(" ".join(tags))
    desc = "\n\n".join(p for p in parts if p)
    return title, desc[: LIMITS.get(platform, 2200)]
