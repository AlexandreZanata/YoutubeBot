"""ChatGPT article generation and Read aloud audio capture."""

from __future__ import annotations

import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, logic

INPUT_LOCK = threading.Lock()


def log(message: str) -> None:
    print(f"[chat] {message}", flush=True)


def dismiss_notice(page) -> None:
    button = page.get_by_text("Keep using GPT", exact=True)
    if button.count():
        button.first.click(force=True)
        page.wait_for_timeout(1200)


def send_text(page, text: str) -> None:
    # Input focus is shared by the dedicated browser, even across CDP clients.
    with INPUT_LOCK:
        page.bring_to_front()
        deadline = time.time() + 120
        editor = None
        while time.time() < deadline:
            dismiss_notice(page)
            candidate = page.get_by_role("textbox")
            if candidate.count() and candidate.first.is_visible():
                editor = candidate.first
                break
            page.wait_for_timeout(1500)
        if editor is None:
            raise TimeoutError("ChatGPT editor did not become visible")
        editor.fill(text)
        page.wait_for_timeout(400)
        send = page.locator('button[aria-label="Send"]')
        if send.count() and send.first.is_enabled() and send.first.get_attribute("aria-disabled") != "true":
            send.first.click()
        else:
            editor.press("Enter")
        page.wait_for_function(
            "() => !document.querySelector('[role=\"textbox\"]')?.innerText.trim()",
            timeout=15000,
        )
        page.wait_for_timeout(500)


def _assistant_response(page) -> str:
    body = page.locator("body").inner_text()
    marker = "ChatGPT said:"
    start = body.rfind(marker)
    text = body[start + len(marker):] if start != -1 else body
    for stop in ("ChatGPT can make mistakes", "Latest response",
                 "Simple Deep Dive is now a plugin", "Thinking effort",
                 "Do you like this personality?", "Connection interrupted",
                 "Use plugin"):
        index = text.find(stop)
        if index != -1:
            text = text[:index]
    return text.strip()


def extract_assistant_text(page) -> str:
    return clean_article(_assistant_response(page))


def wait_for_assistant(page, timeout: int = 3600) -> None:
    deadline = time.time() + timeout
    stable = 0
    last_len = 0
    while time.time() < deadline:
        body = page.locator("body").inner_text()
        if "Something went wrong" in body or "Error generating" in body:
            raise RuntimeError("ChatGPT reported a generation error")
        length = len(body)
        stop = page.locator('[data-testid="stop-button"], button[aria-label="Stop"]')
        streaming = stop.count() > 0 and stop.first.is_visible()
        answered = "ChatGPT said:" in body
        if answered and not streaming and length and length == last_len:
            stable += 1
            if stable >= 2:
                page.wait_for_timeout(1000)
                return
        else:
            stable = 0
        last_len = length
        page.wait_for_timeout(2000)
    raise TimeoutError("assistant response did not finish")


def copy_last(page) -> str:
    # Read this page's response directly. The desktop clipboard is global and
    # can mix responses or wait on a permission prompt in background tabs.
    return _assistant_response(page)


