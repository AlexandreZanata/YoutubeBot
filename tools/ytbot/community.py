"""Publish one question post per calendar day when the Community tab has none for today."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageOps

from . import config, logic

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
    return f"https://www.youtube.com/channel/{config.CHANNEL_ID}/community"


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


def posted_today(page, now: datetime | None = None) -> bool:
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
            return datetime.fromisoformat(entry["at"]).date() == current.date()
        return False
    return (current - timedelta(minutes=minutes)).date() == current.date()


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


def _journal(entry: dict) -> None:
    path = config.DATA_DIR / "community.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        page.goto(community_url(), timeout=90000)
        sort_recent(page)
        if has_posts(page):
            if posted_today(page):
                log("community already has a post today; nothing to do")
                return {"state": "present"}
            log("community has no post today; publishing a new one")
        topic, thumbnail = _topic_image(topics)
        text = post_text(topic, config.CHANNEL.language if config.CHANNEL else "en")
        _open_create_dialog(page)
        image = None
        if thumbnail is not None:
            _select_image(page)
        _fill_message(page, text)
        if thumbnail is not None:
            image = square_image(thumbnail, config.DATA_DIR / "community" / f"{logic.slug(topic)}.png")
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
