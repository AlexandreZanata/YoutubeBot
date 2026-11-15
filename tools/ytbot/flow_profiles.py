"""Explicit, versioned ASR/render choices; channel/browser profiles are unrelated."""

from dataclasses import asdict, dataclass
import os


NAMES = ("standard", "fast")
ENVIRONMENT = "YTBOT_FLOW_PROFILE"
# A reviewed code change with full two-input quality evidence must promote this.
# Neither hardware discovery nor an environment variable can bypass qualification.
FAST_QUALIFIED = False
REVISION = "flow-v1"


@dataclass(frozen=True)
class Selection:
    requested: str
    effective: str
    revision: str = REVISION
    reason: str | None = None

    def record(self):
        from . import flow_media

        return {**asdict(self), "parameters": {
            "asr": flow_media.FAST_ASR if self.effective == "fast" else "standard",
            "render": flow_media.FAST_RENDER if self.effective == "fast" else "standard",
        }}


def name(value=None, *, environment=False):
    selected = os.environ.get(ENVIRONMENT, "standard") if value is None and environment else value
    selected = "standard" if selected is None else selected
    if selected not in NAMES:
        raise ValueError("flow profile must be standard or fast")
    return selected


def resolve(value="standard"):
    selected = name(value)
    if selected == "fast" and not FAST_QUALIFIED:
        return Selection(selected, "standard", reason="quality_validation_pending")
    return Selection(selected, selected)


def activate(value):
    from . import config

    config.FLOW_PROFILE = name(value)
    config.FLOW_SELECTION = resolve(config.FLOW_PROFILE)


def activate_request(request, admitted=None):
    """Legacy operations always use standard, regardless of the caller's environment."""
    activate(request.get("flow_profile", "standard"))
    from . import config

    if admitted and any(admitted.get(key) != current().record().get(key)
                        for key in ("effective", "revision", "parameters")):
        config.FLOW_SELECTION = Selection(configured(), "standard", reason="admitted_profile_unavailable")
    return current().record()


def current():
    from . import config

    return config.FLOW_SELECTION or resolve(configured())


def configured():
    from . import config

    return config.FLOW_PROFILE
