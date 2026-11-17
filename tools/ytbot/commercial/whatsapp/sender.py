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
INVALID_NUMBER = re.compile(r"(phone number shared via url is invalid|"
                            r"n[uú]mero de telefone compartilhado (por|via) url [eé] inv[aá]lido)",
                            re.IGNORECASE)
URL_IN_TEXT = re.compile(r"https?://\S+")
UNCERTAIN = ("started", "unconfirmed", "error")
# Direction of every bubble: `data-id` starts with true_ for our messages; tails and the
# message-in/out row classes are fallbacks; bubbles without a marker continue the group.
READ_BUBBLES = """(limit) => {
  const nodes = Array.from(document.querySelectorAll('[data-testid="msg-container"]'));
  let dir = null;
  const rows = [];
  for (const node of nodes) {
    const holder = node.closest('[data-id]') || node.querySelector('[data-id]');
    const row = node.closest('.message-out, .message-in');
    if (holder && /^(true|false)_/.test(holder.dataset.id || '')) {
      dir = holder.dataset.id.startsWith('true_') ? 'out' : 'in';
    } else if (node.querySelector('span[data-icon="tail-out"]')
               || (row && row.classList.contains('message-out'))) {
      dir = 'out';
    } else if (node.querySelector('span[data-icon="tail-in"]')
               || (row && row.classList.contains('message-in'))) {
      dir = 'in';
    }
    const text = Array.from(node.querySelectorAll('span.selectable-text'))
      .map((span) => span.innerText).join('\\n').trim();
    rows.push({dir: dir || 'unknown', text, id: holder ? holder.dataset.id : ''});
  }
  return rows.slice(-limit);
}"""


class InvalidNumber(RuntimeError):
    """WhatsApp reports that the number has no account."""


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


def open_chat(page, to: str, pacing: Pacing, phone: str | None = None) -> None:
    """Open the conversation by saved name (search) or by number (click-to-chat URL)."""
    if phone:
        _open_by_phone(page, phone, pacing)
        return
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


def _open_by_phone(page, phone: str, pacing: Pacing, timeout: float = 60.0) -> None:
    digits = re.sub(r"\D", "", phone)
    page.goto(f"{LOGIN_URL}send?phone={digits}", timeout=90000)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.locator(COMPOSER).count():
            page.wait_for_timeout(1200)
            time.sleep(pacing.open_chat_pause())
            return
        body = page.locator("body").inner_text() if page.locator("body").count() else ""
        if INVALID_NUMBER.search(body or ""):
            raise InvalidNumber("WhatsApp says the number has no account")
        page.wait_for_timeout(1000)
    raise RuntimeError("WhatsApp chat did not open for the number")


def read_bubbles(page, limit: int = 30) -> list[dict]:
    """Recent bubbles of the open chat, oldest first: {dir: in|out|unknown, text, id}."""
    try:
        rows = page.evaluate(READ_BUBBLES, limit)
    except Exception:
        return []
    return [{"dir": row.get("dir", "unknown"), "text": str(row.get("text", "")).strip(),
             "id": row.get("id", "")} for row in rows or []]


def last_outgoing(page) -> str:
    for bubble in reversed(read_bubbles(page, 15)):
        if bubble["dir"] == "out":
            return bubble["text"]
    return ""


def _outgoing_ids(page) -> set[str]:
    return {bubble["id"] for bubble in read_bubbles(page, 40)
            if bubble["dir"] == "out" and bubble["id"]}


def confirmed(page, text: str, before: set[str]) -> bool:
    """The newest outgoing bubble is new (when ids exist) and starts like the message."""
    prefix = text.strip()[:24]
    bubbles = read_bubbles(page, 15)
    outgoing = [bubble for bubble in bubbles if bubble["dir"] == "out"]
    if not outgoing or prefix not in outgoing[-1]["text"]:
        return False
    newest = outgoing[-1]["id"]
    return not newest or newest not in before


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


def deliver(page, text: str, pacing: Pacing, delay: float | None = None,
            image: Path | None = None, link_wait: float = 0.0) -> str:
    """Type and send one message in the open chat; `sent` only when the bubble is seen."""
    time.sleep(pacing.between_messages() if delay is None else max(0.0, delay))
    before = _outgoing_ids(page)
    if image is not None:
        attach_image(page, image)
    composer = page.locator(COMPOSER).first
    composer.click()
    human_type(page, text, pacing)
    if link_wait and URL_IN_TEXT.search(text):
        page.wait_for_timeout(int(link_wait * 1000))
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
    return "sent" if confirmed(page, text, before) else "unconfirmed"


def send_message(page, to: str, text: str, image: Path | None, pacing: Pacing,
                 dry_run: bool) -> str:
    open_chat(page, to, pacing)
    if dry_run:
        log(f"dry run: would send to {to!r} after {pacing.between_messages():.1f}s")
        return "dry-run"
    return deliver(page, text, pacing, image=image)


def journal_state(path: Path, key: str) -> str | None:
    """`sent`, `uncertain` (started/unconfirmed/error) or None when never attempted."""
    states = [entry.get("state") for entry in read_journal(path) if entry.get("key") == key]
    if "sent" in states:
        return "sent"
    if any(state in UNCERTAIN for state in states):
        return "uncertain"
    return None


def send_sequence(page, to: str, items: list[dict], pacing: Pacing, journal_path: Path,
                  extra: dict | None = None, link_wait: float = 0.0,
                  deliver_fn=None) -> list[dict]:
    """Send several messages in the chat already open, one journaled step each.

    Each item is {key, text, delay}. A key already `sent` is skipped, an uncertain key stops
    the sequence without typing (never a blind retry), and the first message that is not
    confirmed stops the rest.
    """
    deliver_fn = deliver_fn or deliver
    results = []
    for item in items:
        prior = journal_state(journal_path, item["key"])
        if prior == "sent":
            results.append({"key": item["key"], "state": "duplicate"})
            continue
        if prior == "uncertain":
            results.append({"key": item["key"], "state": "fenced"})
            break
        entry = {"key": item["key"], "to": to, **(extra or {})}
        journal(journal_path, {**entry, "state": "started",
                               "at": datetime.now().isoformat(timespec="seconds")})
        try:
            state = deliver_fn(page, item["text"], pacing, delay=item.get("delay"),
                               link_wait=link_wait)
        except Exception as error:
            journal(journal_path, {**entry, "state": "error", "error": str(error)[:300],
                                   "at": datetime.now().isoformat(timespec="seconds")})
            results.append({"key": item["key"], "state": "error", "error": str(error)[:300]})
            break
        journal(journal_path, {**entry, "state": state,
                               "at": datetime.now().isoformat(timespec="seconds")})
        results.append({"key": item["key"], "state": state})
        if state != "sent":
            break
    return results


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
