"""Local intent classifier: Portuguese patterns from the rules plus conversation context.

It is the safety net around the model. Refusals, opt-outs and business auto-replies are
recognized here first; when the model is unavailable its intent decides the fixed reply.
"""

from __future__ import annotations

import re

from .rules import SalesRules, normalize

SAFETY = ("opt_out", "refusal", "auto_reply")
# Checked right after the safety intents: a number, a payment or a staff member answering says
# more about the conversation than any word they contain ("vou falar com o dono").
FIRST = ("referral", "payment_sent", "ready_to_buy", "gatekeeper")
# While qualifying, these still win over "the text is the project description".
# Media, phone numbers for the site, and short "agora não / não tenho" answers to optional
# material questions stay part of the project details (`quote_details`).
QUALIFYING_OVERRIDES = ("human_request", "bot_question", "how_got_number", "trust_concern",
                        "call_request", "callback_later", "sticker", "payment_sent",
                        "ready_to_buy", "links_not_opening")
QUALIFYING_REFUSAL = re.compile(
    r"nao (tenho|temos) (mais )?interesse|sem interesse|\bdesisti\b|"
    r"nao (quero|queremos) mais\b|cancela(r)? (tudo|o orcamento|isso)"
)
QUALIFYING_DONE_FOR_QUOTE = re.compile(r"^pode fazer[.! ]*$")
# Intents the local classifier decides alone for short messages (no model call).
DECISIVE = ("opt_out", "refusal", "auto_reply", "bot_question", "sticker", "thanks",
            "audio", "media", "human_request", "trust_concern", "callback_later", "referral",
            "payment_sent", "gatekeeper", "app_at_site_price", "system_price",
            "links_not_opening")
SHORT = 80
# A photo or document with a caption arrives as "Photo\n<caption>": the caption is the message.
MEDIA_LABEL = re.compile(r"^(photo|foto|image|imagem|video|document|documento)\s+(?=\S)")
LABEL_LINE = re.compile(r"^\s*(photo|foto|image|imagem|video|vídeo|document|documento)\s*\n(?=\S)",
                        re.IGNORECASE)
# Always final locally: while qualifying, the text is the project description; business
# auto-replies (which are often >80 chars) are always ignored to avoid bot-vs-bot loops.
ALWAYS_DECISIVE = ("quote_details", "auto_reply")


def for_model(text: str) -> str:
    """Show a media caption to the model as text with an attachment note."""
    return LABEL_LINE.sub("[mídia anexada] ", text or "")


def last_outgoing(history: list[dict]) -> str:
    for entry in reversed(history or []):
        if entry.get("dir") == "out" and entry.get("state", "sent") == "sent":
            return entry.get("text", "")
    return ""


def _any(patterns: list[str], plain: str) -> bool:
    return any(re.search(pattern, plain) for pattern in patterns)


def classify(rules: SalesRules, text: str, history: list[dict] | None = None,
             state: str = "") -> str:
    plain = MEDIA_LABEL.sub("", normalize(text))
    if not plain:
        return "unknown"
    if state == "qualifying":
        for intent_id in ("opt_out", "auto_reply"):
            if rules.intent(intent_id).matches(plain):
                return intent_id
        if QUALIFYING_REFUSAL.search(plain):
            return "refusal"
        if QUALIFYING_DONE_FOR_QUOTE.search(plain):
            return "quote_details"
        for intent_id in QUALIFYING_OVERRIDES:
            if rules.has_intent(intent_id) and rules.intent(intent_id).matches(plain):
                return intent_id
        return "quote_details"
    for intent_id in SAFETY:
        if rules.intent(intent_id).matches(plain):
            return intent_id
    for intent_id in FIRST:
        if rules.has_intent(intent_id) and rules.intent(intent_id).matches(plain):
            return intent_id
    context = rules.context
    if re.search(context["offer_question"], normalize(last_outgoing(history or []))):
        if _any(context["affirmative"], plain):
            return "quote_accept"
        if _any(context["negative"], plain):
            return "refusal"
    for intent in rules.intents:
        if intent.id not in SAFETY + FIRST and intent.matches(plain):
            return intent.id
    return "unknown"


def decisive(intent_id: str, text: str) -> bool:
    """True when the local result is final and the model is not consulted."""
    if intent_id in ALWAYS_DECISIVE:
        return True
    return intent_id in DECISIVE and len(normalize(text)) <= SHORT
