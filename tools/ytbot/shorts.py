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
    "Por que a análise de solo não termina na coleta?",
    "O que o mapa de produtividade revela depois da colheita?",
    "Como escolher entre plantio direto e cultivo mínimo?",
    "Quando a irrigação compensa o investimento?",
    "Por que o milho safrinha exige planejamento antecipado?",
    "Como o clima afeta a janela de aplicação de defensivos?",
    "Por que o pH do solo muda depois da calagem?",
    "Como o milho responde ao nitrogênio em cobertura?",
    "O que a compactação do solo faz com a raiz?",
    "Quando o gado precisa de suplementação mineral?",
    "Por que a colheitadeira perde grãos na barra de corte?",
)


def log(message: str) -> None:
    print(f"[shorts] {message}", flush=True)


def occupied_slots(root: Path) -> set[tuple[int, int, int, int]]:
    slots = set()
    for upload in root.glob("*/upload.json"):
        try:
            data = json.loads(upload.read_text(encoding="utf-8"))
            slot = datetime.strptime(data.get("slot", ""), "%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            continue
        if data.get("scheduled"):
            slots.add((slot.year, slot.month, slot.day, slot.hour))
    return slots


def short_slots(count: int, per_day: int = 2, start: date | None = None,
                skip: int = 0,
                occupied: set[tuple[int, int, int, int]] | None = None) -> list[datetime]:
    if per_day < 1 or per_day > 2:
        raise ValueError("per_day must be 1 or 2")
    hours = (9, 18)[:per_day]
    day = start or (date.today() + timedelta(days=1))
    slots = []
    for index in range(count + skip):
        slot = datetime.combine(day + timedelta(days=index // per_day), time(hour=hours[index % per_day]))
        while slot <= datetime.now() + timedelta(minutes=60) or (
                occupied and (slot.year, slot.month, slot.day, slot.hour) in occupied):
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
               start_index: int = 0, skip_slots: int = 0,
               *,
               visual_mode: str | None = None,
               video_provider: str | None = None,
               video_model: str | None = None,
               max_credits: float | None = None,
               max_scenes: int | None = None,
               fallback_to_static: bool | None = None,
               dry_run: bool = False) -> list:
    from playwright.sync_api import sync_playwright
    from .shorts_video import assert_channel_policy, assert_shorts_scope
    from .shorts_video.pipeline import render_ai_short
    from .shorts_video.settings import resolve_runtime_settings

    channels.apply(channel_slug)
    if not (config.PROMPTS / "shorts.txt").is_file():
        raise RuntimeError(f"{channel_slug} has no shorts prompt")
    resolved = resolve_runtime_settings(
        visual_mode=visual_mode or "static",
        provider=video_provider,
        model=video_model,
        max_credits_per_short=max_credits,
        max_scenes_per_short=max_scenes,
        fallback_to_static=fallback_to_static,
    )
    effective_mode = resolved["visual_mode"]
    assert_shorts_scope("shorts", width=1080, height=1920, visual_mode=effective_mode)
    if effective_mode == "ai-video":
        assert_channel_policy(channel_slug, resolved)

    topics = list(SHORT_TOPICS[start_index:start_index + count])
    slots = short_slots(len(topics), per_day, start, skip_slots,
                        occupied_slots(config.DATA_DIR / "shorts"))
    root = config.DATA_DIR / "shorts"
    if dry_run:
        for topic, slot in zip(topics, slots):
            run_dir = root / logic.slug(topic)
            run_dir.mkdir(parents=True, exist_ok=True)
            short_path = run_dir / "short.txt"
            script_text = short_path.read_text(encoding="utf-8") if short_path.is_file() else topic
            if effective_mode == "ai-video":
                summary = render_ai_short(
                    run_dir,
                    channel_slug,
                    topic,
                    script_text,
                    visual_mode=effective_mode,
                    video_provider=video_provider,
                    video_model=video_model,
                    max_credits_per_short=max_credits,
                    max_scenes=max_scenes,
                    fallback_to_static=fallback_to_static,
                    dry_run=True,
                )
                log(
                    f"dry-run {topic} ({logic.slot_label(slot)}): provider={summary['provider']} "
                    f"model={summary['model']} scenes={summary['scene_count']} "
                    f"est_credits={summary['estimated_credits']} budget={summary['budget_reason']}"
                )
            else:
                log(f"dry-run {topic} ({logic.slot_label(slot)}): mode=static")
        return []

    store = AccountStore()
    store.activate(upload_account)
    runtime.start_hidden_chrome()
    upload_cdp = store.account(upload_account)["cdp_port"]
    store.activate("legacy")
    runtime.start_hidden_chrome()
    failures = []
    with sync_playwright() as playwright:
        gen_browser, gen = runtime.connect_hidden(playwright)
        upload_browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{upload_cdp}")
        up = upload_browser.contexts[0]
        account.ensure_channel(up)
        runtime.configure_downloads(gen_browser)
        runtime.configure_extension(gen)
        for topic, slot in zip(topics, slots):
            run_dir = root / logic.slug(topic)
            run_dir.mkdir(parents=True, exist_ok=True)
            run_dir.chmod(0o700)
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
                ai_result = None
                if effective_mode == "ai-video":
                    ai_result = render_ai_short(
                        run_dir,
                        channel_slug,
                        topic,
                        text,
                        visual_mode=effective_mode,
                        video_provider=video_provider,
                        video_model=video_model,
                        max_credits_per_short=max_credits,
                        max_scenes=max_scenes,
                        fallback_to_static=fallback_to_static,
                        static_fallback_fn=render_short,
                    )
                else:
                    render_short(run_dir)
                log(f"render {clock.time() - finish_start:.0f}s")
                meta = short_metadata(topic, text)
                if ai_result and ai_result.get("visual_mode") == "ai-video":
                    meta["visual_mode"] = "ai-video"
                    meta["video_provider"] = ai_result.get("provider", "")
                    meta["video_model"] = ai_result.get("model", "")
                    meta["synthetic_media_disclosure"] = bool(
                        ai_result.get("synthetic_disclosure_required", True)
                    )
                (run_dir / "metadata.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                upload_start = clock.time()
                youtube.upload_and_schedule_with_context(
                    up, run_dir, meta, slot, custom_thumbnail=True, end_screen=False)
                log(f"upload {clock.time() - upload_start:.0f}s")
                log(f"scheduled {topic} at {logic.slot_label(slot)}")
            except Exception as error:
                failures.append((topic, str(error)))
                log(f"upload/render failure for {topic}: {error}")
    runtime.stop_hidden_chrome()
    return failures
