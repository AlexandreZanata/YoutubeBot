"""Local intent classifier: Portuguese patterns from the rules plus conversation context.

It is the safety net around the model. Refusals, opt-outs and business auto-replies are
recognized here first; when the model is unavailable its intent decides the fixed reply.
"""

from __future__ import annotations

import re

from .rules import SalesRules, normalize

SAFETY = ("opt_out", "refusal", "auto_reply")
# While qualifying, these still win over "the text is the project description".
QUALIFYING_OVERRIDES = ("bot_question", "how_got_number", "call_request", "audio", "sticker",
                        "media", "thanks")
# Intents the local classifier decides alone for short messages (no model call).
DECISIVE = ("opt_out", "refusal", "auto_reply", "bot_question", "sticker", "thanks",
            "audio", "media")
SHORT = 80


def last_outgoing(history: list[dict]) -> str:
    for entry in reversed(history or []):
        if entry.get("dir") == "out" and entry.get("state", "sent") == "sent":
            return entry.get("text", "")
    return ""


def _any(patterns: list[str], plain: str) -> bool:
    return any(re.search(pattern, plain) for pattern in patterns)


def classify(rules: SalesRules, text: str, history: list[dict] | None = None,
             state: str = "") -> str:
    plain = normalize(text)
    if not plain:
        return "unknown"
    for intent_id in SAFETY:
        if rules.intent(intent_id).matches(plain):
            return intent_id
    context = rules.context
    if re.search(context["offer_question"], normalize(last_outgoing(history or []))):
        if _any(context["affirmative"], plain):
            return "quote_accept"
        if _any(context["negative"], plain):
            return "refusal"
    if state == "qualifying":
        for intent_id in QUALIFYING_OVERRIDES:
            if rules.has_intent(intent_id) and rules.intent(intent_id).matches(plain):
                return intent_id
        return "quote_details"
    for intent in rules.intents:
        if intent.id not in SAFETY and intent.matches(plain):
            return intent.id
    return "unknown"


def decisive(intent_id: str, text: str) -> bool:
    """True when the local result is final and the model is not consulted."""
    return intent_id in DECISIVE and len(normalize(text)) <= SHORT
