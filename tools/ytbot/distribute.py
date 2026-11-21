"""Intelligent distribution of new videos across the registered channels."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
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
