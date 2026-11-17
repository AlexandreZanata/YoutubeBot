"""Private sales state: leads, conversation memory, do-not-contact list and logs.

Everything lives under `.local/commercial/whatsapp/sales/` with 0700/0600 permissions.
Phone numbers stay in `leads.json`; the do-not-contact list keeps only salted hashes so a
refusal survives even if the lead file is cleared.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

# Brazilian area codes (ANATEL). Anything else is rejected at import.
DDD = frozenset({
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "21", "22", "24", "27", "28",
    "31", "32", "33", "34", "35", "37", "38", "41", "42", "43", "44", "45", "46", "47",
    "48", "49", "51", "53", "54", "55", "61", "62", "63", "64", "65", "66", "67", "68",
    "69", "71", "73", "74", "75", "77", "79", "81", "82", "83", "84", "85", "86", "87",
    "88", "89", "91", "92", "93", "94", "95", "96", "97", "98", "99",
})
MAPS_HOSTS = ("https://maps.google.", "https://www.google.com/maps", "https://google.com/maps",
              "https://maps.app.goo.gl/", "https://goo.gl/maps/")
CSV_FIELDS = ("name", "phone", "city", "category", "maps_url", "website", "note")
# States where the agent may still send automated messages.
AUTOMATED_STATES = ("opened", "followed-up", "engaged", "qualifying", "closed")
TERMINAL_STATES = ("do-not-contact", "no-response", "invalid-number")


def stamp(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def canonical_phone(raw: str) -> str | None:
    """`55` + DDD + number, or None when it is not a plausible Brazilian number."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) in (12, 13) and digits.startswith("55"):
        national = digits[2:]
    elif len(digits) in (10, 11):
        national = digits
    else:
        return None
    if national[:2] not in DDD:
        return None
    subscriber = national[2:]
    if len(subscriber) == 9 and not subscriber.startswith("9"):
        return None
    return "55" + national


def phone_key(phone: str) -> str | None:
    """DDD + last eight digits, so numbers with and without the mobile ninth digit match."""
    canonical = canonical_phone(phone)
    if canonical is None:
        return None
    national = canonical[2:]
    return national[:2] + national[-8:]


def lead_id(phone: str) -> str:
    key = phone_key(phone) or re.sub(r"\D", "", phone)
    return "L" + hashlib.sha256(f"lead:{key}".encode()).hexdigest()[:10]


def dnc_hash(phone: str) -> str:
    key = phone_key(phone) or re.sub(r"\D", "", phone)
    return hashlib.sha256(f"zaflas-dnc:{key}".encode()).hexdigest()[:24]


