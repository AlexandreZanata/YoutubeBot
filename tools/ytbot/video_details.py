"""Apply title, description and thumbnail on a video edit page."""

from __future__ import annotations

import time
from pathlib import Path

from . import upload_dialog
from .upload_guard import UploadBlocked


def log(message: str) -> None:
    print(f"[details] {message}", flush=True)


def _show_more(page) -> None:
    if page.locator('input[aria-label="Tags"]').count():
        return
    for label in ("Mostrar mais", "Show more"):
        more = page.get_by_text(label, exact=True)
        if more.count():
            more.last.click()
            page.wait_for_timeout(2000)
            return


def _tag_bar(page):
    return page.locator("ytcp-chip-bar").first


def _apply_tags(page, meta: dict) -> None:
    tags = [tag.strip() for tag in meta.get("tags", "").split(",") if tag.strip()]
    if not tags:
        return
    _show_more(page)
    field = page.locator('input[aria-label="Tags"]')
    if not field.count():
        raise UploadBlocked("tags field was not available on the edit page")
    existing = [text.strip() for text in _tag_bar(page).locator("ytcp-chip").all_inner_texts()]
    if existing:
        return
    field.click()
    for tag in tags:
        page.keyboard.type(tag + ",", delay=10)
    page.keyboard.press("Tab")
    page.wait_for_timeout(800)


def apply_thumbnail(page, run_dir: Path) -> None:
    """Upload only the custom thumbnail and save the edit page."""
    thumbnail = run_dir / "thumbnail.png"
    if not thumbnail.is_file():
        raise UploadBlocked("thumbnail.png is missing; cannot apply it")
    field = page.locator('input[type=file][accept*="image"]')
    if not field.count():
        raise UploadBlocked("thumbnail input is not available on the edit page")
    try:
        with page.expect_response(
                lambda response: "studiothumbnail" in response.url and response.status == 200,
                timeout=90000):
            field.last.set_input_files(str(thumbnail))
    except Exception as error:
        raise UploadBlocked("thumbnail upload did not complete") from error
    page.wait_for_timeout(2500)
    save = page.locator("#save")
    if save.count() and save.get_attribute("aria-disabled") != "true":
        save.click()
        deadline = time.time() + 60
        while time.time() < deadline:
            if page.evaluate("()=>document.querySelector('#save')?.getAttribute('aria-disabled')") == "true":
                break
            page.wait_for_timeout(2000)
        else:
            raise UploadBlocked("thumbnail save did not finish")
    log("thumbnail saved")


def apply_details(page, run_dir: Path, meta: dict, *, custom_thumbnail: bool = True) -> None:
    upload_dialog.fill_editable(page, 0, meta["title"])
    upload_dialog.fill_editable(page, 1, meta["description"])
    try:
        _apply_tags(page, meta)
    except Exception as error:
        log(f"tags warning: {error}")
    thumbnail = run_dir / "thumbnail.png"
    field = page.locator('input[type=file][accept*="image"]')
    if custom_thumbnail and thumbnail.is_file() and field.count():
        try:
            with page.expect_response(
                    lambda response: "studiothumbnail" in response.url and response.status == 200,
                    timeout=60000):
                field.last.set_input_files(str(thumbnail))
        except Exception as error:
            raise UploadBlocked("thumbnail upload did not complete; retry the details step") from error
        page.wait_for_timeout(2000)
    save = page.locator("#save")
    if save.count() and save.get_attribute("aria-disabled") != "true":
        save.click()
        deadline = time.time() + 60
        while time.time() < deadline:
            if page.evaluate("()=>document.querySelector('#save')?.getAttribute('aria-disabled')") == "true":
                break
            page.wait_for_timeout(2000)
        else:
            raise UploadBlocked("details save did not finish; retry the details step")
    page.reload()
    page.wait_for_timeout(9000)
    title = page.evaluate("()=>document.querySelectorAll('#textbox')[0]?.innerText || ''")
    description = page.evaluate("()=>document.querySelectorAll('#textbox')[1]?.innerText || ''")
    if title.strip() != meta["title"].strip() or not description.strip():
        raise UploadBlocked("title or description did not persist; retry the details step")
    expected = [tag.strip() for tag in meta.get("tags", "").split(",") if tag.strip()]
    if expected:
        _show_more(page)
        saved = [text.strip() for text in _tag_bar(page).locator("ytcp-chip").all_inner_texts()]
        if not set(expected).issubset(set(saved)):
            raise UploadBlocked("tags did not persist; retry the details step")
    log("details saved")
