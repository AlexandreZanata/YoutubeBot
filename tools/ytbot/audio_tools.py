"""Narration duration checks. The owner's audio is never sped up."""

from __future__ import annotations

from pathlib import Path

MAX_NARRATION_SECONDS = 124 * 60
MIN_NARRATION_SECONDS = 35 * 60


def log(message: str) -> None:
    print(f"[audio] {message}", flush=True)


def find_narration(run_dir: Path) -> Path:
    for name in ("narration.aac", "narration.webm", "narration.m4a", "narration.wav"):
        path = run_dir / name
        if path.is_file():
            return path
    raise FileNotFoundError("narration file is missing")


def fit_narration(run_dir: Path) -> Path:
    """Keep the narration untouched; the ceiling is the longest video plus 20 minutes."""
    from src.engine.audio_mixer import get_audio_duration

    narration = find_narration(run_dir)
    duration = get_audio_duration(narration)
    if duration < MIN_NARRATION_SECONDS:
        log(f"warning: narration is shorter than the accepted 35 minutes ({duration:.1f}s)")
    if duration > MAX_NARRATION_SECONDS:
        log(f"warning: narration {duration / 60:.1f} min exceeds the "
            f"{MAX_NARRATION_SECONDS / 60:.0f} min ceiling; keeping the original audio")
    return narration
