"""Text burned into the video: a title at the top for the first seconds, and captions synced to speech.

Rendered with libass (inside the bundled FFmpeg) from an .ass subtitle file, using fonts that ship
with the app so the result looks identical on every computer."""
from __future__ import annotations

import difflib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import emoji

FONT_DIR = Path(__file__).parent / "fonts"
# Average character width / font size, measured from the bundled fonts (upper, lower case).
FONT_WIDTH = {"montserrat": (0.66, 0.55), "anton": (0.42, 0.40), "bebas": (0.34, 0.34), "poppins": (0.59, 0.51)}
SIDE_MARGIN = 70  # px each side on a 1080-wide video

# Phrases speech models are known to invent over silence or music (from their training subtitles).
_HALLUCINATIONS = re.compile(r"^(thanks? (you )?for watching|subtitles by|subscribe|amara\.org|transcribed by|♪+|\.+)[.!]*$", re.I)

FONTS = {  # key -> (file, family name inside the font)
    "montserrat": ("Montserrat_900Black.ttf", "Montserrat Black"),
    "anton": ("Anton_400Regular.ttf", "Anton"),
    "bebas": ("BebasNeue_400Regular.ttf", "Bebas Neue"),
    "poppins": ("Poppins_800ExtraBold.ttf", "Poppins ExtraBold"),
}


@dataclass
class Word:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return {"start": round(self.start, 3), "end": round(self.end, 3), "text": self.text}

    @classmethod
    def from_dict(cls, d: dict) -> "Word":
        return cls(float(d["start"]), float(d["end"]), str(d["text"]))


def clean_words(words: list[Word], duration: float) -> list[Word]:
    """Make raw speech-model output safe to display: no invented filler, no repeats, no overlaps."""
    # 1. Merge punctuation-only tokens into the previous word; drop empties.
    merged: list[Word] = []
    for w in words:
        t = re.sub(r"\s+", " ", w.text).strip()
        if not t:
            continue
        if merged and re.fullmatch(r"[^\w']+", t):
            merged[-1].text += t
            merged[-1].end = max(merged[-1].end, w.end)
            continue
        merged.append(Word(float(w.start), float(w.end), t))
    # 2. Drop known hallucinated phrases when they are the whole utterance.
    if merged and _HALLUCINATIONS.match(" ".join(w.text for w in merged)):
        return []
    # 3. Collapse a phrase the model repeated over and over (a classic glitch): keep at most 2 in a row.
    out: list[Word] = []
    for w in merged:
        out.append(w)
        for n in (1, 2, 3, 4):
            if len(out) >= 3 * n:
                a, b, c = out[-3 * n:-2 * n], out[-2 * n:-n], out[-n:]
                norm = lambda ws: [x.text.lower().strip(".,!?") for x in ws]  # noqa: E731
                if norm(a) == norm(b) == norm(c):
                    del out[-n:]
                    break
    # 4. Order, clamp to the clip, remove overlaps, give every word a minimum on-screen moment.
    out = sorted((w for w in out if w.end > 0 and w.start < duration), key=lambda w: w.start)
    for i, w in enumerate(out):
        w.start = max(0.0, min(w.start, duration))
        w.end = max(w.start + 0.08, min(w.end, duration))
        if i and w.start < out[i - 1].end:
            out[i - 1].end = max(out[i - 1].start + 0.05, w.start)
    return out


def max_chars(style: dict, width: int) -> int:
    """How many characters fit on one line at this font and size (so captions never wrap mid-phrase)."""
    upper, lower = FONT_WIDTH.get(style["font"], (0.6, 0.5))
    per_char = style["size"] * (width / 1080) * (upper if style["all_caps"] else lower)
    usable = width - 2 * SIDE_MARGIN * (width / 1080)
    return max(6, int(usable / max(per_char, 1)))


def chunk_words(words: list[Word], per: int, chars: int = 999) -> list[Word]:
    """Group words into short on-screen captions: at most `per` words and `chars` characters, breaking
    early at sentence ends and pauses. Captions never overlap, never flash for less than ~0.4 s, and
    stay up through short gaps so they don't flicker."""
    out: list[Word] = []
    cur: list[Word] = []

    def flush():
        if cur:
            out.append(Word(cur[0].start, cur[-1].end, " ".join(x.text for x in cur)))
            cur.clear()

    for w in words:
        if cur:
            text_len = len(" ".join(x.text for x in cur)) + 1 + len(w.text)
            if len(cur) >= per or text_len > chars or w.start - cur[-1].end > 0.6:
                flush()
        cur.append(w)
        if re.search(r"[.!?]$", w.text):
            flush()
    flush()
    for i, a in enumerate(out):
        nxt = out[i + 1].start if i + 1 < len(out) else None
        if nxt is not None and 0 <= nxt - a.end < 0.35:
            a.end = nxt  # hold through short gaps
        if a.end - a.start < 0.4:
            a.end = a.start + 0.4 if nxt is None else min(a.start + 0.4, nxt)
        if nxt is not None and a.end > nxt:
            a.end = nxt
    return out


