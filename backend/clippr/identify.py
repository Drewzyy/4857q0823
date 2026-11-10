"""Guess whose stream a clip came from, using the post's caption, hashtags and @mentions.

The audio match is what decides; this only orders the search so the streamer the post names is
checked first. That matters for groups who stream together: the same moment is in several
streams, and the clip should be cut from the point of view the post is about.
"""
from __future__ import annotations

import re

Candidate = tuple[int, str, list[str]]  # creator id, name, stream channel links

_HANDLE = re.compile(r"(?:twitch\.tv|kick\.com)/([\w-]+)|youtube\.com/@([\w.-]+)", re.I)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def channel_handle(url: str) -> str:
    """'https://www.twitch.tv/jasontheween' -> 'jasontheween' (empty for links to a single stream)."""
    m = _HANDLE.search(url)
    handle = (m.group(1) or m.group(2)) if m else ""
    return "" if handle.lower() in ("videos", "video") else handle


def mention_score(name: str, text: str) -> int:
    """3 for an exact word, hashtag or @mention; 1 for a longer name inside other text; else 0."""
    n = _norm(name)
    if len(n) < 3:
        return 0
    words = {_norm(w) for w in re.split(r"[\s,.!?:;|/()\[\]]+", text) if w}
    if n in words:
        return 3
    return 1 if len(n) >= 5 and n in _norm(text) else 0


def rank_candidates(candidates: list[Candidate], text: str) -> list[Candidate]:
    """Streamers the post names come first, and within a group, the named member's channel first.
    Ties keep their original order, so nothing is dropped and nothing is reshuffled without reason."""
    ranked = []
    for cid, name, channels in candidates:
        scored = sorted(((mention_score(channel_handle(ch), text), i, ch) for i, ch in enumerate(channels)),
                        key=lambda t: (-t[0], t[1]))
        best_channel = scored[0][0] if scored else 0
        ranked.append((mention_score(name, text) + best_channel, (cid, name, [ch for _, _, ch in scored])))
    return [c for _, c in sorted(ranked, key=lambda t: -t[0])]


def named(candidates: list[Candidate], text: str) -> list[Candidate]:
    """The streamers the text names (name, channel handle, hashtag or @mention), or [] if it names none."""
    return [c for c in candidates if mention_score(c[1], text) or any(mention_score(channel_handle(ch), text) for ch in c[2])]
