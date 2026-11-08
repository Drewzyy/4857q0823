"""Parse what users paste (handles, @handles, profile URLs) into normalised source accounts.

Pure string handling, no network calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

SUPPORTED_SOURCE_PLATFORMS = ("tiktok", "youtube", "twitch", "instagram")

_USERNAME_RE = {
    "tiktok": re.compile(r"^[A-Za-z0-9_.]{2,24}$"),
    "instagram": re.compile(r"^[A-Za-z0-9_.]{1,30}$"),
    "twitch": re.compile(r"^[A-Za-z0-9_]{3,25}$"),
    "youtube": re.compile(r"^[A-Za-z0-9_.\-]{3,30}$"),
}

_HOSTS = {
    "tiktok.com": "tiktok",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "twitch.tv": "twitch",
    "instagram.com": "instagram",
}


class SourceInputError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSource:
    platform: str
    username: str
    profile_url: str


def profile_url(platform: str, username: str) -> str:
    if platform == "tiktok":
        return f"https://www.tiktok.com/@{username}"
    if platform == "youtube":
        return f"https://www.youtube.com/channel/{username}" if username.startswith("UC") and len(username) == 24 else f"https://www.youtube.com/@{username}"
    if platform == "twitch":
        return f"https://www.twitch.tv/{username}"
    if platform == "instagram":
        return f"https://www.instagram.com/{username}/"
    raise SourceInputError(f"Unsupported platform: {platform}")


def _host_platform(host: str) -> str | None:
    host = host.lower().split(":")[0]
    for suffix, plat in _HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return plat
    return None


def _validate(platform: str, username: str) -> str:
    username = username.strip().lstrip("@")
    if platform == "youtube" and username.startswith("UC") and len(username) == 24:
        return username
    if not _USERNAME_RE[platform].match(username):
        raise SourceInputError(f"'{username}' is not a valid {platform} username")
    return username.lower() if platform in ("tiktok", "instagram", "twitch") else username


def parse_source_input(text: str, default_platform: str = "tiktok") -> ParsedSource:
    text = (text or "").strip()
    if not text:
        raise SourceInputError("Enter a username or profile URL")
    if len(text) > 300:
        raise SourceInputError("Input is too long")
    if default_platform not in SUPPORTED_SOURCE_PLATFORMS:
        raise SourceInputError(f"Unsupported platform: {default_platform}")

    looks_like_url = "://" in text or re.match(r"^(www\.|m\.|vm\.|vt\.)?[a-z0-9-]+\.(com|tv|be)/", text, re.I)
    if not looks_like_url:
        name = _validate(default_platform, text)
        return ParsedSource(default_platform, name, profile_url(default_platform, name))

    url = urlparse(text if "://" in text else "https://" + text)
    if url.scheme not in ("http", "https"):
        raise SourceInputError("Only http(s) links are supported")
    platform = _host_platform(url.netloc)
    if not platform:
        raise SourceInputError("Unrecognised link. Supported: TikTok, YouTube, Twitch, Instagram profile links")
    host = url.netloc.lower()
    parts = [p for p in url.path.split("/") if p]

    if platform == "tiktok":
        if host.startswith(("vm.", "vt.")) or (parts and parts[0] == "t"):
            raise SourceInputError("TikTok short links can't be read offline. Open it and paste the full profile URL (tiktok.com/@name)")
        if not parts or not parts[0].startswith("@"):
            raise SourceInputError("Paste a TikTok profile link like tiktok.com/@username")
        name = _validate("tiktok", parts[0])
    elif platform == "youtube":
        if host == "youtu.be" or (parts and parts[0] in ("watch", "shorts", "live")):
            raise SourceInputError("That is a video link. Paste the channel link (youtube.com/@handle)")
        if parts and parts[0].startswith("@"):
            name = _validate("youtube", parts[0])
        elif len(parts) >= 2 and parts[0] in ("channel", "c", "user"):
            name = _validate("youtube", parts[1])
        else:
            raise SourceInputError("Paste a YouTube channel link like youtube.com/@handle")
    elif platform == "twitch":
        if not parts or parts[0] in ("videos", "directory", "settings"):
            raise SourceInputError("Paste a Twitch channel link like twitch.tv/name")
        name = _validate("twitch", parts[0])
    else:  # instagram
        if not parts or parts[0] in ("p", "reel", "reels", "stories", "explore"):
            raise SourceInputError("Paste an Instagram profile link like instagram.com/name")
        name = _validate("instagram", parts[0])
    return ParsedSource(platform, name, profile_url(platform, name))
