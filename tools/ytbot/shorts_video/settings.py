"""Private persistent configuration for Shorts-only AI video generation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .. import config
from ..accounts_store import private_directory, read_private, write_private
from .models import VALID_VISUAL_MODES

VALID_PROVIDERS = ("google-flow", "gemini-api", "manual-import")
VALID_MODELS = ("veo-2-fast", "veo-3-fast", "veo-2-quality", "veo-3-quality")
VALID_QUALITIES = ("fast", "standard", "quality")

DEFAULT_MODEL_COSTS: dict[str, float] = {
    "veo-2-fast": 10.0,
    "veo-3-fast": 20.0,
    "veo-2-quality": 50.0,
    "veo-3-quality": 100.0,
}

QUALITY_DEFAULT_MODELS: dict[str, str] = {
    "fast": "veo-2-fast",
    "standard": "veo-3-fast",
    "quality": "veo-2-quality",
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "schema": 1,
    "enabled": False,
    "visual_mode": "static",
    "provider": "google-flow",
    "model": "veo-2-fast",
    "quality": "fast",
    "max_credits_per_short": 40.0,
    "max_credits_per_batch": 200.0,
    "max_scenes_per_short": 6,
    "fallback_to_static": True,
    "allow_paid_api": False,
    "allow_documentary_illustrative": False,
    "synthetic_disclosure": True,
    "model_costs": dict(DEFAULT_MODEL_COSTS),
}


def settings_path() -> Path:
    return config.ROOT / ".local" / "ytbot-media" / "shorts-video-settings.json"


def _validate_settings(candidate: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_SETTINGS)
    merged.update(candidate)
    if merged["visual_mode"] not in VALID_VISUAL_MODES:
        raise ValueError(f"unsupported visual_mode: {merged['visual_mode']!r}")
    if merged["provider"] not in VALID_PROVIDERS:
        raise ValueError(f"unsupported video provider: {merged['provider']!r}")
    if merged["model"] not in VALID_MODELS:
        raise ValueError(f"unsupported video model: {merged['model']!r}")
    if merged["quality"] not in VALID_QUALITIES:
        raise ValueError(f"unsupported generation quality: {merged['quality']!r}")

    merged["enabled"] = bool(merged["enabled"])
    merged["fallback_to_static"] = bool(merged["fallback_to_static"])
    merged["allow_paid_api"] = bool(merged["allow_paid_api"])
    merged["allow_documentary_illustrative"] = bool(merged["allow_documentary_illustrative"])
    merged["synthetic_disclosure"] = bool(merged["synthetic_disclosure"])

    merged["max_credits_per_short"] = max(0.0, float(merged["max_credits_per_short"]))
    merged["max_credits_per_batch"] = max(0.0, float(merged["max_credits_per_batch"]))
    scenes_limit = int(merged["max_scenes_per_short"])
    if not 1 <= scenes_limit <= 12:
        raise ValueError("max_scenes_per_short must be between 1 and 12")
    merged["max_scenes_per_short"] = scenes_limit

    costs = dict(DEFAULT_MODEL_COSTS)
    raw_costs = merged.get("model_costs")
    if isinstance(raw_costs, dict):
        for model_name in VALID_MODELS:
            if model_name in raw_costs:
                costs[model_name] = max(0.0, float(raw_costs[model_name]))
    merged["model_costs"] = costs
    return merged


def load_settings() -> dict[str, Any]:
    stored = read_private(settings_path(), {}) or {}
    return _validate_settings(stored)


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    current.update({key: value for key, value in updates.items() if value is not None})
    validated = _validate_settings(current)
    private_directory(settings_path().parent)
    write_private(settings_path(), validated)
    return validated


def select_lowest_cost_model(quality: str, settings: dict[str, Any]) -> str:
    """Pick the cheapest model meeting the requested quality tier."""
    if quality == "quality":
        candidates = ("veo-2-quality", "veo-3-quality")
    elif quality == "standard":
        candidates = ("veo-3-fast", "veo-2-quality")
    else:
        candidates = ("veo-2-fast", "veo-3-fast")
    costs = settings.get("model_costs", DEFAULT_MODEL_COSTS)
    return min(candidates, key=lambda name: float(costs.get(name, DEFAULT_MODEL_COSTS[name])))


def resolve_runtime_settings(
    *,
    visual_mode: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    quality: str | None = None,
    max_credits_per_short: float | None = None,
    max_credits_per_batch: float | None = None,
    max_scenes_per_short: int | None = None,
    fallback_to_static: bool | None = None,
    allow_paid_api: bool | None = None,
    allow_documentary_illustrative: bool | None = None,
) -> dict[str, Any]:
    """Combine persisted settings with explicit per-run overrides safely."""
    resolved = load_settings()
    if visual_mode is not None:
        resolved["visual_mode"] = visual_mode
    elif resolved["enabled"]:
        resolved["visual_mode"] = "ai-video"
    else:
        resolved["visual_mode"] = "static"

    if provider is not None:
        resolved["provider"] = provider
    if quality is not None:
        resolved["quality"] = quality
        if model is None:
            resolved["model"] = select_lowest_cost_model(quality, resolved)
    if model is not None:
        resolved["model"] = model
    if max_credits_per_short is not None:
        resolved["max_credits_per_short"] = max_credits_per_short
    if max_credits_per_batch is not None:
        resolved["max_credits_per_batch"] = max_credits_per_batch
    if max_scenes_per_short is not None:
        resolved["max_scenes_per_short"] = max_scenes_per_short
    if fallback_to_static is not None:
        resolved["fallback_to_static"] = fallback_to_static
    if allow_paid_api is not None:
        resolved["allow_paid_api"] = allow_paid_api
    if allow_documentary_illustrative is not None:
        resolved["allow_documentary_illustrative"] = allow_documentary_illustrative

    return _validate_settings(resolved)
