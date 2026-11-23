"""Bounded ZaturoBot service operations for Shorts-only AI video generation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .. import channels, config, logic, shorts_distribute
from . import credits, flow_browser
from .models import assert_channel_policy, assert_shorts_scope
from .pipeline import render_ai_short
from .providers import get_provider
from .settings import VALID_PROVIDERS, load_settings, resolve_runtime_settings
from .storyboard import load_storyboard
from .validator import validate_clip

SAFE_RUN_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,120}\Z")


def redact_paths(text: str) -> str:
    """Strip host filesystem paths from public service messages."""
    clean = re.sub(r"/(?:[^\s'\":,)]+/)*([^\s'\":,)]+)", r"\1", str(text or ""))
    return clean[:300]


def validate_run_id(run_id: str) -> str:
    if not SAFE_RUN_ID.fullmatch(run_id or ""):
        raise ValueError("run_id must be a safe lowercase slug")
    return run_id


def short_run_dir(channel_slug: str, run_id: str) -> Path:
    channels.get(channel_slug)
    validate_run_id(run_id)
    return shorts_distribute.shorts_root(channel_slug) / run_id


def providers_status() -> dict[str, Any]:
    active = load_settings()
    flow = flow_browser.check_flow_readiness(probe_browser=False)
    providers = {}
    for name in VALID_PROVIDERS:
        info = get_provider(name).check_availability(active)
        providers[name] = {
            "available": bool(info.get("available")),
            "paid_api": bool(info.get("paid_api")),
            "state": str(info.get("state", "unknown")),
            "credits_reported": info.get("credits_reported"),
            "detail": redact_paths(str(info.get("detail", ""))),
        }
    return {
        "schema_version": 1,
        "enabled": bool(active["enabled"]),
        "default_provider": active["provider"],
        "default_model": active["model"],
        "providers": providers,
        "flow_readiness": {
            "configured": bool(flow["configured"]),
            "state": str(flow["state"]),
            "credits_reported": flow.get("credits_reported"),
            "browser_running": bool(flow["browser_running"]),
            "verified_at": str(flow.get("verified_at", "")),
            "detail": redact_paths(str(flow.get("detail", ""))),
        },
        "credits": credits.ledger_summary(),
    }


def estimate_shorts(
    channel_slug: str,
    count: int,
    *,
    visual_mode: str = "ai-video",
    video_provider: str | None = None,
    video_model: str | None = None,
    max_credits: float | None = None,
    max_scenes: int | None = None,
) -> dict[str, Any]:
    if not 1 <= count <= 10:
        raise ValueError("count must be 1..10")
    channels.get(channel_slug)
    resolved = resolve_runtime_settings(
        visual_mode=visual_mode,
        provider=video_provider,
        model=video_model,
        max_credits_per_short=max_credits,
        max_scenes_per_short=max_scenes,
    )
    assert_shorts_scope("shorts", width=1080, height=1920, visual_mode=resolved["visual_mode"])
    if resolved["visual_mode"] == "ai-video":
        assert_channel_policy(channel_slug, resolved)
    scene_count = min(int(resolved["max_scenes_per_short"]), 6)
    per_short = credits.estimate_short_cost(
        scene_count, resolved["provider"], resolved["model"], resolved
    )
    total_estimated = round(per_short["estimated_total_credits"] * count, 2)
    batch_ok, batch_reason = credits.check_budget(total_estimated, settings=resolved)
    return {
        "schema_version": 1,
        "channel": channel_slug,
        "count": count,
        "visual_mode": resolved["visual_mode"],
        "provider": resolved["provider"],
        "model": resolved["model"],
        "scenes_per_short": scene_count if resolved["visual_mode"] == "ai-video" else 0,
        "estimated_credits_per_short": (
            per_short["estimated_total_credits"] if resolved["visual_mode"] == "ai-video" else 0.0
        ),
        "estimated_total_credits": (
            total_estimated if resolved["visual_mode"] == "ai-video" else 0.0
        ),
        "within_batch_budget": True if resolved["visual_mode"] == "static" else batch_ok,
        "budget_reason": "static mode uses 0 credits" if resolved["visual_mode"] == "static" else batch_reason,
        "paid_api_enabled": bool(resolved["allow_paid_api"]),
    }


def inspect_short_run(channel_slug: str, run_id: str) -> dict[str, Any]:
    run_dir = short_run_dir(channel_slug, run_id)
    if not run_dir.is_dir() or run_dir.is_symlink():
        return {
            "schema_version": 1,
            "channel": channel_slug,
            "run_id": run_id,
            "exists": False,
            "status": "not_found",
        }

    storyboard = load_storyboard(run_dir)
    meta_path = run_dir / "metadata.json"
    meta = {}
    if meta_path.is_file() and not meta_path.is_symlink():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}

    video_path = run_dir / "video.mp4"
    video_ready = False
    video_duration = 0.0
    if video_path.is_file() and not video_path.is_symlink():
        check = validate_clip(video_path, require_portrait=True, min_duration=1.0)
        video_ready = check.valid
        video_duration = check.duration_sec

    scenes = []
    failed_scenes = []
    if storyboard is not None:
        for scene in storyboard.scenes:
            entry = {
                "scene_id": scene.scene_id,
                "scene_index": scene.scene_index,
                "status": scene.status,
                "provider": scene.provider,
                "model": scene.model,
                "estimated_credits": scene.estimated_credits,
                "actual_credits": scene.actual_credits,
                "attempts": scene.attempts,
                "error": redact_paths(scene.error),
            }
            scenes.append(entry)
            if scene.status in ("failed", "uncertain", "skipped_budget"):
                failed_scenes.append(entry)

    return {
        "schema_version": 1,
        "channel": channel_slug,
        "run_id": run_id,
        "exists": True,
        "title": str(meta.get("title", storyboard.topic if storyboard else ""))[:200],
        "status": storyboard.status if storyboard else ("completed" if video_ready else "unknown"),
        "visual_mode": storyboard.visual_mode if storyboard else str(meta.get("visual_mode", "static")),
        "provider": storyboard.provider if storyboard else str(meta.get("video_provider", "")),
        "model": storyboard.model if storyboard else str(meta.get("video_model", "")),
        "fallback_used": bool(storyboard.fallback_used) if storyboard else False,
        "estimated_credits": storyboard.estimated_total_credits if storyboard else 0.0,
        "actual_credits": storyboard.actual_total_credits if storyboard else 0.0,
        "synthetic_media_disclosure": bool(
            meta.get(
                "synthetic_media_disclosure",
                storyboard.synthetic_disclosure_required if storyboard else False,
            )
        ),
        "video_ready": video_ready,
        "video_file": "video.mp4" if video_ready else "",
        "video_duration_sec": video_duration,
        "scenes": scenes,
        "failed_scenes": failed_scenes,
    }


def resume_short_run(channel_slug: str, run_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resume an existing interrupted Short run directory without uploading."""
    channels.apply(channel_slug)
    run_dir = short_run_dir(channel_slug, run_id)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Short run directory does not exist: {run_id}")

    topic_path = run_dir / "topic.txt"
    short_path = run_dir / "short.txt"
    topic = topic_path.read_text(encoding="utf-8").strip() if topic_path.is_file() else run_id
    script_text = short_path.read_text(encoding="utf-8").strip() if short_path.is_file() else topic
    opts = options or {}

    from .. import faith_shorts, shorts as legacy_shorts

    fallback_fn = legacy_shorts.render_short if channel_slug == "zaflas" else faith_shorts.render_short
    result = render_ai_short(
        run_dir,
        channel_slug,
        topic,
        script_text,
        visual_mode=opts.get("visual_mode") or "ai-video",
        video_provider=opts.get("video_provider"),
        video_model=opts.get("video_model"),
        max_credits_per_short=opts.get("max_credits"),
        max_scenes=opts.get("max_scenes"),
        fallback_to_static=opts.get("fallback_to_static"),
        static_fallback_fn=fallback_fn,
    )
    meta_fn = legacy_shorts.short_metadata if channel_slug == "zaflas" else faith_shorts.metadata
    meta = meta_fn(topic, script_text)
    if result.get("visual_mode") == "ai-video":
        meta["visual_mode"] = "ai-video"
        meta["video_provider"] = result.get("provider", "")
        meta["video_model"] = result.get("model", "")
        meta["synthetic_media_disclosure"] = bool(result.get("synthetic_disclosure_required", True))
    (run_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "id": run_dir.name,
        "title": meta.get("title", topic)[:200],
        "topic": topic[:240],
        "state": "ready" if (run_dir / "video.mp4").is_file() else "failed",
        "slot": "",
        "video_id": "",
        "artifacts": [
            name
            for name in ("thumbnail.png", "video.mp4", "narration.aac", "metadata.json", "storyboard.json")
            if (run_dir / name).is_file()
        ],
    }


