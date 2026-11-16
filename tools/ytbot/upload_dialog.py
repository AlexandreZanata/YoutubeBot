"""Schedule a video from the YouTube upload dialog."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import config, logic


def answer_audience(page) -> None:
    if not page.locator('ytkc-made-for-kids-select').count():
        return
    page.evaluate(
        "()=>{document.querySelectorAll('ytkc-made-for-kids-select').forEach(c=>{"
        "const g=c.querySelector('tp-yt-paper-radio-group.made-for-kids-group');"
        "if(g)g.selected='VIDEO_MADE_FOR_KIDS_NOT_MFK';"
        "c.madeForKids='VIDEO_MADE_FOR_KIDS_NOT_MFK';"
        "c.onMadeForKidsRatingChange({detail:{selected:'VIDEO_MADE_FOR_KIDS_NOT_MFK'}})})}")
    page.wait_for_timeout(700)
    checked = page.evaluate(
        "()=>[...document.querySelectorAll('ytkc-made-for-kids-select')]"
        ".every(c=>c.madeForKids==='VIDEO_MADE_FOR_KIDS_NOT_MFK'"
        " && !c.getAttribute('crosswalk-rating-error'))")
    if not checked:
        raise RuntimeError("could not answer the audience question")


def _show_visibility(page) -> None:
    page.evaluate("()=>{const b=document.querySelector('#step-badge-3'); if(b)b.click()}")
    page.wait_for_timeout(2500)
    for _ in range(3):
        if page.locator("#datepicker-trigger").is_visible():
            return
        button = page.locator("#next-button")
        if button.count() and button.first.is_visible() and button.first.get_attribute("aria-disabled") != "true":
            page.evaluate("()=>{const b=document.querySelector('#next-button'); if(b)b.click()}")
        page.wait_for_timeout(2500)


def log(message: str) -> None:
    print(f"[schedule] {message}", flush=True)


def _calendar_date(page, slot) -> bool:
    month = logic.format_pt_date(slot.date()).split(" de ")[1][:3].upper()
    for section in page.locator(".calendar-month").all():
        text = section.inner_text().upper()
        if month not in text or str(slot.year) not in text:
            continue
        day = section.get_by_text(str(slot.day), exact=True)
        if day.count():
            day.first.evaluate("el=>el.click()")
            return True
    return False


def _set_date(page, slot) -> None:
    if page.locator("ytcp-date-picker input").count():
        field = page.locator("ytcp-date-picker input").first
        field.fill(logic.format_pt_date(slot.date()))
        field.press("Enter")
    else:
        page.evaluate("()=>{const b=document.querySelector('#datepicker-trigger'); if(b)b.click()}")
        page.wait_for_timeout(1500)
        if not _calendar_date(page, slot):
            raise RuntimeError("could not select the schedule date")
    page.wait_for_timeout(1000)
    time_input = page.locator("#time-of-day-container input")
    if time_input.count():
        time_input.first.fill(slot.strftime("%H:%M"))
        time_input.first.press("Enter")
        page.wait_for_timeout(1000)


def schedule_in_dialog(page, slot) -> None:
    log("answering audience")
    answer_audience(page)
    _show_visibility(page)
    if not page.locator("#datepicker-trigger").count() and not page.locator("ytcp-date-picker input").count():
        page.evaluate("()=>{const e=[...document.querySelectorAll('*')].find(x=>x.children.length===0 && ['Programar','Schedule'].includes((x.innerText||'').trim())); if(e){const c=e.closest('#second-container')||e.parentElement; if(c)c.click()}}")
        page.wait_for_timeout(2500)
    if not page.locator("#datepicker-trigger").count() and not page.locator("ytcp-date-picker input").count():
        raise RuntimeError("the schedule dialog did not open")
    log("waiting for checks")
    deadline = time.time() + 300
    while time.time() < deadline:
        body = page.locator("body").inner_text()
        state = page.evaluate(
            "()=>{const b=document.querySelector('#done-button'); return b?{text:(b.innerText||'').trim(),disabled:b.getAttribute('aria-disabled')}:null}")
        if state and state.get("disabled") != "true" and ("Verificações concluídas" in body or "Checks complete" in body):
            break
        if not page.locator("#step-badge-3").count() and not page.locator("#datepicker-trigger").count():
            raise RuntimeError("the dialog closed during checks")
        page.wait_for_timeout(5000)
    else:
        raise RuntimeError("video checks did not finish")
    log("setting schedule date")
    if not page.locator("#datepicker-trigger").count() and not page.locator("ytcp-date-picker input").count():
        page.evaluate("()=>{const e=[...document.querySelectorAll('*')].find(x=>x.children.length===0 && ['Programar','Schedule'].includes((x.innerText||'').trim())); if(e){const c=e.closest('#second-container')||e.parentElement; if(c)c.click()}}")
        page.wait_for_timeout(2500)
    if not page.locator("#datepicker-trigger").is_visible():
        page.evaluate("()=>{const b=document.querySelector('#second-container-expand-button'); if(b)b.click()}")
        page.wait_for_timeout(1500)
    _set_date(page, slot)
    model = page.evaluate(
        "()=>document.querySelector('#publish-from-private-non-sponsor-selector')?.getAttribute('model')")
    if not model:
        raise RuntimeError("schedule model was not created")
    parsed = json.loads(model)
    expected = {"year": slot.year, "month": slot.month - 1, "day": slot.day}
    if parsed.get("date") != expected or parsed.get("selectedTimeOfDayValue") != slot.hour * 3600:
        raise RuntimeError(f"schedule model mismatch: {model}")
    log("clicking schedule")
    deadline = time.time() + 180
    words = ("Programar", "Schedule", "Salvar", "Save", "Concluir", "Done", "Publish")
    while time.time() < deadline:
        state = page.evaluate(
            "()=>{const b=document.querySelector('#done-button'); return b?{text:(b.innerText||'').trim(),disabled:b.getAttribute('aria-disabled')}:null}")
        if state and state.get("disabled") != "true" and any(word in state.get("text", "") for word in words):
            break
        page.wait_for_timeout(3000)
    else:
        raise RuntimeError("schedule button did not become ready")
    page.evaluate("()=>{const b=document.querySelector('#done-button'); if(b)b.click()}")
    page.wait_for_timeout(10000)


def scheduled_at(context, video_id: str, slot) -> bool:
    for attempt in range(3):
        page = context.new_page()
        matched = False
        try:
            page.goto(config.STUDIO_EDIT.format(video_id=video_id), timeout=90000)
            page.wait_for_timeout(8000)
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1200)
            if page.evaluate("()=>document.querySelector('#visibility-text')?.innerText") in ("Programado", "Scheduled"):
                for name in ("Editar status de visibilidade", "Edit video visibility status", "Edit visibility"):
                    button = page.get_by_role("button", name=name)
                    if not button.count():
                        continue
                    button.click()
                    page.wait_for_timeout(1500)
                    model = page.evaluate(
                        "()=>document.querySelector('#publish-from-private-non-sponsor-selector')?.getAttribute('model')")
                    if model:
                        parsed = json.loads(model)
                        expected = {"year": slot.year, "month": slot.month - 1, "day": slot.day}
                        matched = (parsed.get("date") == expected
                                   and parsed.get("selectedTimeOfDayValue") == slot.hour * 3600)
                    break
        except Exception:
            pass
        finally:
            page.close()
        if matched:
            return True
        if attempt < 2:
            time.sleep(3)
    return False


def fill_editable(page, index: int, text: str) -> None:
    page.evaluate("(i)=>{const e=document.querySelectorAll('#textbox')[i]; if(e)e.focus()}", index)
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    page.keyboard.insert_text(text)
    page.wait_for_timeout(350)


def ensure_title(page, title: str) -> None:
    for _ in range(3):
        current = page.evaluate("()=>document.querySelectorAll('#textbox')[0]?.innerText || ''")
        if current.strip() == title.strip():
            return
        fill_editable(page, 0, title)
        page.wait_for_timeout(800)
    raise RuntimeError("YouTube overwrote the video title")


def set_thumbnail(page, path) -> None:
    button = page.get_by_text("Enviar arquivo", exact=True)
    if not button.count():
        raise RuntimeError("the thumbnail upload button is not available")
    with page.expect_file_chooser() as chooser:
        button.first.click()
    chooser.value.set_files(str(path))
    page.wait_for_timeout(6000)
    log(f"thumbnail uploaded: {Path(path).name}")


def set_file_input(page, path: str) -> None:
    client = page.context.new_cdp_session(page)
    client.send("DOM.enable")
    expression = """(() => {
      const found = [];
      const walk = (root) => {
        for (const el of root.querySelectorAll('*')) {
          if (el.tagName === 'INPUT' && el.type === 'file' && el.name === 'Filedata') found.push(el);
          if (el.shadowRoot) walk(el.shadowRoot);
        }
      };
      walk(document);
      return found.length ? found[found.length - 1] : null;
    })()"""
    result = client.send("Runtime.evaluate", {"expression": expression, "returnByValue": False})
    object_id = result.get("result", {}).get("objectId")
    if not object_id:
        raise RuntimeError("upload file input not found")
    client.send("DOM.setFileInputFiles", {"files": [path], "objectId": object_id})
