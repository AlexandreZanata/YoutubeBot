"""Publish one reviewed agenda item on X with a durable, no-retry fence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ... import config
from .. import agenda
from ..store import SocialStore


def log(message: str) -> None:
    print(f"[social] {message}", flush=True)


def _visible_dialog(page):
    dialog = page.locator('[role="dialog"]:visible').last
    dialog.wait_for(state="visible", timeout=30000)
    return dialog


def _fill_editor(dialog, text: str) -> None:
    editor = dialog.locator('[data-testid="tweetTextarea_0"]').first
    editor.click()
    editor.page.keyboard.insert_text(text)
    editor.page.wait_for_timeout(800)


def _image_path(item: dict) -> Path | None:
    value = item.get("image")
    if not value:
        if item["format"] == "image":
            raise RuntimeError(f"{item['id']} is an image post without an image")
        return None
    path = Path(value).expanduser().resolve()
    allowed = (config.ROOT / ".local").resolve()
    if not path.is_relative_to(allowed) or not path.is_file():
        raise RuntimeError("the post image must be a real file under .local")
    if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise RuntimeError("the post image must be PNG, JPG or WEBP")
    if path.stat().st_size > 5 * 1024 * 1024:
        raise RuntimeError("the post image must be at most 5 MB")
    return path


def _attach_image(dialog, path: Path) -> None:
    dialog.locator('input[data-testid="fileInput"]').last.set_input_files(str(path))
    dialog.page.wait_for_selector('[data-testid="attachments"]', timeout=60000)


def _wait_enabled(button, timeout: int = 30) -> None:
    for _ in range(timeout * 2):
        if button.is_enabled():
            return
        button.page.wait_for_timeout(500)
    raise RuntimeError("the X post button did not become enabled")


def _tweet_url(page) -> str:
    toast = page.locator('[data-testid="toast"]')
    if toast.count():
        link = toast.locator('a[href*="/status/"]')
        if link.count():
            href = link.first.get_attribute("href") or ""
            return href if href.startswith("http") else "https://x.com" + href
    return ""


def _confirmed(page) -> bool:
    for _ in range(20):
        body = page.locator("body").inner_text()
        if any(marker in body for marker in (
                "Seu post foi enviado", "Your post was sent", "Post enviado", "Post sent")):
            return True
        if page.locator('[role="dialog"]:visible').count() == 0:
            return True
        page.wait_for_timeout(1000)
    return False


def publish(context, store: SocialStore, network: str, item: dict, *,
            dry_run: bool = False) -> dict:
    if item["format"] not in ("text", "image"):
        raise RuntimeError(f"{item['id']} is a {item['format']} item; this publisher supports text and image only")
    text = agenda.render_text(item)
    length = agenda.x_length(text)
    if length > 280:
        raise RuntimeError(f"{item['id']} is {length} characters on X; the limit is 280")
    digest = agenda.text_hash(text)
    previous = agenda.already_posted(store, network, item["id"], digest)
    if previous:
        raise RuntimeError(
            f"{item['id']} is already {previous.get('state', 'recorded')} in the private journal; "
            "inspect it before retrying")
    if item["status"] != "approved":
        raise RuntimeError(f"{item['id']} is {item['status']}; approve the copy before posting")
    image = _image_path(item)

    page = context.new_page()
    try:
        page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        dialog = _visible_dialog(page)
        _fill_editor(dialog, text)
        if image:
            _attach_image(dialog, image)
            if item.get("alt_text"):
                alt = dialog.get_by_role("button", name="Adicionar descrição")
                if alt.count():
                    alt.first.click()
                    page.wait_for_timeout(500)
                    page.keyboard.insert_text(item["alt_text"])
                    page.get_by_role("button", name="Salvar").last.click()
                    page.wait_for_timeout(500)
        button = dialog.locator('[data-testid="tweetButton"]').last
        _wait_enabled(button)
        if dry_run:
            page.wait_for_timeout(1000)
            return {"state": "dry-run", "length": length, "text": text,
                    "image": str(image) if image else None}
        agenda.save_post(store, network, item["id"], {
            "state": "started", "item_id": item["id"], "text_sha256": digest,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "image": str(image) if image else None,
        })
        button.click()
        page.wait_for_timeout(4000)
        confirmed = _confirmed(page)
        result = {
            "state": "posted" if confirmed else "unconfirmed",
            "item_id": item["id"],
            "text_sha256": digest,
            "tweet_url": _tweet_url(page),
            "posted_at": datetime.now().isoformat(timespec="seconds"),
            "image": str(image) if image else None,
        }
        agenda.save_post(store, network, item["id"], result)
        if not confirmed:
            raise RuntimeError("the X post was not confirmed; inspect before any retry")
        log(f"posted {item['id']}: {result['tweet_url'] or 'URL pending'}")
        return result
    except Exception:
        current = agenda.read_posts(store, network).get("posts", {}).get(item["id"])
        if current and current.get("state") == "started":
            agenda.save_post(store, network, item["id"], {
                **current,
                "state": "unconfirmed",
                "unconfirmed_at": datetime.now().isoformat(timespec="seconds"),
            })
        raise
    finally:
        page.close()
