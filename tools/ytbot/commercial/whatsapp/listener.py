"""Incoming WhatsApp Web message listener with contact rules.

The listener reads the chat list previews instead of opening every conversation, so it never
marks the owner's chats as read. A new preview (contact, text, time) becomes one event.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from . import CHAT_LIST, LOGIN_URL

ROW = '[data-testid="cell-frame-container"]'
TIME = re.compile(r"^(\d{1,2}:\d{2}( ?[ap]\.? ?m\.?)?|\d{1,2}/\d{1,2}/\d{2,4}|yesterday|ontem|"
                  r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                  r"segunda-feira|terça-feira|quarta-feira|quinta-feira|sexta-feira|sábado|domingo)$",
                  re.IGNORECASE)
# 2026 chat list: title, time and preview have their own test ids; a delivered/read/sent check
# icon in the row means the last message is ours (1:1 chats show no "You:" prefix).
READ_ROW = """(row) => {
  const pick = (id) => row.querySelector(`[data-testid="${id}"]`);
  const clean = (node) => node ? node.innerText.replace(/\\u00a0/g, ' ').trim() : '';
  const titleNode = pick('cell-frame-title');
  const named = titleNode ? titleNode.querySelector('span[title]') : null;
  const icons = Array.from(row.querySelectorAll('svg title, [data-icon]'))
    .map((node) => node.textContent || node.getAttribute('data-icon') || '');
  return {
    title: named && named.getAttribute('title') ? named.getAttribute('title').trim() : clean(titleNode),
    stamp: clean(pick('chat-list-timestamp')),
    preview: clean(pick('last-msg-status')),
    outgoing: icons.some((name) => /(delivered|-read$|-sent$|pending|msg-time|dblcheck|-check$)/.test(name)),
    unread: Boolean(pick('icon-unread-count')),
  };
}"""
READ_ROWS = """(limit) => {
  const rows = Array.from(document.querySelectorAll('[data-testid="cell-frame-container"]')).slice(0, limit);
  const unreadSel = '[aria-label*="unread"],[aria-label*="não lida"],[aria-label*="não lidas"]';
  return rows.map((row) => {
    const pick = (id) => row.querySelector(`[data-testid="${id}"]`);
    const clean = (node) => node ? node.innerText.replace(/\\u00a0/g, ' ').trim() : '';
    const titleNode = pick('cell-frame-title');
    const named = titleNode ? titleNode.querySelector('span[title]') : null;
    const icons = Array.from(row.querySelectorAll('svg title, [data-icon]'))
      .map((node) => node.textContent || node.getAttribute('data-icon') || '');
    const statusTitles = Array.from(row.querySelectorAll('span[title]'))
      .filter((node) => !titleNode || !titleNode.contains(node))
      .map((node) => (node.getAttribute('title') || '').replace(/\\u00a0/g, ' ').trim())
      .filter(Boolean);
    return {
      title: named && named.getAttribute('title') ? named.getAttribute('title').trim() : clean(titleNode),
      stamp: clean(pick('chat-list-timestamp')),
      preview: clean(pick('last-msg-status')),
      outgoing: icons.some((name) => /(delivered|-read$|-sent$|pending|msg-time|dblcheck|-check$)/.test(name)),
      unread: Boolean(pick('icon-unread-count') || row.querySelector(unreadSel)),
      statusTitles,
      fallbackText: clean(row),
    };
  });
}"""
UNREAD = ('[aria-label*="unread"]', '[aria-label*="não lida"]', '[aria-label*="não lidas"]')
OUTGOING_PREFIXES = ("you:", "you :", "você:", "você :", "voce:")
TYPING_TEXT = re.compile(r"^(digitando|typing)(?:\.{1,3}|…)?$", re.IGNORECASE)
DEFAULT_RULES = {"mode": "allow", "contacts": []}


def is_typing_text(value: str) -> bool:
    """True only for the live 'digitando...' / 'typing...' status (never audio recording)."""
    return bool(TYPING_TEXT.match((value or "").replace("\xa0", " ").strip()))


def log(message: str) -> None:
    print(f"[listener] {message}", flush=True)


def load_rules(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULT_RULES)
    mode = data.get("mode", "allow")
    contacts = [str(item).strip() for item in data.get("contacts", []) if str(item).strip()]
    return {"mode": mode if mode in ("allow", "block") else "allow", "contacts": contacts}


def save_rules(path: Path, mode: str, contacts: list[str]) -> dict:
    if mode not in ("allow", "block"):
        raise ValueError("mode must be allow or block")
    rules = {"mode": mode, "contacts": [item.strip() for item in contacts if item.strip()]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return rules


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _listed(item: str, name: str) -> bool:
    """Phone entries match on the last eight digits; names keep the partial match."""
    item_digits, name_digits = _digits(item), _digits(name)
    if len(item_digits) >= 8 and len(name_digits) >= 8:
        return item_digits[-8:] == name_digits[-8:]
    return item.casefold() in name or name in item.casefold()


def contact_allowed(contact: str, rules: dict) -> bool:
    name = contact.casefold().strip()
    listed = any(_listed(item, name) for item in rules.get("contacts", []))
    if rules.get("mode") == "block":
        return not listed
    return listed


def allow_contact(path: Path, entry: str) -> dict:
    """Let automated replies reach `entry`; an owner block in block mode is kept."""
    rules = load_rules(path)
    contacts = rules["contacts"]
    if rules["mode"] == "allow" and not any(_listed(item, entry.casefold()) for item in contacts):
        return save_rules(path, "allow", contacts + [entry])
    return rules


def revoke_contact(path: Path, entry: str) -> dict:
    """Stop automated replies to `entry` (refusal or owner block)."""
    rules = load_rules(path)
    contacts = rules["contacts"]
    if rules["mode"] == "allow":
        kept = [item for item in contacts if not _listed(item, entry.casefold())]
        return save_rules(path, "allow", kept) if kept != contacts else rules
    if not any(_listed(item, entry.casefold()) for item in contacts):
        return save_rules(path, "block", contacts + [entry])
    return rules


def event_id(chat: str, text: str, stamp: str) -> str:
    payload = f"{chat}\n{text}\n{stamp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def append_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    path.chmod(0o600)


def unread(page, row) -> bool:
    return any(row.locator(selector).count() for selector in UNREAD)


def looks_like_time(value: str) -> bool:
    return bool(TIME.match(value.strip()))


def _preview(lines: list[str]) -> str:
    return " ".join(lines).replace(" :", ":").strip()


def parse_row(text: str) -> dict:
    """Text fallback: the title is the line before the time (an avatar initial may come first)."""
    lines = [line.replace("\xa0", " ").strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 3:
        return {}
    index = next((position for position, line in enumerate(lines)
                  if position and looks_like_time(line)), 1)
    return {"title": lines[index - 1], "preview": _preview(lines[index + 1:]),
            "stamp": lines[index]}


def read_row(row) -> dict:
    """Structured row (2026 test ids) or the text fallback; `outgoing` marks our last message."""
    try:
        data = row.evaluate(READ_ROW)
    except Exception:
        data = {}
    if data.get("title") and data.get("stamp"):
        lines = [line.strip() for line in str(data.get("preview", "")).splitlines() if line.strip()]
        return {"title": data["title"], "stamp": data["stamp"], "preview": _preview(lines),
                "outgoing": bool(data.get("outgoing")), "unread": bool(data.get("unread"))}
    parsed = parse_row(row.inner_text())
    if parsed:
        parsed["outgoing"] = False
    return parsed


def stamped(value: str) -> bool:
    return bool(value)


def _chat_list_ready(page) -> bool:
    url = getattr(page, "url", "") or ""
    if "web.whatsapp.com" not in url:
        return False
    try:
        return bool(page.locator(CHAT_LIST).count() and page.locator(ROW).count())
    except Exception:
        return False


def _parsed_rows(page, limit: int) -> list[dict]:
    try:
        items = page.evaluate(READ_ROWS, limit)
    except Exception:
        items = None
    if isinstance(items, list):
        parsed_rows = []
        for data in items:
            if not isinstance(data, dict):
                continue
            if data.get("title") and data.get("stamp"):
                lines = [line.strip() for line in str(data.get("preview", "")).splitlines()
                         if line.strip()]
                preview = _preview(lines)
                typing = (is_typing_text(preview)
                          or any(is_typing_text(item) for item in (data.get("statusTitles") or [])))
                parsed_rows.append({
                    "title": data["title"], "stamp": data["stamp"],
                    "preview": preview, "outgoing": bool(data.get("outgoing")),
                    "unread": bool(data.get("unread")), "typing": typing,
                })
            elif data.get("fallbackText"):
                parsed = parse_row(data["fallbackText"])
                if parsed:
                    parsed["outgoing"] = False
                    parsed["unread"] = bool(data.get("unread"))
                    parsed["typing"] = (
                        is_typing_text(parsed.get("preview", ""))
                        or any(is_typing_text(item) for item in (data.get("statusTitles") or []))
                    )
                    parsed_rows.append(parsed)
        return parsed_rows
    rows = page.locator(ROW)
    parsed_rows = []
    for index in range(min(rows.count(), limit)):
        row = rows.nth(index)
        parsed = read_row(row)
        if parsed:
            parsed["unread"] = bool(parsed.get("unread") or unread(page, row))
            parsed_rows.append(parsed)
    return parsed_rows


def scan_once(page, seen: set[str], rules: dict, limit: int = 30) -> list[dict]:
    if not _chat_list_ready(page):
        page.goto(LOGIN_URL, timeout=90000)
        page.wait_for_selector(CHAT_LIST, timeout=90000)
        try:
            page.wait_for_selector(ROW, timeout=10000)
        except Exception:
            page.wait_for_timeout(1500)
    events: list[dict] = []
    for parsed in _parsed_rows(page, limit):
        if not parsed.get("title"):
            continue
        if parsed.get("typing") or is_typing_text(parsed.get("preview", "")):
            events.append({
                "id": f"typing:{parsed['title']}",
                "kind": "typing",
                "at": datetime.now().isoformat(timespec="seconds"),
                "message_at": parsed.get("stamp", ""),
                "chat": parsed["title"],
                "text": "",
                "typing": True,
                "unread": bool(parsed.get("unread")),
                "allowed": contact_allowed(parsed["title"], rules),
            })
            continue
        if not parsed.get("preview"):
            continue
        if parsed.get("outgoing") or parsed["preview"].casefold().startswith(OUTGOING_PREFIXES):
            continue
        key = event_id(parsed["title"], parsed["preview"], parsed["stamp"])
        if key in seen:
            continue
        seen.add(key)
        events.append({
            "id": key,
            "at": datetime.now().isoformat(timespec="seconds"),
            "message_at": parsed["stamp"],
            "chat": parsed["title"],
            "text": parsed["preview"][:1000],
            "unread": bool(parsed.get("unread")),
            "allowed": contact_allowed(parsed["title"], rules),
        })
    return events


def listen(page, base: Path, once: bool = False, interval: int = 30,
           limit: int = 30, max_events: int = 500) -> list[dict]:
    seen_path = base / "seen.json"
    seen_exists = seen_path.is_file()
    seen = set(read_json(seen_path, []))
    rules = load_rules(base / "rules.json")
    collected: list[dict] = []
    while True:
        batch = scan_once(page, seen, rules, limit)
        persisted = False
        for event in batch:
            if event.get("kind") != "typing":
                append_event(base / "events.jsonl", event)
                log(f"{event['chat']}: {event['text'][:60]}")
                persisted = True
        collected.extend(batch)
        if persisted or not seen_exists:
            write_json(seen_path, sorted(seen)[-5000:])
            seen_exists = True
        if once or len(collected) >= max_events:
            break
        page.wait_for_timeout(interval * 1000)
    return collected
