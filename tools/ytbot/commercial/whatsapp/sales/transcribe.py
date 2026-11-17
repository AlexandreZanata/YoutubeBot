"""Local speech-to-text for client voice messages (faster-whisper large-v3-turbo).

Reuses the project's transcriber (`src/core/ai_transcriber.py`): runs on this PC's GPU (CPU
fallback), Portuguese only, so the client's voice never leaves the machine and costs nothing.
"""

from __future__ import annotations

from pathlib import Path


class TranscriptionError(RuntimeError):
    """The audio could not be turned into text; the owner listens instead."""


def local_transcriber(path: Path) -> str:
    try:
        from src.core.ai_transcriber import transcribe_audio_in_language
    except ImportError as error:
        raise TranscriptionError(f"transcriber unavailable: {error}") from error
    segments = transcribe_audio_in_language(str(path), "pt")
    text = " ".join(segment.get("text", "").strip() for segment in segments).strip()
    if not text:
        raise TranscriptionError("empty transcription")
    return text
