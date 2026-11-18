"""Message-length pacing: reading and typing time, clamped, one conversation at a time."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .rules import SalesRules


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class SalesPacing:
    typing_cps: float = 6.0
    min_seconds: float = 3.0
    max_seconds: float = 45.0
    reading_cps: float = 18.0
    reading_min: float = 2.0
    reading_max: float = 15.0
    jitter: float = 0.2
    link_preview: float = 4.0
    between_min: float = 20.0
    between_max: float = 60.0

    @classmethod
    def from_rules(cls, rules: SalesRules) -> "SalesPacing":
        raw = rules.pacing
        return cls(float(raw["typing_chars_per_second"]), float(raw["min_seconds"]),
                   float(raw["max_seconds"]), float(raw["reading_chars_per_second"]),
                   float(raw["reading_min_seconds"]), float(raw["reading_max_seconds"]),
                   float(raw["jitter"]), float(raw["link_preview_seconds"]),
                   float(raw["between_chats_min_seconds"]),
                   float(raw["between_chats_max_seconds"]))

    def _jittered(self, value: float, rng) -> float:
        return value * rng.uniform(1 - self.jitter, 1 + self.jitter)

    def typing(self, text: str, rng=random) -> float:
        """Seconds a person would take to type this message."""
        return _clamp(self._jittered(len(text.strip()) / self.typing_cps, rng),
                      self.min_seconds, self.max_seconds)

    def reading(self, text: str, rng=random) -> float:
        """Seconds a person would take to read the received message."""
        return _clamp(self._jittered(len((text or "").strip()) / self.reading_cps, rng),
                      self.reading_min, self.reading_max)

    def between_chats(self, rng=random) -> float:
        return rng.uniform(self.between_min, max(self.between_min, self.between_max))

    def plan(self, messages: list[str], incoming: str | None = None, rng=random) -> list[float]:
        """Wait before each message; the first also reads the received text."""
        delays = [self.typing(message, rng) for message in messages]
        if delays and incoming is not None:
            delays[0] += self.reading(incoming, rng)
        return delays