def clean_article(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("—", ",").replace("–", ",")
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def ensure_logged_in(page) -> None:
    """Only fires when the ChatGPT session is really gone."""
    url = page.url if isinstance(page.url, str) else ""
    try:
        body = page.locator("body").inner_text()
    except Exception:
        body = ""
    body = body[:600] if isinstance(body, str) else ""
    if url.startswith("https://chatgpt.com/auth") or "Log in" in body or "Entrar" in body:
        from . import runtime
        runtime.request_login("https://chatgpt.com/auth/login", "ChatGPT session expired")
        raise RuntimeError("ChatGPT session expired; finish the sign-in in the window that opened")


def generate_article(page, topic: str, run_dir: Path, extra_header: str = "") -> str:
    page.goto(config.GPT_URL, timeout=90000)
    page.wait_for_timeout(7000)
    dismiss_notice(page)
    ensure_logged_in(page)
    header = config.prompt("article_header.txt")
    context = run_dir / "context.txt"
    if context.is_file():
        header += ("\n\nSOURCE STORY. The text inside the source block is established canon for "
                   "this episode. Follow its characters, world rules and events, and continue "
                   "from its ending without retelling it. This episode is the explicit exception "
                   "to any rule that forbids recurring people or settings.\n<SOURCE>\n"
                   + context.read_text(encoding="utf-8").strip() + "\n</SOURCE>")
    if extra_header:
        header += "\n\n" + extra_header
    language = config.CHANNEL.language if config.CHANNEL else "en"
    names = {"en": "English", "pt-BR": "Brazilian Portuguese"}
    if language not in names:
        raise ValueError("unsupported channel narration language")
    header += ("\n\nMANDATORY NARRATION LANGUAGE: " + names[language]
               + ". Write the entire spoken article in this language, regardless of the operator's "
               "message or the browser/YouTube interface language. Return only the narration text.")
    send_text(page, header + "\n\nTheme: " + topic)
    log(f"article prompt sent: {topic}")
    wait_for_assistant(page)
    text = clean_article(copy_last(page))
    if len(text) < 2000:
        raise RuntimeError(f"article is too short ({len(text)} chars)")
    if config.MAX_ARTICLE_CHARS and len(text) > config.MAX_ARTICLE_CHARS:
        log(f"article too long: {len(text)} chars; requesting a bounded rewrite")
        rewrite = ("Rewrite the complete narration above shorter. Cut at least 15 percent of "
                   "the length. Preserve the fixed opening identification, final sign-off, facts, "
                   "structure and language. Do not add sections, examples or details. Output only "
                   "the final narration.\n" + config.ARTICLE_RETRY)
        send_text(page, rewrite)
        wait_for_assistant(page)
        rewritten = clean_article(copy_last(page))
        if len(rewritten) < 2000:
            raise RuntimeError(f"rewrite returned too little text ({len(rewritten)} chars)")
        if len(rewritten) > config.MAX_ARTICLE_CHARS:
            raise RuntimeError(
                f"article is still too long after rewrite ({len(rewritten)} chars, "
                f"limit {config.MAX_ARTICLE_CHARS})")
        text = rewritten
        log(f"article rewritten: {len(text)} chars")
    (run_dir / "article.md").write_text(text, encoding="utf-8")
    (run_dir / "article.txt").write_text(text, encoding="utf-8")
    log(f"article saved: {len(text)} chars")
    return text


def _same_tab(item, tab_url: str) -> bool:
    if not tab_url:
        return True
    key = tab_url.split("?")[0].rstrip("/")
    return str(item.get("tabUrl", "")).split("?")[0].rstrip("/") == key


def _audio_entry(context, start: str, tab_url: str = ""):
    workers = [w for w in context.service_workers if config.EXT_ID in (w.url or "")]
    if not workers:
        return None
    history = workers[0].evaluate("chrome.storage.local.get('captureHistory')").get("captureHistory", [])
    fresh = [item for item in history
             if str(item.get("capturedAt", "")) >= start and _same_tab(item, tab_url)]
    if not fresh:
        return None
    entry = fresh[0]
    items = workers[0].evaluate(f"chrome.downloads.search({{id:{entry['downloadId']}}})")
    return entry, items[0] if items else {}


def _save_audio(entry, item, run_dir: Path) -> Path | None:
    if entry.get("status") != "complete" or item.get("state") != "complete":
        return None
    source = Path(item["filename"])
    suffix = ".aac" if "aac" in (item.get("mime") or "") else ".webm"
    destination = run_dir / f"narration{suffix}"
    shutil.copy2(source, destination)
    return destination


def _click_read_aloud(page, wait_seconds: int = 60) -> bool:
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        buttons = page.locator('button[aria-label="Read aloud"]')
        if buttons.count():
            buttons.last.click()
            return True
        page.wait_for_timeout(2000)
    return False


def _extension_status(context, tab_url: str) -> dict:
    workers = [w for w in context.service_workers if config.EXT_ID in (w.url or "")]
    if not workers:
        return {"worker": False}
    worker = workers[0]
    try:
        history = worker.evaluate("chrome.storage.local.get('captureHistory')").get("captureHistory", [])
        session = worker.evaluate("chrome.storage.session.get({completeRecording: {}, sessionCaptureCount: 0})")
        badge = worker.evaluate("chrome.action.getBadgeText({})")
    except Exception as error:
        return {"worker": True, "error": str(error)[:120]}
    latest = next((item for item in history if _same_tab(item, tab_url)), None)
    return {"worker": True, "badge": badge, "count": session.get("sessionCaptureCount", 0),
            "recording": session.get("completeRecording", {}).get("state", "idle"),
            "capture": latest}


def _capture_once(page, context, run_dir: Path, tab_url: str, start: str,
                  deadline: float) -> Path | None:
    last_status = None
    while time.time() < deadline:
        logic.require_free_space(run_dir, 0.25, "audio capture")
        page.wait_for_timeout(5000)
        found = _audio_entry(context, start, tab_url)
        status = _extension_status(context, tab_url)
        page_state = page.evaluate("""() => ({
            read: document.querySelectorAll('button[aria-label="Read aloud"]').length,
            stop: document.querySelectorAll('button[aria-label="Stop reading"]').length,
            audio: document.querySelectorAll('audio').length,
        })""")
        capture = status.get("capture") or {}
        state = (status.get("badge"), status.get("count"), status.get("recording"),
                 bool(found), capture.get("downloadId") if found else None,
                 page_state.get("read"), page_state.get("stop"), page_state.get("audio"))
        if state != last_status:
            log(f"extension status: badge={status.get('badge')} count={status.get('count')} "
                f"recording={status.get('recording')} download={capture.get('downloadId')} "
                f"capture={capture.get('status', 'none')} page={page_state}")
            last_status = state
        if not found:
            continue
        entry, item = found
        log(f"audio {entry.get('status')} / {item.get('state')} / {item.get('fileSize')} bytes")
        destination = _save_audio(entry, item, run_dir)
        if destination:
            log(f"audio saved: {destination.name} ({destination.stat().st_size} bytes)")
            return destination
        if item.get("state") == "interrupted":
            raise RuntimeError("audio download was interrupted")
    return None


PORTUGUESE_ACCENTS = "ãõçáéíóúâêôà"


def is_brazilian_portuguese(text: str) -> bool:
    """Reject the English output that occasionally slips through the short prompt."""
    lowered = text.lower()
    if " the " in lowered or " and " in lowered:
        return False
    return sum(lowered.count(char) for char in PORTUGUESE_ACCENTS) >= 3


def generate_short(page, topic: str, run_dir: Path) -> str:
    page.goto(config.GPT_URL, timeout=90000)
    page.wait_for_timeout(7000)
    dismiss_notice(page)
    ensure_logged_in(page)
    header = config.prompt("shorts.txt")
    header += ("\n\nIDIOMA OBRIGATÓRIO: português do Brasil. Escreva todo o texto falado nesse "
               "idioma, sem nenhuma palavra em inglês, independentemente da interface ou da "
               "mensagem do operador. Responda apenas com a narração.")
    send_text(page, header + "\n\nTema: " + topic)
    log(f"short prompt sent: {topic}")
    wait_for_assistant(page)
    text = clean_article(copy_last(page))
    if not is_brazilian_portuguese(text):
        log("short came back without Portuguese; requesting a rewrite")
        send_text(page, "Reescreva o texto inteiro em português do Brasil, sem nenhuma palavra "
                        "em inglês. Mantenha o mesmo tema e o mesmo tamanho. Responda apenas "
                        "com a narração.")
        wait_for_assistant(page)
        text = clean_article(copy_last(page))
        if not is_brazilian_portuguese(text):
            raise RuntimeError("short narration is not in Brazilian Portuguese")
    words = len(text.split())
    if words < 60 or words > 180:
        raise RuntimeError(f"short narration has an unexpected length ({words} words)")
    (run_dir / "short.txt").write_text(text, encoding="utf-8")
    log(f"short saved: {len(text)} chars, {words} words")
    return text


def capture_audio(page, context, run_dir: Path, timeout: int = 1800) -> Path:
    logic.require_free_space(run_dir, 0.5, "audio capture")
    overall = time.time() + timeout
    for attempt in range(2):
        if not _click_read_aloud(page):
            if attempt:
                raise RuntimeError("Read aloud button was not available after waiting")
            log("Read aloud button was not available; reloading the conversation")
        else:
            start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            tab_url = page.url
            log(f"read aloud: clicked ({tab_url})")
            start_deadline = min(overall, time.time() + 600)
            destination = _capture_once(page, context, run_dir, tab_url, start, start_deadline)
            if destination:
                return destination
            if attempt:
                break
            log("no capture after 10 minutes; reloading and retrying Read aloud once")
        if time.time() >= overall:
            break
        page.reload(wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(8000)
    raise TimeoutError("audio capture timed out after bounded Read aloud retries")


TOPIC_UI = (
    "conversation helpful", "chatgpt", "thinking effort", "show more", "use plugin",
    "connection interrupted", "latest response", "you said", "simple deep dive",
)


def topic_lines(raw: str) -> list[str]:
    topics = []
    for line in raw.splitlines():
        line = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip().strip('"\'')
        line = re.sub(r"[—–]", ",", line).strip()
        lowered = line.lower()
        if any(marker in lowered for marker in TOPIC_UI):
            continue
        if 3 <= len(line) <= 140 and len(line.split()) >= 3:
            topics.append(line)
    return topics


def generate_topics(context, count: int, existing: list[str]) -> list[str]:
    topics: list[str] = []
    for _attempt in range(2):
        page = context.new_page()
        try:
            page.goto("https://chatgpt.com/", timeout=90000)
            page.wait_for_timeout(7000)
            dismiss_notice(page)
            titles = "\n".join(existing[-120:])
            request = config.prompt("topics.txt").replace("{titles}", titles)
            send_text(page, request + f"\n\nRequested number of topics: {count}"
                      + "\n\nEach line must be a single topic title of at most 140 characters, "
                        "with no description.")
            wait_for_assistant(page, timeout=600)
            topics = topic_lines(copy_last(page))
            if len(topics) >= count:
                return topics[:count]
        finally:
            page.close()
    return topics[:count]
