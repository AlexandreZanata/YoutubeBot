"""OpenCode Go models for the sales agent: free models first, rotating, paid fallback.

Owner decision (2026-11-17, evening): use the OpenCode Go free tier first (longcat-2.5-free,
iceman-contributor-free and any free model added later), rotate between them, skip a model at
once when it times out or runs out of credits, and only then fall back to deepseek-v4.1-flash
and muse-spark-1.3-contributor.

- A model is free when the live catalog (`/v1/models`) lists it with input and output price 0
  and the chat-completions API. New free models are picked up automatically; no other paid model
  than the configured fallback is ever called.
- A parallel probe (tiny prompt, a few seconds for all) runs when the router starts and with
  every catalog refresh, so a dead model is skipped before a real conversation waits on it.
- A timeout or error cools a model down for minutes, "no credits" (429/402/quota) for half an
  hour; a reply that is not a JSON object moves on to the next model.
- Models that reject JSON mode are called without it (the prompts already ask for JSON).

The transport mirrors OpenTatu's client: Bearer key, a product `User-Agent`, one
`x-opencode-session` per conversation, no redirects or automatic retries. The key is only placed
in the Authorization header and never appears in logs, errors or records.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = "YoutubeBot-Sales/1.0 (+https://github.com/AlexandreZanata/chatgpt-recorder)"
SESSION_HEADER = "x-opencode-session"
MAX_ERROR_CHARS = 300
# The only paid models the agent may call (owner decision); free ones come from the catalog.
FALLBACK_ALLOWED = ("deepseek-v4.1-flash", "muse-spark-1.3-contributor")
NO_CREDIT_WORDS = ("credit", "quota", "limit", "exceeded", "insufficient", "balance", "billing")
PROBE = [{"role": "system", "content": "Responda somente JSON."},
         {"role": "user", "content": 'Responda exatamente {"pong": true}'}]


class LlmError(RuntimeError):
    """The model call failed; `kind` says why (auth, no-credits, timeout, ...)."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


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


@dataclass(frozen=True)
class ModelInfo:
    id: str
    free: bool
    json: bool
    training: bool
    zdr: bool


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_ERROR_CHARS else text[:MAX_ERROR_CHARS] + "…"


def json_object(content: str) -> bool:
    text = (content or "").strip()
    try:
        return isinstance(json.loads(text[text.find("{"):text.rfind("}") + 1]), dict)
    except ValueError:
        return False


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


def parse_catalog(data: dict, exclude: list[str] | tuple = ()) -> list[ModelInfo]:
    """Models of the live catalog; `free` = price 0 in and out on chat-completions."""
    models = []
    for item in (data or {}).get("data", []):
        model_id = str(item.get("id") or "")
        text = ((item.get("cost") or {}).get("text") or {}) if isinstance(item.get("cost"), dict) \
            else {}
        prices = ((text.get("input") or {}).get("price"), (text.get("output") or {}).get("price"))
        apis = item.get("api") or {}
        go = item.get("go") or {}
        free = (all(isinstance(price, (int, float)) and price == 0 for price in prices)
                and "chat-completions" in apis)
        if not model_id or model_id in exclude:
            continue
        models.append(ModelInfo(model_id, free,
                                (item.get("capabilities") or {}).get("structured_output") is True,
                                go.get("training") is True, go.get("zdr") is True))
    return models


