"""Render the final 16:9 video with the channel's standard settings."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from . import config, flow_media, flow_profiles, logic
from .audio_tools import fit_narration


def _render_jobs() -> int:
    """Concurrent renders per batch; the NVENC fallback keeps 2 a safe default."""
    try:
        return max(1, int(os.environ.get("YTBOT_RENDER_JOBS", "2")))
    except ValueError:
        return 2


RENDER_SEMAPHORE = threading.Semaphore(_render_jobs())


def log(message: str) -> None:
    print(f"[render] {message}", flush=True)


def render_video(run_dir: Path) -> Path:
    with RENDER_SEMAPHORE:
        selection = flow_profiles.current()
        log(f"flow profile {selection.requested} -> {selection.effective} ({selection.reason or selection.revision})")
        logic.set_run_field(run_dir, flow_profile=selection.record())
        logic.record_event(run_dir, "flow_profile", "selected",
                           f"{selection.requested}/{selection.effective}/{selection.revision}/{selection.reason or 'selected'}")
        return _render_video(run_dir)


def transcribe_narration(narration: Path | str) -> list[dict]:
    from src.core.ai_transcriber import transcribe_audio_in_language

    language = config.CHANNEL.language if config.CHANNEL else "en"
    return transcribe_audio_in_language(str(narration), language.split("-", 1)[0])


def _render_video(run_dir: Path) -> Path:
    from src.engine.audio_mixer import get_audio_duration
    from src.engine.classic_parallel import parallel_workers, render_parallel_video
    from src.engine.standard_backgrounds import resolve_standard_background
    from src.engine.subtitle_generator import save_ass_subtitles
    from src.engine.video_composer import render_single_pass_video

    narration = fit_narration(run_dir)
    output = run_dir / "video.mp4"
    if config.THUMBNAIL_THEME == "thumbnail":
        background = run_dir / "thumbnail.png"
        is_video = False
    else:
        background_image = (
            config.ROOT / "assets" / "backgrounds" / f"{config.THUMBNAIL_THEME}.jpg")
        background, is_video = resolve_standard_background(
            background_image, config.THUMBNAIL_THEME)
    narration_seconds = get_audio_duration(narration)
    if narration_seconds <= 0:
        raise RuntimeError("narration duration is unknown; rendering and upload were stopped")
    duration = narration_seconds + config.QUICK_OUTRO_SECONDS
    log(f"narration {narration_seconds:.1f}s, output {duration:.1f}s")
    selection = flow_profiles.current()

    def fallback(stage, reason):
        log(f"{stage}: falling back to standard ({reason})")
        logic.record_event(run_dir, "flow_profile", "fallback", f"{stage}/{reason}")

    if selection.effective == "fast":
        language = config.CHANNEL.language.split("-", 1)[0] if config.CHANNEL else "en"
        segments = flow_media.transcribe_fast(narration, language,
                                               lambda: transcribe_narration(narration), fallback)
    else:
        segments = transcribe_narration(narration)
    if not segments or not any(segment.get("text", "").strip() for segment in segments):
        raise RuntimeError("subtitle transcription produced no text; rendering and upload were stopped")
    log(f"transcribed {len(segments)} segments")
    subtitle = save_ass_subtitles(
        segments, run_dir / "narration.ass",
        font_size=round(min(config.VIDEO_WIDTH, config.VIDEO_HEIGHT) * 0.09),
        width=config.VIDEO_WIDTH, height=config.VIDEO_HEIGHT, alignment=5,
        outline_width=4, margin_horizontal=round(config.VIDEO_WIDTH * 0.10),
    )
    start = time.time()
    last = [0.0]

    def progress(pct, seconds):
        if pct - last[0] >= 5:
            last[0] = pct
            log(f"{pct:.1f}% ({seconds:.1f}s / {duration:.1f}s) elapsed {time.time()-start:.0f}s")

    parallel = parallel_workers(duration, is_video) > 1
    renderer = render_parallel_video if parallel else render_single_pass_video
    arguments = dict(
        image_path=background, narr_path=narration, bgm_path=None,
        subtitle_path=subtitle, output_path=output,
        narr_vol=config.NARRATION_VOLUME, bgm_vol=0.0,
        width=config.VIDEO_WIDTH, height=config.VIDEO_HEIGHT, fps=config.VIDEO_FPS,
        progress_callback=progress, total_duration=duration, background_is_video=is_video,
    )
    def standard(target=None):
        return renderer(**{**arguments, "output_path": output if target is None else target})
    ok = (flow_media.render_fast(arguments, standard, fallback)
          if selection.effective == "fast" else standard())
    if not ok:
        raise RuntimeError("video rendering failed")
    log(f"video saved: {output} ({output.stat().st_size} bytes)")
    return output
