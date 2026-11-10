"""Database models. Secrets (tokens, client secrets) are never stored here; see secrets_store."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores UTC, always returns timezone-aware datetimes (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Creator(Base):
    """A streamer / creator whose content pipelines are kept separate."""

    __tablename__ = "creators"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    color: Mapped[str] = mapped_column(String(16), default="#8b5cf6")
    notes: Mapped[str] = mapped_column(Text, default="")
    # Where this creator's full streams live (Twitch/YouTube channel links). Clips are cut from these.
    vod_channels: Mapped[list[Any]] = mapped_column(default=list)
    # User confirmed they're allowed to clip this creator (e.g. part of their clipping program).
    clip_permission: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Folder(Base):
    __tablename__ = "folders"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class SourceAccount(Base):
    __tablename__ = "source_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), default="tiktok")
    username: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(200), default="")
    profile_url: Mapped[str] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id", ondelete="SET NULL"), nullable=True)  # first of creator_ids
    creator_ids: Mapped[list[Any]] = mapped_column(default=list)  # every streamer this account clips
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"), nullable=True)
    monitoring: Mapped[str] = mapped_column(String(10), default="active")  # active | paused
    notes: Mapped[str] = mapped_column(Text, default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    # First check only records what already exists, so adding an account doesn't clip its whole history.
    baseline_done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    __table_args__ = (UniqueConstraint("platform", "username"),)

    creator: Mapped[Creator | None] = relationship(lazy="joined")
    folder: Mapped[Folder | None] = relationship(lazy="joined")


class DestinationAccount(Base):
    __tablename__ = "destination_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))  # tiktok | instagram | youtube | facebook
    external_id: Mapped[str] = mapped_column(String(200))
    handle: Mapped[str] = mapped_column(String(200), default="")
    display_name: Mapped[str] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id", ondelete="SET NULL"), nullable=True)
    creator_ids: Mapped[list[Any]] = mapped_column(default=list)  # every streamer whose clips this page takes; empty = any
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    __table_args__ = (UniqueConstraint("platform", "external_id"),)

    creator: Mapped[Creator | None] = relationship(lazy="joined")


class FunnelRoute(Base):
    """Edge in the account funnel: clips from a source flow to a destination."""

    __tablename__ = "funnel_routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source_accounts.id", ondelete="CASCADE"))
    destination_id: Mapped[int] = mapped_column(ForeignKey("destination_accounts.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set only when the user explicitly confirmed routing one creator's clips to another creator's page.
    allow_cross_creator: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    __table_args__ = (UniqueConstraint("source_id", "destination_id"),)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Job(Base):
    """Persistent background job. Survives restarts; running jobs are re-queued on boot."""

    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|succeeded|failed|cancelled
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Event(Base):
    """Something worth knowing happened. Shown in Vyral and, per the user's preferences, sent to Discord."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    category: Mapped[str] = mapped_column(String(20))  # see events.CATEGORIES
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # low | normal | high | urgent
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    delivery: Mapped[str] = mapped_column(String(10), default="none")  # none | queued | held | sent | failed | off
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ReferenceVideo(Base):
    """A post by a source account (or pasted by the user) that a clip is built from."""

    __tablename__ = "reference_videos"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_accounts.id", ondelete="SET NULL"), nullable=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id", ondelete="SET NULL"), nullable=True)
    platform: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    duration: Mapped[float | None] = mapped_column(nullable=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # baseline | new | processing | ready | no_match | needs_setup | failed
    status: Mapped[str] = mapped_column(String(20), default="new")
    status_detail: Mapped[str] = mapped_column(Text, default="")
    vod_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    vod_start: Mapped[float | None] = mapped_column(nullable=True)
    vod_end: Mapped[float | None] = mapped_column(nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("platform", "external_id"),)

    source: Mapped[SourceAccount | None] = relationship(lazy="joined")
    creator: Mapped[Creator | None] = relationship(lazy="joined")


class VodAsset(Base):
    """A creator's full stream we've analysed. Only compact audio features are kept, not the video."""

    __tablename__ = "vod_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500), unique=True)
    title: Mapped[str] = mapped_column(Text, default="")
    duration: Mapped[float | None] = mapped_column(nullable=True)
    features_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Clip(Base):
    __tablename__ = "clips"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference_id: Mapped[int | None] = mapped_column(ForeignKey("reference_videos.id", ondelete="SET NULL"), nullable=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("creators.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    vod_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    vod_start: Mapped[float | None] = mapped_column(nullable=True)
    vod_end: Mapped[float | None] = mapped_column(nullable=True)
    stream_date: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Full-quality cut of the stream kept until expiry so text edits can be re-rendered.
    files_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_start: Mapped[float | None] = mapped_column(nullable=True)
    source_duration: Mapped[float | None] = mapped_column(nullable=True)
    words: Mapped[list[Any]] = mapped_column(default=list)  # [{start, end, text}] relative to the clip
    captions_note: Mapped[str] = mapped_column(Text, default="")
    edit: Mapped[dict[str, Any]] = mapped_column(default=dict)  # video editor: trim, zoom/pan, speed, extra texts
    status: Mapped[str] = mapped_column(String(16), default="ready")  # ready | expired
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())

    reference: Mapped[ReferenceVideo | None] = relationship(lazy="joined")
    creator: Mapped[Creator | None] = relationship(lazy="joined")


class ClipOutput(Base):
    """One clip prepared for one destination: the video file plus its ready-to-paste text."""

    __tablename__ = "clip_outputs"
    id: Mapped[int] = mapped_column(primary_key=True)
    clip_id: Mapped[int] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"))
    destination_id: Mapped[int | None] = mapped_column(ForeignKey("destination_accounts.id", ondelete="SET NULL"), nullable=True)
    platform: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ready")  # ready | uploaded | expired
    video_title: Mapped[str] = mapped_column(Text, default="")  # the title burned into the top of the video
    overlay: Mapped[dict[str, Any]] = mapped_column(default=dict)
    format: Mapped[dict[str, Any]] = mapped_column(default=dict)
    render_state: Mapped[str] = mapped_column(String(16), default="ready")  # ready | rendering | failed
    render_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # where you uploaded it (for analytics)
    uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    destination: Mapped[DestinationAccount | None] = relationship(lazy="joined")


class MetricSnapshot(Base):
    """Public numbers for an uploaded clip at a point in time."""

    __tablename__ = "metric_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    output_id: Mapped[int] = mapped_column(ForeignKey("clip_outputs.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="auto")  # auto | manual
