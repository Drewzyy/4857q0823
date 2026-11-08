"""Speech to text on this computer (faster-whisper). Free and private: audio never leaves the machine.

Accuracy levels (downloaded once, the first time each is used):
  fast      -> whisper "base"            ~145 MB, quickest
  accurate  -> whisper "small"           ~480 MB, default: much better with fast talkers, slang, names
  best      -> whisper "large-v3-turbo"  ~1.6 GB, best accuracy, slower on older computers

Glitch protection: voice-activity detection skips silence and music (where speech models invent text),
segments the model itself flags as probably-not-speech are dropped, and the output goes through
overlay.clean_words (repeats, overlaps, stray punctuation, known filler phrases).
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from .ffmpeg import decode_audio_chunks
from .overlay import Word

log = logging.getLogger("clippr.transcribe")
MODELS = {"fast": "base", "accurate": "small", "best": "large-v3-turbo"}
MODEL_SIZES = {"fast": "about 145 MB", "accurate": "about 480 MB", "best": "about 1.6 GB"}


class TranscribeError(Exception):
    pass


class Transcriber(Protocol):
    def words(self, audio_or_video: Path) -> list[Word]: ...


class WhisperTranscriber:
    def __init__(self, model_dir: Path, settings: Callable[[], tuple[str, str]] = lambda: ("accurate", "auto")):
        self.model_dir = model_dir
        self.settings = settings
        self._models: dict[str, object] = {}
        self._lock = threading.Lock()

    def _load(self, name: str):
        with self._lock:
            if name not in self._models:
                try:
                    from faster_whisper import WhisperModel

                    self.model_dir.mkdir(parents=True, exist_ok=True)
                    self._models = {name: WhisperModel(name, device="cpu", compute_type="int8", download_root=str(self.model_dir))}
                except Exception as e:
                    log.exception("speech model %s failed to load", name)
                    raise TranscribeError(f"Couldn't load the speech model ({type(e).__name__}). Check your internet connection for the one-time download.")
            return self._models[name]

    def words(self, audio_or_video: Path) -> list[Word]:
        audio = np.concatenate(list(decode_audio_chunks(audio_or_video, 16000)) or [np.zeros(0, dtype=np.float32)])
        if len(audio) < 1600:
            return []
        accuracy, language = self.settings()
        model = self._load(MODELS.get(accuracy, "small"))
        segments, _ = model.transcribe(
            audio,
            language=None if language == "auto" else language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
            condition_on_previous_text=False,  # stops one mistake from snowballing into repeated text
            beam_size=5,
            temperature=[0.0, 0.2, 0.4],
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            hallucination_silence_threshold=1.0,
        )
        out: list[Word] = []
        for seg in segments:
            if seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.8:
                continue  # the model itself thinks this wasn't speech
            for w in seg.words or []:
                text = w.word.strip()
                if text and (w.probability is None or w.probability >= 0.05):
                    out.append(Word(float(w.start), float(w.end), text))
        return out
