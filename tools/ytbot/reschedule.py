"""Move already-scheduled future videos to the channel's current slot hours.

The frequency never changes: each scheduled video keeps its date when the date still has a
free slot, keeps its within-day order, and days above the channel frequency are rebalanced
into future free slots at the same cadence. ``--enforce-interval`` instead re-spaces every
future video on the channel's ``interval_days`` cadence. Videos whose new slot would be less
than the minimum lead time away stay untouched and are reported.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from . import catalog, channels, config, logic, runtime, upload_dialog, youtube
from .account import ensure_channel
from .accounts_store import AccountStore

MAX_RESCHEDULE_DAYS = 120


def log(message: str) -> None:
    print(f"[reschedule] {message}", flush=True)


def scheduled_entries(payload: dict) -> list[dict]:
    """Future scheduled videos as {videoId, title, moment} from the Studio payload."""
    found: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            details = node.get("scheduledPublishingDetails")
            if isinstance(details, dict) and node.get("videoId"):
                for entry in details.get("scheduledPublishings", []):
                    try:
                        moment = datetime.fromtimestamp(int(entry["scheduledTimeSeconds"]))
                    except (KeyError, TypeError, ValueError, OSError):
                        continue
                    found.append({"videoId": node["videoId"], "title": node.get("title", ""),
                                  "moment": moment})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def _moment(day: date, hour: int) -> datetime:
    return datetime.combine(day, datetime.min.time()).replace(hour=hour)


def _plan_cadence(entries: list[dict], hours: tuple[int, ...], interval_days: int,
                  now: datetime, lead_minutes: int) -> list[dict]:
    """Pack every future video on a strict one-day-every-``interval_days`` cadence."""
    hours = tuple(sorted(hours))
    earliest = now + timedelta(minutes=lead_minutes)
    future = [entry for entry in sorted(entries, key=lambda item: (item["moment"], item["videoId"]))
              if entry["moment"] > now]
    if not future:
        return []
    day = future[0]["moment"].date()
    targets: list[datetime] = []
    while len(targets) < len(future) and day < future[0]["moment"].date() + timedelta(days=MAX_RESCHEDULE_DAYS):
        for hour in hours:
            moment = _moment(day, hour)
            if moment >= earliest:
                targets.append(moment)
        day += timedelta(days=max(1, interval_days))
    moves = []
    for entry, target in zip(future, targets):
        note = "aligned" if entry["moment"] == target else "cadence"
        moves.append({"entry": entry, "target": target, "note": note})
    for entry in future[len(targets):]:
        moves.append({"entry": entry, "target": None, "note": "keep"})
    return moves


def plan(entries: list[dict], hours: tuple[int, ...], interval_days: int,
         now: datetime, lead_minutes: int = config.MIN_LEAD_MINUTES,
         enforce_interval: bool = False) -> list[dict]:
    """Return one move per future scheduled video: video, moment, target, note.

    Targets are None when the video must stay at its current slot (lead time or no free
    slot). ``note`` is one of aligned, slot, late-slot, rebalanced, cadence, keep.
    ``enforce_interval`` re-spaces every future video on the channel cadence instead of
    keeping each video's current date.
    """
    if enforce_interval:
        return _plan_cadence(entries, hours, interval_days, now, lead_minutes)
    hours = tuple(sorted(hours))
    earliest = now + timedelta(minutes=lead_minutes)
    by_day: dict[date, list[dict]] = {}
    for entry in sorted(entries, key=lambda item: (item["moment"], item["videoId"])):
        if entry["moment"] <= now:
            continue
        by_day.setdefault(entry["moment"].date(), []).append(entry)

    taken: set[tuple[date, int]] = set()
    moves: list[dict] = []
    extras: list[dict] = []

    def take(entry: dict, day: date, hour: int, note: str) -> None:
        taken.add((day, hour))
        moves.append({"entry": entry, "target": _moment(day, hour), "note": note})

    for day in sorted(by_day):
        for index, entry in enumerate(by_day[day]):
            if index >= len(hours):
                extras.append(entry)
                continue
            hour = hours[index]
            if _moment(day, hour) >= earliest and (day, hour) not in taken:
                take(entry, day, hour, "slot" if entry["moment"].hour != hour else "aligned")
                continue
            later = [later_hour for later_hour in hours
                     if later_hour > now.hour and (day, later_hour) not in taken
                     and _moment(day, later_hour) >= earliest]
            if later:
                take(entry, day, later[0], "late-slot")
            else:
                moves.append({"entry": entry, "target": None, "note": "keep"})

    step = max(1, interval_days)
    for entry in extras:
        day = entry["moment"].date()
        placed = False
        while not placed and day < entry["moment"].date() + timedelta(days=MAX_RESCHEDULE_DAYS):
            day += timedelta(days=step)
            for hour in hours:
                if (day, hour) not in taken and _moment(day, hour) >= earliest:
                    take(entry, day, hour, "rebalanced")
                    placed = True
                    break
        if not placed:
            moves.append({"entry": entry, "target": None, "note": "keep"})

    moves.sort(key=lambda move: move["entry"]["moment"])
    return moves


def _run_dirs() -> dict[str, Path]:
    """videoId -> run directory from the channel's local upload records."""
    mapping: dict[str, Path] = {}
    for upload in config.RUNS.glob("*/upload.json"):
        try:
            data = json.loads(upload.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("videoId"):
            mapping[data["videoId"]] = upload.parent
    return mapping


def _record_incident(line: str) -> None:
    with (config.DATA / "incidents.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} reschedule {line}\n")


def _chain_pending() -> bool:
    """A new generation chain claims the shared legacy profile; yield to it."""
    return (config.DATA / "auto-chain.active").is_file()


def _channel_busy(slug: str) -> bool:
    """A Shorts pipeline is using this channel's upload profile; yield to it."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"faith-shorts --channel {slug}"],
            capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _open_schedule_dialog(context, video_id: str):
    """Open the visibility dialog of an already-scheduled video on its edit page."""
    page = youtube.open_edit(context, video_id)
    try:
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1200)
        status = page.evaluate("()=>document.querySelector('#visibility-text')?.innerText")
        if status not in ("Programado", "Scheduled"):
            page.close()
            return None
        for name in ("Editar status de visibilidade", "Edit video visibility status", "Edit visibility"):
            button = page.get_by_role("button", name=name)
            if button.count():
                button.first.click()
                page.wait_for_timeout(2500)
                return page
        page.close()
        return None
    except Exception:
        page.close()
        raise


def _confirm_scheduled(context, run_dir, result: dict, target) -> bool:
    """Verify the new slot and record it; the video keeps its own identity."""
    if not upload_dialog.scheduled_at(context, result["videoId"], target):
        return False
    result["scheduled"] = True
    result["slot"] = logic.slot_label(target)
    if run_dir is not None:
        youtube.write_result(run_dir, result)
        logic.set_run_field(run_dir, slot=result["slot"])
        logic.record_event(run_dir, "upload", "ok", "rescheduled to " + result["slot"])
    return True


def move_video(context, entry: dict, target, run_dir) -> dict:
    """Move one already-scheduled video to the target slot."""
    result = {"videoId": entry["videoId"], "url": f"https://youtu.be/{entry['videoId']}"}
    if _confirm_scheduled(context, run_dir, result, target):
        youtube.log(f"scheduled {result['videoId']} at {result['slot']}")
        return result
    page = _open_schedule_dialog(context, entry["videoId"])
    if page is not None:
        try:
            upload_dialog.change_scheduled_time(page, target)
        finally:
            page.close()
        if _confirm_scheduled(context, run_dir, result, target):
            youtube.log(f"scheduled {result['videoId']} at {result['slot']}")
            return result
    # A draft without the scheduled badge still uses the upload dialog path.
    return youtube.schedule_existing(context, run_dir, result, target)


def run(channel_slug: str, dry_run: bool = False, enforce_interval: bool = False) -> list:
    channel = channels.apply(channel_slug)
    store = AccountStore()
    binding = store.load()["bindings"].get(channel_slug)
    account_id = binding["account_id"] if binding else "legacy"
    store.activate(account_id)
    runtime.start_hidden_chrome()
    failures: list = []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, context = runtime.connect_hidden(playwright)
        with store.profile_lock(account_id):
            ensure_channel(context)
            payload = catalog.fetch_creator_videos(context)
            entries = scheduled_entries(payload)
            now = datetime.now()
            moves = plan(entries, channel.slots, channel.interval_days, now,
                         enforce_interval=enforce_interval)
            runs = _run_dirs() if not dry_run else {}
            chain_at_start = _chain_pending()
            log(f"{channel_slug}: {len(moves)} future scheduled, "
                f"slots {channel.slots}, now {now:%Y-%m-%d %H:%M}")
            for move in moves:
                entry = move["entry"]
                old = entry["moment"]
                target = move["target"]
                if target is None:
                    log(f"keep {entry['videoId']} at {old:%Y-%m-%d %H:%M} ({move['note']})")
                    continue
                if target == old:
                    continue
                line = (f"{entry['videoId']} {old:%Y-%m-%d %H:%M} -> "
                        f"{target:%Y-%m-%d %H:%M} ({move['note']})")
                if dry_run:
                    log(f"plan {line}")
                    continue
                if not chain_at_start and _chain_pending():
                    log("generation chain active again; stopping early, rerun later to finish")
                    break
                if _channel_busy(channel_slug):
                    log("Shorts pipeline using this profile; stopping early, rerun later")
                    break
                run_dir = runs.get(entry["videoId"])
                try:
                    move_video(context, entry, target, run_dir)
                    log(f"moved {line}")
                except Exception as error:
                    failures.append((entry["videoId"], str(error)))
                    _record_incident(f"{channel_slug} {line}: {error}")
                    log(f"failed {line}: {error}")
        browser.close()
    if not dry_run:
        logic.write_records_markdown()
    return failures
