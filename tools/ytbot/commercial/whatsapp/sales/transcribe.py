"""Local speech-to-text for client voice messages (faster-whisper large-v3-turbo).

Runs on this PC's GPU (CPU fallback), Portuguese only, so the client's voice never leaves the
machine and costs nothing. Voice notes are short, so the decoder uses beam search (5) and word
timestamps: every word keeps its confidence, and numbers heard with low confidence are
reported so the bot can confirm them with the client instead of trusting a guess. Measured on
the owner's test notes (2026-11-17): model load ~2.5 s, a 26 s note ~0.5 s on the RTX 4060.
The project's subtitle transcriber (`src/core/ai_transcriber.py`) is the fallback.
"""

from __future__ import annotations

import re
from pathlib import Path

MODEL = "large-v3-turbo"
UNCERTAIN_BELOW = 0.6
OPTIONS = {"language": "pt", "beam_size": 5, "best_of": 5, "temperature": [0.0, 0.2, 0.4],
           "vad_filter": True, "condition_on_previous_text": False, "word_timestamps": True}


class TranscriptionError(RuntimeError):
    """The audio could not be turned into text; the owner listens instead."""


def _whisper(path: Path) -> dict:
    import src.core.ai_transcriber  # noqa: F401  (prepares the CUDA libraries like the project)
    import torch
    from faster_whisper import WhisperModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = WhisperModel(MODEL, device=device,
                         compute_type="int8_float16" if device == "cuda" else "int8")
    try:
        segments, _ = model.transcribe(str(path), **OPTIONS)
        words = [(word.word.strip(), float(word.probability))
                 for segment in segments for word in (segment.words or [])]
    finally:
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
    return {"text": " ".join(word for word, _ in words).strip(),
            "uncertain": [word for word, probability in words
                          if probability < UNCERTAIN_BELOW and re.search(r"\d", word)],
            "engine": f"faster-whisper {MODEL} beam 5"}


def local_transcriber(path: Path) -> dict:
    """{text, uncertain, engine} for a voice note; raises TranscriptionError when empty."""
    try:
        result = _whisper(path)
    except ImportError as error:
        raise TranscriptionError(f"transcriber unavailable: {error}") from error
    except Exception:
        try:
            from src.core.ai_transcriber import transcribe_audio_in_language
        except ImportError as error:
            raise TranscriptionError(f"transcriber unavailable: {error}") from error
        segments = transcribe_audio_in_language(str(path), "pt")
        result = {"text": " ".join(item.get("text", "").strip() for item in segments).strip(),
                  "uncertain": [], "engine": f"project {MODEL} beam 1"}
    if not result["text"]:
        raise TranscriptionError("empty transcription")
    return result
