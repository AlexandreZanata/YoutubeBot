"""Resumable private run records under `.local/commercial/maps/runs/`."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ...accounts_store import private_directory, read_private, write_private
from .rules import normalize

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def slug_of(city: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", normalize(city)).strip("-")
    if not SLUG.fullmatch(value):
        raise ValueError("city must produce a short lowercase slug")
    return value


def validate_city(city: str) -> str:
    value = (city or "").strip()
    if not 2 <= len(value) <= 80 or "\n" in value:
        raise ValueError("city is required")
    return value


def validate_state(state: str) -> str:
    value = (state or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", value):
        raise ValueError("state must be the two-letter UF")
    return value


def url_key(url: str) -> str:
    """Stable identity for a place link: host and path, without campaign query strings."""
    from urllib.parse import urlsplit

    parsed = urlsplit((url or "").strip())
    if not parsed.netloc:
        return ""
    return f"{parsed.netloc.casefold()}{parsed.path}".rstrip("/")


def identity(listing: dict) -> str:
    if listing.get("identity"):
        return str(listing["identity"])
    name = normalize(listing.get("name", ""))
    if name:
        return f"{name}|{normalize(listing.get('address', ''))}"
    return url_key(listing.get("maps_url", ""))


def _append(path: Path, entry: dict) -> None:
    private_directory(path.parent)
    data = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)
    path.chmod(0o600)


def _lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def _latest(entries: list[dict], key: str = "identity") -> list[dict]:
    order = []
    latest = {}
    for entry in entries:
        value = entry.get(key) or identity(entry)
        if value not in latest:
            order.append(value)
        latest[value] = entry
    return [latest[value] for value in order]


@dataclass(frozen=True)
class Run:
    path: Path
    city: str
    state: str
    day: str
    slug: str

    @property
    def id(self) -> str:
        return f"{self.slug}/{self.day}"

    def append_query(self, entry: dict) -> None:
        _append(self.path / "queries.jsonl", entry)

    def append_listing(self, entry: dict) -> None:
        value = dict(entry)
        value.setdefault("identity", identity(value))
        if value.get("maps_url"):
            value.setdefault("url_key", url_key(value["maps_url"]))
        _append(self.path / "listings.jsonl", value)

    def append_check(self, entry: dict) -> None:
        value = dict(entry)
        value.setdefault("identity", identity(value))
        _append(self.path / "checks.jsonl", value)

    def queries(self) -> list[dict]:
        return _lines(self.path / "queries.jsonl")

    def listings(self) -> list[dict]:
        return _lines(self.path / "listings.jsonl")

    def checks(self) -> list[dict]:
        return _latest([entry for entry in _lines(self.path / "checks.jsonl")
                        if entry.get("outcome")])

    def read_listings(self) -> list[dict]:
        return _latest([entry for entry in self.listings() if entry.get("state") == "read"])

    def attempted(self) -> set[str]:
        """Every identity or place URL already opened (or about to be opened)."""
        keys = set()
        for entry in self.listings():
            value = entry.get("identity") or identity(entry)
            if value:
                keys.add(value)
            if entry.get("url_key"):
                keys.add(entry["url_key"])
        return keys

    def done_queries(self) -> set[str]:
        return {normalize(entry.get("query", "")) for entry in self.queries()
                if entry.get("status") == "done"}

    def checked(self) -> set[str]:
        return {entry.get("identity") or identity(entry) for entry in self.checks()}

    def pending_checks(self) -> list[dict]:
        done = self.checked()
        return [listing for listing in self.read_listings()
                if (listing.get("identity") or identity(listing)) not in done]


class RunStore:
    """The private `.local/commercial/maps` root and the run directories below it."""

    def __init__(self, root: Path):
        self.root = private_directory(Path(root))

    @property
    def runs_root(self) -> Path:
        return private_directory(self.root / "runs")

    @property
    def attention_path(self) -> Path:
        return self.root / "needs-attention.json"

    def create(self, city: str, state: str, now: datetime) -> Run:
        city, state = validate_city(city), validate_state(state)
        slug = slug_of(city)
        day = now.date().isoformat()
        path = private_directory(self.runs_root / slug / day)
        meta = path / "run.json"
        if not meta.is_file():
            write_private(meta, {"city": city, "state": state, "slug": slug, "day": day,
                                 "started_at": now.isoformat(timespec="seconds")})
        else:
            saved = read_private(meta, {}) or {}
            city = str(saved.get("city") or city)
            state = str(saved.get("state") or state)
        return Run(path, city, state, day, slug)

    def resolve(self, value: str) -> Run:
        text = (value or "").strip().strip("/")
        if "/" in text:
            slug, day = text.split("/", 1)
            if not SLUG.fullmatch(slug) or not DAY.fullmatch(day):
                raise ValueError("run must be <city-slug>/<YYYY-MM-DD>")
            path = self.runs_root / slug / day
            if not path.is_dir():
                raise ValueError(f"run not found: {slug}/{day}")
            return self._load(path, slug, day)
        if not SLUG.fullmatch(text):
            raise ValueError("run must be <city-slug>/<YYYY-MM-DD> or <city-slug>")
        directory = self.runs_root / text
        if not directory.is_dir():
            raise ValueError(f"city not found: {text}")
        days = sorted(item.name for item in directory.iterdir()
                      if item.is_dir() and DAY.fullmatch(item.name))
        if not days:
            raise ValueError(f"no runs for {text}")
        return self._load(directory / days[-1], text, days[-1])

    @staticmethod
    def _load(path: Path, slug: str, day: str) -> Run:
        meta = read_private(path / "run.json", {}) or {}
        return Run(path, str(meta.get("city") or slug.replace("-", " ").title()),
                   str(meta.get("state") or ""), day, slug)

    def daily_businesses(self, day: str) -> int:
        """Unique businesses read on that date across every city run."""
        found = set()
        for city in self.runs_root.glob("*"):
            directory = city / day
            if not city.is_dir() or not directory.is_dir() or not DAY.fullmatch(day):
                continue
            run = self._load(directory, city.name, day)
            for listing in run.read_listings():
                found.add(listing.get("identity") or identity(listing))
        return len(found)

    def attention(self) -> dict | None:
        return read_private(self.attention_path)

    def record_attention(self, run: Run, stage: str, reason: str, evidence: dict | None,
                         now: datetime) -> dict:
        entry = {"at": now.isoformat(timespec="seconds"), "run": run.id, "stage": stage,
                 "reason": reason, "evidence": evidence or {}}
        write_private(self.attention_path, entry)
        self._notify(entry)
        return entry

    def clear_attention(self) -> None:
        self.attention_path.unlink(missing_ok=True)

    @staticmethod
    def _notify(entry: dict) -> None:
        body = f"{entry['reason']} ({entry['stage']}, run {entry['run']})"
        try:
            subprocess.run(["notify-send", "-u", "critical", "-a", "Zaflas Maps",
                            "Zaflas Maps · Verificar", body], timeout=5, check=False)
        except Exception:
            pass
