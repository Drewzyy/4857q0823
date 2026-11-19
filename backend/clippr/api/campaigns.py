"""Clipping campaigns: add one (or paste its post), tag clips to it, and see which posted videos qualify."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import campaigns, describe
from ..audit import audit
from ..models import Campaign, CampaignClip, Clip, Creator, DestinationAccount
from .analytics import latest_snapshots
from .streamers import rules_of
from .deps import ApiError, ctx, db, get_or_404

router = APIRouter()
FIELDS = ("name", "tag", "status", "pool", "min_views", "platforms", "audience", "footage_from", "ends_at", "required_hashtags", "must_mention",
          "keywords", "join_url", "discord_url", "guidelines_url", "submit_within_minutes", "destination_ids", "rules")  # and clip_rules, which _out fills in whole
URL = {"pattern": r"^(https?://\S+)?$", "max_length": 500}  # only web links: they become buttons


class ClipRules(BaseModel):
    """What a campaign asks of the video itself. 0 or empty means no rule."""
    min_seconds: int = Field(0, ge=0, le=3600)
    max_seconds: int = Field(0, ge=0, le=3600)
    overlay_mentions: list[str] = Field(default_factory=list, max_length=10)
    language: str = Field("", max_length=40)
    no_logos: bool = False
    focus_creator: bool = False

    @field_validator("overlay_mentions")
    @classmethod
    def _names(cls, v: list[str]) -> list[str]:
        return describe.clean_list(v)

    @model_validator(mode="after")
    def _order(self):
        if self.max_seconds and self.min_seconds > self.max_seconds:
            raise ValueError("The shortest length can't be longer than the longest")
        return self


class CampaignPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    tag: str | None = Field(None, pattern=r"^[a-z0-9-]{2,40}$")
    status: Literal["live", "ended"] = "live"
    pool: str = Field("", max_length=40)
    min_views: int = Field(0, ge=0, le=10**10)
    platforms: list[Literal["tiktok", "instagram", "youtube", "x"]] = Field(default_factory=list, max_length=4)
    audience: str = Field("", max_length=200)
    footage_from: date | None = None
    ends_at: date | None = None
    required_hashtags: list[str] = Field(default_factory=list, max_length=20)
    must_mention: list[str] = Field(default_factory=list, max_length=20)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    join_url: str = Field("", **URL)
    discord_url: str = Field("", **URL)
    guidelines_url: str = Field("", **URL)
    submit_within_minutes: int | None = Field(None, ge=1, le=100_000)
    destination_ids: list[int] = Field(default_factory=list, max_length=100)
    rules: str = Field("", max_length=20_000)
    clip_rules: ClipRules = Field(default_factory=ClipRules)

    @field_validator("required_hashtags", "must_mention", "keywords")
    @classmethod
    def _words(cls, v: list[str], info) -> list[str]:
        return describe.clean_list(v, info.field_name == "required_hashtags")


class CampaignIn(CampaignPatch):
    name: str = Field(min_length=1, max_length=200)
    tag: str = Field(pattern=r"^[a-z0-9-]{2,40}$")
    creator_id: int | None = None


class CampaignUpdate(CampaignPatch):
    creator_id: int | None = None


def _out(s: Session, c: Campaign) -> dict:
    return {"id": c.id, "creator": {"id": c.creator.id, "name": c.creator.name} if c.creator else None, **{f: getattr(c, f) for f in FIELDS},
            "clip_rules": ClipRules(**(c.clip_rules or {})).model_dump(), "views": campaigns.campaign_views(s, c)}


def _check(s: Session, data: dict, cid: int | None = None) -> None:
    if data.get("tag") and s.scalar(select(Campaign.id).where(Campaign.tag == data["tag"], Campaign.id != (cid or 0))):
        raise ApiError(409, "conflict", f"The tag \"{data['tag']}\" is already used by another campaign")
    if data.get("creator_id") and not s.get(Creator, data["creator_id"]):
        raise ApiError(422, "validation", "Streamer not found")
    ids = set(data.get("destination_ids") or [])
    if ids and s.scalar(select(func.count()).select_from(DestinationAccount).where(DestinationAccount.id.in_(ids))) != len(ids):
        raise ApiError(422, "validation", "One of the pages wasn't found")


@router.get("/campaigns")
def list_campaigns(q: str = "", s: Session = Depends(db)):
    query = select(Campaign).order_by(Campaign.created_at.desc(), Campaign.id.desc())
    if q.strip():
        query = query.where(Campaign.tag.icontains(q.strip(), autoescape=True) | Campaign.name.icontains(q.strip(), autoescape=True))
    return [_out(s, c) for c in s.scalars(query).unique()]


class ParseIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


@router.post("/campaigns/parse")
def parse_post(body: ParseIn, s: Session = Depends(db)):
    """The fields found in a pasted campaign post. Nothing is saved: you correct them first."""
    found = campaigns.parse(body.text)
    creator = s.scalar(select(Creator).where(func.lower(Creator.name) == found["creator"].lower())) if found["creator"] else None
    return {**found, "creator_id": creator.id if creator else None}


@router.post("/campaigns", status_code=201)
def add_campaign(body: CampaignIn, s: Session = Depends(db)):
    data = body.model_dump()
    _check(s, data)
    c = Campaign(**data)
    s.add(c)
    s.flush()
    audit(s, "campaign.added", "campaign", c.id, {"tag": c.tag})
    return _out(s, c)


@router.patch("/campaigns/{cid}")
def edit_campaign(cid: int, body: CampaignUpdate, s: Session = Depends(db)):
    c = get_or_404(s, Campaign, cid, "Campaign")
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k in ("footage_from", "ends_at", "submit_within_minutes", "creator_id")}
    _check(s, data, cid)
    for k, v in data.items():
        setattr(c, k, v)
    audit(s, "campaign.edited", "campaign", cid, {"fields": sorted(data)})
    s.flush()
    return _out(s, c)


@router.delete("/campaigns/{cid}", status_code=204)
def delete_campaign(cid: int, s: Session = Depends(db)):
    """Removes the campaign and its tags. The clips themselves stay."""
    c = get_or_404(s, Campaign, cid, "Campaign")
    audit(s, "campaign.deleted", "campaign", cid, {"tag": c.tag})
    s.delete(c)


@router.get("/campaigns/{cid}/clips")
def campaign_clips(cid: int, s: Session = Depends(db)):
    """Clips tagged to the campaign with how each page's video stands, and untagged clips that would match."""
    c = get_or_404(s, Campaign, cid, "Campaign")
    links = list(s.scalars(select(CampaignClip).where(CampaignClip.campaign_id == cid).order_by(CampaignClip.created_at.desc(), CampaignClip.id.desc())))
    clips = {x.id: x for x in s.scalars(select(Clip).where(Clip.id.in_([l.clip_id for l in links]))).unique()}
    outs = campaigns.tagged_outputs(s, c)
    snaps = latest_snapshots(s, [o.id for o in outs])

    def page(o) -> dict:
        ok, why = campaigns.qualifies(c, o)
        return {"output_id": o.id, "platform": o.platform, "page": o.destination.display_name if o.destination else None, "post_url": o.post_url,
                "qualifies": ok, "reasons": why, "views": snaps[o.id].views if o.id in snaps else None}

    tagged = set(clips)
    suggested = [] if not c.creator_id else [
        x for x in s.scalars(select(Clip).where(Clip.creator_id == c.creator_id, Clip.status == "ready", Clip.id.not_in(tagged))
                             .order_by(Clip.created_at.desc()).limit(200)).unique() if campaigns.matches(c, x)][:50]
    return {"clips": [{"clip_id": l.clip_id, "title": clips[l.clip_id].title, "added_by": l.added_by, "outputs": [page(o) for o in outs if o.clip_id == l.clip_id]}
                      for l in links if l.clip_id in clips],
            "suggested": [{"clip_id": x.id, "title": x.title, "created_at": x.created_at.isoformat()} for x in suggested]}


