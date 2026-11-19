"""Clipping campaigns, the rules in one place: reading a pasted campaign post, which clips belong to a campaign,
which posted videos count for it, and telling you on Discord when one does."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import describe, events
from .api.analytics import latest_snapshots
from .audit import audit
from .models import Campaign, CampaignClip, Clip, ClipOutput, utcnow

_PLATFORM_WORDS = {"tiktok": "tiktok", "tik tok": "tiktok", "instagram": "instagram", "youtube": "youtube", "x": "x", "twitter": "x"}
_UNITS = {"k": 1_000, "m": 1_000_000, "": 1}
_LEAD = r"[^\w\n]*(?:\d+[.)][ \t]+[^\w\n]*)?"  # bullets, numbering, emoji and markdown in front of a line
_ITEM = re.compile(r"^[ \t]*(?:[-*•·▪‣◦✓✔✅►>]|\d+[.)])[ \t]+\S")
_NOT = r"(?:not|n['’]t|never)\s+(?:\w+\s+)?"
_NEGATED = re.compile(rf"\b{_NOT}(?:use|add|mention|include|say|credit|show|display)\b", re.I)
_SECONDS = r"(seconds?|secs?|minutes?|mins?|s)\b"
_NOT_NAMES = {"MVR", "USD", "CPM", "FAQ", "CAD", "EUR", "GBP", "THE", "AND", "FOR"}


def _section(label: str, lines: list[str], must_follow: bool = False) -> str:
    """What follows a label: the rest of its line, or, when nothing follows it there, the next line and any list items
    under it ("Audience: English", "Platforms:" then "- TikTok", "Audience" then "English")."""
    for i, line in enumerate(lines):
        m = re.match(rf"{_LEAD}(?:{label})\b[ \t*_]*(:?)[ \t*_]*(.*)$", line, re.I)
        if not m or (must_follow and m.group(2).strip() and not m.group(1)):
            continue
        got = [m.group(2).strip()] if m.group(2).strip() else []
        for nxt in [] if got else lines[i + 1:i + 8]:
            if not nxt.strip() or (got and not _ITEM.match(nxt)):
                break
            got.append(re.sub(r"^[ \t]*(?:[-*•·▪‣◦✓✔✅►>]|\d+[.)])[ \t]*", "", nxt).strip())
        return ", ".join(got).strip(" *_")
    return ""


def _length(lines: list[str]) -> tuple[int, int]:
    """(shortest, longest) video length in seconds that the rules ask for, 0 when not asked."""
    lo = hi = 0

    def secs(n: str, unit: str) -> int:
        return int(float(n) * (60 if unit.lower().startswith("m") else 1))
    for line in lines:
        if not re.search(r"video|clip|length|duration|long|short|runtime", line, re.I):
            continue
        r = re.search(rf"(\d+(?:\.\d+)?)\s*(?:-|–|—|to|and)\s*(\d+(?:\.\d+)?)\s*{_SECONDS}", line, re.I)
        if r:
            lo, hi = max(lo, secs(r.group(1), r.group(3))), min(hi or 10**6, secs(r.group(2), r.group(3)))
            continue
        low = re.finditer(rf"(?:at least|minimum(?: of| length| duration)?|min\.?(?: length| duration)?|no (?:shorter|less) than)[:\s]*(\d+(?:\.\d+)?)\s*{_SECONDS}", line, re.I)
        high = re.finditer(rf"(?:under|less than|below|up to|at most|maximum(?: of| length| duration)?|max\.?(?: length| duration)?|no (?:longer|more) than|shorter than|(?:not|n['’]t)\s+(?:be\s+)?(?:exceed(?:ing)?|(?:longer|more|over) than))[:\s]*(\d+(?:\.\d+)?)\s*{_SECONDS}", line, re.I)
        lo = max([lo, *(secs(*m.groups()) for m in low)])
        hi = min([hi or 10**6, *(secs(*m.groups()) for m in high)])
    return lo, hi if hi < 10**6 else 0


def _names(lines: list[str], creator: str) -> tuple[list[str], list[str]]:
    """The names the rules say to mention: (in the caption, on the video)."""
    caption, overlay = [], []
    for line in lines:
        m = re.search(r"\b(?:mention|credit|include|say|show|display|name)\s+(?:the\s+(?:name\s+of\s+)?)?(@?\w[\w .'-]*?)(?:['’]s)?\s+name\b", line, re.I)
        if not m or _NEGATED.search(line):
            continue
        name = creator if m.group(1).lower() in ("creator", "streamer") and creator else m.group(1).strip()
        on_video = re.search(r"overlay|on[- ]?screen|on the video|in the video|video text", line, re.I)
        (caption if not on_video or re.search(r"caption|description", line, re.I) else []).append(name)
        if on_video:
            overlay.append(name)
    return list(dict.fromkeys(caption)), list(dict.fromkeys(overlay))


def _hashtags(lines: list[str]) -> list[str]:
    """Hashtags the rules ask for: on a line that says to use or include them, or listed under one that names them."""
    found, listing = [], False
    for line in lines:
        tags = re.findall(r"#\w+", line)
        only = bool(tags) and not re.sub(r"#\w+|and|[\s,;/&•*\-–·\d.)]", "", line)
        if (re.search(r"\b(?:hashtags?|must|required?|include|use|add)\b", line, re.I) or (only and listing)) and not _NEGATED.search(line):
            found += tags
        listing = bool(re.search(r"hashtags?\b", line, re.I)) or (listing and only)
    return list(dict.fromkeys(found))


def _clip_rules(lines: list[str], creator: str) -> dict:
    lo, hi = _length(lines)
    said = lambda pattern: any(re.search(pattern, l, re.I) for l in lines)  # noqa: E731
    return {"min_seconds": lo, "max_seconds": hi, "overlay_mentions": _names(lines, creator)[1],
            "language": "English" if any(re.search(r"\benglish\b", l, re.I) and re.search(r"caption|audience|language|speak|subtitle|text|narrat|spoken", l, re.I) for l in lines) else "",
            "no_logos": said(rf"\b(?:no|without|{_NOT}(?:add|use|include|have|put|show|contain))\s+(?:\w+\s+){{0,2}}?(?:logos?|watermarks?)|\b(?:logos?|watermarks?)\b[^\n.]{{0,50}}\b(?:not allowed|prohibited|forbidden|banned|not permitted|disallowed|aren['’]t allowed)"),
            "focus_creator": said(r"\b(?:main|primary|central) focus\b|\b(?:creator|streamer)\b[^\n.]{0,50}\b(?:appear|featured?|visible|on[- ]screen|shown|present|in (?:the|your) (?:video|edit|clip))")}


def parse(text: str) -> dict:
    """The fields of a pasted campaign post, in whatever layout (bullets, numbered lists, markdown, plain lines).
    Anything it can't find is left empty, for you to fill in."""
    lines = [re.sub(r"https?://\S+", "", l) for l in text.splitlines()]  # links aren't rules
    name = next((l for l in lines if re.search(r"campaign", l, re.I) and not re.match(rf"{_LEAD}(?:join|campaign (?:information|details|rules|requirements|overview)|about)\b", l, re.I)), "") \
        or next((l for l in lines if l.strip()), "")
    name = "".join(ch for ch in name if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Cf", "Mn")).strip("#*_ \t")
    pool_line = next((l for l in lines if re.search(r"pool|prize|budget|total", l, re.I) and "$" in l), "")
    pool = re.search(r"\$\s?\d[\d,]*(?:\.\d+)?[kKmM]?(?!\w)", pool_line or text)
    creator = _section("creator|streamer", lines, must_follow=True)
    where = _section(r"(?:eligible )?platforms?", lines)
    views = next((m for p in (r"(?:min(?:imum)?\.? views|MVR)[^\d]{0,40}(\d[\d,]*(?:\.\d+)?)([kKmM])?(?!\w)",
                              r"min(?:imum)?\.?(?: of)?\s*(\d[\d,]*(?:\.\d+)?)([kKmM])?\s*views",
                              r"(\d[\d,]*(?:\.\d+)?)([kKmM])?\s*views?\s*(?:min(?:imum)?|required)") if (m := re.search(p, text, re.I))), None)
    start = re.search(r"(?:beginning|starting|begins?|from|since)\s+(?:on\s+)?([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", text, re.I)
    within = re.search(r"within\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)", text, re.I)
    caption, _ = _names(lines, creator)
    footage = _section(r"what to look for|looking for|approved (?:footage|content)|footage", lines)
    skip = {creator.upper(), *(n.upper() for n in caption)}
    out = {"name": re.sub(r"\s+", " ", name).strip(), "pool": re.sub(r"\s", "", pool.group()) if pool else "", "creator": creator,
           "platforms": list(dict.fromkeys(_PLATFORM_WORDS[w.lower()] for w in re.findall(r"tik ?tok|instagram|youtube|twitter|\bx\b", where, re.I))),
           "min_views": int(float(views.group(1).replace(",", "")) * _UNITS[(views.group(2) or "").lower()]) if views else 0,
           "audience": _section("audience", lines), "required_hashtags": _hashtags(lines), "must_mention": caption,
           # Capitalized names like GTA or "Grand Theft Auto" in what to look for: the footage has to be about one of them
           "keywords": list(dict.fromkeys(k for k in [*re.findall(r"\b[A-Z][A-Z0-9]{2,7}\b", footage), *re.findall(r"[\"“]([^\"”]{3,30})[\"”]", footage)] if k.upper() not in skip | _NOT_NAMES)),
           "footage_from": None, "clip_rules": _clip_rules(lines, creator),
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
        url = url.rstrip(".,;")
        kind = "discord_url" if re.search(r"discord\.(?:com/invite|gg)/", url) else \
               "join_url" if "join" in label.lower() or re.search(r"contentrewards|whop", url) else "guidelines_url"
        out[kind] = out[kind] or url
    return out


# ---------- which clips belong, which videos count ----------

def fits(c: Campaign, creator_id: int | None, day: date, text: str) -> bool:
    """A clip of this streamer, from footage on this day, with this text (title, speech, game), is one the campaign
    wants: its streamer, inside its dates, and about what it asks for."""
    if not c.creator_id or c.creator_id != creator_id:
        return False
    if (c.footage_from and day < c.footage_from) or (c.ends_at and day >= c.ends_at):
        return False
    return not c.keywords or any(k.lower() in _searchable(text) for k in c.keywords)


def _searchable(text: str) -> str:
    """The text plus the initials of each run of capitalized words, so a rule saying "GTA" matches Twitch's
    "Grand Theft Auto V" (and "RDR" matches "Red Dead Redemption")."""
    runs = re.findall(r"(?:\b[A-Z][a-z]+\b[ ]?){2,}", text)
    return " ".join([text, *("".join(w[0] for w in r.split()) for r in runs)]).lower()


def matches(c: Campaign, clip: Clip) -> bool:
    said = " ".join(w["text"] for w in clip.words or [])
    return fits(c, clip.creator_id, (clip.stream_date or clip.created_at).date(),
                " ".join([clip.title, clip.reference.title if clip.reference else "", said, (clip.safety or {}).get("game") or ""]))


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


def merge_clip_rules(cs) -> dict:
    """What a video has to be to suit all of these campaigns at once: the strictest of each rule."""
    rs = [c.clip_rules or {} for c in cs]
    lo, hi = max((r.get("min_seconds") or 0 for r in rs), default=0), min((r["max_seconds"] for r in rs if r.get("max_seconds")), default=0)
    return {"min_seconds": min(lo, hi) if hi else lo, "max_seconds": hi,
            "overlay_mentions": list(dict.fromkeys(n for r in rs for n in r.get("overlay_mentions") or []))}


def coming_rules(s: Session, creator_id: int | None, stream_date: datetime | None, text: str) -> dict:
    """The video rules of the live campaigns a clip about to be made will be tagged to (see auto_tag)."""
    return merge_clip_rules(c for c in s.scalars(select(Campaign).where(Campaign.status == "live")).unique()
                            if fits(c, creator_id, (stream_date or utcnow()).date(), text))


def clip_rules_of(s: Session, clip: Clip) -> dict:
    return merge_clip_rules(s.scalars(select(Campaign).join(CampaignClip).where(CampaignClip.clip_id == clip.id, Campaign.status == "live")).unique())


def too_short(rules: dict, seconds: float) -> str:
    """A note for the clip when the footage couldn't be as long as the campaign's minimum, else nothing."""
    return f"Shorter than the campaign's {rules['min_seconds']} second minimum: there isn't more footage." if seconds < rules["min_seconds"] - 0.05 else ""


def complies(clip: Clip, rules: dict) -> bool:
    """The clip's length (with its teaser) and on-screen title already follow the rules."""
    e = clip.edit or {}
    seconds = (e.get("end", 0) - e.get("start", 0) + (e["hook"][1] - e["hook"][0] if e.get("hook") else 0)) / (e.get("speed") or 1)
    return (not rules["max_seconds"] or seconds <= rules["max_seconds"] + 0.05) and not too_short(rules, seconds) \
        and all(describe.has_name(clip.title, n) for n in rules["overlay_mentions"])


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
