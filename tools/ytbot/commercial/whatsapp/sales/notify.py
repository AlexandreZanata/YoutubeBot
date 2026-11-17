"""Owner hand-off: the record and the desktop notification with the contact to call back.

A hand-off happens when the bot must stop: a buying signal (hot), a question or decision it
has no authority for (needed) or a failure (alert). The record keeps everything the owner
needs to take over without opening the bot: name, phone, a wa.me link, the reason, the last
message and the recent conversation. It stays in the private `handoff.jsonl`.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime

from .context import effective

LABELS = {"hot": "🔥 Atender agora", "needed": "⚠️ Precisa de você", "alert": "🛑 Verificar"}
URGENCY = {"hot": "critical", "needed": "normal", "alert": "critical"}


def format_phone(phone: str) -> str:
    """+55 66 9638-4527 / +55 65 90000-0001 from the canonical digits."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) in (12, 13) and digits.startswith("55"):
        ddd, number = digits[2:4], digits[4:]
        return f"+55 {ddd} {number[:-4]}-{number[-4:]}"
    return f"+{digits}" if digits else ""


def wa_link(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return f"https://wa.me/{digits}" if digits else ""


def recent(history: list[dict], agent_name: str, limit: int = 6) -> list[str]:
    lines = []
    for entry in effective(history):
        if entry.get("dir") not in ("in", "out") or entry.get("state", "sent") != "sent":
            continue
        speaker = agent_name if entry["dir"] == "out" else "Cliente"
        lines.append(f"{speaker}: {entry.get('text', '')}")
    return lines[-limit:]


def handoff_entry(lead: dict, history: list[dict], reason: str, priority: str, intent: str,
                  text: str, now: datetime, agent_name: str = "Alexandre",
                  ficha: str = "") -> dict:
    priority = priority if priority in LABELS else "needed"
    return {
        "at": now.isoformat(timespec="seconds"), "lead": lead["id"], "name": lead["name"],
        "phone": format_phone(lead.get("phone", "")), "wa_link": wa_link(lead.get("phone", "")),
        "priority": priority, "label": LABELS[priority], "reason": reason, "intent": intent,
        "state": lead.get("state"), "last_message": text,
        "recent": recent(history, agent_name), "ficha": ficha,
    }


def message(entry: dict) -> tuple[str, str]:
    """Notification title and body."""
    title = f"Zaflas vendas · {entry['label']}"
    lines = [f"{entry['name']} · {entry['phone']}", entry["reason"]]
    if entry.get("last_message"):
        lines.append(f"“{entry['last_message'][:140]}”")
    if entry.get("wa_link"):
        lines.append(entry["wa_link"])
    if entry.get("ficha"):
        lines.append(f"Ficha: {entry['ficha']}")
    return title, "\n".join(lines)


def desktop_notify(entry: dict) -> None:
    title, body = message(entry)
    try:
        subprocess.run(["notify-send", "-u", URGENCY.get(entry.get("priority"), "normal"),
                        "-a", "Zaflas vendas", title, body], timeout=5, check=False)
    except Exception:
        pass
