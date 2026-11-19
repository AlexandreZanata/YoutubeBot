"""Intelligent distribution of new videos across the registered channels."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import channels, config, logic

UPLOAD_ACCOUNTS = {
    "whispers-from-heaven": "youtube-2",
    "zaflas": "zaflas",
    "infinite-random-worlds": "infinite",
    "vocal-pages": "vocal",
    "zanata": "zanata",
    "reflection": "reflection",
    "midnight-tales": "midnight",
}


def log(message: str) -> None:
    print(f"[distribute] {message}", flush=True)


def runs_root(slug: str) -> Path:
    if slug == "fallem-prince":
        return config.DATA / "runs"
    return config.DATA / "channels" / slug / "runs"


def future_scheduled(slug: str, now: datetime | None = None) -> int:
    """Count scheduled uploads whose slot is still in the future."""
    now = now or datetime.now()
    total = 0
    for upload in runs_root(slug).glob("*/upload.json"):
        try:
            data = json.loads(upload.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        slot = logic.slot_from_label(data.get("slot", ""), None)
        if data.get("scheduled") and slot and slot > now:
            total += 1
    return total


def allocate(count: int, scheduled: dict[str, int]) -> dict[str, int]:
    """Water-fill: every video goes to the channel with the fewest scheduled ones."""
    if count < 0:
        raise ValueError("count must be zero or positive")
    order = list(scheduled)
    current = dict(scheduled)
    added = {slug: 0 for slug in order}
    for _ in range(count):
        slug = min(order, key=lambda name: (current[name], order.index(name)))
        current[slug] += 1
        added[slug] += 1
    return added


def audit() -> dict[str, int]:
    return {slug: future_scheduled(slug) for slug in channels.CHANNELS}


def command_for(slug: str, count: int) -> list[str]:
    command = [sys.executable, "-m", "tools.ytbot", "run", "--channel", slug,
               "--account", "legacy", "--count", str(count)]
    upload = UPLOAD_ACCOUNTS.get(slug)
    if upload:
        command += ["--upload-account", upload]
    return command


def run_distribution(count: int, dry_run: bool = False) -> list:
    scheduled = audit()
    plan = allocate(count, scheduled)
    log(f"future scheduled: {scheduled}")
    log(f"plan: {plan}")
    failures: list = []
    if dry_run:
        return failures
    from .comments import answer_all
    try:
        answer_all()
    except Exception as error:
        log(f"comments check warning: {error}")
    for slug in channels.CHANNELS:
        amount = plan[slug]
        if not amount:
            continue
        log(f"{slug}: generating {amount}")
        result = subprocess.run(command_for(slug, amount), cwd=config.ROOT)
        if result.returncode:
            failures.append((slug, result.returncode))
    return failures
