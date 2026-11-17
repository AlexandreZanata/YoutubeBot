"""Load and validate the versioned sales rules (`sales_rules.toml`)."""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

RULES_PATH = Path(__file__).with_name("sales_rules.toml")
# Owner decision 2026-11-17: only DeepSeek V4.1 Flash through OpenCode Go.
ALLOWED_MODELS = ("deepseek-v4.1-flash",)
ACTIONS = ("reply", "qualify", "quote", "collect", "close", "block", "handoff", "ignore")
REQUIRED_INTENTS = ("opt_out", "refusal", "auto_reply", "bot_question", "unknown",
                    "quote_accept", "quote_details", "system_request", "site_institutional",
                    "human_request", "stuck")
PRIORITIES = ("hot", "needed", "alert")
MONEY = re.compile(r"r\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?")
REAIS = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s*reais")
NUMBER = re.compile(r"\d+")
URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\."
                 r"(?:com\.br|com|net|org|io|app|dev|site|online|store|br)\b(?:/[^\s]*)?")


class RulesError(ValueError):
    """The rules file is missing a required field or holds an unsafe value."""


def normalize(text: str) -> str:
    """Lowercase, strip accents and collapse spaces, the form every pattern is matched on."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", plain.casefold()).strip()


def money_values(text: str) -> set[str]:
    """Every money amount in a text, as cents-precision strings ("39.90", "500.00")."""
    plain = normalize(text)
    values = set()
    for pattern in (MONEY, REAIS):
        for whole, cents in pattern.findall(plain):
            values.add(f"{int(whole.replace('.', ''))}.{(cents or '0').ljust(2, '0')}")
    return values


def link_key(url: str) -> str:
    value = normalize(url).rstrip(".,;:!?)")
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    return value.rstrip("/")


def links_in(text: str) -> list[str]:
    return [match.group(0) for match in URL.finditer(normalize(text))]


def _clock(value: str, name: str) -> time:
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except (AttributeError, ValueError) as error:
        raise RulesError(f"{name} must be HH:MM") from error


@dataclass(frozen=True)
class Intent:
    id: str
    action: str
    fixed: bool
    when: str
    patterns: tuple[re.Pattern, ...]
    messages: tuple[str, ...]
    priority: str = "needed"
    reason: str = ""

    def matches(self, plain: str) -> bool:
        return any(pattern.search(plain) for pattern in self.patterns)


@dataclass(frozen=True)
class SalesRules:
    raw: dict
    intents: tuple[Intent, ...]
    allowed_money: frozenset[str] = field(default_factory=frozenset)
    allowed_numbers: frozenset[str] = field(default_factory=frozenset)
    allowed_links: frozenset[str] = field(default_factory=frozenset)

    @property
    def limits(self) -> dict:
        return self.raw["limits"]

    @property
    def pacing(self) -> dict:
        return self.raw["pacing"]

    @property
    def llm(self) -> dict:
        return self.raw["llm"]

    @property
    def context(self) -> dict:
        return self.raw["context"]

    @property
    def brief(self) -> dict:
        return self.raw["brief"]

    @property
    def company(self) -> str:
        return self.raw["company"]

    def intent(self, intent_id: str) -> Intent:
        for intent in self.intents:
            if intent.id == intent_id:
                return intent
        raise KeyError(intent_id)

    def has_intent(self, intent_id: str) -> bool:
        return any(intent.id == intent_id for intent in self.intents)

    def greeting(self, now: datetime) -> str:
        greetings = self.raw["greetings"]
        if now.hour < 12:
            return greetings["morning"]
        if now.hour < 18:
            return greetings["afternoon"]
        return greetings["evening"]

    def opening_messages(self, now: datetime) -> list[str]:
        """The fixed opening, one text per bubble, each link in its own bubble."""
        greeting = self.greeting(now)
        texts = [text.replace("{greeting}", greeting) for text in self.raw["opening"]["messages"]]
        return texts + list(self.raw["opening"]["links"])

    def opening_delays(self) -> list[float]:
        """Seconds before each opening message, aligned with `opening_messages`."""
        opening = self.raw["opening"]
        return ([float(value) for value in opening["delays"]]
                + [float(opening["link_delay"])] * len(opening["links"]))

    def followup_messages(self) -> list[str]:
        return list(self.raw["followup"]["messages"])

    def handoff_messages(self) -> list[str]:
        return list(self.raw["handoff"]["messages"])

    def in_window(self, now: datetime, kind: str) -> bool:
        hours = self.raw["hours"]
        if now.weekday() not in hours[f"{kind}_days"]:
            return False
        start = _clock(hours[f"{kind}_start"], f"hours.{kind}_start")
        end = _clock(hours[f"{kind}_end"], f"hours.{kind}_end")
        return start <= now.time() < end

    def facts_text(self) -> str:
        lines = []
        for group, items in self.raw["facts"].items():
            lines.append(f"[{group}]")
            lines.extend(f"- {item}" for item in items)
        return "\n".join(lines)


def _texts(raw: dict) -> list[str]:
    """Every text the owner wrote: the source of the values the model may repeat."""
    texts = list(raw["opening"]["messages"]) + list(raw["opening"]["links"])
    texts += list(raw["followup"]["messages"]) + list(raw["handoff"]["messages"])
    for items in raw["facts"].values():
        texts.extend(items)
    for intent in raw["intents"]:
        texts.extend(intent.get("messages", []))
    return texts


def _require(raw: dict, section: str, keys: tuple[str, ...]) -> None:
    if not isinstance(raw.get(section), dict):
        raise RulesError(f"missing [{section}]")
    for key in keys:
        if key not in raw[section]:
            raise RulesError(f"missing {section}.{key}")


def build(raw: dict) -> SalesRules:
    for key in ("version", "company", "timezone"):
        if key not in raw:
            raise RulesError(f"missing {key}")
    _require(raw, "limits", ("daily_openings", "max_replies_per_lead_per_day",
                             "max_messages_per_reply", "max_message_chars",
                             "max_bot_replies_before_owner", "owner_reminder_minutes",
                             "followup_after_hours", "max_followups",
                             "no_response_after_followup_hours"))
    _require(raw, "hours", ("opening_days", "opening_start", "opening_end", "reply_days",
                            "reply_start", "reply_end"))
    _require(raw, "pacing", ("typing_chars_per_second", "min_seconds", "max_seconds",
                             "reading_chars_per_second", "reading_min_seconds",
                             "reading_max_seconds", "jitter", "link_preview_seconds",
                             "between_chats_min_seconds", "between_chats_max_seconds"))
    _require(raw, "llm", ("base_url", "model", "api_key_env", "temperature",
                          "max_output_tokens", "timeout_seconds"))
    _require(raw, "greetings", ("morning", "afternoon", "evening"))
    _require(raw, "opening", ("messages", "links", "delays", "link_delay"))
    _require(raw, "followup", ("messages",))
    _require(raw, "handoff", ("messages",))
    _require(raw, "context", ("offer_question", "affirmative", "negative"))
    _require(raw, "guard", ("forbidden", "human_claims", "quote_promises"))
    _require(raw, "brief", ("max_collect_turns", "required", "optional", "done_patterns",
                            "fallback_question"))
    for pattern in raw["brief"]["done_patterns"]:
        try:
            re.compile(pattern)
        except re.error as error:
            raise RulesError(f"brief.done_patterns: bad pattern ({error})") from error
    if not isinstance(raw.get("facts"), dict) or not raw["facts"]:
        raise RulesError("missing [facts]")
    if raw["llm"]["model"] not in ALLOWED_MODELS:
        raise RulesError(f"llm.model must be one of {', '.join(ALLOWED_MODELS)}")
    if not str(raw["llm"]["base_url"]).startswith("https://"):
        raise RulesError("llm.base_url must use https")
    limits = raw["limits"]
    if not 0 < int(limits["daily_openings"]) <= 50:
        raise RulesError("limits.daily_openings must be between 1 and 50")
    if int(limits["max_followups"]) not in (0, 1):
        raise RulesError("limits.max_followups must be 0 or 1")
    pacing = raw["pacing"]
    if not 0 < float(pacing["min_seconds"]) <= float(pacing["max_seconds"]):
        raise RulesError("pacing.min_seconds must be positive and not above max_seconds")
    for kind in ("opening", "reply"):
        _clock(raw["hours"][f"{kind}_start"], f"hours.{kind}_start")
        _clock(raw["hours"][f"{kind}_end"], f"hours.{kind}_end")
    delays = raw["opening"]["delays"]
    if len(delays) != len(raw["opening"]["messages"]):
        raise RulesError("opening.delays needs one value per opening message")
    if not all(0 < float(value) <= 60 for value in [*delays, raw["opening"]["link_delay"]]):
        raise RulesError("opening delays must be between 0 and 60 seconds")
    for link in raw["opening"]["links"]:
        if not str(link).startswith("https://"):
            raise RulesError(f"opening link must use https: {link}")
    intents = []
    seen = set()
    for item in raw.get("intents", []):
        intent_id = item.get("id")
        if not intent_id or intent_id in seen:
            raise RulesError(f"intent id missing or repeated: {intent_id!r}")
        seen.add(intent_id)
        if item.get("action") not in ACTIONS:
            raise RulesError(f"intent {intent_id}: action must be one of {', '.join(ACTIONS)}")
        messages = tuple(item.get("messages", []))
        if item["action"] not in ("ignore",) and not messages:
            raise RulesError(f"intent {intent_id}: action {item['action']} needs messages")
        try:
            patterns = tuple(re.compile(pattern) for pattern in item.get("patterns", []))
        except re.error as error:
            raise RulesError(f"intent {intent_id}: bad pattern ({error})") from error
        priority = item.get("priority", "needed")
        if priority not in PRIORITIES:
            raise RulesError(f"intent {intent_id}: priority must be one of {', '.join(PRIORITIES)}")
        if item["action"] in ("handoff", "quote", "collect") and not item.get("reason"):
            raise RulesError(f"intent {intent_id}: a hand-off needs a reason for the owner")
        intents.append(Intent(intent_id, item["action"], bool(item.get("fixed", False)),
                              item.get("when", ""), patterns, messages, priority,
                              item.get("reason", "")))
    missing = [intent for intent in REQUIRED_INTENTS if intent not in seen]
    if missing:
        raise RulesError(f"missing intents: {', '.join(missing)}")
    for intent_id in ("opt_out", "refusal"):
        if next(i for i in intents if i.id == intent_id).action != "block":
            raise RulesError(f"intent {intent_id} must use action block")
    texts = _texts(raw)
    money = set()
    numbers = set()
    for text in texts:
        money |= money_values(text)
        numbers |= set(NUMBER.findall(normalize(text)))
    links = frozenset(link_key(link) for link in raw["opening"]["links"])
    return SalesRules(raw, tuple(intents), frozenset(money), frozenset(numbers), links)


def load(path: Path | None = None) -> SalesRules:
    path = path or RULES_PATH
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise RulesError(f"cannot read {path.name}: {error}") from error
    return build(raw)
