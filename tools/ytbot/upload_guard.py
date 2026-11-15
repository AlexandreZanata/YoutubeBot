"""Bounded upload preflight, page checks and recovery helpers."""

from __future__ import annotations

import time
from pathlib import Path


class UploadBlocked(RuntimeError):
    """An operator-actionable upload failure; never retry this blindly."""


def log(message: str) -> None:
    print(f"[upload] {message}", flush=True)


def preflight(run_dir: Path, meta: dict) -> None:
    video = run_dir / "video.mp4"
    if not video.is_file() or video.stat().st_size == 0:
        raise UploadBlocked("video.mp4 is missing; render the topic before uploading")
    if not (meta.get("title") or "").strip():
        raise UploadBlocked("metadata title is missing; regenerate metadata before uploading")
    if not (meta.get("description") or "").strip():
        raise UploadBlocked("metadata description is missing; regenerate metadata before uploading")
    thumbnail = run_dir / "thumbnail.png"
    if not thumbnail.is_file() or thumbnail.stat().st_size == 0:
        raise UploadBlocked("thumbnail.png is missing; retry the Codex thumbnail before uploading")
    try:
        from PIL import Image
        with Image.open(thumbnail) as image:
            if image.width < 640 or image.height < 360:
                raise UploadBlocked("thumbnail.png is too small; regenerate it")
    except UploadBlocked:
        raise
    except Exception as error:
        raise UploadBlocked(f"thumbnail.png is not a valid image: {error}") from error


def page_blocked(page) -> None:
    body = page.locator("body").inner_text()
    if "Fazer login" in body or "Sign in" in body:
        raise UploadBlocked("YouTube session expired; sign in to the bot profile")
    if "Selecione um canal" in body or "Select a channel" in body:
        raise UploadBlocked("YouTube channel selection is required; select the channel in the bot profile")


def wait_upload(page, timeout: int = 900) -> None:
    deadline = time.time() + timeout
    last = 0.0
    while time.time() < deadline:
        if (page.get_by_text("Envio concluído").count()
                or page.get_by_text("Upload complete").count()
                or page.get_by_text("processamento vai começar").count()):
            log("upload complete")
            return
        if page.get_by_text("Arquivo ilegível").count():
            raise UploadBlocked("Studio cannot read the staged upload file")
        if time.time() - last > 60:
            compact = " ".join(page.locator("body").inner_text().split())
            log(f"upload still running: {compact[:180]}")
            last = time.time()
        page.wait_for_timeout(3000)
    raise UploadBlocked("upload did not finish within 15 minutes; check the connection and Studio")


def verify_end_screen(page) -> None:
    for _ in range(3):
        try:
            page.get_by_text("Tela final", exact=True).last.click()
            page.wait_for_timeout(3000)
        except Exception:
            pass
        body = page.locator("body").inner_text()
        checked = page.evaluate(
            "()=>[...document.querySelectorAll('tp-yt-paper-radio-button')]"
            ".some(e=>/melhor para o espectador/i.test(e.innerText||'')"
            " && (e.hasAttribute('checked')||e.getAttribute('aria-checked')==='true'))")
        if "Melhor para o espectador" in body and "Inscrever-se" in body and checked:
            return
        page.wait_for_timeout(2000)
    raise UploadBlocked("end screen missing Best for viewer or Subscribe; retry the end screen")
