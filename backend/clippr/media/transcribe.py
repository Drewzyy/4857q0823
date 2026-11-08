"""Speech to text on this computer (faster-whisper). Free and private: audio never leaves the machine.
The model (~145 MB) downloads once, the first time it's needed."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

from .ffmpeg import decode_audio_chunks
from .overlay import Word

log = logging.getLogger("clippr.transcribe")
MODEL = "base"


class TranscribeError(Exception):
    pass


class Transcriber(Protocol):
    def words(self, audio_or_video: Path) -> list[Word]: ...


class WhisperTranscriber:
    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel

                    self.model_dir.mkdir(parents=True, exist_ok=True)
                    self._model = WhisperModel(MODEL, device="cpu", compute_type="int8", download_root=str(self.model_dir))
                except Exception as e:  # network or packaging problems surface as a skipped-captions note
                    log.exception("speech model failed to load")
                    raise TranscribeError(f"Couldn't load the speech model ({type(e).__name__}). Check your internet connection for the one-time download.")
            return self._model

    def words(self, audio_or_video: Path) -> list[Word]:
        audio = np.concatenate(list(decode_audio_chunks(audio_or_video, 16000)) or [np.zeros(0, dtype=np.float32)])
        if len(audio) < 1600:
            return []
        model = self._load()
        segments, _ = model.transcribe(audio, word_timestamps=True, vad_filter=False, condition_on_previous_text=False, beam_size=5)
        out: list[Word] = []
        for seg in segments:
            for w in seg.words or []:
                text = w.word.strip()
                if text:
                    out.append(Word(float(w.start), float(w.end), text))
        return out
