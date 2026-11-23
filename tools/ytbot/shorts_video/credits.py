"""Credit estimation, budget enforcement and durable attempt ledger for Shorts video clips."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import config
from ..accounts_store import private_directory, read_private, write_private
from .settings import DEFAULT_MODEL_COSTS, load_settings


def ledger_path() -> Path:
    return config.ROOT / ".local" / "ytbot-media" / "shorts-credits-ledger.json"


def _empty_ledger() -> dict[str, Any]:
    return {
        "schema": 1,
        "batch_credits_used": 0.0,
        "total_credits_used": 0.0,
        "total_attempts": 0,
        "successful_clips": 0,
        "failed_clips": 0,
        "by_provider": {},
        "recent_events": [],
    }


def load_ledger() -> dict[str, Any]:
    data = read_private(ledger_path(), _empty_ledger())
    if not isinstance(data, dict) or data.get("schema") != 1:
        return _empty_ledger()
    return data


def _save_ledger(ledger: dict[str, Any]) -> None:
    private_directory(ledger_path().parent)
    write_private(ledger_path(), ledger)


def reset_batch_counter() -> dict[str, Any]:
    ledger = load_ledger()
    ledger["batch_credits_used"] = 0.0
    _save_ledger(ledger)
    return ledger


def estimate_scene_cost(
    provider: str,
    model: str,
    settings: dict[str, Any] | None = None,
) -> float:
    if provider == "manual-import":
        return 0.0
    active = settings or load_settings()
    costs = active.get("model_costs", DEFAULT_MODEL_COSTS)
    return float(costs.get(model, DEFAULT_MODEL_COSTS.get(model, 20.0)))


def estimate_short_cost(
    scene_count: int,
    provider: str,
    model: str,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active = settings or load_settings()
    per_scene = estimate_scene_cost(provider, model, active)
    total = round(max(0, int(scene_count)) * per_scene, 2)
    ledger = load_ledger()
    batch_used = float(ledger.get("batch_credits_used", 0.0))
    within_short, short_reason = check_budget(total, short_spent=0.0, batch_spent=batch_used, settings=active)
    return {
        "provider": provider,
        "model": model,
        "scene_count": max(0, int(scene_count)),
        "credits_per_scene": per_scene,
        "estimated_total_credits": total,
        "max_credits_per_short": float(active.get("max_credits_per_short", 40.0)),
        "max_credits_per_batch": float(active.get("max_credits_per_batch", 200.0)),
        "batch_credits_used": batch_used,
        "within_budget": within_short,
        "budget_reason": short_reason,
        "paid_api_enabled": bool(active.get("allow_paid_api", False)),
    }


def check_budget(
    estimated_cost: float,
    *,
    short_spent: float = 0.0,
    batch_spent: float | None = None,
    settings: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    active = settings or load_settings()
    max_short = float(active.get("max_credits_per_short", 40.0))
    max_batch = float(active.get("max_credits_per_batch", 200.0))
    current_batch = float(load_ledger().get("batch_credits_used", 0.0)) if batch_spent is None else float(batch_spent)

    if short_spent + estimated_cost > max_short + 1e-9:
        return False, (
            f"short credit budget reached ({short_spent + estimated_cost:.1f} > {max_short:.1f})"
        )
    if current_batch + estimated_cost > max_batch + 1e-9:
        return False, (
            f"batch credit budget reached ({current_batch + estimated_cost:.1f} > {max_batch:.1f})"
        )
    return True, "ok"


def record_attempt(
    run_dir: Path,
    scene_id: str,
    provider: str,
    model: str,
    estimated_credits: float,
) -> dict[str, Any]:
    ledger = load_ledger()
    ledger["total_attempts"] = int(ledger.get("total_attempts", 0)) + 1
    by_provider = ledger.setdefault("by_provider", {})
    stats = by_provider.setdefault(provider, {
        "attempts": 0,
        "successful_clips": 0,
        "failed_clips": 0,
        "credits_used": 0.0,
    })
    stats["attempts"] = int(stats.get("attempts", 0)) + 1
    event = {
        "at": int(time.time()),
        "type": "attempt",
        "run": run_dir.name,
        "scene_id": scene_id,
        "provider": provider,
        "model": model,
        "estimated_credits": float(estimated_credits),
    }
    ledger["recent_events"] = (ledger.get("recent_events", []) + [event])[-50:]
    _save_ledger(ledger)
    return ledger


def record_outcome(
    run_dir: Path,
    scene_id: str,
    provider: str,
    model: str,
    *,
    success: bool,
    actual_credits: float = 0.0,
    detail: str = "",
) -> dict[str, Any]:
    ledger = load_ledger()
    credits = max(0.0, float(actual_credits))
    ledger["batch_credits_used"] = round(float(ledger.get("batch_credits_used", 0.0)) + credits, 3)
    ledger["total_credits_used"] = round(float(ledger.get("total_credits_used", 0.0)) + credits, 3)
    key = "successful_clips" if success else "failed_clips"
    ledger[key] = int(ledger.get(key, 0)) + 1

    by_provider = ledger.setdefault("by_provider", {})
    stats = by_provider.setdefault(provider, {
        "attempts": 0,
        "successful_clips": 0,
        "failed_clips": 0,
        "credits_used": 0.0,
    })
    stats[key] = int(stats.get(key, 0)) + 1
    stats["credits_used"] = round(float(stats.get("credits_used", 0.0)) + credits, 3)

    event = {
        "at": int(time.time()),
        "type": "success" if success else "failure",
        "run": run_dir.name,
        "scene_id": scene_id,
        "provider": provider,
        "model": model,
        "actual_credits": credits,
        "detail": str(detail)[:240],
    }
    ledger["recent_events"] = (ledger.get("recent_events", []) + [event])[-50:]
    _save_ledger(ledger)
    return ledger


def ledger_summary() -> dict[str, Any]:
    ledger = load_ledger()
    active = load_settings()
    return {
        "batch_credits_used": float(ledger.get("batch_credits_used", 0.0)),
        "total_credits_used": float(ledger.get("total_credits_used", 0.0)),
        "total_attempts": int(ledger.get("total_attempts", 0)),
        "successful_clips": int(ledger.get("successful_clips", 0)),
        "failed_clips": int(ledger.get("failed_clips", 0)),
        "max_credits_per_short": float(active["max_credits_per_short"]),
        "max_credits_per_batch": float(active["max_credits_per_batch"]),
        "by_provider": ledger.get("by_provider", {}),
    }
