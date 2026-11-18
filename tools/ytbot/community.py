"""Publish one question post per calendar day when the Community tab has none for today."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageOps

from . import codex_media, config, logic

POST_TYPES = (
    "text",
    "image",
    "gif",
    "poll-text",
    "poll-image",
    "quiz",
    "video",
    "playlist",
)

POST_SELECTOR = "ytd-backstage-post-renderer, ytd-post-renderer"
EMPTY_MARKERS = (
    "As postagens aparecem aqui depois de publicadas",
    "Posts appear here after",
)

RELATIVE_UNITS = {
    "segundo": 1 / 60, "segundos": 1 / 60,
    "minuto": 1, "minutos": 1,
    "hora": 60, "horas": 60,
    "dia": 1440, "dias": 1440,
    "semana": 10080, "semanas": 10080,
    "mês": 43200, "meses": 43200,
    "mes": 43200,
    "ano": 525600, "anos": 525600,
    "second": 1 / 60, "seconds": 1 / 60,
    "minute": 1, "minutes": 1,
    "hour": 60, "hours": 60,
    "day": 1440, "days": 1440,
    "week": 10080, "weeks": 10080,
    "month": 43200, "months": 43200,
    "year": 525600, "years": 525600,
}

TEXT = {
    "en": (
        "{topic}\n\n"
        "Every new video starts with a question like this. Before I record it, "
        "I want to hear your answer: what do you think, and why?\n\n"
        "Tell me in the comments."
    ),
    "pt-BR": (
        "{topic}\n\n"
        "Todo novo vídeo começa com uma pergunta assim. Antes de gravar, "
        "quero ouvir a sua resposta: o que você acha, e por quê?\n\n"
        "Conte nos comentários."
    ),
}


def log(message: str) -> None:
    print(f"[community] {message}", flush=True)


def community_url() -> str:
    handle = config.CHANNEL.handle if config.CHANNEL else ""
    if handle:
        return f"https://www.youtube.com/{handle}/posts"
    return f"https://www.youtube.com/channel/{config.CHANNEL_ID}/community"


def open_community(page) -> None:
    """Open the channel's Posts tab; the /community URL no longer renders for every profile."""
    handle = config.CHANNEL.handle if config.CHANNEL else ""
    if handle:
        page.goto(f"https://www.youtube.com/{handle}", timeout=90000)
        page.wait_for_timeout(7000)
        for label in ("Posts", "Postagens"):
            tab = page.get_by_text(label, exact=True)
            if tab.count():
                tab.first.click()
                page.wait_for_timeout(5000)
                break
        return
    page.goto(community_url(), timeout=90000)
    page.wait_for_timeout(5000)


def post_text(topic: str, language: str = "en") -> str:
    question = topic.strip()
    if not question.endswith("?"):
        question += "?"
    template = TEXT.get(language, TEXT["en"])
    return template.format(topic=question)


def square_image(source: Path, destination: Path, size: int = 1080) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        fitted = ImageOps.fit(image.convert("RGB"), (size, size), Image.Resampling.LANCZOS,
                              centering=(0.5, 0.35))
        fitted.save(destination, format="PNG", optimize=True)
    destination.chmod(0o600)
    return destination


def relative_minutes(label: str) -> int | None:
    """Convert YouTube's relative post time to minutes, or None when unreadable."""
    text = " ".join(label.lower().split())
    if not text:
        return None
    if "agora" in text or "just now" in text:
        return 0
    words = {word: int(number) for number, word in re.findall(r"(\d+)\s+([a-zà-ÿ]+)", text)}
    for word, minutes in RELATIVE_UNITS.items():
        if word in words:
            return int(words[word] * minutes)
    if "uma hora" in text or "one hour" in text:
        return 60
    if "um minuto" in text or "one minute" in text:
        return 1
    if "um dia" in text or "one day" in text:
        return 1440
    return None


def sort_recent(page) -> None:
    for label in ("Mais recentes", "Newest"):
        tab = page.get_by_text(label, exact=True)
        if tab.count():
            tab.last.click()
            page.wait_for_timeout(2000)
            return


def latest_post_label(page) -> str:
    post = page.locator(POST_SELECTOR).first
    if not post.count():
        return ""
    label = post.locator("#published-time-text")
    if not label.count():
        return ""
    return label.first.inner_text().strip()


def posted_recently(page, now: datetime | None = None, hours: int = 24) -> bool:
    """One post per rolling 24 hours, not per calendar day."""
    current = now or datetime.now()
    label = latest_post_label(page)
    minutes = relative_minutes(label)
    if minutes is None:
        path = config.DATA_DIR / "community.json"
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entry = {}
        if entry.get("state") == "posted" and entry.get("at"):
            return current - datetime.fromisoformat(entry["at"]) < timedelta(hours=hours)
        return False
    return minutes <= hours * 60


def has_posts(page) -> bool:
    page.wait_for_timeout(2500)
    if page.locator(POST_SELECTOR).count():
        return True
    body = page.locator("body").inner_text()
    if any(marker in body for marker in EMPTY_MARKERS):
        return False
    composer = page.locator("ytd-comment-simplebox-renderer, [contenteditable=true]")
    if composer.count():
        return False
    raise RuntimeError("community page did not load or show the composer")


def _click_text(page, labels: tuple[str, ...]) -> bool:
    for label in labels:
        target = page.get_by_text(label, exact=True)
        if target.count():
            target.first.click()
            return True
    return False


def _open_create_dialog(page) -> None:
    for label in ("Criar", "Create"):
        button = page.get_by_role("button", name=label, exact=True)
        if button.count():
            button.first.click()
            break
    page.wait_for_timeout(1000)
    if not _click_text(page, ("Criar post", "Create post")):
        raise RuntimeError("create post entry is not available")
    page.wait_for_timeout(2500)


