"""Apply title, description, tags and thumbnail on a video edit page."""

from __future__ import annotations

import time
from pathlib import Path

from . import upload_dialog


def log(message: str) -> None:
    print(f"[details] {message}", flush=True)


def apply_details(page, run_dir: Path, meta: dict) -> None:
    upload_dialog.fill_editable(page, 0, meta["title"])
    upload_dialog.fill_editable(page, 1, meta["description"])
    thumbnail = run_dir / "thumbnail.png"
    field = page.locator('input[type=file][accept*="image"]')
    if thumbnail.is_file() and field.count():
        with page.expect_response(
                lambda response: "studiothumbnail" in response.url and response.status == 200,
                timeout=60000):
            field.last.set_input_files(str(thumbnail))
        page.wait_for_timeout(2000)
    tags = page.locator('input[aria-label="Tags"]')
    if tags.count():
        tags.first.fill(meta.get("tags", ""))
        tags.first.press("Enter")
        page.wait_for_timeout(500)
    save = page.locator("#save")
    if save.count() and save.get_attribute("aria-disabled") != "true":
        save.click()
        deadline = time.time() + 60
        while time.time() < deadline:
            if page.evaluate("()=>document.querySelector('#save')?.getAttribute('aria-disabled')") == "true":
                break
            page.wait_for_timeout(2000)
    log("details saved")