class OpenCodeGo:
    """One HTTP call to one model (Chat Completions)."""

    def __init__(self, settings: dict, api_key: str | None, opener=None, model: str = "",
                 free: bool = False):
        self.model = model or settings.get("model") or settings["fallback"][0]
        if not free and self.model not in FALLBACK_ALLOWED:
            raise LlmError(f"model {self.model} is not allowed", "config")
        if not api_key:
            raise LlmUnavailable(f"{settings['api_key_env']} is not set", "auth")
        self.settings = settings
        self._key = api_key
        self._opener = opener or urllib.request.build_opener(_NoRedirect()).open

    def __repr__(self) -> str:
        return f"OpenCodeGo(model={self.model!r})"

    def build_request(self, messages: list[dict], session_id: str,
                      json_mode: bool = True) -> urllib.request.Request:
        body = {"model": self.model, "messages": messages,
                "temperature": float(self.settings["temperature"]),
                "max_tokens": int(self.settings["max_output_tokens"])}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        endpoint = self.settings["base_url"].rstrip("/") + "/chat/completions"
        return urllib.request.Request(
            endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                     "User-Agent": USER_AGENT, SESSION_HEADER: session_id})

    def complete(self, messages: list[dict], session_id: str, timeout: float | None = None,
                 json_mode: bool = True) -> LlmReply:
        request = self.build_request(messages, session_id, json_mode)
        started = time.monotonic()
        limit = float(timeout or self.settings["timeout_seconds"])
        try:
            with self._opener(request, timeout=limit) as handle:
                status = getattr(handle, "status", 200)
                body = handle.read()
        except urllib.error.HTTPError as error:
            raise self._http_error(error.code, error.read()) from None
        except (TimeoutError, socket.timeout):
            raise LlmError(f"{self.model}: no answer in {limit:.0f}s", "timeout") from None
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            kind = "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "transport"
            raise LlmError(_truncate(f"{self.model}: request failed: {reason}"), kind) from None
        if not 200 <= status < 300:
            raise self._http_error(status, body)
        duration = int((time.monotonic() - started) * 1000)
        try:
            parsed = json.loads(body)
            content = parsed["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise LlmError(f"{self.model}: unexpected response format", "format") from None
        usage = parsed.get("usage") or {}
        allowance = (usage.get("opencode") or {}).get("allowance")
        return LlmReply(content, parsed.get("model", self.model),
                        int(usage.get("prompt_tokens") or 0),
                        int(usage.get("completion_tokens") or 0),
                        float(allowance) if allowance is not None else None, duration)

    def _http_error(self, status: int, body: bytes) -> LlmError:
        try:
            error = json.loads(body).get("error", {})
            detail = f"{error.get('type', 'error')}: {error.get('message', '')}"
        except (ValueError, AttributeError):
            detail = "unrecognized error body"
        lowered = detail.casefold()
        if status in (401, 403) and not any(word in lowered for word in NO_CREDIT_WORDS):
            return LlmError("authentication failed (check the OpenCode Go key)", "auth")
        if status in (402, 429) or any(word in lowered for word in NO_CREDIT_WORDS):
            return LlmError(_truncate(f"{self.model}: no credits or rate limited ({status})"),
                            "no-credits")
        if status == 400 and "response_format" in lowered:
            return LlmError(f"{self.model}: JSON mode not supported", "json-unsupported")
        kind = "server" if status >= 500 else "bad-request"
        return LlmError(_truncate(f"{self.model}: HTTP {status}: {detail}"), kind)


class ModelRouter:
    """Free models in rotation, then the paid fallback, with fast cooldowns."""

    def __init__(self, settings: dict, api_key: str | None, opener=None,
                 cache_path: Path | None = None, clock=time.monotonic, wall=time.time, log=None):
        if not api_key:
            raise LlmUnavailable(f"{settings['api_key_env']} is not set", "auth")
        for model in settings["fallback"]:
            if model not in FALLBACK_ALLOWED:
                raise LlmError(f"fallback model {model} is not allowed", "config")
        self.settings = settings
        self._key = api_key
        self._opener = opener or urllib.request.build_opener(_NoRedirect()).open
        self.cache_path = cache_path
        self.clock = clock
        self.wall = wall
        self.log = log or (lambda message: None)
        self.catalog: list[ModelInfo] = []
        self._fetched = None
        self._cooldown: dict[str, tuple[float, str]] = {}
        self._no_json: set[str] = set()
        self._cursor = 0
        self.last_model = ""

    def __repr__(self) -> str:
        return f"ModelRouter(free={self.free_models()}, fallback={self.settings['fallback']})"

    # Catalog ---------------------------------------------------------------------------
    def refresh(self, force: bool = False) -> None:
        """Read the live catalog (and probe the free models) when stale."""
        age = None if self._fetched is None else self.clock() - self._fetched
        if not force and age is not None and age < float(self.settings["catalog_refresh_seconds"]):
            return
        self._fetched = self.clock()
        data = None
        try:
            request = urllib.request.Request(self.settings["models_url"],
                                             headers={"User-Agent": USER_AGENT})
            with self._opener(request, timeout=5) as handle:
                data = json.loads(handle.read())
        except Exception as error:
            self.log(f"model catalog unavailable ({str(error)[:80]}); using the cache")
            data = self._read_cache()
        if data:
            self.catalog = parse_catalog(data, self.settings.get("exclude", []))
            self._write_cache(data)
        self.probe()

    def _read_cache(self) -> dict | None:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path else None
        except (OSError, ValueError):
            return None

    def _write_cache(self, data: dict) -> None:
        if self.cache_path is None:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.cache_path.chmod(0o600)
        except OSError:
            pass

    def free_models(self) -> list[str]:
        return [model.id for model in self.catalog if model.free]

    def _info(self, model_id: str) -> ModelInfo | None:
        return next((model for model in self.catalog if model.id == model_id), None)

    # Health ----------------------------------------------------------------------------
    def cooling(self, model_id: str) -> bool:
        until = self._cooldown.get(model_id, (0.0, ""))[0]
        return self.clock() < until

    def _cool(self, model_id: str, kind: str) -> None:
        seconds = float(self.settings["no_credit_cooldown_seconds"] if kind == "no-credits"
                        else self.settings["cooldown_seconds"])
        self._cooldown[model_id] = (self.clock() + seconds, kind)
        self.log(f"model {model_id} paused {seconds:.0f}s ({kind})")

    def status(self) -> list[dict]:
        rows = []
        for model in self.catalog:
            if model.free or model.id in self.settings["fallback"]:
                until, kind = self._cooldown.get(model.id, (0.0, ""))
                rows.append({"model": model.id, "free": model.free, "training": model.training,
                             "zdr": model.zdr, "json": model.json and model.id not in self._no_json,
                             "paused_for": max(0, round(until - self.clock())),
                             "reason": kind if until > self.clock() else ""})
        return rows

    def probe(self) -> list[dict]:
        """Ping every free model at once with a tiny prompt; pause the ones that fail."""
        models = self.free_models()
        if not models:
            return []
        timeout = float(self.settings["probe_timeout_seconds"])

        def check(model_id: str) -> dict:
            started = self.clock()
            try:
                reply = self._call(model_id, PROBE, f"zaflas-probe-{int(self.wall())}", timeout)
                ok = json_object(reply.content)
                return {"model": model_id, "ok": ok, "kind": "" if ok else "format",
                        "seconds": round(self.clock() - started, 1)}
            except LlmError as error:
                return {"model": model_id, "ok": False, "kind": error.kind,
                        "seconds": round(self.clock() - started, 1)}

        with ThreadPoolExecutor(max_workers=min(8, len(models))) as pool:
            results = list(pool.map(check, models))
        for result in results:
            if result["ok"]:
                self._cooldown.pop(result["model"], None)
            elif result["kind"] != "auth":
                self._cool(result["model"], result["kind"])
        return results

    # Calls -----------------------------------------------------------------------------
    def _call(self, model_id: str, messages: list[dict], session_id: str,
              timeout: float) -> LlmReply:
        info = self._info(model_id)
        free = bool(info and info.free)
        client = OpenCodeGo(self.settings, self._key, self._opener, model_id, free=free)
        json_mode = model_id not in self._no_json and (info.json if info else True)
        try:
            return client.complete(messages, session_id, timeout, json_mode)
        except LlmError as error:
            if error.kind != "json-unsupported":
                raise
            self._no_json.add(model_id)
            return client.complete(messages, session_id, timeout, json_mode=False)

    def candidates(self) -> list[tuple[str, bool]]:
        free = [model for model in self.free_models() if not self.cooling(model)]
        if free:
            start = self._cursor % len(free)
            free = free[start:] + free[:start]
        fallback = list(self.settings["fallback"])
        ready = [model for model in fallback if not self.cooling(model)]
        paused = [model for model in fallback if self.cooling(model)]
        # A paused fallback is still tried last: better a late answer than none.
        return [(model, True) for model in free] + [(model, False) for model in ready + paused]

    def complete(self, messages: list[dict], session_id: str, quick: bool = False) -> LlmReply:
        """First model that answers with a JSON object.

        `quick` is for small optional lookups (a name in a message) whose caller has a local
        fallback: each model gets `quick_timeout_seconds` and only `quick_attempts` are tried,
        so one hung free model cannot hold a reply for the full `free_timeout_seconds`.
        """
        self.refresh()
        failures = []
        attempts = int(self.settings.get("quick_attempts", 2)) if quick else None
        for model_id, free in self.candidates():
            if attempts is not None and len(failures) >= attempts:
                break
            timeout = float(self.settings["free_timeout_seconds"] if free
                            else self.settings["timeout_seconds"])
            if quick:
                timeout = min(timeout, float(self.settings.get("quick_timeout_seconds", 8)))
            try:
                reply = self._call(model_id, messages, session_id, timeout)
            except LlmError as error:
                if error.kind in ("auth", "config"):
                    raise
                self._cool(model_id, error.kind)
                failures.append(f"{model_id}: {error.kind}")
                continue
            if not json_object(reply.content):
                self._cool(model_id, "format")
                failures.append(f"{model_id}: format")
                continue
            if free:
                self._cursor += 1
            self.last_model = model_id
            return reply
        raise LlmError("no model answered (" + "; ".join(failures) + ")", "exhausted")
