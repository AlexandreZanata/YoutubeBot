"""OpenCode Go client for the sales agent (Chat Completions, DeepSeek V4.1 Flash only).

Mirrors the OpenTatu client (docs/opencode-go.md in that repository): Bearer key, a product
`User-Agent`, one stable `x-opencode-session` per conversation, JSON mode and no automatic
retry or redirect. The key is read from the environment or the private `llm.env`, is only
placed in the Authorization header and never appears in logs, errors or records.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .rules import ALLOWED_MODELS

USER_AGENT = "YoutubeBot-Sales/1.0 (+https://github.com/AlexandreZanata/chatgpt-recorder)"
SESSION_HEADER = "x-opencode-session"
MAX_ERROR_CHARS = 300


class LlmError(RuntimeError):
    """The model call failed; the caller falls back to fixed texts or the owner."""


class LlmUnavailable(LlmError):
    """No key configured."""


@dataclass(frozen=True)
class LlmReply:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    duration_ms: int


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_ERROR_CHARS else text[:MAX_ERROR_CHARS] + "…"


def load_api_key(env_name: str, key_file: Path) -> str | None:
    """Environment first, then `KEY=value` lines in the private key file."""
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    try:
        lines = key_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        name, _, rest = line.partition("=")
        if name.strip() == env_name and rest.strip():
            return rest.strip().strip('"').strip("'")
    return None


class OpenCodeGo:
    def __init__(self, settings: dict, api_key: str | None, opener=None):
        model = settings["model"]
        if model not in ALLOWED_MODELS:
            raise LlmError(f"model {model} is not allowed")
        if not api_key:
            raise LlmUnavailable(f"{settings['api_key_env']} is not set")
        self.settings = settings
        self._key = api_key
        self._opener = opener or urllib.request.build_opener(_NoRedirect()).open

    def __repr__(self) -> str:
        return f"OpenCodeGo(model={self.settings['model']!r})"

    def build_request(self, messages: list[dict], session_id: str) -> urllib.request.Request:
        body = {
            "model": self.settings["model"],
            "messages": messages,
            "temperature": float(self.settings["temperature"]),
            "max_tokens": int(self.settings["max_output_tokens"]),
            "response_format": {"type": "json_object"},
        }
        endpoint = self.settings["base_url"].rstrip("/") + "/chat/completions"
        return urllib.request.Request(
            endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                     "User-Agent": USER_AGENT, SESSION_HEADER: session_id})

    def complete(self, messages: list[dict], session_id: str) -> LlmReply:
        request = self.build_request(messages, session_id)
        started = time.monotonic()
        try:
            with self._opener(request, timeout=float(self.settings["timeout_seconds"])) as handle:
                status = getattr(handle, "status", 200)
                body = handle.read()
        except urllib.error.HTTPError as error:
            raise LlmError(self._http_error(error.code, error.read())) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise LlmError(_truncate(f"request failed: {reason}")) from None
        if not 200 <= status < 300:
            raise LlmError(self._http_error(status, body))
        duration = int((time.monotonic() - started) * 1000)
        try:
            parsed = json.loads(body)
            choice = parsed["choices"][0]
            content = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise LlmError("unexpected response format") from None
        usage = parsed.get("usage") or {}
        allowance = (usage.get("opencode") or {}).get("allowance")
        return LlmReply(content, parsed.get("model", self.settings["model"]),
                        int(usage.get("prompt_tokens") or 0),
                        int(usage.get("completion_tokens") or 0),
                        float(allowance) if allowance is not None else None, duration)

    @staticmethod
    def _http_error(status: int, body: bytes) -> str:
        if status in (401, 403):
            return "authentication failed (check the OpenCode Go key)"
        if status == 429:
            return "rate limited by OpenCode Go"
        try:
            error = json.loads(body).get("error", {})
            detail = f"{error.get('type', 'error')}: {error.get('message', '')}"
        except (ValueError, AttributeError):
            detail = "unrecognized error body"
        return _truncate(f"HTTP {status}: {detail}")
