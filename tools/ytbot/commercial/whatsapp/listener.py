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
UNREAD = ('[aria-label*="unread"]', '[aria-label*="não lida"]', '[aria-label*="não lidas"]')
OUTGOING_PREFIXES = ("you:", "you :", "você:", "você :", "voce:")
DEFAULT_RULES = {"mode": "allow", "contacts": []}


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


def parse_row(text: str) -> dict:
    lines = [line.replace("\xa0", " ").strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 3:
        return {}
    title, stamp = lines[0], lines[1]
    preview = " ".join(lines[2:]).replace(" :", ":").strip()
    return {"title": title, "preview": preview, "stamp": stamp}


def looks_like_time(value: str) -> bool:
    value = value.strip()
    return bool(value) and (value[:1].isdigit() or value.casefold() in ("yesterday", "ontem"))


def stamped(value: str) -> bool:
    return bool(value)


def scan_once(page, seen: set[str], rules: dict, limit: int = 30) -> list[dict]:
    page.goto(LOGIN_URL, timeout=90000)
    page.wait_for_selector(CHAT_LIST, timeout=90000)
    page.wait_for_timeout(2500)
    events: list[dict] = []
    rows = page.locator(ROW)
    for index in range(min(rows.count(), limit)):
        row = rows.nth(index)
        parsed = parse_row(row.inner_text())
        if not parsed.get("title") or not parsed.get("preview"):
            continue
        if parsed["preview"].casefold().startswith(OUTGOING_PREFIXES):
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
            "unread": unread(page, row),
            "allowed": contact_allowed(parsed["title"], rules),
        })
    return events


def listen(page, base: Path, once: bool = False, interval: int = 30,
           limit: int = 30, max_events: int = 500) -> list[dict]:
    seen_path = base / "seen.json"
    seen = set(read_json(seen_path, []))
    rules = load_rules(base / "rules.json")
    collected: list[dict] = []
    while True:
        batch = scan_once(page, seen, rules, limit)
        for event in batch:
            append_event(base / "events.jsonl", event)
            log(f"{event['chat']}: {event['text'][:60]}")
        collected.extend(batch)
        write_json(seen_path, sorted(seen)[-5000:])
        if once or len(collected) >= max_events:
            break
        page.wait_for_timeout(interval * 1000)
    return collected
