"""Human-paced WhatsApp Web sender for the commercial module."""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import CHAT_LIST, COMPOSER, LOGIN_URL, SEARCH

ATTACH_BUTTONS = ("Attach", "Anexar", "Anexar arquivo")
SEND_BUTTONS = ("Send", "Enviar")


def log(message: str) -> None:
    print(f"[whatsapp] {message}", flush=True)


@dataclass(frozen=True)
class Pacing:
    """Bounds mirror the Telegram rule: a minimum interval and an optional maximum."""

    min_interval: float = 8.0
    max_interval: float = 25.0
    typing_min_ms: int = 35
    typing_max_ms: int = 95
    open_chat_min: float = 1.0
    open_chat_max: float = 3.0

    def between_messages(self) -> float:
        low = max(0.5, min(self.min_interval, self.max_interval))
        high = max(low, self.max_interval)
        return random.uniform(low, high)

    def open_chat_pause(self) -> float:
        return random.uniform(self.open_chat_min, self.open_chat_max)


def message_key(to: str, text: str, image: Path | None) -> str:
    payload = f"{to.strip()}\n{text.strip()}\n{image.name if image else ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def read_journal(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def already_sent(path: Path, key: str) -> bool:
    return any(entry.get("state") == "sent" and entry.get("key") == key
               for entry in read_journal(path))


def journal(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    path.chmod(0o600)


def human_type(page, text: str, pacing: Pacing) -> None:
    """Type in small chunks with plausible pauses instead of pasting."""
    for chunk in re.findall(r"\S+\s*|\s+", text):
        page.keyboard.insert_text(chunk)
        delay = random.uniform(pacing.typing_min_ms, pacing.typing_max_ms) / 1000
        if chunk.rstrip().endswith((".", "?", "!", ",")):
            delay += random.uniform(0.15, 0.45)
        time.sleep(delay)


def open_chat(page, to: str, pacing: Pacing) -> None:
    page.goto(LOGIN_URL, timeout=90000)
    page.wait_for_selector(CHAT_LIST, timeout=90000)
    search = page.locator(SEARCH).first
    search.click()
    search.fill(to)
    page.wait_for_timeout(2000)
    page.keyboard.press("Enter")
    page.wait_for_selector(COMPOSER, state="attached", timeout=30000)
    page.wait_for_timeout(1200)
    time.sleep(pacing.open_chat_pause())


def last_outgoing(page) -> str:
    bubbles = page.locator(
        '[data-testid="msg-container"]:has(span[data-icon="tail-out"]) span.selectable-text')
    if not bubbles.count():
        return ""
    return bubbles.last.inner_text().strip()


def attach_image(page, image: Path) -> None:
    field = page.locator('input[type=file][accept*="image"]')
    if not field.count():
        for label in ATTACH_BUTTONS:
            button = page.get_by_role("button", name=label)
            if button.count():
                button.first.click()
                break
        page.wait_for_timeout(1200)
        field = page.locator('input[type=file][accept*="image"]')
    if not field.count():
        raise RuntimeError("WhatsApp image input was not found")
    field.last.set_input_files(str(image.resolve()))
    page.wait_for_timeout(5000)
    for label in SEND_BUTTONS:
        button = page.get_by_role("button", name=label)
        if button.count():
            button.last.click()
            break
    page.wait_for_timeout(4000)


def send_message(page, to: str, text: str, image: Path | None, pacing: Pacing,
                 dry_run: bool) -> str:
    open_chat(page, to, pacing)
    if dry_run:
        log(f"dry run: would send to {to!r} after {pacing.between_messages():.1f}s")
        return "dry-run"
    time.sleep(pacing.between_messages())
    if image is not None:
        attach_image(page, image)
    composer = page.locator(COMPOSER).first
    composer.click()
    human_type(page, text, pacing)
    page.wait_for_timeout(600)
    page.wait_for_timeout(random.randint(400, 1200))
    for label in SEND_BUTTONS:
        button = page.get_by_role("button", name=label)
        if button.count():
            button.first.click()
            break
    else:
        page.keyboard.press("Enter")
    page.wait_for_timeout(2500)
    if text.strip()[:24] not in last_outgoing(page):
        return "unconfirmed"
    return "sent"


def send_batch(page, messages: list[dict], pacing: Pacing, dry_run: bool,
               journal_path: Path, force: bool = False) -> list[dict]:
    results = []
    for index, item in enumerate(messages):
        key = message_key(item["to"], item["text"], item.get("image"))
        if not force and already_sent(journal_path, key):
            results.append({"to": item["to"], "state": "duplicate"})
            continue
        if index:
            time.sleep(pacing.between_messages())
        started = datetime.now().isoformat(timespec="seconds")
        journal(journal_path, {"key": key, "to": item["to"], "state": "started", "at": started})
        try:
            state = send_message(page, item["to"], item["text"], item.get("image"), pacing,
                                 dry_run)
            journal(journal_path, {"key": key, "to": item["to"], "state": state,
                                   "at": datetime.now().isoformat(timespec="seconds")})
            results.append({"to": item["to"], "state": state})
        except Exception as error:
            journal(journal_path, {"key": key, "to": item["to"], "state": "error",
                                   "error": str(error),
                                   "at": datetime.now().isoformat(timespec="seconds")})
            results.append({"to": item["to"], "state": "error", "error": str(error)})
    return results
