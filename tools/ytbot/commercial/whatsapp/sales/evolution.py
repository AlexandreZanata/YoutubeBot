"""Evolution API transport: openings through a local REST gateway instead of the browser.

Owner decision 2026-11-23. The gateway runs from `.local/evolution/docker-compose.yml`
(Postgres + Redis + Evolution on 127.0.0.1:8091) and pairs once by QR. This module is a
typed client plus a channel with the same interface the browser channel exposes, so the
journal, fences and pacing stay identical. The API key lives in the private env file and is
never logged.

Honest limit: Evolution's default mode is Baileys, an unofficial WhatsApp Web client that
WhatsApp actively detects. It removes the browser/session fragility; it does not make cold
outreach safe. Keep the volume low, never put a link in the first message, and stop on the
first restriction.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from .. import sender

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_ENV = REPO_ROOT / ".local" / "evolution" / "evolution.env"


class EvolutionError(RuntimeError):
    """The gateway refused the call or is not configured; never retried blindly."""


def _env(path: Path | None = None) -> dict:
    file = Path(os.environ.get("EVOLUTION_ENV_FILE") or (path or DEFAULT_ENV))
    values = {}
    try:
        for line in file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    except OSError as error:
        raise EvolutionError(f"Evolution env file not found at {file}") from error
    return values


def settings(path: Path | None = None) -> dict:
    values = _env(path)
    key = values.get("AUTHENTICATION_API_KEY", "").strip()
    if not key:
        raise EvolutionError("AUTHENTICATION_API_KEY is missing from the Evolution env file")
    port = values.get("EVOLUTION_PORT", "8091").strip()
    base = os.environ.get("EVOLUTION_URL") or f"http://127.0.0.1:{port}"
    instance = values.get("EVOLUTION_INSTANCE", "zaflas").strip()
    return {"base": base.rstrip("/"), "key": key, "instance": instance}


def _call(method: str, path: str, body: dict | None, config: dict, timeout: float = 20.0,
          opener=None) -> dict:
    url = f"{config['base']}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "apikey": config["key"],
        "Content-Type": "application/json",
    })
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read(300).decode("utf-8", errors="replace")
        except OSError:
            pass
        raise EvolutionError(f"Evolution API HTTP {error.code}: {detail}".strip()) from error
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise EvolutionError(f"Evolution API request failed: {error}") from error


def state(config: dict, opener=None) -> str:
    data = _call("GET", f"/instance/connectionState/{config['instance']}", None, config,
                 opener=opener)
    return str((data.get("instance") or {}).get("state") or "")


def send_text(phone: str, text: str, config: dict, opener=None) -> dict:
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        raise EvolutionError("empty phone for Evolution send")
    return _call("POST", f"/message/sendText/{config['instance']}",
                 {"number": digits, "text": text}, config, opener=opener)


class EvolutionChannel:
    """The browser channel's interface over REST: send_sequence keeps the journal/fences."""

    def __init__(self, config: dict, journal_path: Path, pacing=None, opener=None):
        self.config = config
        self.journal_path = journal_path
        self.pacing = pacing or sender.Pacing()
        self.opener = opener
        self.sent: list[str] = []
        self.current: dict | None = None

    def open(self, lead: dict) -> str:
        self.current = lead
        return "ready"

    def chat_title(self) -> str:
        return ""

    def read_recent(self) -> list[dict]:
        return []

    def fetch_media(self, bubble: dict) -> list[tuple[bytes, str]]:
        return []

    def is_typing(self) -> bool:
        return False

    def send(self, lead: dict, items: list[dict], extra: dict) -> list[dict]:
        def deliver(page, text, pacing, delay=None, link_wait=0.0, **kwargs):
            send_text(lead.get("phone", ""), text, self.config, opener=self.opener)
            self.sent.append(text)
            return "sent"

        return sender.send_sequence(None, lead.get("name", ""), items, self.pacing,
                                    self.journal_path, extra=extra, deliver_fn=deliver)
