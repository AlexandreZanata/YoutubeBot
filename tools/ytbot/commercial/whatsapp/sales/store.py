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
import unicodedata
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
# Where leads come from; the acquisition module (Receita Federal, manual Maps search) adds rows
# through `import_rows` with its own source so numbering and contact export stay the same.
SOURCES = ("google-maps-reviewed", "google-maps-manual", "receita-federal", "manual", "referral")
# Sources that enter the opening queue (`sales queue`), in CSV row order.
QUEUE_SOURCES = ("google-maps-reviewed", "google-maps-manual")


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


def reply_is_active(lead: dict) -> bool:
    """Imported leads answer replies by default; the owner can pause one or all."""
    return bool(lead.get("reply_active", True))


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


def category_slug(category: str) -> str:
    """"Barbearia" -> "barbearia", "Salão de Beleza" -> "salao-de-beleza"; empty -> "lead"."""
    plain = unicodedata.normalize("NFKD", category or "")
    plain = "".join(char for char in plain if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:30] or "lead"


def contact_name(lead: dict) -> str:
    """Name saved on the phone: the category label first, so one search finds a whole niche."""
    label = lead.get("label") or ""
    return f"{label} {lead.get('name', '')}".strip()


def _vcard_text(value: str) -> str:
    """Escape a vCard 3.0 text value."""
    for raw, escaped in (("\\", "\\\\"), (",", "\\,"), (";", "\\;"), ("\n", "\\n")):
        value = value.replace(raw, escaped)
    return value


def vcard(lead: dict) -> str:
    name = _vcard_text(contact_name(lead))
    note = " · ".join(part for part in (f"Lead {lead['id']}", lead.get("source", ""),
                                        lead.get("city", ""), lead.get("maps_url", "")) if part)
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"N:;{name};;;", f"FN:{name}",
             "ORG:Zaflas prospecção", f"TEL;TYPE=CELL:+{lead['phone']}",
             f"CATEGORIES:Zaflas,{category_slug(lead.get('category', ''))}",
             f"NOTE:{_vcard_text(note)}", "END:VCARD"]
    return "\r\n".join(lines) + "\r\n"


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

    def __init__(self, base: Path, root_name: str = "sales"):
        self.base = base
        self.root = base / root_name
        self.leads_path = self.root / "leads.json"
        self.dnc_path = self.root / "do-not-contact.json"
        self.conversations = self.root / "conversations"
        self.handoff_path = self.root / "handoff.jsonl"
        self.decisions_path = self.root / "decisions.jsonl"
        self.usage_path = self.root / "llm-usage.jsonl"
        self.key_path = self.root / "llm.env"
        self.lock_path = self.root / "run.lock"
        self.contacts_dir = self.root / "contatos"
        self.central_path = self.root / "central.json"
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

    def set_reply_active(self, identifier: str, active: bool) -> dict:
        """Activate or pause automatic replies for one imported number."""
        changes = {"reply_active": bool(active)}
        if not active:
            changes["awaiting"] = None
        return self.update_lead(identifier, **changes)

    def ensure_labels(self, leads: dict[str, dict] | None = None) -> dict[str, dict]:
        """Give every lead a category number (barbearia-1, barbearia-2, ...), never reused."""
        own = leads is None
        leads = self.leads() if own else leads
        used: dict[str, int] = {}
        for lead in leads.values():
            match = re.fullmatch(r"(.+)-(\d+)", lead.get("label") or "")
            if match:
                used[match.group(1)] = max(used.get(match.group(1), 0), int(match.group(2)))
        changed = False
        for lead in sorted(leads.values(), key=lambda item: item.get("imported_at") or ""):
            if lead.get("label"):
                continue
            slug = category_slug(lead.get("category", ""))
            used[slug] = used.get(slug, 0) + 1
            lead["label"] = f"{slug}-{used[slug]}"
            lead["contact_name"] = contact_name(lead)
            changed = True
        if own and changed:
            self.save_leads(leads)
        return leads

    def find_lead(self, chat: str) -> dict | None:
        """Match a WhatsApp chat title to a lead: phone digits, saved contact name or label."""
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
            names = {str(lead.get(key) or "").strip().casefold()
                     for key in ("name", "chat", "contact_name", "label")} - {""}
            label = str(lead.get("label") or "").casefold()
            if title in names or (label and title.startswith(label + " ")):
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
    def import_csv(self, path: Path, now: datetime, source: str = "google-maps-reviewed") -> dict:
        """Import the owner's reviewed Google Maps list (no scraping, see the docs)."""
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = [field for field in ("name", "phone") if field not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"CSV needs the columns {', '.join(CSV_FIELDS)}; "
                                 f"missing {', '.join(missing)}")
            rows = [{key: (value or "").strip() for key, value in row.items() if key}
                    for row in reader]
        return self.import_rows(rows, now, source, first_line=2)

    def import_rows(self, rows: list[dict], now: datetime, source: str = "manual",
                    first_line: int = 1, extra: dict | None = None) -> dict:
        """Add approved leads, number them per category and export their contacts.

        The single entry point for every acquisition path (reviewed Maps list, manual search,
        Receita Federal data): same validation, do-not-contact check, numbering and vCard.
        """
        if source not in SOURCES:
            raise ValueError(f"source must be one of {', '.join(SOURCES)}")
        report = {"imported": 0, "duplicates": 0, "do_not_contact": 0, "rejected": [],
                  "labels": [], "contacts_file": None, "ids": []}
        leads = self.ensure_labels(self.leads())
        added = []
        queued = source in QUEUE_SOURCES and not (extra or {}).get("referral")
        position = max((int(lead.get("queue_position") or 0) for lead in leads.values()),
                       default=0)
        for line, row in enumerate(rows, start=first_line):
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
                "source": source, "state": "new", "reply_active": True,
                "imported_at": stamp(now), "opened_at": None, "followups": 0,
                "last_out_at": None, "last_in_at": None, "awaiting": None,
                "replies": {}, "handoff_reason": None, "chat": None, **(extra or {}),
            }
            if queued:
                # The owner's CSV order is the opening order; never re-sorted at send time.
                position += 1
                leads[identifier]["queue_position"] = position
            self.ensure_labels(leads)
            added.append(leads[identifier])
            report["imported"] += 1
        self.save_leads(leads)
        report["reply_active"] = len(added)
        report["labels"] = [f"{lead['label']} {lead['name']}" for lead in added]
        report["ids"] = [lead["id"] for lead in added]
        if added:
            report["contacts_file"] = str(self.export_contacts(added, now, "novos"))
            self.export_contacts(None, now, "todos")
        return report

    # Phone contacts --------------------------------------------------------------------
    def export_contacts(self, leads: list[dict] | None, now: datetime, kind: str) -> Path:
        """vCard file to import into the phone (Google Contacts syncs it to WhatsApp).

        `novos` holds one batch; `todos` is every lead that may still be contacted.
        """
        if leads is None:
            leads = [lead for lead in self.ensure_labels().values()
                     if lead.get("state") not in ("do-not-contact", "invalid-number")
                     and not self.is_dnc(lead["phone"])]
        _private_dir(self.contacts_dir)
        name = "todos.vcf" if kind == "todos" else f"novos-{now.strftime('%Y%m%d-%H%M%S')}.vcf"
        path = self.contacts_dir / name
        path.write_text("".join(vcard(lead) for lead in leads), encoding="utf-8")
        path.chmod(0o600)
        return path

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
