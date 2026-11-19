"""Which pages a clip goes to: each page lists the streamers whose clips it takes (set from either side: a
streamer's "Post to" list or a page's streamer list), and the kinds of clips it takes (regular, gaming, podcast).
A clip's kind is detected from the clip itself (content.py), falling back to the streamer's kind (Source Accounts)
when that isn't clear. A clip goes to every enabled page that lists its streamer and its kind.
A page with no streamers listed gets no streamer's clips.

Default kinds for the pages Vyral was set up with (changeable per page in its settings): @vyralclips19 (TikTok)
and @vyralclipr (Instagram) take regular clips, @vyralgames7 (TikTok) gaming, @vyralpods (Instagram) podcasts.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DestinationAccount, SourceAccount

KINDS = ("regular", "gaming", "podcast")
DEFAULT_KINDS = {"vyralclips19": ["regular"], "vyralclipr": ["regular"], "vyralgames7": ["gaming"], "vyralpods": ["podcast"]}


def source_creator_ids(src: SourceAccount) -> list[int]:
    """All streamers a watched account covers (most cover one; general clipping accounts cover several)."""
    ids = [int(i) for i in (src.creator_ids or [])]
    if not ids and src.creator_id:
        ids = [src.creator_id]
    return ids


def destination_creator_ids(dest: DestinationAccount) -> list[int]:
    """Every streamer whose clips a page takes."""
    ids = [int(i) for i in (dest.creator_ids or [])]
    if not ids and dest.creator_id:
        ids = [dest.creator_id]
    return ids


def takes(dest: DestinationAccount, creator_ids: set[int]) -> bool:
    """Whether a page takes clips of any of these streamers."""
    return bool(set(destination_creator_ids(dest)) & creator_ids)


def page_kinds(dest: DestinationAccount) -> list[str]:
    return list((dest.settings or {}).get("content_kinds") or KINDS)


def pages_for(s: Session, creator_ids: set[int], kind: str | None = None) -> list[DestinationAccount]:
    """Enabled pages that take clips of any of these streamers; with kind, only pages taking that kind of clip."""
    return [d for d in s.scalars(select(DestinationAccount).where(DestinationAccount.enabled.is_(True))).unique()
            if takes(d, creator_ids) and (kind is None or kind in page_kinds(d))]


def for_kind(pages: list, kind: str, fallback: str) -> list:
    """The pages (DestinationAccount or (id, platform, name, handle, settings) rows) that take this kind of clip;
    else those taking the fallback kind (the streamer's own); else all of them, so a clip is never lost."""
    def kinds(p) -> list[str]:
        st = p[4] if isinstance(p, tuple) else (p.settings or {})
        return list(st.get("content_kinds") or KINDS)
    return [p for p in pages if kind in kinds(p)] or [p for p in pages if fallback in kinds(p)] or pages
