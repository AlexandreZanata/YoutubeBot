"""Rehearse whole conversations offline: real agent and rules, fake WhatsApp, synthetic lead.

Used by `commercial sales rehearse` to check an edited rules file against many customer
replies before going live. Nothing is sent and the owner's state is never touched.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import sender
from .agent import SalesAgent
from .rules import SalesRules
from .store import SalesStore

SCENARIOS_PATH = Path(__file__).with_name("scenarios.json")
SYNTHETIC = "+55 65 90000-0001"


class RehearsalChannel:
    def __init__(self, journal_path: Path):
        self.journal_path = journal_path
        self.sent: list[str] = []

    def open(self, lead: dict) -> str:
        return "ready"

    def read_recent(self) -> list[dict]:
        return []

    def send(self, lead: dict, items: list[dict], extra: dict) -> list[dict]:
        def deliver(page, text, pacing, **kwargs):
            self.sent.append(text)
            return "sent"
        return sender.send_sequence(None, lead["name"], items, sender.Pacing(),
                                    self.journal_path, extra=extra, deliver_fn=deliver)


def load_scenarios(path: Path | None = None) -> dict[str, list[str]]:
    data = json.loads((path or SCENARIOS_PATH).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(turns, list) for turns in data.values()):
        raise ValueError("scenarios must map a name to a list of customer messages")
    return data


def rehearse(rules: SalesRules, scenarios: dict[str, list[str]], model=None) -> list[dict]:
    now = datetime(2026, 11, 16, 10, 0, tzinfo=ZoneInfo(rules.raw["timezone"]))
    transcripts = []
    for name, turns in scenarios.items():
        with tempfile.TemporaryDirectory() as directory:
            store = SalesStore(Path(directory) / "whatsapp")
            csv = Path(directory) / "lead.csv"
            csv.write_text(f"name,phone,city,category\nBarbearia Teste,{SYNTHETIC},Cuiabá,"
                           "Barbearia\n", encoding="utf-8")
            store.import_csv(csv, now)
            channel = RehearsalChannel(store.journal_path)
            handoffs: list[dict] = []
            agent = SalesAgent(rules, store, channel, model, live=True, clock=lambda: now,
                               sleep=lambda seconds: None, notify=handoffs.append,
                               log=lambda message: None)
            agent.prospect()
            lead_id = next(iter(store.leads()))
            record = {"name": name, "turns": [], "handoffs": handoffs}
            for index, text in enumerate(turns):
                before = len(channel.sent)
                agent.ingest([{"id": f"r{index}", "chat": SYNTHETIC, "text": text}])
                result = (agent.reply_pending() or [{}])[0]
                record["turns"].append({
                    "customer": text, "bot": channel.sent[before:],
                    "intent": result.get("intent"), "action": result.get("action"),
                    "source": result.get("source"), "state": store.lead(lead_id)["state"]})
            transcripts.append(record)
    return transcripts


def render(transcripts: list[dict]) -> str:
    lines = []
    for record in transcripts:
        lines.append(f"### {record['name']}")
        for turn in record["turns"]:
            lines.append(f"  cliente: {turn['customer']}")
            lines.extend(f"     bot: {message}" for message in turn["bot"])
            if turn["intent"] is None:
                lines.append(f"     (sem resposta automática; estado {turn['state']})")
            else:
                lines.append(f"     [{turn['intent']}/{turn['action']}/{turn['source']} -> "
                             f"{turn['state']}]")
        for entry in record["handoffs"]:
            lines.append(f"  >> {entry['label']} | {entry['reason']} | {entry['phone']}")
        lines.append("")
    return "\n".join(lines)
