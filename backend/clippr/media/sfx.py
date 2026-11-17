"""Sound effects for clips: Vyral's own, made here from scratch, so there's nothing to license and nothing to
download. Each is styled on a sound clip editors reach for (the boom that lands a punchline, the scratch that
stops everything, the crickets after a bad joke), not copied from any recording.

Restraint matters more than the sound: one hit on the biggest moment lands; one every few seconds gets the
video scrolled past (see VIRALITY_RESEARCH.md). Vyral places at most one by itself.
"""
from __future__ import annotations

import re
from pathlib import Path

from .ffmpeg import run

# name: (label, what it's for, length in seconds, FFmpeg audio source, extra filters)
SOUNDS: dict[str, tuple[str, str, float, str, str]] = {
    "boom": ("Boom", "lands the punchline or the shock", 1.6,
             "aevalsrc='0.95*sin(2*PI*t*(42+70*exp(-t*14)))*exp(-t*2.6)+0.25*sin(2*PI*t*(84+140*exp(-t*14)))*exp(-t*5)':s=48000:d=1.6",
             "lowpass=f=900,aecho=0.6:0.5:60:0.25"),
    "bass_drop": ("Bass drop", "something big just happened", 1.8,
                  "aevalsrc='0.9*sin(2*PI*(160*t-125*t*t/2/1.8))*min(1,t*30)*exp(-t*1.2)':s=48000:d=1.8", "lowpass=f=500"),
    "whoosh": ("Whoosh", "a quick change or a reveal", 0.7,
               "aevalsrc='(random(0)*2-1)*sin(PI*t/0.7)^2':s=48000:d=0.7", "bandpass=f=1800:width_type=h:w=2400,lowpass=f=6000"),
    "scratch": ("Record scratch", "everything stops: wait, what?", 0.8,
                "aevalsrc='0.6*sin(2*PI*t*(320+260*sin(2*PI*t*7)))*exp(-t*2.5)':s=48000:d=0.8",
                "highpass=f=200,acrusher=bits=8:mix=0.4"),
    "ding": ("Ding", "nailed it, correct", 1.2,
             "aevalsrc='0.5*sin(2*PI*1318*t)*exp(-t*4)+0.25*sin(2*PI*2637*t)*exp(-t*6)':s=48000:d=1.2", ""),
    "riser": ("Riser", "builds tension right before the moment", 1.6,
              "aevalsrc='0.35*sin(2*PI*(180*t+560*t*t/2/1.6))*(t/1.6)^2':s=48000:d=1.6", "aecho=0.5:0.4:40:0.2"),
    "pop": ("Pop", "text or a detail appears", 0.15,
            "aevalsrc='0.8*sin(2*PI*t*(700-3000*t))*exp(-t*35)':s=48000:d=0.15", ""),
    "crickets": ("Crickets", "awkward silence", 2.0,
                 "aevalsrc='0.25*sin(2*PI*4400*t)*gt(sin(2*PI*30*t),0)*lt(mod(t,0.5),0.18)':s=48000:d=2", "highpass=f=3000"),
}


def is_sound_name(name: str) -> bool:
    """A built-in sound, or one of the user's own from the library ("lib:<id>")."""
    return name in SOUNDS or bool(re.fullmatch(r"lib:\d{1,9}", name))


def library_id(name: str) -> int | None:
    return int(name[4:]) if name.startswith("lib:") else None


def path(name: str, folder: Path) -> Path:
    """The sound as a WAV file, made the first time it's needed and kept in `folder`."""
    if name not in SOUNDS:
        raise KeyError(name)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{name}-v2.wav"
    if not out.exists():
        _, _, dur, source, extra = SOUNDS[name]
        part = out.with_suffix(".part.wav")
        af = ",".join(x for x in [extra, f"afade=t=out:st={max(0.0, dur - 0.08):.2f}:d=0.08", "aformat=sample_rates=48000:channel_layouts=stereo"] if x)
        raw = out.with_suffix(".raw.wav")
        run(["-f", "lavfi", "-i", source, "-af", af, "-t", f"{dur:.2f}", str(raw)])
        # Every sound peaks at the same level, so the volume a user picks means the same for each.
        peak = re.search(r"max_volume: (-?[\d.]+) dB", run(["-i", str(raw), "-af", "volumedetect", "-f", "null", "-"]))
        gain = -3.0 - float(peak.group(1)) if peak else 0.0
        run(["-i", str(raw), "-af", f"volume={gain:.2f}dB", str(part)])
        raw.unlink(missing_ok=True)
        part.replace(out)
    return out


def length(name: str) -> float:
    return SOUNDS[name][2]


def catalog() -> list[dict]:
    return [{"name": k, "label": v[0], "use": v[1], "seconds": v[2]} for k, v in SOUNDS.items()]