def _fill_message(page, text: str) -> None:
    editable = page.locator("[contenteditable=true]").last
    editable.click()
    editable.type(text)


def _select_image(page) -> None:
    for label in ("Imagem", "Image"):
        target = page.get_by_text(label, exact=True)
        if target.count():
            target.last.click()
            page.wait_for_timeout(1200)
            return
    raise RuntimeError("image option is not available")


def _attach_image(page, image: Path) -> None:
    page.locator("input[type=file]").last.set_input_files(str(image.resolve()))
    page.wait_for_timeout(6000)


def _publish(page) -> None:
    for label in ("Postar", "Post"):
        button = page.get_by_role("button", name=label, exact=True)
        if button.count():
            button.last.click()
            break
    page.wait_for_timeout(1500)
    for label in ("Publicar post", "Publish post"):
        confirm = page.get_by_role("button", name=label, exact=True)
        if confirm.count() and confirm.last.is_visible():
            confirm.last.click()
            break
    page.wait_for_timeout(6000)


def _confirmed(page) -> bool:
    for _ in range(6):
        body = page.locator("body").inner_text()
        if "Post publicado" in body or "Post published" in body:
            return True
        if page.locator(POST_SELECTOR).count():
            return True
        page.wait_for_timeout(5000)
    return False


HISTORY_FILE = "community-history.jsonl"


def _journal(entry: dict) -> None:
    """Keep the latest entry for the 24-hour check and append every transition to the
    append-only history that the desktop manager reads for monthly counts."""
    path = config.DATA_DIR / "community.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = dict(entry)
    if config.CHANNEL is not None:
        record.setdefault("channel", config.CHANNEL.slug)
    with (config.DATA_DIR / HISTORY_FILE).open("a", encoding="utf-8") as history:
        history.write(json.dumps(record, ensure_ascii=False) + "\n")


ART_STYLES = {
    "fallem-prince": "dark monochrome narrative engraving with etched midtones",
    "whispers-from-heaven": "warm brown engraving with fine stippling, sacred and quiet",
    "zaflas": "photorealistic Brazilian agribusiness at golden hour",
    "infinite-random-worlds": "cinematic speculative world in gold and deep teal",
    "vocal-pages": "dark navy and warm gold, contemplative cinematic still life",
    "zanata": "cinematic black and amber, restrained and bookish",
    "reflection": "full-bleed cinematic biblical scene with warm golden light",
}


def _generate_art(topic: str) -> Path | None:
    """One dedicated square image per post; never a crop of a video thumbnail."""
    from datetime import date
    from PIL import Image, ImageOps

    if not codex_media.available():
        return None
    slug = config.CHANNEL.slug if config.CHANNEL else "channel"
    style = ART_STYLES.get(slug, "cinematic")
    run_dir = config.DATA / "community" / "codex" / slug
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir.chmod(0o700)
    schema = {"type": "object", "properties": {"image_path": {"type": "string", "maxLength": 4096}},
              "required": ["image_path"], "additionalProperties": False}
    prompt = ("Create one square 1:1 image for a YouTube community post. No text, no letters, "
              "no numbers, no logos, no watermarks, no borders. Style: " + style +
              ". Illustrate this question: " + topic[:160])
    value = codex_media._execute(run_dir, f"art-{date.today():%Y%m%d}", prompt, schema,
                                 images=True)
    root = (Path.home() / ".codex" / "generated_images").resolve()
    source = codex_media._bounded_image(value.get("image_path", ""), root)
    if source is None:
        source = codex_media._recent_image(root, __import__("time").time() - 900)
    if source is None:
        return None
    destination = config.DATA / "community" / f"{slug}-{date.today():%Y%m%d}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        ImageOps.fit(image.convert("RGB"), (1080, 1080), Image.Resampling.LANCZOS).save(
            destination, format="PNG", optimize=True)
    destination.chmod(0o600)
    return destination


def _topic_image(topics: list[str]) -> tuple[str, Path | None]:
    for topic in topics:
        run_dir = logic.run_path(topic)
        thumbnail = run_dir / "thumbnail.png"
        if thumbnail.is_file():
            return topic, thumbnail
    return topics[0], None


def ensure_post(context, topics: list[str]) -> dict:
    page = context.new_page()
    try:
        open_community(page)
        sort_recent(page)
        if has_posts(page):
            if posted_recently(page):
                log("community already has a post in the last 24 hours; nothing to do")
                return {"state": "present"}
            log("community has no post today; publishing a new one")
        topic, _thumbnail = _topic_image(topics)
        text = post_text(topic, config.CHANNEL.language if config.CHANNEL else "en")
        image = _generate_art(topic)
        if image is None:
            log("dedicated post art is required; skipping the automatic post")
            return {"state": "skipped-art"}
        _open_create_dialog(page)
        _select_image(page)
        _fill_message(page, text)
        _attach_image(page, image)
        _journal({"state": "started", "topic": topic, "text": text,
                  "image": str(image) if image else None,
                  "at": datetime.now().isoformat(timespec="seconds")})
        _publish(page)
        if not _confirmed(page):
            _journal({"state": "unconfirmed", "topic": topic, "text": text,
                      "image": str(image) if image else None,
                      "at": datetime.now().isoformat(timespec="seconds")})
            raise RuntimeError("community post was not confirmed; inspect before retrying")
        entry = {"state": "posted", "topic": topic, "text": text,
                 "image": str(image) if image else None,
                 "at": datetime.now().isoformat(timespec="seconds")}
        _journal(entry)
        log(f"community post published: {topic}")
        return entry
    finally:
        page.close()
