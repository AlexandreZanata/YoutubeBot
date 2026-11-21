"""Parallel batch orchestration for the YouTube bot."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from playwright.sync_api import sync_playwright

from . import account, catalog, comments, community, config, logic, pipeline, runtime
from .topics import prepare_topics


def log(message: str) -> None:
    print(f"[batch] {message}", flush=True)


def _local_state() -> tuple[set[tuple], list[str]]:
    occupied: set[tuple] = set()
    titles: list[str] = []
    for upload_path in config.RUNS.glob("*/upload.json"):
        data = json.loads(upload_path.read_text(encoding="utf-8"))
        if data.get("scheduled"):
            slot = logic.slot_from_label(data.get("slot", ""), None)
            if slot:
                occupied.add((slot.date(), slot.hour))
        meta_path = upload_path.parent / "metadata.json"
        if meta_path.is_file():
            titles.append(json.loads(meta_path.read_text(encoding="utf-8")).get("title", ""))
    return occupied, titles


def _asset_worker(topic: str) -> None:
    with sync_playwright() as playwright:
        _browser, context = runtime.connect_hidden(playwright)
        pipeline.asset_stage(context, topic)


def _record_asset_failure(topic: str, error: Exception, failures: list) -> None:
    run_dir = logic.run_path(topic)
    run_dir.mkdir(parents=True, exist_ok=True)
    logic.record_event(run_dir, "assets", "error", str(error))
    failures.append((topic, str(error)))
    log(f"asset failure for {topic}: {error}")


def _asset_phase(context, topics: list[str], parallel: int) -> list:
    failures: list = []
    if parallel <= 1:
        for topic in topics:
            try:
                pipeline.asset_stage(context, topic)
            except Exception as error:
                _record_asset_failure(topic, error, failures)
        return failures
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(_asset_worker, topic): topic for topic in topics}
        for future, topic in futures.items():
            try:
                future.result()
            except Exception as error:
                _record_asset_failure(topic, error, failures)
    return failures


def _summary(topics: list[str]) -> None:
    lines = ["", "=== batch summary ==="]
    for topic in topics:
        record_path = logic.run_path(topic) / "record.json"
        data = json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
        lines.append(f"- {topic}: slot={data.get('slot', '?')} video={data.get('video', '?')}")
    print("\n".join(lines), flush=True)


def _upload_stage_safe(upload_context, topic: str, slot, failures: list) -> None:
    try:
        pipeline.upload_stage(upload_context, topic, slot)
    except Exception as error:
        logic.record_event(logic.run_path(topic), "upload", "error", str(error))
        failures.append((topic, str(error)))
        log(f"upload failure for {topic}: {error}")


def _upload_worker(upload_cdp: int | None, topic: str, slot, failures: list) -> None:
    """One upload in its own thread with its own CDP connection (sync API rule)."""
    with sync_playwright() as playwright:
        if upload_cdp:
            browser = playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{upload_cdp}", timeout=60000)
            upload_context = browser.contexts[0]
        else:
            _browser, upload_context = runtime.connect_hidden(playwright)
        _upload_stage_safe(upload_context, topic, slot, failures)


def _upload_phase(upload_context, upload_cdp: int | None, jobs: list,
                  parallel: int) -> list:
    """Upload the finished videos; bounded concurrent tabs pipeline the Studio waits."""
    failures: list = []
    if not jobs:
        return failures
    if parallel <= 1 or len(jobs) == 1:
        for topic, slot in jobs:
            _upload_stage_safe(upload_context, topic, slot, failures)
        return failures
    workers = min(parallel, len(jobs))
    log(f"upload tabs: {workers}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_upload_worker, upload_cdp, topic, slot, failures)
                   for topic, slot in jobs]
        for future in futures:
            future.result()
    return failures


def _refresh_catalog(context) -> None:
    data = logic.load_catalog()
    if not data and config.CHANNEL_HANDLE:
        data = catalog.scrape_public_catalog(context)
    if data:
        catalog.write_catalog_markdown(data)


def _upload_context(playwright, context, upload_cdp):
    if not upload_cdp:
        return context
    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{upload_cdp}")
    upload_context = browser.contexts[0]
    account.ensure_channel(upload_context)
    return upload_context


def run_batch(count: int, parallel: int = 0, upload_cdp: int | None = None,
              start_date=None, topics: list[str] | None = None,
              upload_parallel: int = 2) -> list:
    from . import channels
    if config.CHANNEL and config.CHANNEL.slug in channels.DOCUMENTARY_CHANNELS:
        raise RuntimeError(
            f"{config.CHANNEL.slug} is a documentary channel: build it with "
            "python3 -m tools.ytbot documentary init|collect|audit|narrate|render|qc. "
            "The batch path would generate an AI thumbnail and use it as the background, "
            "which this channel forbids.")
    if not (config.PROFILE / "Default" / "Cookies").is_file():
        runtime.setup_profile()
    runtime.start_hidden_chrome()
    failures: list = []
    with sync_playwright() as playwright:
        browser, context = runtime.connect_hidden(playwright)
        runtime.configure_downloads(browser)
        runtime.configure_extension(context)
        upload_context = _upload_context(playwright, context, upload_cdp)
        try:
            comments.answer(upload_context)
        except Exception as error:
            log(f"comments check warning: {error}")
        _refresh_catalog(upload_context)
        studio_payload = catalog.fetch_creator_videos(upload_context)
        local_occupied, local_titles = _local_state()
        scheduled_titles = [item.get("title", "") for item in catalog.studio_videos(studio_payload)] + local_titles
        occupied = logic.scheduled_slots(studio_payload) | local_occupied
        topics = topics or prepare_topics(context, count, scheduled_titles)
        start = datetime.combine(start_date, datetime.min.time()) if start_date else None
        if start and start < datetime.now():
            start = None
        slots = logic.next_slots(len(topics), occupied, start=start,
                                 interval_days=config.CHANNEL.interval_days)
        config.RUNS.mkdir(parents=True, exist_ok=True)
        free_gb = logic.require_free_space(config.RUNS, max(2.0, len(topics) * 0.32), "batch")
        log(f"free disk: {free_gb:.2f} GB")
        for index, topic in enumerate(topics):
            style = (logic.thumbnail_style(index)
                     if config.THUMBNAIL_THEME == "fallem_prince" else "dense")
            logic.set_run_field(logic.run_path(topic), thumbnail_style=style)
        workers = parallel if parallel > 0 else max(1, len(topics))
        log(f"topics: {topics}")
        log(f"tabs: {workers}, slots: {[logic.slot_label(slot) for slot in slots]}")
        asset_failures = _asset_phase(context, topics, workers)
        failures += asset_failures
        try:
            community.ensure_post(upload_context, topics, art_context=context)
        except Exception as error:
            log(f"community post warning: {error}")
        failed_topics = {topic for topic, _error in asset_failures}
        jobs = [(topic, slot) for topic, slot in zip(topics, slots)
                if topic not in failed_topics]
        failures += _upload_phase(upload_context, upload_cdp, jobs, upload_parallel)
    logic.write_records_markdown()
    _summary(topics)
    if failures:
        log(f"{len(failures)} failure(s): {failures}")
    return failures
