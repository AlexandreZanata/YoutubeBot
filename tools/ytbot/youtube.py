"""YouTube Studio upload, end screen and scheduled publishing."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from . import config, logic, runtime, upload_dialog, upload_guard, video_details


def log(message: str) -> None:
    print(f"[youtube] {message}", flush=True)


def click_text(page, names: list[str]) -> bool:
    for name in names:
        locator = page.get_by_text(name, exact=True)
        if locator.count():
            locator.first.click()
            return True
    return False


def video_id_from(page) -> str:
    match = re.search(r"/video/([A-Za-z0-9_-]{11})/", page.url)
    if match:
        return match.group(1)
    try:
        texts = page.get_by_text(re.compile(r"youtu\.be/[A-Za-z0-9_-]{11}")).all_inner_texts()
        found = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", " ".join(texts))
        if found:
            return found.group(1)
    except Exception:
        pass
    body = page.locator("body").inner_text()
    match = re.search(r"(?:Link do vídeo|Video link)\s*(https://youtu\.be/[A-Za-z0-9_-]+)", body, re.I)
    if not match:
        match = re.search(r"https://youtu\.be/([A-Za-z0-9_-]+)", body)
        return match.group(1) if match else ""
    return match.group(1).rsplit("/", 1)[-1]


def wait_for_video_id(page, timeout: int = 90) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        video_id = video_id_from(page)
        if video_id:
            return video_id
        page.wait_for_timeout(3000)
    return ""


def upload_video(context, run_dir: Path, meta: dict) -> str:
    page, video_id = open_upload(context, run_dir, meta)
    page.close()
    return video_id


def lookup_video_id(context, title: str, timeout: int = 90) -> str:
    """Find the draft by its unique title when the dialog link stays pending."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        page = context.new_page()
        try:
            page.goto(config.STUDIO_UPLOAD, timeout=90000)
            page.wait_for_timeout(6000)
            rows = page.evaluate("""(title) => [...document.querySelectorAll('ytcp-video-row')]
                .filter(r => (r.innerText || '').includes(title))
                .map(r => (r.querySelector('a') || {}).href || '')""", title)
            for href in rows:
                found = re.search(r"/video/([A-Za-z0-9_-]{11})/", href or "")
                if found:
                    return found.group(1)
        finally:
            page.close()
        time.sleep(4)
    return ""


def open_upload(context, run_dir: Path, meta: dict, require_id: bool = True):
    page = context.new_page()
    page.goto(config.STUDIO_UPLOAD, timeout=90000)
    runtime.select_channel(page)
    upload_guard.page_blocked(page)
    try:
        page.get_by_role("button", name="Criar", exact=True).first.click()
    except Exception:
        page.get_by_role("button", name="Create", exact=True).first.click()
    page.wait_for_timeout(1200)
    click_text(page, ["Enviar vídeos", "Upload videos"])
    page.wait_for_timeout(1500)
    page.wait_for_selector('input[type=file][name="Filedata"]', state="attached", timeout=60000)
    staging = config.ROOT / ".local/ytbot/upload-tmp"
    staging.mkdir(parents=True, exist_ok=True)
    upload_file = staging / f"upload-{run_dir.name}.mp4"
    upload_file.unlink(missing_ok=True)
    try:
        os.link(run_dir / "video.mp4", upload_file)
    except OSError:
        # Different filesystem or a filesystem without hard links.
        shutil.copy2(run_dir / "video.mp4", upload_file)
    upload_dialog.set_file_input(page, str(upload_file))
    page.wait_for_selector("#textbox", state="attached", timeout=120000)
    page.wait_for_timeout(4000)
    upload_dialog.fill_editable(page, 0, meta["title"])
    upload_dialog.fill_editable(page, 1, meta["description"])
    try:
        upload_dialog.answer_audience(page)
        log("audience set to not made for kids")
    except Exception as error:
        log(f"audience pending on the draft: {error}")
    try:
        upload_guard.wait_upload(page)
        try:
            upload_dialog.ensure_title(page, meta["title"])
        except Exception as error:
            log(f"title will be re-applied on the edit page: {error}")
        video_id = wait_for_video_id(page)
        if not video_id and require_id:
            video_id = lookup_video_id(context, meta["title"])
        if not video_id and require_id:
            raise RuntimeError("could not read the uploaded video id")
    except Exception:
        page.close()
        raise
    finally:
        upload_file.unlink(missing_ok=True)
    log(f"uploaded video id: {video_id}")
    return page, video_id


def open_edit(context, video_id: str):
    page = context.new_page()
    page.goto(config.STUDIO_EDIT.format(video_id=video_id), timeout=90000)
    page.wait_for_timeout(8000)
    upload_guard.page_blocked(page)
    return page


def add_end_screen(page) -> None:
    page.get_by_text("Tela final", exact=True).last.click()
    page.wait_for_timeout(4000)
    page.locator("#add-element-menu-button").first.click()
    page.wait_for_timeout(1000)
    page.evaluate("""()=>{const els=[...document.querySelectorAll('tp-yt-paper-item')]; const v=els.find(e=>(e.innerText||'').trim()==='Vídeo'); if(v)v.click()}""")
    page.wait_for_timeout(1800)
    page.evaluate("""()=>{const r=[...document.querySelectorAll('tp-yt-paper-radio-button')].find(e=>/melhor para o espectador/i.test(e.innerText||'')); if(r)r.click()}""")
    page.wait_for_timeout(1200)
    log("end screen video element set to best for viewer")
    page.locator("#add-element-menu-button").first.click()
    page.wait_for_timeout(1000)
    page.evaluate("""()=>{const els=[...document.querySelectorAll('tp-yt-paper-item')]; const v=els.find(e=>(e.innerText||'').trim()==='Inscrever-se'); if(v)v.click()}""")
    page.wait_for_timeout(1200)
    page.evaluate("""()=>{const modal=document.querySelector('ytve-endscreen-modal')||document; const b=[...modal.querySelectorAll('#save-button, button, ytcp-button')].filter(e=>e.offsetWidth>0 && /salvar|save/i.test((e.innerText||''))).pop(); if(b)b.click()}""")
    page.wait_for_timeout(4000)
    log("end screen saved")


