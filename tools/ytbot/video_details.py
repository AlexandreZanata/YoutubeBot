"""Apply title, description and thumbnail on a video edit page."""

from __future__ import annotations

import time
from pathlib import Path

from . import upload_dialog
from .upload_guard import UploadBlocked


def log(message: str) -> None:
    print(f"[details] {message}", flush=True)


def apply_details(page, run_dir: Path, meta: dict) -> None:
    upload_dialog.fill_editable(page, 0, meta["title"])
    upload_dialog.fill_editable(page, 1, meta["description"])
    thumbnail = run_dir / "thumbnail.png"
    field = page.locator('input[type=file][accept*="image"]')
    if thumbnail.is_file() and field.count():
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
    log("details saved")
