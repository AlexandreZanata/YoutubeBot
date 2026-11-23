"""Resumable Shorts-only AI video clip generation and assembly orchestration."""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from pathlib import Path
from typing import Any, Callable

from .. import config, logic, render
from ..accounts_store import private_directory, read_private, write_private
from . import credits
from .assembler import assemble_short_video
from .models import (
    CreditBudgetExceededError,
    ProviderAuthRequiredError,
    ProviderUnavailableError,
    SceneSpec,
    Storyboard,
    assert_channel_policy,
    assert_shorts_scope,
)
from .providers import VideoGenerationProvider, get_provider
from .settings import resolve_runtime_settings
from .storyboard import load_storyboard, plan_short_storyboard, save_storyboard
from .validator import validate_clip


def log(message: str) -> None:
    print(f"[shorts-video] {message}", flush=True)


@contextlib.contextmanager
def _file_lock(lock_path: Path):
    private_directory(lock_path.parent)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                f"another worker is already processing {lock_path.stem}"
            ) from None
        yield
    finally:
        os.close(fd)


def _scene_state_path(run_dir: Path, scene_id: str) -> Path:
    return run_dir / "scenes" / f"{scene_id}.json"


def _save_scene_state(run_dir: Path, scene: SceneSpec) -> None:
    private_directory(run_dir / "scenes")
    write_private(_scene_state_path(run_dir, scene.scene_id), scene.to_dict())


def _merge_scene_states(run_dir: Path, storyboard: Storyboard) -> None:
    for idx, scene in enumerate(storyboard.scenes):
        stored = read_private(_scene_state_path(run_dir, scene.scene_id))
        if isinstance(stored, dict):
            storyboard.scenes[idx] = SceneSpec.from_dict(stored)


def _notify(callback: Callable[[str, str], None] | None, state: str, detail: str) -> None:
    if callback is not None:
        callback(state, detail)


