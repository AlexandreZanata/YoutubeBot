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
    const labels = Array.from(node.querySelectorAll('button,[role=button]'))
      .map((button) => button.getAttribute('aria-label') || '').join(' ');
    const ids = Array.from(node.querySelectorAll('[data-testid]'))
      .map((item) => item.getAttribute('data-testid')).join(' ');
    let media = '';
    if (/image-thumb/.test(ids)) media = 'image';
    else if (/video/i.test(ids) || /video|vídeo/i.test(labels)) media = 'video';
    else if (node.querySelector('audio') || /audio|ptt|voice/i.test(ids)
             || /voice|áudio|audio|play|reproduzir/i.test(labels)) media = 'audio';
    else if (/document/i.test(ids) || /document|download/i.test(labels)) media = 'document';
    rows.push({dir: dir || 'unknown', text, id: holder ? holder.dataset.id : '', media});
  }
  return rows.slice(-limit);
}"""


# Installed on the bot's own page before navigation: remembers the media WhatsApp plays or
# turns into object URLs, so a voice message can be read without depending on its DOM, and
# mutes playback in the hidden browser.
MEDIA_HOOK = """(() => {
  if (window.__ytbotHooked) return;
  window.__ytbotHooked = true;
  window.__ytbotBlobs = [];
  window.__ytbotPlayed = [];
  const create = URL.createObjectURL.bind(URL);
  URL.createObjectURL = (object) => {
    const url = create(object);
    try {
      if (object && object.type) {
        window.__ytbotBlobs.push({url, type: object.type, blob: object});
        if (window.__ytbotBlobs.length > 60) window.__ytbotBlobs.shift();
      }
    } catch (error) {}
    return url;
  };
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    try { this.muted = true; window.__ytbotPlayed.push(this); } catch (error) {}
    return play.apply(this, arguments);
  };
})();"""
FETCH_MEDIA = """async ({id, kind}) => {
  const holders = Array.from(document.querySelectorAll('[data-id]'))
    .filter((holder) => holder.dataset.id === id);
  const node = holders.length ? holders[holders.length - 1] : null;
  if (!node) return null;
  const read = (blob) => new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve({type: blob.type, data: reader.result});
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(blob);
  });
  const fromUrl = async (url) => read(await (await fetch(url)).blob());
  if (kind === 'image') {
    const images = Array.from(node.querySelectorAll('img')).filter((img) => img.src.startsWith('blob:'));
    images.sort((a, b) => b.naturalWidth * b.naturalHeight - a.naturalWidth * a.naturalHeight);
    return images.length ? fromUrl(images[0].src) : null;
  }
  if (kind !== 'audio') return null;
  const inline = node.querySelector('audio[src^="blob:"]');
  if (inline) return fromUrl(inline.src);
  const blobs = (window.__ytbotBlobs || []).length;
  const played = (window.__ytbotPlayed || []).length;
  const button = Array.from(node.querySelectorAll('button,[role=button]'))
    .find((item) => /play|reproduzir|voice|áudio|audio/i.test(item.getAttribute('aria-label') || ''));
  if (!button) return null;
  button.click();
  for (let step = 0; step < 60; step += 1) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    const element = (window.__ytbotPlayed || []).slice(played)
      .find((item) => (item.currentSrc || item.src || '').startsWith('blob:'));
    if (element) {
      try { element.pause(); } catch (error) {}
      return fromUrl(element.currentSrc || element.src);
    }
    const hooked = (window.__ytbotBlobs || []).slice(blobs)
      .find((item) => /^audio\\//.test(item.type) || /ogg|opus/.test(item.type));
    if (hooked) return read(hooked.blob);
    const tag = node.querySelector('audio[src^="blob:"]') || document.querySelector('audio[src^="blob:"]');
    if (tag) { try { tag.pause(); } catch (error) {} return fromUrl(tag.src); }
  }
  return null;
}"""
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
              "image/gif": ".gif", "audio/ogg": ".ogg", "audio/mpeg": ".mp3",
              "audio/mp4": ".m4a", "audio/webm": ".webm", "audio/wav": ".wav"}
MAX_MEDIA_BYTES = 25 * 1024 * 1024


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
             "id": row.get("id", ""), "media": row.get("media", "")} for row in rows or []]


def fetch_media(page, message_id: str, kind: str) -> tuple[bytes, str] | None:
    """Bytes and file extension of an image or voice message in the open chat."""
    if not message_id or kind not in ("image", "audio"):
        return None
    try:
        result = page.evaluate(FETCH_MEDIA, {"id": message_id, "kind": kind})
    except Exception:
        return None
    if not result or not str(result.get("data", "")).startswith("data:"):
        return None
    import base64

    header, _, payload = result["data"].partition(",")
    data = base64.b64decode(payload) if ";base64" in header else payload.encode()
    if not data or len(data) > MAX_MEDIA_BYTES:
        return None
    kind_type = (result.get("type") or "").split(";")[0].strip().lower()
    extension = EXTENSIONS.get(kind_type, ".ogg" if kind == "audio" else ".jpg")
    return data, extension


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
            image: Path | None = None, link_wait: float = 0.0, timing: dict | None = None,
            confirm_timeout: float = 8.0) -> str:
    """Type and send one message in the open chat; `sent` only when the bubble is seen.

    `delay` is the interval since the previous send (or since the call when there is none) and
    already includes the typing; a link also waits at least `link_wait` after being typed.
    """
    timing = timing if timing is not None else {}
    start = timing.get("last_send", time.monotonic())
    interval = pacing.between_messages() if delay is None else max(0.0, delay)
    before = _outgoing_ids(page)
    if image is not None:
        attach_image(page, image)
    composer = page.locator(COMPOSER).first
    composer.click()
    human_type(page, text, pacing)
    typed = time.monotonic()
    page.wait_for_timeout(150)
    ready = start + interval
    if link_wait and URL_IN_TEXT.search(text):
        ready = max(ready, typed + link_wait)
    remaining = ready - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    for label in SEND_BUTTONS:
        button = page.get_by_role("button", name=label)
        if button.count():
            button.first.click()
            break
    else:
        page.keyboard.press("Enter")
    timing["last_send"] = time.monotonic()
    deadline = timing["last_send"] + confirm_timeout
    while True:
        page.wait_for_timeout(300)
        if confirmed(page, text, before):
            return "sent"
        if time.monotonic() >= deadline:
            return "unconfirmed"


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
    timing: dict = {}
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
                               link_wait=link_wait, timing=timing)
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