class LinkIn(BaseModel):
    clip_id: int


@router.post("/campaigns/{cid}/clips", status_code=201)
def link_clip(cid: int, body: LinkIn, c=Depends(ctx), s: Session = Depends(db)):
    camp = get_or_404(s, Campaign, cid, "Campaign")
    clip = get_or_404(s, Clip, body.clip_id, "Clip")
    campaigns.tag(s, camp, clip, "you")
    s.flush()
    if not campaigns.complies(clip, campaigns.clip_rules_of(s, clip)):  # its length or title breaks the campaign's video rules
        c.jobs.enqueue("clip.recut", {"clip_id": clip.id}, max_attempts=1, session=s)
    c.jobs.enqueue("campaigns.check", {}, max_attempts=1, session=s)  # it may already be posted and qualify
    return {"ok": True}


@router.delete("/campaigns/{cid}/clips/{clip_id}", status_code=204)
def unlink_clip(cid: int, clip_id: int, s: Session = Depends(db)):
    link = s.scalar(select(CampaignClip).where(CampaignClip.campaign_id == cid, CampaignClip.clip_id == clip_id))
    if not link:
        raise ApiError(404, "not_found", "That clip isn't tagged to this campaign")
    audit(s, "campaign.clip_untagged", "campaign", cid, {"clip": clip_id})
    s.delete(link)


@router.post("/campaigns/{cid}/apply-rules")
def apply_rules_to_streamer(cid: int, s: Session = Depends(db)):
    """Add this campaign's hashtags, names and rules text to its streamer's caption rules. What's there stays."""
    c = get_or_404(s, Campaign, cid, "Campaign")
    if not c.creator:
        raise ApiError(422, "validation", "Pick a streamer for this campaign first")
    r = rules_of(c.creator)
    for key, new in (("hashtags", c.required_hashtags), ("mention", c.must_mention)):
        r[key] = list(dict.fromkeys([*r[key], *new]))
        if len(r[key]) > 10:
            raise ApiError(422, "validation", f"{c.creator.name} would have more than 10 {'hashtags' if key == 'hashtags' else 'names'} in their rules")
    note = f"{c.name}\n{c.rules}".strip()
    if c.rules and c.rules not in r["notes"] and len(r["notes"]) + len(note) + 2 <= 4000:
        r["notes"] = f"{r['notes']}\n\n{note}".strip()
    c.creator.caption_rules = r
    audit(s, "streamer.rules_changed", "creator", c.creator.id, {"from_campaign": cid})
    return r