def mask(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return f"+{digits[:4]}•••••{digits[-2:]}" if len(digits) > 6 else "•••"


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def _write_json(path: Path, value) -> None:
    _private_dir(path.parent)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _append(path: Path, entry: dict) -> None:
    _private_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    path.chmod(0o600)


def _read_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


class SalesStore:
    """File-backed state for one WhatsApp account (`.local/commercial/whatsapp`)."""

    def __init__(self, base: Path):
        self.base = base
        self.root = base / "sales"
        self.leads_path = self.root / "leads.json"
        self.dnc_path = self.root / "do-not-contact.json"
        self.conversations = self.root / "conversations"
        self.handoff_path = self.root / "handoff.jsonl"
        self.decisions_path = self.root / "decisions.jsonl"
        self.usage_path = self.root / "llm-usage.jsonl"
        self.key_path = self.root / "llm.env"
        self.lock_path = self.root / "run.lock"
        # Shared with the sender and the listener; formats stay compatible.
        self.journal_path = base / "journal.jsonl"
        self.contact_rules_path = base / "rules.json"

    # Single run ----------------------------------------------------------------------
    def acquire(self) -> bool:
        """Take the run lock; False when another live process holds it."""
        _private_dir(self.root)
        try:
            holder = int(self.lock_path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            holder = 0
        if holder and holder != os.getpid():
            try:
                os.kill(holder, 0)
                return False
            except ProcessLookupError:
                self.lock_path.unlink(missing_ok=True)
            except PermissionError:
                return False
        try:
            descriptor = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return holder == os.getpid()
        with os.fdopen(descriptor, "w") as handle:
            handle.write(str(os.getpid()))
        return True

    def release(self) -> None:
        try:
            if int(self.lock_path.read_text(encoding="utf-8").strip() or 0) == os.getpid():
                self.lock_path.unlink()
        except (OSError, ValueError):
            pass

    # Leads ---------------------------------------------------------------------------
    def leads(self) -> dict[str, dict]:
        data = _read_json(self.leads_path, {})
        return data.get("leads", {}) if isinstance(data, dict) else {}

    def save_leads(self, leads: dict[str, dict]) -> None:
        _write_json(self.leads_path, {"version": 1, "leads": leads})

    def lead(self, identifier: str) -> dict | None:
        return self.leads().get(identifier)

    def update_lead(self, identifier: str, **changes) -> dict:
        leads = self.leads()
        if identifier not in leads:
            raise KeyError(identifier)
        leads[identifier].update(changes)
        self.save_leads(leads)
        return leads[identifier]

    def find_lead(self, chat: str) -> dict | None:
        """Match a WhatsApp chat title to a lead by phone digits or exact saved name."""
        leads = self.leads().values()
        digits = re.sub(r"\D", "", chat or "")
        if len(digits) >= 10:
            key = phone_key(digits)
            for lead in leads:
                if key and phone_key(lead["phone"]) == key:
                    return lead
        title = (chat or "").strip().casefold()
        if not title:
            return None
        for lead in leads:
            names = {str(lead.get("name", "")).strip().casefold(),
                     str(lead.get("chat") or "").strip().casefold()}
            if title in names:
                return lead
        return None

    # Do-not-contact ------------------------------------------------------------------
    def dnc(self) -> dict:
        data = _read_json(self.dnc_path, {})
        return data.get("entries", {}) if isinstance(data, dict) else {}

    def is_dnc(self, phone: str) -> bool:
        return dnc_hash(phone) in self.dnc()

    def add_dnc(self, phone: str, reason: str, now: datetime) -> None:
        entries = self.dnc()
        entries.setdefault(dnc_hash(phone), {"at": stamp(now), "reason": reason})
        _write_json(self.dnc_path, {"version": 1, "entries": entries})

    # Conversation memory -------------------------------------------------------------
    def history_path(self, identifier: str) -> Path:
        return self.conversations / f"{identifier}.jsonl"

    def history(self, identifier: str) -> list[dict]:
        return _read_lines(self.history_path(identifier))

    def remember(self, identifier: str, entry: dict) -> None:
        _append(self.history_path(identifier), entry)

    # Logs ----------------------------------------------------------------------------
    def log_decision(self, entry: dict) -> None:
        _append(self.decisions_path, entry)

    def log_handoff(self, entry: dict) -> None:
        _append(self.handoff_path, entry)

    def log_usage(self, entry: dict) -> None:
        _append(self.usage_path, entry)

    def handoffs(self) -> list[dict]:
        return _read_lines(self.handoff_path)

    # Import --------------------------------------------------------------------------
    def import_csv(self, path: Path, now: datetime) -> dict:
        """Import the owner's reviewed Google Maps list (no scraping, see the docs)."""
        report = {"imported": 0, "duplicates": 0, "do_not_contact": 0, "rejected": []}
        leads = self.leads()
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = [field for field in ("name", "phone") if field not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"CSV needs the columns {', '.join(CSV_FIELDS)}; "
                                 f"missing {', '.join(missing)}")
            for line, row in enumerate(reader, start=2):
                row = {key: (value or "").strip() for key, value in row.items() if key}
                reason = self._reject_reason(row)
                if reason:
                    report["rejected"].append({"line": line, "reason": reason})
                    continue
                phone = canonical_phone(row["phone"])
                if self.is_dnc(phone):
                    report["do_not_contact"] += 1
                    continue
                identifier = lead_id(phone)
                if identifier in leads:
                    report["duplicates"] += 1
                    continue
                leads[identifier] = {
                    "id": identifier, "name": row["name"], "phone": phone,
                    "city": row.get("city", ""), "category": row.get("category", ""),
                    "maps_url": row.get("maps_url", ""), "note": row.get("note", ""),
                    "source": "google-maps-reviewed", "state": "new",
                    "imported_at": stamp(now), "opened_at": None, "followups": 0,
                    "last_out_at": None, "last_in_at": None, "awaiting": None,
                    "replies": {}, "handoff_reason": None, "chat": None,
                }
                report["imported"] += 1
        self.save_leads(leads)
        return report

    @staticmethod
    def _reject_reason(row: dict) -> str | None:
        if not row.get("name"):
            return "name is empty"
        if canonical_phone(row.get("phone", "")) is None:
            return "phone is not a valid Brazilian number"
        if row.get("website"):
            return "the business already lists a website"
        maps_url = row.get("maps_url", "")
        if maps_url and not maps_url.startswith(MAPS_HOSTS):
            return "maps_url is not a Google Maps link"
        return None