def render_ai_short(
    run_dir: Path,
    channel_slug: str,
    topic: str,
    script_text: str,
    *,
    visual_mode: str | None = None,
    video_provider: str | None = None,
    video_model: str | None = None,
    quality: str | None = None,
    max_credits_per_short: float | None = None,
    max_credits_per_batch: float | None = None,
    max_scenes: int | None = None,
    fallback_to_static: bool | None = None,
    allow_paid_api: bool | None = None,
    allow_documentary_illustrative: bool | None = None,
    dry_run: bool = False,
    provider_instance: VideoGenerationProvider | None = None,
    static_fallback_fn: Callable[[Path], Path] | None = None,
    progress_callback: Callable[[str, str], None] | None = None,
    transcript_segments: list[dict[str, Any]] | None = None,
    narration_duration_sec: float | None = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Plan, generate/import, validate and assemble a 9:16 AI video Short.

    Never valid for long-form videos. Preserves untouched narration audio and
    burned-in subtitles, and falls back gracefully when allowed.
    """
    settings = resolve_runtime_settings(
        visual_mode=visual_mode or "ai-video",
        provider=video_provider,
        model=video_model,
        quality=quality,
        max_credits_per_short=max_credits_per_short,
        max_credits_per_batch=max_credits_per_batch,
        max_scenes_per_short=max_scenes,
        fallback_to_static=fallback_to_static,
        allow_paid_api=allow_paid_api,
        allow_documentary_illustrative=allow_documentary_illustrative,
    )
    settings["channel"] = channel_slug
    assert_shorts_scope("shorts", width=1080, height=1920, visual_mode=settings["visual_mode"])
    assert_channel_policy(channel_slug, settings)

    run_dir.mkdir(parents=True, exist_ok=True)
    if not run_dir.is_symlink():
        run_dir.chmod(0o700)
    if settings["visual_mode"] == "static":
        if static_fallback_fn is None:
            raise RuntimeError("static fallback renderer was not supplied")
        output = static_fallback_fn(run_dir)
        return {
            "status": "completed",
            "visual_mode": "static",
            "fallback_used": False,
            "video_path": str(output),
            "credits_used": 0.0,
        }

    narration = run_dir / "narration.aac"
    segments = transcript_segments
    duration = float(narration_duration_sec or 0.0)

    if not dry_run:
        if not narration.is_file():
            raise FileNotFoundError(f"Short narration audio missing: {narration}")
        if duration <= 0:
            from src.engine.audio_mixer import get_audio_duration

            duration = get_audio_duration(narration)
        if duration <= 0:
            raise RuntimeError("Short narration duration is unknown")
        if segments is None:
            segments = render.transcribe_narration(narration)
        if not segments:
            raise RuntimeError("Short subtitle transcription produced no text")
    elif duration <= 0:
        words = max(30, len((script_text or "").split()))
        duration = round(max(20.0, min(55.0, words / 2.4)), 2)

    provider = provider_instance or get_provider(settings["provider"])

    with _file_lock(run_dir / ".shorts-video.lock"):
        _notify(progress_callback, "Preparing storyboard", f"Planning scenes for {topic}")
        existing = load_storyboard(run_dir)
        if (
            existing is not None
            and existing.channel == channel_slug
            and existing.topic == topic
            and existing.provider == provider.name
            and existing.model == settings["model"]
            and existing.scenes
        ):
            storyboard = existing
            _merge_scene_states(run_dir, storyboard)
        else:
            storyboard = plan_short_storyboard(
                channel_slug,
                topic,
                script_text,
                total_duration_sec=duration,
                transcript_segments=segments,
                settings=settings,
            )
            save_storyboard(run_dir, storyboard)
            for scene in storyboard.scenes:
                _save_scene_state(run_dir, scene)

        estimate = credits.estimate_short_cost(
            len(storyboard.scenes), provider.name, storyboard.model, settings
        )
        if dry_run:
            storyboard.status = "dry_run"
            save_storyboard(run_dir, storyboard)
            _notify(progress_callback, "Completed", "Dry-run storyboard & estimate ready")
            return {
                "status": "dry_run",
                "visual_mode": "ai-video",
                "provider": provider.name,
                "model": storyboard.model,
                "scene_count": len(storyboard.scenes),
                "estimated_credits": estimate["estimated_total_credits"],
                "within_budget": estimate["within_budget"],
                "budget_reason": estimate["budget_reason"],
                "storyboard_path": str(run_dir / "storyboard.json"),
                "prompts_path": str(run_dir / "flow-prompts.md"),
            }

        if provider.is_paid_api() and not settings["allow_paid_api"]:
            storyboard.status = "failed"
            storyboard.error = "Paid Gemini Video API is disabled by default."
            save_storyboard(run_dir, storyboard)
            raise ProviderUnavailableError(storyboard.error)

        short_spent = sum(float(scene.actual_credits or 0.0) for scene in storyboard.scenes)
        auth_error: ProviderAuthRequiredError | None = None
        budget_exhausted = False

        for scene in storyboard.scenes:
            with _file_lock(run_dir / "scenes" / f"{scene.scene_id}.lock"):
                if scene.status == "validated" and scene.output_path:
                    check = validate_clip(Path(scene.output_path))
                    if check.valid:
                        scene.validation = check.to_dict()
                        _save_scene_state(run_dir, scene)
                        continue

                if scene.status in ("generating", "uncertain"):
                    _notify(
                        progress_callback,
                        "Downloading or importing",
                        f"Reconciling {scene.scene_id}",
                    )
                    reconciled = provider.reconcile_scene(scene, run_dir, settings)
                    if reconciled is not None:
                        check = validate_clip(reconciled)
                        if check.valid:
                            scene.status = "validated"
                            scene.output_path = str(reconciled)
                            scene.validation = check.to_dict()
                            scene.error = ""
                            _save_scene_state(run_dir, scene)
                            continue

                allowed, reason = credits.check_budget(
                    scene.estimated_credits, short_spent=short_spent, settings=settings
                )
                if not allowed:
                    budget_exhausted = True
                    scene.status = "skipped_budget"
                    scene.error = reason
                    _save_scene_state(run_dir, scene)
                    _notify(progress_callback, "Credit limit reached", reason)
                    continue

                if budget_exhausted:
                    scene.status = "skipped_budget"
                    scene.error = "Stopped after budget limit reached"
                    _save_scene_state(run_dir, scene)
                    continue

                for attempt in range(max_retries + 1):
                    scene.attempts += 1
                    scene.status = "generating"
                    _save_scene_state(run_dir, scene)
                    _notify(
                        progress_callback,
                        "Generating",
                        f"{scene.scene_id} ({provider.name}/{scene.model}, attempt {attempt + 1})",
                    )
                    credits.record_attempt(
                        run_dir, scene.scene_id, provider.name, scene.model, scene.estimated_credits
                    )
                    try:
                        clip_path, charged = provider.generate_scene(scene, run_dir, settings)
                        _notify(progress_callback, "Validating", f"Validating {scene.scene_id}")
                        check = validate_clip(clip_path)
                        if not check.valid:
                            raise ProviderUnavailableError(
                                f"Generated clip failed validation: {check.reason}"
                            )
                        short_spent = round(short_spent + float(charged), 3)
                        scene.actual_credits = round(float(scene.actual_credits) + float(charged), 3)
                        scene.output_path = str(clip_path)
                        scene.validation = check.to_dict()
                        scene.status = "validated"
                        scene.error = ""
                        credits.record_outcome(
                            run_dir,
                            scene.scene_id,
                            provider.name,
                            scene.model,
                            success=True,
                            actual_credits=charged,
                        )
                        _save_scene_state(run_dir, scene)
                        break
                    except ProviderAuthRequiredError as error:
                        scene.status = "failed"
                        scene.error = str(error)
                        credits.record_outcome(
                            run_dir,
                            scene.scene_id,
                            provider.name,
                            scene.model,
                            success=False,
                            detail="auth_required",
                        )
                        _save_scene_state(run_dir, scene)
                        auth_error = error
                        _notify(progress_callback, "Needs login", str(error))
                        break
                    except TimeoutError as error:
                        scene.status = "uncertain"
                        scene.error = str(error)
                        _save_scene_state(run_dir, scene)
                        reconciled = provider.reconcile_scene(scene, run_dir, settings)
                        if reconciled is not None and validate_clip(reconciled).valid:
                            scene.status = "validated"
                            scene.output_path = str(reconciled)
                            scene.validation = validate_clip(reconciled).to_dict()
                            scene.error = ""
                            _save_scene_state(run_dir, scene)
                            break
                        if attempt >= max_retries:
                            credits.record_outcome(
                                run_dir,
                                scene.scene_id,
                                provider.name,
                                scene.model,
                                success=False,
                                detail="timeout_uncertain",
                            )
                        else:
                            time.sleep(min(2.0, 0.25 * (2**attempt)))
                    except Exception as error:
                        scene.status = "failed"
                        scene.error = str(error)
                        _save_scene_state(run_dir, scene)
                        if attempt >= max_retries:
                            credits.record_outcome(
                                run_dir,
                                scene.scene_id,
                                provider.name,
                                scene.model,
                                success=False,
                                detail=str(error)[:120],
                            )
                        else:
                            time.sleep(min(2.0, 0.25 * (2**attempt)))
            if auth_error is not None:
                break

        storyboard.actual_total_credits = round(short_spent, 3)

        if auth_error is not None:
            storyboard.status = "needs_login"
            storyboard.error = str(auth_error)
            save_storyboard(run_dir, storyboard)
            logic.record_event(run_dir, "shorts_ai_video", "needs_login", str(auth_error))
            raise auth_error

        validated_count = sum(1 for scene in storyboard.scenes if scene.status == "validated")
        missing_count = len(storyboard.scenes) - validated_count

        if validated_count == 0:
            if settings["fallback_to_static"] and static_fallback_fn is not None:
                _notify(
                    progress_callback,
                    "Rendering",
                    "No AI clips available; falling back to still-image Short render",
                )
                storyboard.fallback_used = True
                storyboard.status = "fallback_static"
                for scene in storyboard.scenes:
                    if scene.status != "validated":
                        scene.status = "fallback_static"
                        _save_scene_state(run_dir, scene)
                save_storyboard(run_dir, storyboard)
                output = static_fallback_fn(run_dir)
                logic.record_event(run_dir, "shorts_ai_video", "fallback_static", "0 AI clips; used static render")
                _notify(progress_callback, "Completed", "Rendered via static image fallback")
                return {
                    "status": "completed",
                    "visual_mode": "static",
                    "fallback_used": True,
                    "budget_exhausted": budget_exhausted,
                    "validated_scenes": 0,
                    "total_scenes": len(storyboard.scenes),
                    "credits_used": storyboard.actual_total_credits,
                    "video_path": str(output),
                }
            if budget_exhausted:
                storyboard.status = "credit_limit_reached"
                save_storyboard(run_dir, storyboard)
                raise CreditBudgetExceededError("Credit budget reached and static fallback is disabled.")
            storyboard.status = "failed"
            save_storyboard(run_dir, storyboard)
            _notify(progress_callback, "Failed", "All scene generations failed")
            raise ProviderUnavailableError("No valid AI clips were generated and static fallback is disabled.")

        if missing_count > 0:
            if not settings["fallback_to_static"]:
                storyboard.status = "failed"
                save_storyboard(run_dir, storyboard)
                raise ProviderUnavailableError(
                    f"{missing_count} scene(s) incomplete and static fallback is disabled."
                )
            storyboard.fallback_used = True
            for scene in storyboard.scenes:
                if scene.status != "validated":
                    scene.status = "fallback_static"
                    _save_scene_state(run_dir, scene)

        _notify(progress_callback, "Rendering", "Assembling clips, narration and burned-in subtitles")
        from src.engine.subtitle_generator import save_ass_subtitles

        subtitle = save_ass_subtitles(
            segments,
            run_dir / "narration.ass",
            font_size=72,
            width=1080,
            height=1920,
            alignment=5,
            outline_width=5,
            margin_horizontal=72,
        )
        output = assemble_short_video(
            run_dir,
            storyboard,
            narration_path=narration,
            subtitle_path=subtitle,
            narr_vol=config.NARRATION_VOLUME,
        )
        storyboard.status = "completed"
        storyboard.error = ""
        save_storyboard(run_dir, storyboard)
        logic.record_event(
            run_dir,
            "shorts_ai_video",
            "ok",
            f"provider={provider.name} model={storyboard.model} ai_clips={validated_count}/{len(storyboard.scenes)}",
        )
        _notify(progress_callback, "Completed", f"Short ready: {output.name}")
        return {
            "status": "completed",
            "visual_mode": "ai-video",
            "provider": provider.name,
            "model": storyboard.model,
            "fallback_used": storyboard.fallback_used,
            "budget_exhausted": budget_exhausted,
            "validated_scenes": validated_count,
            "total_scenes": len(storyboard.scenes),
            "credits_used": storyboard.actual_total_credits,
            "video_path": str(output),
            "synthetic_disclosure_required": storyboard.synthetic_disclosure_required,
        }
