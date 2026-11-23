"""Data models, exceptions and non-negotiable Shorts-only scope guards."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .. import channels

SHORTS_CONTEXTS = frozenset({
    "shorts",
    "faith-shorts",
    "shorts-video",
    "shorts_generate",
    "shorts_resume",
})
VALID_VISUAL_MODES = frozenset({"static", "ai-video"})
VALID_SCENE_STATUSES = frozenset({
    "pending",
    "generating",
    "downloaded",
    "validated",
    "failed",
    "uncertain",
    "skipped_budget",
    "fallback_static",
})
GENERATION_STATES = (
    "Waiting",
    "Preparing storyboard",
    "Generating",
    "Downloading or importing",
    "Validating",
    "Rendering",
    "Completed",
    "Needs login",
    "Credit limit reached",
    "Failed",
)


class ShortsOnlyViolationError(ValueError):
    """Raised when AI video clip generation is attempted outside YouTube Shorts."""


class ChannelPolicyError(ValueError):
    """Raised when a channel's editorial/authenticity policy forbids AI clips."""


class ProviderAuthRequiredError(RuntimeError):
    """Raised when the provider session expired or requires manual Google login."""


class CreditBudgetExceededError(RuntimeError):
    """Raised when generating a scene would exceed configured credit budgets."""


class ProviderUnavailableError(RuntimeError):
    """Raised when a video provider cannot generate or import the requested clip."""


def assert_shorts_scope(
    context_kind: str,
    *,
    width: int = 1080,
    height: int = 1920,
    visual_mode: str = "static",
) -> None:
    """Enforce that AI video generation and assembly only run for vertical Shorts."""
    normalized_context = (context_kind or "").strip().lower()
    if normalized_context not in SHORTS_CONTEXTS:
        raise ShortsOnlyViolationError(
            "AI video clip generation is exclusively allowed for YouTube Shorts, "
            f"never for '{context_kind}'."
        )
    if visual_mode not in VALID_VISUAL_MODES:
        raise ShortsOnlyViolationError(f"Unsupported Shorts visual mode: {visual_mode!r}")
    if width <= 0 or height <= 0 or width >= height:
        raise ShortsOnlyViolationError(
            f"Shorts AI video clips require vertical 9:16 dimensions, got {width}x{height}."
        )


def assert_channel_policy(channel_slug: str, settings: dict[str, Any] | None = None) -> None:
    """Enforce channel-level rules, including documentary authenticity protections."""
    channels.get(channel_slug)
    if channel_slug in channels.DOCUMENTARY_CHANNELS:
        allowed = bool((settings or {}).get("allow_documentary_illustrative", False))
        if not allowed:
            raise ChannelPolicyError(
                f"AI video clip generation is disabled by default for documentary channel "
                f"'{channel_slug}' to preserve authentic archival/scientific imagery."
            )


@dataclass
class ClipValidationResult:
    valid: bool
    path: str
    width: int = 0
    height: int = 0
    duration_sec: float = 0.0
    fps: float = 0.0
    has_video: bool = False
    codec: str = ""
    file_size: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ClipValidationResult:
        return cls(**payload)


@dataclass
class SceneSpec:
    scene_id: str
    scene_index: int
    script_section: str
    start_sec: float
    end_sec: float
    duration_sec: float
    visual_description: str
    generation_prompt: str
    aspect_ratio: str = "9:16"
    estimated_credits: float = 0.0
    actual_credits: float = 0.0
    provider: str = "google-flow"
    model: str = "veo-2-fast"
    status: str = "pending"
    output_path: str = ""
    validation: dict[str, Any] | None = None
    attempts: int = 0
    operation_name: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SceneSpec:
        return cls(**payload)


@dataclass
class Storyboard:
    channel: str
    topic: str
    language: str
    scope: str = "shorts"
    visual_mode: str = "ai-video"
    provider: str = "google-flow"
    model: str = "veo-2-fast"
    aspect_ratio: str = "9:16"
    total_duration_sec: float = 0.0
    estimated_total_credits: float = 0.0
    actual_total_credits: float = 0.0
    visual_identity: str = ""
    continuity_anchor: str = ""
    synthetic_disclosure_required: bool = True
    scenes: list[SceneSpec] = field(default_factory=list)
    status: str = "planned"
    fallback_used: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scenes"] = [scene.to_dict() for scene in self.scenes]
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Storyboard:
        scenes = [SceneSpec.from_dict(item) for item in payload.get("scenes", [])]
        data = dict(payload)
        data["scenes"] = scenes
        return cls(**data)