def wait_for_checks(page, timeout: int = 1800) -> None:
    deadline = time.time() + timeout
    stable = 0
    while time.time() < deadline:
        body = page.locator("body").inner_text()
        match = re.search(r"Verifica[çc][ãa]o\s+(\d+)%", body)
        if match:
            stable = 0
            page.wait_for_timeout(20000)
            continue
        stable += 1
        if stable >= 2:
            return
        page.wait_for_timeout(20000)


def write_result(run_dir: Path, result: dict) -> None:
    (run_dir / "upload.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def open_upload_dialog(context, video_id: str, title: str = ""):
    page = open_edit(context, video_id)
    draft = page.get_by_text("Editar rascunho", exact=True)
    if not draft.count():
        draft = page.get_by_text("Edit draft", exact=True)
    if draft.count():
        draft.first.click()
        page.wait_for_timeout(8000)
        return page
    page.close()
    url = (config.STUDIO_UPLOAD + "?d=ud&filter=%5B%5D&sort=%7B%22columnType%22%3A%22date%22%2C%22sortOrder%22%3A%22DESCENDING%22%7D&udvid=" + video_id)
    page = context.new_page()
    page.goto(url, timeout=90000)
    page.wait_for_timeout(8000)
    if page.locator("#step-badge-3").count() == 0 and title:
        page.goto(config.STUDIO_UPLOAD, timeout=90000)
        page.wait_for_timeout(10000)
        link = page.get_by_text(title, exact=True)
        if link.count():
            link.first.click()
            page.wait_for_timeout(7000)
    return page


def upload_and_schedule_short(context, run_dir: Path, meta: dict, slot) -> dict:
    """Upload and schedule in one dialog, without the edit page or custom tags."""
    upload_guard.preflight(run_dir, meta)
    page, video_id = open_upload(context, run_dir, meta, require_id=False)
    schedule_error = None
    try:
        if (run_dir / "thumbnail.png").is_file():
            upload_dialog.set_thumbnail(page, run_dir / "thumbnail.png")
        upload_dialog.schedule_in_dialog(page, slot)
    except Exception as error:
        schedule_error = error
    finally:
        page.close()
    video_id = video_id or lookup_video_id(context, meta["title"])
    if not video_id:
        raise schedule_error or RuntimeError("could not find the short in Studio")
    if not upload_dialog.scheduled_at(context, video_id, slot):
        raise schedule_error or RuntimeError("the short schedule was not confirmed")
    result = {"videoId": video_id, "url": f"https://youtu.be/{video_id}",
              "slot": logic.slot_label(slot), "visibility": "scheduled",
              "endScreen": False, "customThumbnail": False, "scheduled": True}
    write_result(run_dir, result)
    log(f"scheduled {video_id} at {result['slot']}")
    return result


def schedule_existing(context, run_dir: Path, result: dict, slot) -> dict:
    title = ""
    try:
        title = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8")).get("title", "")
    except (OSError, ValueError):
        pass
    if upload_dialog.scheduled_at(context, result["videoId"], slot):
        result["scheduled"] = True
        result["slot"] = logic.slot_label(slot)
        write_result(run_dir, result)
        log(f"scheduled {result['videoId']} at {result['slot']}")
        return result
    for attempt in range(2):
        page = open_upload_dialog(context, result["videoId"], title)
        try:
            upload_dialog.schedule_in_dialog(page, slot)
        except Exception as error:
            log(f"schedule attempt {attempt + 1} failed: {error}")
        finally:
            page.close()
        if upload_dialog.scheduled_at(context, result["videoId"], slot):
            result["scheduled"] = True
            result["slot"] = logic.slot_label(slot)
            write_result(run_dir, result)
            log(f"scheduled {result['videoId']} at {result['slot']}")
            return result
        log(f"schedule not confirmed, retry {attempt + 1}")
    raise RuntimeError("could not confirm the schedule")


def upload_and_schedule_with_context(context, run_dir: Path, meta: dict, slot, *,
                                     custom_thumbnail: bool = True, end_screen: bool = True) -> dict:
    upload_guard.preflight(run_dir, meta)
    video_id = upload_video(context, run_dir, meta)
    result = {"videoId": video_id, "url": f"https://youtu.be/{video_id}",
              "slot": logic.slot_label(slot), "visibility": "scheduled",
              "endScreen": False, "scheduled": False}
    write_result(run_dir, result)
    page = open_edit(context, video_id)
    try:
        video_details.apply_details(page, run_dir, meta, custom_thumbnail=custom_thumbnail)
        if end_screen:
            wait_for_checks(page)
            try:
                add_end_screen(page)
                upload_guard.verify_end_screen(page)
            except Exception as error:
                log(f"end screen warning: {error}")
    finally:
        page.close()
    result["endScreen"] = end_screen
    write_result(run_dir, result)
    return schedule_existing(context, run_dir, result, slot)
