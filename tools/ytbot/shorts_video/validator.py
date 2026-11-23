"""Media validation for Shorts AI video clips and rendered output."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from .models import ClipValidationResult


def _parse_fps(rate_text: str) -> float:
    if not rate_text or rate_text == "0/0":
        return 0.0
    if "/" in rate_text:
        num, den = rate_text.split("/", 1)
        try:
            n_val = float(num)
            d_val = float(den)
            return round(n_val / d_val, 3) if d_val > 0 else 0.0
        except ValueError:
            return 0.0
    try:
        return round(float(rate_text), 3)
    except ValueError:
        return 0.0


def validate_clip(
    path: Path,
    *,
    require_portrait: bool = False,
    min_duration: float = 1.0,
) -> ClipValidationResult:
    """Validate that a local file is a real, decodable non-symlink video clip."""
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        return ClipValidationResult(
            valid=False, path=str(target), reason="clip file is missing or is a symlink"
        )
    file_size = target.stat().st_size
    if file_size < 512:
        return ClipValidationResult(
            valid=False,
            path=str(target),
            file_size=file_size,
            reason=f"clip file is too small ({file_size} bytes)",
        )

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_name,codec_type,width,height,r_frame_rate,duration",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(target),
    ]
    try:
        probe = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return ClipValidationResult(
            valid=False, path=str(target), file_size=file_size, reason=f"ffprobe failed: {error}"
        )

    if probe.returncode != 0:
        detail = (probe.stderr or "").strip()[:200] or "ffprobe rejected clip"
        return ClipValidationResult(
            valid=False, path=str(target), file_size=file_size, reason=detail
        )

    try:
        payload = json.loads(probe.stdout or "{}")
    except ValueError:
        return ClipValidationResult(
            valid=False, path=str(target), file_size=file_size, reason="invalid ffprobe output"
        )

    streams = payload.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video_stream:
        return ClipValidationResult(
            valid=False, path=str(target), file_size=file_size, reason="clip has no video stream"
        )

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    fps = _parse_fps(str(video_stream.get("r_frame_rate") or ""))
    codec = str(video_stream.get("codec_name") or "")

    raw_dur = video_stream.get("duration") or (payload.get("format") or {}).get("duration") or 0.0
    try:
        duration = float(raw_dur)
    except (TypeError, ValueError):
        duration = 0.0

    if width <= 0 or height <= 0:
        return ClipValidationResult(
            valid=False,
            path=str(target),
            width=width,
            height=height,
            duration_sec=duration,
            fps=fps,
            has_video=True,
            codec=codec,
            file_size=file_size,
            reason="clip has invalid dimensions",
        )
    if not math.isfinite(duration) or duration < min_duration:
        return ClipValidationResult(
            valid=False,
            path=str(target),
            width=width,
            height=height,
            duration_sec=duration,
            fps=fps,
            has_video=True,
            codec=codec,
            file_size=file_size,
            reason=f"clip duration {duration:.2f}s is below minimum {min_duration:.2f}s",
        )
    if require_portrait and width >= height:
        return ClipValidationResult(
            valid=False,
            path=str(target),
            width=width,
            height=height,
            duration_sec=duration,
            fps=fps,
            has_video=True,
            codec=codec,
            file_size=file_size,
            reason=f"clip is not vertical 9:16 ({width}x{height})",
        )

    return ClipValidationResult(
        valid=True,
        path=str(target),
        width=width,
        height=height,
        duration_sec=round(duration, 3),
        fps=fps,
        has_video=True,
        codec=codec,
        file_size=file_size,
        reason="ok",
    )