def generate_shorts_batch(
    channel_slug: str,
    count: int,
    context,
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate 1..10 Shorts without uploading or scheduling."""
    from .. import assets, chat, faith_shorts, shorts as legacy_shorts

    if not 1 <= count <= 10:
        raise ValueError("Shorts count must be 1..10")
    channels.apply(channel_slug)
    opts = options or {}
    visual_mode = str(opts.get("visual_mode") or "ai-video")
    resolved = resolve_runtime_settings(
        visual_mode=visual_mode,
        provider=opts.get("video_provider"),
        model=opts.get("video_model"),
        max_credits_per_short=opts.get("max_credits"),
        max_scenes_per_short=opts.get("max_scenes"),
        fallback_to_static=opts.get("fallback_to_static"),
    )
    assert_shorts_scope("shorts", width=1080, height=1920, visual_mode=resolved["visual_mode"])
    if resolved["visual_mode"] == "ai-video":
        assert_channel_policy(channel_slug, resolved)

    root = shorts_distribute.shorts_root(channel_slug)
    root.mkdir(parents=True, exist_ok=True)
    spec = faith_shorts.CHANNELS.get(channel_slug, {})
    topic_pool = list(spec.get("topics") or legacy_shorts.SHORT_TOPICS)
    topics = []
    for candidate in topic_pool:
        run_dir = root / logic.slug(candidate)
        if (run_dir / "upload.json").is_file() or (run_dir / "video.mp4").is_file():
            continue
        topics.append(candidate)
        if len(topics) == count:
            break
    if len(topics) < count:
        raise RuntimeError(f"only {len(topics)} unused Short topics left for {channel_slug}")

    results: list[dict[str, Any]] = []
    fallback_fn = legacy_shorts.render_short if channel_slug == "zaflas" else faith_shorts.render_short
    meta_fn = legacy_shorts.short_metadata if channel_slug == "zaflas" else faith_shorts.metadata

    for topic in topics:
        run_dir = root / logic.slug(topic)
        run_dir.mkdir(parents=True, exist_ok=True)
        run_dir.chmod(0o700)
        (run_dir / "topic.txt").write_text(topic, encoding="utf-8")
        logic.set_run_field(run_dir, topic=topic)
        page = context.new_page()
        try:
            if channel_slug == "zaflas":
                text = chat.generate_short(page, topic, run_dir)
            else:
                text = faith_shorts.generate_script(page, topic, run_dir)
            chat.capture_audio(page, context, run_dir)
        finally:
            page.close()

        thumb_style = "shorts" if channel_slug == "zaflas" else "short-background"
        if not (run_dir / "thumbnail.png").is_file():
            assets.generate_thumbnail(context, run_dir, thumb_style)

        if resolved["visual_mode"] == "ai-video":
            ai_res = render_ai_short(
                run_dir,
                channel_slug,
                topic,
                text,
                visual_mode="ai-video",
                video_provider=resolved["provider"],
                video_model=resolved["model"],
                max_credits_per_short=resolved["max_credits_per_short"],
                max_scenes=resolved["max_scenes_per_short"],
                fallback_to_static=resolved["fallback_to_static"],
                static_fallback_fn=fallback_fn,
            )
        else:
            fallback_fn(run_dir)
            ai_res = {"visual_mode": "static"}

        meta = meta_fn(topic, text) if channel_slug == "zaflas" else faith_shorts.metadata(topic, text, spec)
        if ai_res.get("visual_mode") == "ai-video":
            meta["visual_mode"] = "ai-video"
            meta["video_provider"] = ai_res.get("provider", "")
            meta["video_model"] = ai_res.get("model", "")
            meta["synthetic_media_disclosure"] = bool(ai_res.get("synthetic_disclosure_required", True))
        (run_dir / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logic.record_event(run_dir, "ready", "ok")
        results.append({
            "id": run_dir.name,
            "title": meta["title"][:200],
            "topic": topic[:240],
            "state": "ready" if (run_dir / "video.mp4").is_file() else "failed",
            "slot": "",
            "video_id": "",
            "artifacts": [
                name
                for name in ("thumbnail.png", "video.mp4", "narration.aac", "metadata.json", "storyboard.json")
                if (run_dir / name).is_file()
            ],
        })
    return results
