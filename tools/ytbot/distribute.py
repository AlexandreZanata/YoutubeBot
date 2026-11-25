"""Intelligent distribution of new videos across the registered channels."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
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
    "sepia-atlas": "sepia",
    "bathylora": "bathylora",
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


def last_scheduled(slug: str, now: datetime | None = None) -> datetime | None:
    """Latest future scheduled slot for a channel (None when the queue is empty)."""
    now = now or datetime.now()
    latest = None
    for upload in runs_root(slug).glob("*/upload.json"):
        try:
            data = json.loads(upload.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        slot = logic.slot_from_label(data.get("slot", ""), None)
        if data.get("scheduled") and slot and slot > now:
            if latest is None or slot > latest:
                latest = slot
    return latest


def audit_dates() -> dict[str, datetime | None]:
    """Latest scheduled slot per long-form channel; the queue end drives distribution."""
    return {slug: last_scheduled(slug) for slug in channels.CHANNELS
            if slug not in channels.DOCUMENTARY_CHANNELS}


def _next_slot(slug: str, last: datetime | None, now: datetime | None = None) -> datetime:
    """Advance a channel's queue end by one video, following its own slots and cadence."""
    channel = channels.get(slug)
    hours = sorted(set(channel.slots)) or (0,)
    if last is None:
        base = now or datetime.now()
        earliest = base + timedelta(minutes=config.MIN_LEAD_MINUTES)
        for hour in hours:
            candidate = base.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate >= earliest:
                return candidate
        return (base + timedelta(days=1)).replace(
            hour=hours[0], minute=0, second=0, microsecond=0)
    for hour in hours:
        if hour > last.hour:
            return last.replace(hour=hour, minute=0, second=0, microsecond=0)
    return (last + timedelta(days=max(1, channel.interval_days))).replace(
        hour=hours[0], minute=0, second=0, microsecond=0)


def allocate_by_date(count: int, last_dates: dict[str, datetime | None]) -> dict[str, int]:
    """Water-fill by queue end: every video goes to the channel that runs out first."""
    if count < 0:
        raise ValueError("count must be zero or positive")
    order = list(last_dates)
    current = dict(last_dates)
    added = {slug: 0 for slug in order}
    for _ in range(count):
        slug = min(order, key=lambda name: (
            current[name] or datetime.min, order.index(name)))
        current[slug] = _next_slot(slug, current[slug])
        added[slug] += 1
    return added


def audit() -> dict[str, int]:
    return {slug: future_scheduled(slug) for slug in channels.CHANNELS
            if slug not in channels.DOCUMENTARY_CHANNELS}


def command_for(slug: str, count: int) -> list[str]:
    command = [sys.executable, "-m", "tools.ytbot", "run", "--channel", slug,
               "--account", "legacy", "--count", str(count)]
    upload = UPLOAD_ACCOUNTS.get(slug)
    if upload:
        command += ["--upload-account", upload]
    return command


def _run_channel(slug: str, amount: int, delay: int = 0) -> int:
    """Run one channel batch into its own log; staggered start avoids browser races."""
    if delay:
        time.sleep(delay)
    log_path = config.DATA / f"distribute-{slug}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command_for(slug, amount), cwd=config.ROOT,
                                 stdout=handle, stderr=subprocess.STDOUT)
    log(f"{slug}: exit={result.returncode} (log: {log_path.name})")
    return result.returncode


def run_distribution(count: int, dry_run: bool = False, concurrency: int = 2) -> list:
    scheduled = audit()
    dates = audit_dates()
    plan = allocate_by_date(count, dates)
    log(f"future scheduled: {scheduled}")
    log("queue ends: " + ", ".join(
        f"{slug}={value:%Y-%m-%d %H:%M}" if value else f"{slug}=empty"
        for slug, value in dates.items()))
    log(f"plan: {plan}")
    failures: list = []
    if dry_run:
        return failures
    from .comments import answer_all
    try:
        answer_all()
    except Exception as error:
        log(f"comments check warning: {error}")
    jobs = [(slug, plan[slug]) for slug in channels.CHANNELS if plan.get(slug)]
    if concurrency <= 1 or len(jobs) <= 1:
        for slug, amount in jobs:
            log(f"{slug}: generating {amount}")
            if _run_channel(slug, amount):
                failures.append((slug, 1))
        return failures
    workers = min(concurrency, len(jobs))
    log(f"channel tabs: {workers}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_channel, slug, amount, index * 30): slug
                   for index, (slug, amount) in enumerate(jobs)}
        for future, slug in futures.items():
            if future.result():
                failures.append((slug, 1))
    return failures
