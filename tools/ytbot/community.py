"""Check the channel community tab and publish a first question post when empty."""

from __future__ import annotations

import json
from datetime import datetime
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


def _open_create_dialog(page) -> None:
    page.get_by_role("button", name="Criar", exact=True).first.click()
    page.wait_for_timeout(1000)
    page.get_by_text("Criar post", exact=True).first.click()
    page.wait_for_timeout(2500)


def _fill_message(page, text: str) -> None:
    editable = page.locator("[contenteditable=true]").last
    editable.click()
    editable.type(text)


def _select_image(page) -> None:
    page.get_by_text("Imagem", exact=True).last.click()
    page.wait_for_timeout(1200)


def _attach_image(page, image: Path) -> None:
    page.locator("input[type=file]").last.set_input_files(str(image.resolve()))
    page.wait_for_selector("text=Editar visualização", timeout=60000)


def _publish(page) -> None:
    page.get_by_role("button", name="Postar", exact=True).last.click()
    page.wait_for_timeout(1500)
    confirm = page.get_by_role("button", name="Publicar post", exact=True)
    if confirm.count() and confirm.last.is_visible():
        confirm.last.click()
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
        if has_posts(page):
            log("community already has a post; nothing to do")
            return {"state": "present"}
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
