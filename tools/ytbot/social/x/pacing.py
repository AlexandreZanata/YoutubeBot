"""Human-paced intervals for X publishing, mirroring the WhatsApp sender."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Pacing:
    """Bounds for the wait between two published items, in seconds."""

    min_interval: float = 120.0
    max_interval: float = 300.0

    def between_posts(self) -> float:
        low = max(0.5, min(self.min_interval, self.max_interval))
        high = max(low, self.max_interval)
        return random.uniform(low, high)


def delay_seconds(last_at: datetime | None, now: datetime, target: float) -> float:
    """Remaining wait so the next publish respects the target interval."""
    if last_at is None:
        return 0.0
    return max(0.0, target - (now - last_at).total_seconds())


def wait(last_at: datetime | None, pacing: Pacing | None = None,
         sleep=time.sleep, now: datetime | None = None) -> float:
    """Sleep only the missing part of the interval and return it."""
    pacing = pacing or Pacing()
    now = now or datetime.now()
    delay = delay_seconds(last_at, now, pacing.between_posts())
    if delay:
        print(f"[social] pacing: waiting {delay:.0f}s before the next publish", flush=True)
        sleep(delay)
    return delay