def apply_text_edit(words: list[Word], new_text: str) -> list[Word]:
    """Keep word timings when the user corrects the transcript text."""
    new = new_text.split()
    if not words:
        return []
    old = [w.text for w in words]
    sm = difflib.SequenceMatcher(a=[o.lower().strip(".,!?") for o in old], b=[n.lower().strip(".,!?") for n in new], autojunk=False)
    out: list[Word] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out += [Word(words[i1 + k].start, words[i1 + k].end, new[j1 + k]) for k in range(i2 - i1)]
        elif tag in ("replace", "insert"):
            if i2 > i1:
                start, end = words[i1].start, words[i2 - 1].end
            else:  # pure insert: squeeze next to the previous word
                prev = out[-1] if out else words[0]
                start, end = prev.end, prev.end + 0.3
            n = j2 - j1
            span = max(end - start, 0.05 * n)
            out += [Word(start + span * k / n, start + span * (k + 1) / n, new[j1 + k]) for k in range(n)]
    return out


def _ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U0000200D\U0001F1E6-\U0001F1FF]")


def _clean(text: str, caps: bool, keep_emoji: bool = False) -> str:
    # The text renderer can't draw color emoji: they're removed, or (keep_emoji) placed as pictures by emoji.layout.
    text = re.sub(r"\s+", " ", text if keep_emoji else _EMOJI.sub("", text))
    text = text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ").strip()
    return text.upper() if caps else text


def build_ass(width: int, height: int, overlay: dict, title_text: str, words: list[Word], duration: float, texts: list[dict] | None = None,
              emoji_cache: Path | None = None, emoji_out: list | None = None) -> str:
    """emoji_cache: where emoji pictures are kept; with it, emoji in the title and texts are kept, and
    emoji_out gets (start, end, emoji.Placed, picture) for each, to lay over the video under the text."""
    scale = width / 1080
    t, c = overlay["title"], overlay["captions"]

    def text_for(raw: str, caps: bool, font_key: str, size_px: float, y: float, start: float, end: float) -> str:
        if emoji_cache is None or emoji_out is None or not emoji.has_emoji(raw):
            return _clean(raw, caps)
        # Emoji that can't be had (offline, unknown) are dropped; the rest get a gap and a picture.
        try:
            pics = {e: emoji.image(e, emoji_cache) for e in emoji.split(raw) if emoji.is_emoji(e)}
            kept = "".join(p for p in emoji.split(raw) if not emoji.is_emoji(p) or pics.get(p))
            ass, placed = emoji.layout(_clean(kept, caps, keep_emoji=True), FONT_DIR / FONTS[font_key][0], size_px,
                                       width - 140 * scale, width / 2, y)
        except Exception:
            emoji.log.exception("emoji layout failed; drawing the text without them")
            return _clean(raw, caps)
        emoji_out.extend((start, end, pl, pics[pl.emoji]) for pl in placed)
        return ass

    def style(name: str, s: dict) -> str:
        font = FONTS[s["font"]][1]
        return (f"Style: {name},{font},{round(s['size'] * scale)},{_ass_color(s['color'])},{_ass_color(s['color'])},"
                f"{_ass_color(s['outline_color'])},&H64000000,-1,0,0,0,100,100,0,0,1,{s['outline'] * scale:.1f},{2 * scale:.1f},5,"
                f"{round(70 * scale)},{round(70 * scale)},0,1")

    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style("Title", t), style("Caption", c), "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if t["enabled"] and title_text.strip():
        y = round(height * t["y_percent"] / 100)
        end = min(float(t["duration"]), duration)
        body = text_for(title_text, t["all_caps"], t["font"], round(t["size"] * scale), y, 0, end)
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(end)},Title,,0,0,0,,{{\\pos({width // 2},{y})\\fad(150,300)}}{body}")
    if c["enabled"]:
        y = round(height * c["y_percent"] / 100)
        for w in chunk_words(words, int(c["words_per_caption"]), max_chars(c, width)):
            if w.end <= 0 or w.start >= duration:
                continue
            lines.append(f"Dialogue: 0,{_ts(w.start)},{_ts(min(w.end, duration))},Caption,,0,0,0,,{{\\pos({width // 2},{y})}}{_clean(w.text, c['all_caps'])}")
    for tx in texts or []:  # extra text added in the video editor
        if tx["end"] <= tx["start"] or tx["start"] >= duration:
            continue
        y = round(height * tx["y_percent"] / 100)
        style = (f"{{\\pos({width // 2},{y})\\fn{FONTS[tx['font']][1]}\\fs{round(tx['size'] * scale)}\\c{_ass_color(tx['color'])}"
                 f"\\3c{_ass_color('#000000')}\\bord{tx['outline'] * scale:.1f}}}")
        body = text_for(tx["text"], tx["all_caps"], tx["font"], round(tx["size"] * scale), y, tx["start"], min(tx["end"], duration))
        lines.append(f"Dialogue: 2,{_ts(tx['start'])},{_ts(min(tx['end'], duration))},Title,,0,0,0,,{style}{body}")
    return "\n".join(lines) + "\n"


def prepare(workdir: Path, ass_text: str) -> tuple[str, str]:
    """Write the subtitle file and fonts next to each other; FFmpeg runs in workdir with relative paths
    (avoids Windows drive-letter escaping problems inside filter arguments)."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "overlay.ass").write_text(ass_text, encoding="utf-8")
    fonts = workdir / "fonts"
    fonts.mkdir(exist_ok=True)
    for file, _ in FONTS.values():
        if not (fonts / file).exists():
            shutil.copyfile(FONT_DIR / file, fonts / file)
    return "overlay.ass", "fonts"
