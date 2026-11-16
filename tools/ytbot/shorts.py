"""Zaflas Shorts protocol: short script, vertical render, upload and schedule."""

from __future__ import annotations

import json
import subprocess
import time as clock
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import account, assets, channels, chat, config, logic, render, runtime, youtube
from .accounts_store import AccountStore
from .render import log as render_log

SHORT_TOPICS = (
    "Calagem e gessagem: qual é a diferença?",
    "Como a água de má qualidade afeta o gado?",
    "Secagem de grãos: o que acontece se secar demais?",
    "Regulagem da plantadeira: o erro que aparece depois",
    "NDVI não mostra a causa do problema",
    "Por que o Brasil importa fertilizantes?",
    "Armazenar grãos na fazenda vale a pena?",
    "Seguro rural cobre qualquer prejuízo?",
    "Frete e logística: onde o lucro desaparece?",
    "Pasto bonito não significa pasto produtivo",
    "Plantas daninhas resistentes: como identificar?",
    "Quem é dono dos dados das máquinas agrícolas?",
)


def log(message: str) -> None:
    print(f"[shorts] {message}", flush=True)


def short_slots(count: int, per_day: int = 2, start: date | None = None,
                skip: int = 0) -> list[datetime]:
    if per_day < 1 or per_day > 2:
        raise ValueError("per_day must be 1 or 2")
    hours = (9, 18)[:per_day]
    day = start or (date.today() + timedelta(days=1))
    slots = []
    for index in range(count + skip):
        slot = datetime.combine(day + timedelta(days=index // per_day), time(hour=hours[index % per_day]))
        while slot <= datetime.now() + timedelta(minutes=60):
            slot += timedelta(days=1)
        slots.append(slot)
    return slots[skip:]


def short_metadata(topic: str, text: str) -> dict:
    description = (
        "🌱 Conheça o Zaflas:  https://zaflas.com.br/\n\n"
        "🔔 Gostou do conteúdo? Inscreva-se no canal Zaflas Agro:\n"
        "https://www.youtube.com/channel/UCi2aftoK7vlS3A6OozMHXKg?sub_confirmation=1\n\n"
        "nossas redes:\n\n"
        "LinkedIn: https://linkedin.com/company/zaflas\n"
        "Instagram: https://instagram.com/zaflas\n"
        "Facebook: https://facebook.com/zaflas\n"
        "YouTube: https://youtube.com/@zaflas\n"
        "GitHub: https://github.com/zaflas\n\n"
        + text
        + "\n\n#zaflasagro #agricultura #agro #shorts #gestaorural\n\n"
        "TAGS: Zaflas Agro, agricultura, agronegócio, gestão rural, produção agrícola, "
        "solo, lavoura, pecuária, tecnologia no campo, shorts"
    )
    return {"title": topic + " #Shorts", "description": description,
            "tags": "Zaflas Agro, agricultura, agronegócio, gestão rural, produção agrícola, "
                    "solo, lavoura, pecuária, tecnologia no campo, shorts"}


def render_short(run_dir: Path) -> Path:
    from src.engine.audio_mixer import get_audio_duration
    from src.engine.standard_backgrounds import resolve_standard_background
    from src.engine.subtitle_generator import save_ass_subtitles
    from src.engine.video_composer import render_single_pass_video

    narration = run_dir / "narration.aac"
    duration = get_audio_duration(narration)
    if duration <= 0:
        raise RuntimeError("short narration duration is unknown")
    background_image = config.ROOT / "assets" / "backgrounds" / f"{config.THUMBNAIL_THEME}.jpg"
    background, is_video = resolve_standard_background(
        background_image, config.THUMBNAIL_THEME, portrait=True)
    segments = render.transcribe_narration(narration)
    if not segments:
        raise RuntimeError("short subtitle transcription produced no text")
    subtitle = save_ass_subtitles(
        segments, run_dir / "narration.ass", font_size=72, width=1080, height=1920,
        alignment=5, outline_width=5, margin_horizontal=72)
    output = run_dir / "video.mp4"
    ok = render_single_pass_video(
        image_path=background, narr_path=narration, bgm_path=None, subtitle_path=subtitle,
        output_path=output, narr_vol=config.NARRATION_VOLUME, bgm_vol=0.0,
        width=1080, height=1920, fps=30, total_duration=duration,
        background_is_video=is_video,
    )
    if not ok:
        raise RuntimeError("short render failed")
    if not (run_dir / "thumbnail.png").is_file():
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", "1", "-i", str(output), "-frames:v", "1", str(run_dir / "thumbnail.png"),
        ], check=True)
    render_log(f"short saved: {output} ({output.stat().st_size} bytes)")
    return output


def run_shorts(channel_slug: str, count: int = 12, per_day: int = 2,
               start: date | None = None, upload_account: str = "zaflas",
               start_index: int = 0, skip_slots: int = 0) -> list:
    from playwright.sync_api import sync_playwright

    channels.apply(channel_slug)
    if not (config.PROMPTS / "shorts.txt").is_file():
        raise RuntimeError(f"{channel_slug} has no shorts prompt")
    store = AccountStore()
    store.activate(upload_account)
    runtime.start_hidden_chrome()
    upload_cdp = store.account(upload_account)["cdp_port"]
    store.activate("legacy")
    runtime.start_hidden_chrome()
    topics = list(SHORT_TOPICS[start_index:start_index + count])
    slots = short_slots(len(topics), per_day, start, skip_slots)
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
            (run_dir / "topic.txt").write_text(topic, encoding="utf-8")
            logic.set_run_field(run_dir, topic=topic)
            page = gen.new_page()
            try:
                started = clock.time()
                text = chat.generate_short(page, topic, run_dir)
                log(f"script {clock.time() - started:.0f}s")
                audio_start = clock.time()
                chat.capture_audio(page, gen, run_dir)
                log(f"audio {clock.time() - audio_start:.0f}s")
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
            finish_start = clock.time()
            try:
                thumb_start = clock.time()
                if not (run_dir / "thumbnail.png").is_file():
                    assets.generate_thumbnail(gen, run_dir, "shorts")
                log(f"thumbnail {clock.time() - thumb_start:.0f}s")
                render_short(run_dir)
                log(f"render {clock.time() - finish_start:.0f}s")
                meta = short_metadata(topic, text)
                (run_dir / "metadata.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                upload_start = clock.time()
                youtube.upload_and_schedule_short(up, run_dir, meta, slot)
                log(f"upload {clock.time() - upload_start:.0f}s")
                log(f"scheduled {topic} at {logic.slot_label(slot)}")
            except Exception as error:
                failures.append((topic, str(error)))
                log(f"upload/render failure for {topic}: {error}")
    runtime.stop_hidden_chrome()
    return failures
