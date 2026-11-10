"""Color emoji in titles and on-video text.

The video text renderer (libass) can't draw color emoji, so text with emoji is laid out here instead: every
glyph is measured from the font itself, lines are wrapped here (so we know exactly where everything lands), each
emoji gets an invisible gap the size of the emoji, and the emoji image is placed in that gap as a layer under the
text. Images are Twemoji (CC-BY 4.0, by Twitter and contributors), downloaded the first time each one is used and
kept. With no internet and nothing cached, that emoji is left out, as before.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx

log = logging.getLogger("clippr.emoji")

SOURCE = "https://raw.githubusercontent.com/jdecked/twemoji/main/assets/72x72/{}.png"
EMOJI_SCALE = 0.92  # an emoji is about as tall as the capitals around it

_BASE = "\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U00003030\U0000303D\U00003297\U00003299\U000000A9\U000000AE\U00002122\U00002190-\U000021FF\U00002300-\U000023FF\U000025A0-\U000025FF"
_MOD = "\U0001F3FB-\U0001F3FF\U0000FE0F\U000020E3\U000E0020-\U000E007F"
# One emoji: a base (or a keycap digit, or a flag's two letters), its modifiers, and anything joined to it with ZWJ.
_ONE = re.compile(rf"[\U0001F1E6-\U0001F1FF]{{2}}|[0-9#*]\U0000FE0F?\U000020E3|[{_BASE}][{_MOD}]*(?:\U0000200D[{_BASE}][{_MOD}]*)*")


def has_emoji(text: str) -> bool:
    return bool(_ONE.search(text))


def split(text: str) -> list[str]:
    """Text and emoji in order: emoji are their own items."""
    out, pos = [], 0
    for m in _ONE.finditer(text):
        if m.start() > pos:
            out.append(text[pos:m.start()])
        out.append(m.group(0))
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return out


def is_emoji(piece: str) -> bool:
    return bool(_ONE.fullmatch(piece))


def _codes(e: str, keep_fe0f: bool) -> str:
    return "-".join(f"{ord(ch):x}" for ch in e if keep_fe0f or ch != "\uFE0F")


def image(e: str, cache: Path) -> Path | None:
    """The emoji's picture, downloaded once and kept. None if it can't be had (offline, unknown emoji)."""
    cache.mkdir(parents=True, exist_ok=True)
    names = list(dict.fromkeys([_codes(e, False), _codes(e, True)]))  # Twemoji names drop FE0F, except a few
    for name in names:
        if (cache / f"{name}.png").exists():
            return cache / f"{name}.png"
    if (cache / f"{names[0]}.missing").exists():
        return None
    if os.environ.get("CLIPPR_OFFLINE_EMOJI"):  # tests: never go online
        return None
    for name in names:
        try:
            r = httpx.get(SOURCE.format(name), timeout=10, follow_redirects=True)
        except Exception:  # offline or anything else: an emoji must never stop a clip; try again next time
            return None
        if r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n":
            (cache / f"{name}.png").write_bytes(r.content)
            return cache / f"{name}.png"
    (cache / f"{names[0]}.missing").touch()  # not a Twemoji: don't ask again
    return None


@lru_cache(maxsize=8)
def _metrics(font_path: str) -> tuple[dict, dict, float]:
    from fontTools.ttLib import TTFont

    f = TTFont(font_path, lazy=True)
    os2 = f["OS/2"]
    # libass sizes a font so its Windows ascent + descent equal the font size.
    return f.getBestCmap(), {k: v[0] for k, v in f["hmtx"].metrics.items()}, float(os2.usWinAscent + os2.usWinDescent)


def advance(text: str, font_path: Path, size: float) -> float:
    """Width in pixels of plain text at this font size."""
    cmap, hmtx, units = _metrics(str(font_path))
    fallback = hmtx.get(cmap.get(ord("n"), ""), units / 2)
    return sum(hmtx.get(cmap.get(ord(ch), ""), fallback) for ch in text) * size / units


@dataclass
class Placed:
    emoji: str
    x: float  # center, pixels
    y: float
    size: float


def layout(text: str, font_path: Path, size: float, max_width: float, cx: float, cy: float) -> tuple[str, list[Placed]]:
    """ASS text for a block centered on (cx, cy), with an invisible gap for each emoji, and where each emoji goes.
    The ASS text has its own line breaks and turns off automatic wrapping, so the positions are exact."""
    e_size = size * EMOJI_SCALE
    space = advance(" ", font_path, size)
    m_width = advance("M", font_path, size) or size * 0.8
    words = [w for w in re.split(r"(\s+)", text) if w and not w.isspace()]
    lines: list[list[str]] = [[]]
    width = 0.0

    def w_of(word: str) -> float:
        return sum(e_size if is_emoji(p) else advance(p, font_path, size) for p in split(word))

    for word in words:
        ww = w_of(word)
        if lines[-1] and width + space + ww > max_width:
            lines.append([])
            width = 0.0
        width += (space if lines[-1] else 0) + ww
        lines[-1].append(word)

    placed: list[Placed] = []
    out_lines = []
    top = cy - len(lines) * size / 2
    for i, line in enumerate(lines):
        line_text = " ".join(line)
        total = w_of(line_text.replace(" ", "")) + space * (len(line) - 1)
        x = cx - total / 2
        y = top + (i + 0.5) * size
        parts = []
        for p in split(line_text):
            if is_emoji(p):
                placed.append(Placed(p, x + e_size / 2, y, e_size))
                # An invisible capital M stretched to the emoji's width holds its place in the line.
                parts.append(f"{{\\1a&HFF&\\3a&HFF&\\4a&HFF&\\fscx{100 * e_size / m_width:.1f}}}M{{\\1a&H00&\\3a&H00&\\4a&H64&\\fscx100}}")
                x += e_size
            else:
                parts.append(p)
                x += advance(p, font_path, size)
        out_lines.append("".join(parts))
    return "{\\q2}" + "\\N".join(out_lines), placed
