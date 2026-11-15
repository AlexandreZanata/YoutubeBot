"""Free disk space before a batch without touching records or unscheduled media."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import config

TRASH = Path.home() / ".local" / "share" / "Trash"
CACHE_TARGETS = (Path.home() / ".cache" / "go-build",)
PRUNE_FILES = ("video.mp4", "narration.wav", "thumbnail.frame.png")
MIN_FREE_GB = 20.0


def log(message: str) -> None:
    print(f"[cleanup] {message}", flush=True)


def free_gb(path: Path = config.ROOT) -> float:
    return shutil.disk_usage(path).free / 1024 ** 3


def run_roots() -> list[Path]:
    roots = [config.DATA / "runs"]
    channels = config.DATA / "channels"
    if channels.is_dir():
        roots += [entry / "runs" for entry in channels.iterdir()]
    return [root for root in roots if root.is_dir()]


def scheduled_upload(run_dir: Path) -> bool:
    try:
        data = json.loads((run_dir / "upload.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(data.get("scheduled") and data.get("videoId"))


def prune_run(run_dir: Path, dry_run: bool = False) -> tuple[int, int]:
    files = 0
    freed = 0
    for path in [run_dir / name for name in PRUNE_FILES] + list(run_dir.glob("upload-*.mp4")):
        if not path.is_file():
            continue
        freed += path.stat().st_size
        files += 1
        if not dry_run:
            path.unlink(missing_ok=True)
    return files, freed


def prune_scheduled(dry_run: bool = False) -> tuple[int, int]:
    files = 0
    freed = 0
    for root in run_roots():
        for upload in root.glob("*/upload.json"):
            if not scheduled_upload(upload.parent):
                continue
            count, size = prune_run(upload.parent, dry_run)
            files += count
            freed += size
    return files, freed


def clean_staging(dry_run: bool = False) -> tuple[int, int]:
    staging = config.DATA / "upload-tmp"
    files = 0
    freed = 0
    if not staging.is_dir():
        return files, freed
    for path in staging.iterdir():
        if not path.is_file():
            continue
        freed += path.stat().st_size
        files += 1
        if not dry_run:
            path.unlink(missing_ok=True)
    return files, freed


def empty_trash(dry_run: bool = False) -> tuple[int, int]:
    files = 0
    freed = 0
    for name in ("files", "info"):
        directory = TRASH / name
        if not directory.is_dir():
            continue
        for entry in list(directory.iterdir()):
            try:
                size = sum(item.stat().st_size for item in entry.rglob("*") if item.is_file())
                if entry.is_file():
                    size = entry.stat().st_size
            except OSError:
                size = 0
            files += 1
            freed += size
            if dry_run:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
    return files, freed


def clean_build_cache(dry_run: bool = False) -> tuple[int, int]:
    files = 0
    freed = 0
    for target in CACHE_TARGETS:
        if not target.is_dir():
            continue
        try:
            size = sum(item.stat().st_size for item in target.rglob("*") if item.is_file())
        except OSError:
            size = 0
        files += 1
        freed += size
        if not dry_run:
            shutil.rmtree(target, ignore_errors=True)
    return files, freed


def before_run(dry_run: bool = False) -> dict:
    """Rule run before every batch: trash, staging and already scheduled media."""
    report = {"trash": empty_trash(dry_run), "staging": clean_staging(dry_run),
              "scheduled": prune_scheduled(dry_run), "cache": (0, 0)}
    if free_gb() < MIN_FREE_GB:
        report["cache"] = clean_build_cache(dry_run)
    freed = sum(size for _files, size in report.values()) / 1024 ** 3
    log(f"freed {freed:.2f} GB; {free_gb():.2f} GB available")
    return report
