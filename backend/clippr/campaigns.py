"""Clipping campaigns, the rules in one place: reading a pasted campaign post, which clips belong to a campaign,
which posted videos count for it, and telling you on Discord when one does."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import describe, events
from .api.analytics import latest_snapshots
from .audit import audit
from .models import Campaign, CampaignClip, Clip, ClipOutput

_PLATFORM_WORDS = {"tiktok": "tiktok", "tik tok": "tiktok", "instagram": "instagram", "youtube": "youtube", "x": "x", "twitter": "x"}
_UNITS = {"k": 1_000, "m": 1_000_000, "": 1}


# ---------- reading a pasted campaign post ----------

def _after(label: str, text: str) -> str:
    """What follows a label on its own line ("Audience: English" or "Audience" then the next line)."""
    m = re.search(rf"^[ \t*•-]*{label}\b[ \t]*(?::[ \t]*|\n[ \t]*)?(\S[^\n]*)$", text, re.I | re.M)
    return m.group(1).strip() if m else ""


def parse(text: str) -> dict:
    """The fields of a pasted campaign post. Anything it can't find is left empty, for you to fill in."""
    name = next((l for l in text.splitlines() if "campaign" in l.lower()), "")
    name = "".join(ch for ch in name if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Cf", "Mn"))
    pool = re.search(r"\$\s?\d[\d,]*(?:\.\d+)?[kKmM]?(?!\w)", text)
    creator = re.search(r"^[ \t*•-]*Creator[ \t]*(?::[ \t]*|\n[ \t]*)(\S[^\n]*)$", text, re.I | re.M)
    where = _after(r"(?:eligible )?platforms?", text)
    views = re.search(r"(?:min(?:imum)?\.? views|MVR)[^\d]{0,40}(\d[\d,]*(?:\.\d+)?)([kKmM])?(?!\w)", text, re.I)
    tags = re.search(r"must use the hashtags?\s*:?\s*((?:#\w+[\s,]*(?:and\s+)?)+)", text, re.I)
    mention = re.search(r"must mention ([^\n]+?)(?:['’]s)? name", text, re.I)
    start = re.search(r"(?:beginning|starting|begins?|from)\s+(?:on\s+)?([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", text, re.I)
    within = re.search(r"within\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)", text, re.I)
    out = {"name": re.sub(r"\s+", " ", name).strip(), "pool": re.sub(r"\s", "", pool.group()) if pool else "",
           "creator": creator.group(1).strip() if creator else "",
           "platforms": list(dict.fromkeys(_PLATFORM_WORDS[w.lower()] for w in re.findall(r"tik ?tok|instagram|youtube|twitter|\bx\b", where, re.I))),
           "min_views": int(float(views.group(1).replace(",", "")) * _UNITS[(views.group(2) or "").lower()]) if views else 0,
           "audience": _after("audience", text),
           "required_hashtags": re.findall(r"#\w+", tags.group(1)) if tags else [],
           "must_mention": [mention.group(1).strip()] if mention else [],
           "footage_from": None,
           "submit_within_minutes": int(within.group(1)) * (60 if within.group(2).lower().startswith("h") else 1) if within else None,
           "join_url": "", "discord_url": "", "guidelines_url": "", "rules": text.strip()}
    if start:
        for fmt in ("%B", "%b"):
            try:
                out["footage_from"] = datetime.strptime(f"{start.group(1)} {start.group(2)} {start.group(3)}", f"{fmt} %d %Y").date()
                break
            except ValueError:
                continue
    for label, url in re.findall(r"(?:\[([^\]]*)\]\()?(https?://[^\s)\]]+)", text):
        kind = "discord_url" if re.search(r"discord\.(?:com/invite|gg)/", url) else \
               "join_url" if "join campaign" in label.lower() or re.search(r"contentrewards|whop", url) else "guidelines_url"
        out[kind] = out[kind] or url
    return out


# ---------- which clips belong, which videos count ----------

def matches(c: Campaign, clip: Clip) -> bool:
    """The clip is of this campaign's streamer, from footage inside its dates, and about what it asks for."""
    if not c.creator_id or c.creator_id != clip.creator_id:
        return False
    day = (clip.stream_date or clip.created_at).date()
    if (c.footage_from and day < c.footage_from) or (c.ends_at and day >= c.ends_at):
        return False
    if not c.keywords:
        return True
    said = " ".join(w["text"] for w in clip.words or [])
    text = " ".join([clip.title, clip.reference.title if clip.reference else "", said, (clip.safety or {}).get("game") or ""]).lower()
    return any(k.lower() in text for k in c.keywords)


def qualifies(c: Campaign, o: ClipOutput) -> tuple[bool, list[str]]:
    """Whether one page's posted video meets the campaign's rules, and what's missing if not. Views aren't part of
    it: the minimum is for the whole campaign (campaign_views)."""
    why = []
    if not (o.post_url or o.status == "uploaded" or o.postiz_state == "published"):
        why.append("Not posted yet")
    if c.platforms and o.platform not in c.platforms:
        why.append(f"{o.platform.title()} isn't an eligible platform")
    text = f"{o.description}\n{o.title}"
    why += [f"Caption is missing {h}" for h in c.required_hashtags if not describe.has_tag(text, h)]
    why += [f"Caption doesn't mention {n}" for n in c.must_mention if not describe.has_name(text, n)]
    if c.destination_ids and o.destination_id not in c.destination_ids:
        why.append("Posted from a page that isn't on this campaign")
    return not why, why


def tagged_outputs(s: Session, c: Campaign) -> list[ClipOutput]:
    ids = select(CampaignClip.clip_id).where(CampaignClip.campaign_id == c.id)
    return list(s.scalars(select(ClipOutput).where(ClipOutput.clip_id.in_(ids), ClipOutput.status != "expired")).unique())


def qualifying(s: Session, c: Campaign) -> list[ClipOutput]:
    return [o for o in tagged_outputs(s, c) if qualifies(c, o)[0]]


def _views(s: Session, outs: list[ClipOutput]) -> int:
    snaps = latest_snapshots(s, [o.id for o in outs])
    return sum(snaps[o.id].views or 0 for o in outs if o.id in snaps)


def campaign_views(s: Session, c: Campaign) -> int:
    """Latest views of the tagged videos that qualify."""
    return _views(s, qualifying(s, c))


# ---------- tagging ----------

def _rules(c: Campaign) -> dict:
    return {"hashtags": c.required_hashtags, "mention": c.must_mention}


def caption_rules(s: Session, clip: Clip) -> dict:
    """What this clip's captions have to follow: its streamer's rules and those of the live campaigns it's tagged to."""
    mine = (clip.creator.caption_rules or {}) if clip.creator else {}
    sets = [mine, *(_rules(c) for c in s.scalars(select(Campaign).join(CampaignClip).where(
        CampaignClip.clip_id == clip.id, Campaign.status == "live")).unique())]
    return {"extra": mine.get("extra", ""), **{k: list(dict.fromkeys(x for r in sets for x in r.get(k) or [])) for k in ("hashtags", "mention")}}


def tag(s: Session, c: Campaign, clip: Clip, added_by: str) -> CampaignClip:
    """Tag a clip to a campaign and put the campaign's hashtags on every page video not posted yet."""
    link = s.scalar(select(CampaignClip).where(CampaignClip.campaign_id == c.id, CampaignClip.clip_id == clip.id))
    if link:
        return link
    link = CampaignClip(campaign_id=c.id, clip_id=clip.id, added_by=added_by)
    s.add(link)
    for o in s.scalars(select(ClipOutput).where(ClipOutput.clip_id == clip.id, ClipOutput.status == "ready")).unique():
        if not o.post_url and o.postiz_state != "published":
            new = describe.apply_rules(o.description, _rules(c), o.platform, o.title)
            if new != o.description and o.review == "approved" and not o.postiz_post_id:
                o.review = "pending"  # an approval was for the exact caption
            o.description = new
    audit(s, "campaign.clip_tagged", "campaign", c.id, {"clip": clip.id, "by": added_by})
    return link


def auto_tag(s: Session, clip: Clip) -> None:
    """A clip has just been made: tag it to every live campaign it matches."""
    for c in s.scalars(select(Campaign).where(Campaign.status == "live")).unique():
        if matches(c, clip):
            tag(s, c, clip, "auto")


# ---------- telling you ----------

def check(ctx) -> dict:
    """Job: one Discord message for each tagged page video that now qualifies, and one when a campaign's qualifying
    videos pass its minimum views."""
    todo, passed = [], []
    with ctx.db.session() as s:
        for c in s.scalars(select(Campaign).where(Campaign.status == "live")).unique():
            links = {l.clip_id: l for l in s.scalars(select(CampaignClip).where(CampaignClip.campaign_id == c.id))}
            ok = qualifying(s, c)
            for o in ok:
                if o.id not in links[o.clip_id].notified_output_ids:
                    todo.append((links[o.clip_id].id, o.id, s.get(Clip, o.clip_id).title, o.post_url, c.id, c.name, c.join_url, c.submit_within_minutes))
            views = _views(s, ok)
            if c.min_views and views >= c.min_views:
                passed.append((c.id, c.name, c.min_views, views))
    for link_id, oid, clip_title, post, cid, name, join, minutes in todo:
        ask = f"Submit it within {minutes} minutes" if minutes else "Submit it"
        events.emit(ctx, "opportunities", f"{clip_title} qualifies for {name}", priority="high", link=post, dedupe_key=f"campaign:{cid}:{oid}",
                    body="\n".join(filter(None, [f"{ask}: {join}" if join else "", f"Post: {post}" if post else ""])), data={"campaign_id": cid, "output_id": oid})
        with ctx.db.session() as s:  # after the message is recorded, so a failure here can't send it twice (dedupe_key)
            link = s.get(CampaignClip, link_id)
            link.notified_output_ids = [*link.notified_output_ids, oid]
    for cid, name, goal, views in passed:
        # shortcut: remembered by the event log, which is cleared after 90 days; a campaign still over its minimum then says it once more
        events.emit(ctx, "opportunities", f"{name} passed {goal:,} views", body=f"Its qualifying videos have {views:,} views together.",
                    priority="high", dedupe_key=f"campaign:{cid}:views", data={"campaign_id": cid})
    return {"qualified": len(todo)}


def register(ctx) -> None:
    ctx.jobs.register("campaigns.check", lambda jc, pl: check(ctx))
    ctx.jobs.every("campaigns.check", 600)
