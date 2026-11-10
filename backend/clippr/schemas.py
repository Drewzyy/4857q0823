"""Validated shapes for settings blobs stored as JSON."""
from __future__ import annotations

from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

M = TypeVar("M", bound=BaseModel)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def lenient(model: type[M], data: Any) -> M:
    """Load settings saved by an older or newer Vyral. Options this version doesn't know are dropped and an
    invalid value falls back to its default, so one bad value never resets the rest. (What the user sends is
    still validated strictly.)"""
    if isinstance(data, model):
        return data
    if not isinstance(data, dict):
        return model()
    values: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if name not in data:
            continue
        sub = field.annotation
        values[name] = lenient(sub, data[name]) if isinstance(sub, type) and issubclass(sub, BaseModel) else data[name]
    good: dict[str, Any] = {}
    for name, value in values.items():
        try:
            model.model_validate({**good, name: value})
            good[name] = value
        except ValidationError:
            pass
    return model.model_validate(good)


def deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class ExportFormat(Strict):
    aspect: Literal["9:16", "16:9", "1:1"] = "9:16"
    resolution: Literal["1080x1920", "1920x1080", "1080x1080", "720x1280"] = "1080x1920"
    fps: Literal[24, 25, 30, 50, 60] = 60  # upper limit; output keeps the stream's own frame rate up to this
    codec: Literal["h264", "h265"] = "h264"
    bitrate_mbps: float = Field(12, ge=1, le=80)


FontName = Literal["montserrat", "anton", "bebas", "poppins"]
HEXCOLOR = r"^#[0-9a-fA-F]{6}$"


class TextStyle(Strict):
    enabled: bool = True
    font: FontName = "montserrat"
    size: int = Field(80, ge=20, le=200)  # pixels on a 1080-wide video; scaled for other sizes
    color: str = Field("#FFE500", pattern=HEXCOLOR)
    outline_color: str = Field("#000000", pattern=HEXCOLOR)
    outline: int = Field(6, ge=0, le=20)
    all_caps: bool = True
    y_percent: int = Field(70, ge=3, le=97)  # vertical center of the text, % from the top


class TitleStyle(TextStyle):
    color: str = Field("#FFFFFF", pattern=HEXCOLOR)
    size: int = Field(76, ge=20, le=200)
    y_percent: int = Field(13, ge=3, le=97)
    duration: float = Field(5.0, ge=1, le=30)


class CaptionStyle(TextStyle):
    size: int = Field(88, ge=20, le=200)
    y_percent: int = Field(70, ge=3, le=97)
    words_per_caption: int = Field(3, ge=1, le=6)


class OverlaySettings(Strict):
    title: TitleStyle = Field(default_factory=TitleStyle)
    captions: CaptionStyle = Field(default_factory=CaptionStyle)


class DestinationSettings(Strict):
    default_caption: str = Field("", max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    format: ExportFormat = Field(default_factory=ExportFormat)
    overlay: OverlaySettings = Field(default_factory=OverlaySettings)


def default_destination_settings(platform: str) -> dict:
    s = DestinationSettings()
    s.format.fps = 60  # keep smooth source footage smooth; lower-fps sources are never upsampled
    return s.model_dump()


class StorageSettings(Strict):
    retention_days: int = Field(30, ge=1, le=365)  # clips and cached media are deleted after this


class MonitoringSettings(Strict):
    enabled: bool = True
    interval_minutes: int = Field(10, ge=3, le=240)
    streams_to_search: int = Field(4, ge=1, le=15)
    max_clip_seconds: int = Field(180, ge=15, le=600)
    twitch_min_views: int = Field(25, ge=0, le=1_000_000)  # a Twitch clip is made into a video once this many people watched it
    twitch_clips_per_check: int = Field(3, ge=1, le=10)


class CaptionEngineSettings(Strict):
    accuracy: Literal["fast", "accurate", "best"] = "accurate"
    language: str = Field("auto", pattern=r"^(auto|[a-z]{2})$")


class ProcessingSettings(Strict):
    max_concurrent_jobs: int = Field(2, ge=1, le=16)
    cut_dead_air: bool = True  # cut stretches with no sound out of new clips


class IntakeSettings(Strict):
    clipboard: bool = True  # a copied TikTok / YouTube Shorts video link is made into a clip


class AppSettings(Strict):
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    captions: CaptionEngineSettings = Field(default_factory=CaptionEngineSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    intake: IntakeSettings = Field(default_factory=IntakeSettings)


class TextOverlay(Strict):
    text: str = Field(min_length=1, max_length=200)
    start: float = Field(0, ge=0)  # seconds in the finished clip
    end: float = Field(3, ge=0)
    y_percent: int = Field(50, ge=3, le=97)
    size: int = Field(70, ge=20, le=200)
    color: str = Field("#FFFFFF", pattern=HEXCOLOR)
    font: FontName = "montserrat"
    all_caps: bool = True
    outline: int = Field(6, ge=0, le=20)

    @model_validator(mode="after")
    def _ordered(self):
        if self.end <= self.start:
            raise ValueError("a text must end after it starts")
        return self


# New clips are zoomed in: the stream fills 60% of the frame's height, centered, trimmed at the sides, so the
# speaker is easy to see on a phone. 0 means "fit to frame": the whole stream across the full width (about 32%
# for 16:9), which is how clips looked before.
VIDEO_HEIGHT = 0.6


class LayerEdit(Strict):
    """A library picture or video on top of the clip for part of it."""
    media_id: int
    start: float = Field(0, ge=0)  # seconds in the finished clip
    end: float = Field(2, gt=0)
    x: float = Field(0.5, ge=0, le=1)  # center, as shares of the frame
    y: float = Field(0.3, ge=0, le=1)
    width: float = Field(0.4, ge=0.05, le=1)  # share of the frame's width

    @model_validator(mode="after")
    def _ordered(self):
        if self.end <= self.start:
            raise ValueError("a layer must end after it starts")
        return self


class ClipEdit(Strict):
    start: float = Field(ge=0)  # seconds within the downloaded cut
    end: float = Field(gt=0)
    video_height: float = Field(VIDEO_HEIGHT, ge=0, le=1.0)  # share of the frame's height the video fills; 0 = fit to frame
    zoom: float = Field(1.0, ge=1.0, le=3.0)
    pan_x: float = Field(0.5, ge=0, le=1)  # which part stays in view when zoomed (0 left, 1 right)
    pan_y: float = Field(0.5, ge=0, le=1)
    speed: float = Field(1.0, ge=0.5, le=2.0)
    # "stacked": content on top, the streamer's facecam (cam: x, y, w, h as shares of the source) underneath.
    # "split": content on top, a library video (bottom_media, e.g. gameplay) looping underneath.
    layout: Literal["normal", "stacked", "split"] = "normal"
    cam: list[float] | None = Field(None, min_length=4, max_length=4)
    bottom_media: int | None = None
    cut_dead_air: bool = False
    thumb_at: float | None = Field(None, ge=0)  # cover frame, in source seconds; None picks one a second in
    gaps: list[list[float]] = Field(default_factory=list, max_length=200)  # silent stretches, in source seconds
    texts: list[TextOverlay] = Field(default_factory=list, max_length=20)
    layers: list[LayerEdit] = Field(default_factory=list, max_length=20)


class PresetData(Strict):
    """What a preset adds to a clip: texts and layers, and optionally gameplay underneath."""
    texts: list[TextOverlay] = Field(default_factory=list, max_length=20)
    layers: list[LayerEdit] = Field(default_factory=list, max_length=20)
    bottom_media: int | None = None
