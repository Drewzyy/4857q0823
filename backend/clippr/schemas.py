"""Validated shapes for settings blobs stored as JSON."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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
    # Ends every headline on this page, like a brand ("😭❤️"); empty keeps the emoji Vyral picked.
    signature_emoji: str = Field("", max_length=16)


class DestinationSettings(Strict):
    # Which kinds of clips this page takes (a streamer's kind, set under Source Accounts): regular, gaming, podcast.
    content_kinds: list[Literal["regular", "gaming", "podcast"]] = Field(default_factory=lambda: ["regular", "gaming", "podcast"])
    # Auto-post: approved, safe clips go out without your phone approval. Off unless you turn it on, which the app
    # allows only after 5 reviewed posts on this page went out fine.
    auto_post: bool = False
    daily_cap: int = Field(3, ge=1, le=20)
    default_caption: str = Field("", max_length=2200)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    format: ExportFormat = Field(default_factory=ExportFormat)
    overlay: OverlaySettings = Field(default_factory=OverlaySettings)


def default_destination_settings(platform: str, handle: str = "") -> dict:
    from .routing import DEFAULT_KINDS
    s = DestinationSettings()
    s.format.fps = 60  # keep smooth source footage smooth; lower-fps sources are never upsampled
    kinds = DEFAULT_KINDS.get(handle.lstrip("@").lower())
    if kinds:
        s.content_kinds = kinds
    return s.model_dump()


class StorageSettings(Strict):
    retention_days: int = Field(30, ge=1, le=365)  # clips and cached media are deleted after this
    save_folder: str = Field("", max_length=500)  # where "Save to computer" puts videos; "" = Downloads/Vyral
    media_folder: str = Field("", max_length=500)  # where new clips are kept while they wait; "" = the app's data folder

    @field_validator("save_folder", "media_folder")
    @classmethod
    def _absolute(cls, v: str) -> str:
        v = v.strip()
        if v and not Path(v).is_absolute():
            raise ValueError("must be a full folder path, like C:\\Users\\you\\Videos or /Users/you/Videos")
        return v


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
    viral_preedit: bool = True  # headline, strongest stretch, open on sound (see preedit.py)
    hook_first: bool = True  # show the clip's best few seconds first, then play it from the start
    sound_effects: Literal["off", "auto"] = "auto"  # one sound effect on the biggest moment of each new clip
    auto_sound: str = Field("", max_length=40, pattern=r"^(|[a-z_]{1,30}|lib:\d{1,9})$")  # "" = picked by the moment
    hardware_encoding: bool = True  # render on the graphics card when this computer has a working video encoder


class IntakeSettings(Strict):
    clipboard: bool = True  # a copied TikTok / YouTube Shorts video link is made into a clip


class SafetySettings(Strict):
    """Your blocklist, applied to every new clip on top of the built-in checks (see safety.py)."""
    banned_words: list[str] = Field(default_factory=list, max_length=500)
    banned_scenes: list[str] = Field(default_factory=list, max_length=200)  # phrases in what's said or the clip's titles
    banned_games: list[str] = Field(default_factory=list, max_length=100)  # games whose clips never go out


class PostingSettings(Strict):
    auto_post_kill_switch: bool = False  # on: nothing posts by itself, whatever each page's Auto-post says
    mcp_enabled: bool = True  # the local bridge Muse connects to (127.0.0.1 only, token required)
    mcp_port: int = Field(47821, ge=1024, le=65535)
    min_virality: int = Field(50, ge=0, le=100)  # clips scoring lower don't go to review


class AppSettings(Strict):
    safety: SafetySettings = Field(default_factory=SafetySettings)
    posting: PostingSettings = Field(default_factory=PostingSettings)
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
    box: bool = False  # dark text on a white box: the headline look of top-performing clip pages
    headline: bool = False  # Vyral's headline for this clip (each page can add its signature emoji to it)

    @model_validator(mode="after")
    def _ordered(self):
        if self.end <= self.start:
            raise ValueError("a text must end after it starts")
        return self


# New clips are zoomed in to fill each page's shape: on a 9:16 page the stream fills the whole frame, centered
# and trimmed at the sides, with no blurred bars. The editor can zoom out to any share of the height; 0 means
# "fit to frame" (the whole stream across the full width, about 32% for 16:9).
VIDEO_HEIGHT = 1.0


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


class SoundEdit(Strict):
    """A sound effect, at a moment in the source (seconds, like gaps and cuts, so trims keep it in place)."""
    name: str = Field(min_length=1, max_length=40)
    at: float = Field(ge=0)
    volume: float = Field(0.6, ge=0.05, le=1.5)

    @model_validator(mode="after")
    def _known(self):
        from .media.sfx import is_sound_name
        if not is_sound_name(self.name):
            raise ValueError(f"unknown sound {self.name!r}")
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
    cuts: list[list[float]] = Field(default_factory=list, max_length=50)  # stretches the user cut out, in source seconds
    texts: list[TextOverlay] = Field(default_factory=list, max_length=20)
    layers: list[LayerEdit] = Field(default_factory=list, max_length=20)
    hide_title: bool = False  # the page's own title is left off (a headline in texts replaces it)
    sounds: list[SoundEdit] = Field(default_factory=list, max_length=20)
    # A few seconds (source seconds) shown first as a teaser, then the clip plays from its start.
    hook: list[float] | None = Field(None, min_length=2, max_length=2)
    punch: list[float] | None = Field(None, min_length=2, max_length=2)  # a subtle zoom on the peak (source seconds)
    captions: bool = True  # Vyral's word-by-word captions on this clip
    source_has_captions: bool = False  # the footage already shows captions (so Vyral's are off by default)
    preedited: bool = False  # Vyral's viral pre-edit has been applied (see preedit.py)
    preedit_version: int = Field(0, ge=0)  # which version of it; clips get a newer version once


class PresetData(Strict):
    """What a preset adds to a clip: texts and layers, and optionally gameplay underneath."""
    texts: list[TextOverlay] = Field(default_factory=list, max_length=20)
    layers: list[LayerEdit] = Field(default_factory=list, max_length=20)
    bottom_media: int | None = None
