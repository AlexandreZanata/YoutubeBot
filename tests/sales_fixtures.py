"""Shared fixtures for the WhatsApp sales agent tests: synthetic numbers, fake model, fake chat."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tools.ytbot.commercial.whatsapp import sender
from tools.ytbot.commercial.whatsapp.sales.llm import LlmError, LlmReply

ZONE = ZoneInfo("America/Cuiaba")
# Monday 2026-11-16 09:00 local, inside the opening and reply windows.
MONDAY = datetime(2026, 11, 16, 9, 0, tzinfo=ZONE)
# Synthetic numbers only (never real contacts).
PHONES = [f"(65) 90000-{index:04d}" for index in range(1, 30)]


def write_csv(path: Path, rows: list[dict]) -> Path:
    fields = ["name", "phone", "city", "category", "maps_url", "website", "note"]
    lines = [",".join(fields)]
    for row in rows:
        lines.append(",".join(str(row.get(field, "")) for field in fields))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def lead_rows(count: int) -> list[dict]:
    return [{"name": f"Empresa {index}", "phone": PHONES[index], "city": "Cuiabá",
             "category": "Barbearia", "maps_url": "https://maps.app.goo.gl/exemplo"}
            for index in range(count)]


class Clock:
    def __init__(self, now: datetime = MONDAY):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeModel:
    """Returns scripted JSON answers and records every call; never touches the network."""

    def __init__(self, *answers, error: str | None = None):
        self.answers = list(answers)
        self.error = error
        self.calls = []

    def complete(self, messages, session_id):
        self.calls.append({"messages": messages, "session_id": session_id})
        if self.error:
            raise LlmError(self.error)
        answer = self.answers.pop(0) if self.answers else {"intent": "unknown", "messages": []}
        content = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return LlmReply(content, "deepseek-v4.1-flash", 100, 20, 0.00002, 5)


class FakeChannel:
    """The browser stand-in: real journal and fence through `sender.send_sequence`."""

    def __init__(self, journal_path: Path, states=None, open_status="ready", bubbles=None):
        self.journal_path = journal_path
        self.states = list(states or [])
        self.open_status = open_status
        self.bubbles = bubbles or []
        self.opened = []
        self.sent = []

    def open(self, lead):
        self.opened.append(lead["id"])
        return self.open_status

    def read_recent(self):
        return list(self.bubbles)

    def send(self, lead, items, extra):
        def deliver(page, text, pacing, delay=None, link_wait=0.0, **kwargs):
            state = self.states.pop(0) if self.states else "sent"
            if state == "sent":
                self.sent.append({"lead": lead["id"], "text": text, "delay": delay})
            return state

        return sender.send_sequence(None, lead["name"], items, sender.Pacing(),
                                    self.journal_path, extra=extra, deliver_fn=deliver)
