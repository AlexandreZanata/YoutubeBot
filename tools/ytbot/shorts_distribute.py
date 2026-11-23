"""Intelligent distribution of Shorts across the channels that use them."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import config
from .distribute import allocate, log

SHORTS_CHANNELS = {
    "zaflas": {"command": "faith-shorts", "extra": []},
    "reflection": {"command": "faith-shorts", "extra": []},
    "whispers-from-heaven": {"command": "faith-shorts", "extra": []},
    "zanata": {"command": "faith-shorts", "extra": []},
    "fallem-prince": {"command": "faith-shorts", "extra": []},
    "infinite-random-worlds": {"command": "faith-shorts", "extra": []},
    "vocal-pages": {"command": "faith-shorts", "extra": []},
    "midnight-tales": {"command": "faith-shorts", "extra": []},
    "sepia-atlas": {"command": "faith-shorts", "extra": []},
    "bathylora": {"command": "faith-shorts", "extra": []},
}


def shorts_root(slug: str) -> Path:
    if slug == "fallem-prince":
        return config.DATA / "shorts"
    return config.DATA / "channels" / slug / "shorts"


def scheduled_shorts(slug: str) -> int:
    total = 0
    for upload in shorts_root(slug).glob("*/upload.json"):
        try:
            data = json.loads(upload.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("scheduled"):
            total += 1
    return total


def used_topics(slug: str) -> int:
    root = shorts_root(slug)
    if not root.is_dir():
        return 0
    return sum(1 for entry in root.iterdir()
               if entry.is_dir() and (entry / "topic.txt").is_file())


def command_for(
    slug: str,
    amount: int,
    *,
    visual_mode: str | None = None,
    video_provider: str | None = None,
    video_model: str | None = None,
) -> list[str]:
    spec = SHORTS_CHANNELS[slug]
    command = [sys.executable, "-m", "tools.ytbot", spec["command"], "--channel", slug,
               "--count", str(amount), "--start-index", str(used_topics(slug))]
    if visual_mode:
        command.extend(["--visual-mode", visual_mode])
    if video_provider:
        command.extend(["--video-provider", video_provider])
    if video_model:
        command.extend(["--video-model", video_model])
    return command + spec["extra"]


def run_distribution(
    count: int,
    dry_run: bool = False,
    *,
    visual_mode: str | None = None,
    video_provider: str | None = None,
    video_model: str | None = None,
) -> list:
    scheduled = {slug: scheduled_shorts(slug) for slug in SHORTS_CHANNELS}
    plan = allocate(count, scheduled)
    log(f"shorts scheduled: {scheduled}")
    log(f"shorts plan: {plan}")
    failures: list = []
    if dry_run:
        return failures
    from .comments import answer_all
    try:
        answer_all()
    except Exception as error:
        log(f"comments check warning: {error}")
    for slug in SHORTS_CHANNELS:
        amount = plan[slug]
        if not amount:
            continue
        if visual_mode == "ai-video" and slug in ("sepia-atlas", "bathylora"):
            # Documentary Shorts keep still archival/scientific backgrounds by default.
            effective_mode = "static"
        else:
            effective_mode = visual_mode
        log(f"{slug}: generating {amount} short(s)")
        result = subprocess.run(
            command_for(
                slug,
                amount,
                visual_mode=effective_mode,
                video_provider=video_provider,
                video_model=video_model,
            ),
            cwd=config.ROOT,
        )
        if result.returncode:
            failures.append((slug, result.returncode))
    return failures
