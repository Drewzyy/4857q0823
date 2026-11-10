"""Which pages a clip goes to: each page lists the streamers whose clips it takes (set from either side: a
streamer's "Post to" list or a page's streamer list), and a clip goes to every enabled page that lists its
streamer. A page with no streamers listed gets no streamer's clips.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DestinationAccount, SourceAccount


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


def pages_for(s: Session, creator_ids: set[int]) -> list[DestinationAccount]:
    """Enabled pages that take clips of any of these streamers."""
    return [d for d in s.scalars(select(DestinationAccount).where(DestinationAccount.enabled.is_(True))).unique() if takes(d, creator_ids)]
