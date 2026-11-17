"""Vertical religious Shorts with one generated background image per short."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import account, channels, chat, codex_media, config, logic, render, runtime, youtube
from .accounts_store import AccountStore

CHANNELS = {
    "reflection": {
        "upload": "reflection",
        "hours": (8, 20),
        "hashtags": "#shorts #faith #bible #prayer #hope #god",
        "tags": "faith, bible, prayer, hope, god, short, devotional, scripture",
        "topics": (
            "Hannah: When You Have No Words Left to Pray",
            "Elijah in the Cave: When the Storm Is Not God",
            "Peter's Nets: When Obedience Comes Before the Catch",
            "The Widow's Oil: When Little Is All You Have",
            "Joseph in Prison: When the Promise Feels Forgotten",
        ),
    },
    "zanata": {
        "upload": "zanata",
        "hours": (9,),
        "hashtags": "#books #philosophy #psychology #summary #shorts",
        "tags": "book summary, philosophy, psychology, sociology, ideas, short",
        "topics": (
            "Why We Perform: Goffman and the Masks We Wear",
            "The Tyranny of the Should: Karen Horney on the Ideal Self",
            "Why a Scapegoat Unites a Crowd: René Girard",
            "The Banality of Evil: Arendt on Ordinary People",
            "The Denial of Death: Becker on Why We Build",
        ),
    },
    "whispers-from-heaven": {
        "upload": "youtube-2",
        "hours": (9, 21),
        "hashtags": "#shorts #faith #bible #prayer #hope #god",
        "tags": "faith, bible, prayer, hope, god, short, devotional, scripture",
        "topics": (
            "When the Night Feels Longer Than Your Faith",
            "The Shepherd Who Leaves the Ninety-Nine",
            "A Prayer You Whisper Is Still Heard",
            "The Peace That Does Not Depend on the Storm",
            "He Gathers the Weary, One by One",
        ),
    },
}


def log(message: str) -> None:
    print(f"[faith-shorts] {message}", flush=True)


def short_slots(count: int, hours: tuple[int, int], start: date,
                skip: int = 0) -> list[datetime]:
    slots = []
    day = start
    index = 0
    while len(slots) < count + skip:
        for hour in hours:
            slot = datetime.combine(day, dtime(hour=hour))
            if slot > datetime.now() + timedelta(minutes=60):
                slots.append(slot)
                if len(slots) == count + skip:
                    return slots[skip:]
        day += timedelta(days=1)
        index += 1
    return slots


def generate_script(page, topic: str, run_dir: Path) -> str:
    page.goto(config.GPT_URL, timeout=90000)
    page.wait_for_timeout(7000)
    chat.dismiss_notice(page)
    header = config.prompt("shorts.txt")
    header += ("\n\nMANDATORY NARRATION LANGUAGE: English. Write the entire spoken short in "
               "English, regardless of the operator message or the browser language. Return "
               "only the narration text.")
    chat.send_text(page, header + "\n\nTheme: " + topic)
    log(f"script prompt sent: {topic}")
    chat.wait_for_assistant(page)
    text = chat.clean_article(chat.copy_last(page))
    words = len(text.split())
    if words < 60 or words > 180:
        raise RuntimeError(f"short narration has an unexpected length ({words} words)")
    (run_dir / "short.txt").write_text(text, encoding="utf-8")
    log(f"short saved: {len(text)} chars, {words} words")
    return text


def metadata(topic: str, text: str, spec: dict | None = None) -> dict:
    spec = spec or {}
    hashtags = spec.get("hashtags", "#shorts #faith #bible #prayer #hope #god")
    tags = spec.get("tags", "faith, bible, prayer, hope, god, short, devotional, scripture")
    description = text.strip() + "\n\n" + hashtags + "\n\nTAGS: " + tags
    return {"title": topic + " #Shorts", "description": description, "tags": tags}


def render_short(run_dir: Path) -> Path:
    from src.engine.audio_mixer import get_audio_duration
    from src.engine.subtitle_generator import save_ass_subtitles
    from src.engine.video_composer import render_single_pass_video

    narration = run_dir / "narration.aac"
    duration = get_audio_duration(narration)
    if duration <= 0:
        raise RuntimeError("short narration duration is unknown")
    segments = render.transcribe_narration(narration)
    if not segments:
        raise RuntimeError("short transcription produced no text")
    subtitle = save_ass_subtitles(
        segments, run_dir / "narration.ass", font_size=72, width=1080, height=1920,
        alignment=5, outline_width=5, margin_horizontal=72)
    output = run_dir / "video.mp4"
    ok = render_single_pass_video(
        image_path=run_dir / "thumbnail.png", narr_path=narration, bgm_path=None,
        subtitle_path=subtitle, output_path=output, narr_vol=config.NARRATION_VOLUME,
        bgm_vol=0.0, width=1080, height=1920, fps=30, total_duration=duration,
        background_is_video=False)
    if not ok:
        raise RuntimeError("short render failed")
    log(f"video saved: {output} ({output.stat().st_size} bytes)")
    return output


def run(channel_slug: str, count: int = 5, start: date | None = None,
        skip_slots: int = 0, start_index: int = 0) -> list:
    spec = CHANNELS[channel_slug]
    channels.apply(channel_slug)
    store = AccountStore()
    store.activate(spec["upload"])
    runtime.start_hidden_chrome()
    upload_cdp = store.account(spec["upload"])["cdp_port"]
    store.activate("legacy")
    runtime.start_hidden_chrome()
    topics = list(spec["topics"])[start_index:start_index + count]
    slots = short_slots(len(topics), spec["hours"],
                        start or (date.today() + timedelta(days=1)), skip_slots)
    failures = []
    with sync_playwright() as playwright:
        gen_browser, gen = runtime.connect_hidden(playwright)
        upload_browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{upload_cdp}")
        up = upload_browser.contexts[0]
        account.ensure_channel(up)
        runtime.configure_downloads(gen_browser)
        runtime.configure_extension(gen)
        root = config.DATA_DIR / "shorts"
        for topic, slot in zip(topics, slots):
            run_dir = root / logic.slug(topic)
            run_dir.mkdir(parents=True, exist_ok=True)
            run_dir.chmod(0o700)
            (run_dir / "topic.txt").write_text(topic, encoding="utf-8")
            logic.set_run_field(run_dir, topic=topic)
            started = time.time()
            page = gen.new_page()
            try:
                text = generate_script(page, topic, run_dir)
                chat.capture_audio(page, gen, run_dir)
            except Exception as error:
                failures.append((topic, str(error)))
                log(f"asset failure for {topic}: {error}")
                page.close()
                continue
            finally:
                try:
                    page.close()
                except Exception:
                    pass
            try:
                codex_media.generate_thumbnail(run_dir, "short-background")
                render_short(run_dir)
                meta = metadata(topic, text, spec)
                (run_dir / "metadata.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                youtube.upload_and_schedule_with_context(
                    up, run_dir, meta, slot, custom_thumbnail=False, end_screen=False)
                log(f"scheduled {topic} at {logic.slot_label(slot)} "
                    f"({time.time() - started:.0f}s)")
            except Exception as error:
                failures.append((topic, str(error)))
                log(f"upload/render failure for {topic}: {error}")
    runtime.stop_hidden_chrome()
    return failures

