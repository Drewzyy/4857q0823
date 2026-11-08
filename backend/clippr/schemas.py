"""Validated shapes for settings blobs stored as JSON."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExportFormat(Strict):
    aspect: Literal["9:16", "16:9", "1:1"] = "9:16"
    resolution: Literal["1080x1920", "1920x1080", "1080x1080", "720x1280"] = "1080x1920"
    fps: Literal[24, 25, 30, 50, 60] = 30
    codec: Literal["h264", "h265"] = "h264"
    bitrate_mbps: float = Field(12, ge=1, le=80)


class Branding(Strict):
    watermark_text: str = Field("", max_length=60)
    watermark_position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "bottom-right"


class PublishSlot(Strict):
    weekday: int = Field(ge=0, le=6)  # 0 = Monday
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class DestinationSettings(Strict):
    default_caption: str = Field("", max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    categories: list[str] = Field(default_factory=list, max_length=20)
    approval_required: bool = True
    visibility: Literal["public", "private", "unlisted", "friends"] = "public"
    schedule: list[PublishSlot] = Field(default_factory=list, max_length=50)
    format: ExportFormat = Field(default_factory=ExportFormat)
    branding: Branding = Field(default_factory=Branding)
    caption_preset: str = Field("bold-orange", max_length=60)
    title_style: Literal["curiosity", "reaction", "funny", "dramatic", "question"] = "curiosity"


def default_destination_settings(platform: str) -> dict:
    s = DestinationSettings()
    s.format.fps = 60  # keep smooth source footage smooth; lower-fps sources are never upsampled
    return s.model_dump()


class StorageSettings(Strict):
    retention_days: int = Field(30, ge=1, le=365)  # clips and cached media are deleted after this
    max_cache_gb: float = Field(50, ge=1, le=10000)
    keep_original_imports: bool = True


class MonitoringSettings(Strict):
    enabled: bool = True
    interval_minutes: int = Field(10, ge=3, le=240)
    streams_to_search: int = Field(4, ge=1, le=15)
    max_clip_seconds: int = Field(180, ge=15, le=600)


class AISettings(Strict):
    prefer_local_models: bool = True
    monthly_budget_usd: float = Field(25, ge=0, le=100000)
    hard_stop_at_budget: bool = True
    warn_at_percent: int = Field(80, ge=10, le=100)
    transcription: Literal["local-whisper", "cloud"] = "local-whisper"
    text_model_tier: Literal["economy", "balanced", "best"] = "economy"


class ProcessingSettings(Strict):
    max_concurrent_jobs: int = Field(2, ge=1, le=16)
    quality: Literal["fast", "balanced", "best"] = "balanced"


class PublishingSettings(Strict):
    require_approval: bool = True
    allow_auto_publish_rules: bool = False


class PrivacySettings(Strict):
    allow_cloud_upload_of_footage: bool = False


class AppSettings(Strict):
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    ai: AISettings = Field(default_factory=AISettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    publishing: PublishingSettings = Field(default_factory=PublishingSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
