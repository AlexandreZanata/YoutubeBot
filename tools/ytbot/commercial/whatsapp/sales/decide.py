"""Reply decision: local classifier, OpenCode Go model, guard and the rules' fixed texts.

Order of authority:
1. A short refusal, opt-out, auto-reply, robot question or media label is decided locally.
2. Otherwise the model reads the context model and proposes an intent and messages.
3. A refusal from either side blocks; `handoff` from the model sends the owner's ack.
4. Fixed intents always send the rules' text; model text is sent only when the guard finds no
   money value, number, link, term or claim outside the rules, else the rules' text is used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from . import classifier, context, guard
from .llm import LlmError
from .rules import SalesRules

BLOCKING = ("opt_out", "refusal")
MODEL_TEXT_ACTIONS = ("reply", "qualify", "close")
HANDOFF_ACTIONS = ("handoff", "quote", "buy", "won", "refer")
RANK = {"needed": 1, "alert": 1, "hot": 2}


def _stronger_handoff(rules: SalesRules, hint: str, chosen: str) -> bool:
    """A local hand-off signal is never weakened by the model (safe side)."""
    local, model = rules.intent(hint), rules.intent(chosen)
    if local.action not in HANDOFF_ACTIONS or model.action == "block":
        return False
    if model.action not in HANDOFF_ACTIONS:
        return True
    return RANK.get(local.priority, 1) > RANK.get(model.priority, 1)


@dataclass
class Decision:
    intent: str
    action: str
    messages: list[str]
    source: str                      # local | fixed | model | template
    hint: str
    reason: str = ""
    violations: list[str] = field(default_factory=list)
    error: str = ""
    cost_usd: float | None = None
    priority: str = ""
    owner_reason: str = ""
    brief: dict | None = None
    collect_turns: int = 0
    referred: str = ""

    def record(self) -> dict:
        return {"intent": self.intent, "action": self.action, "source": self.source,
                "hint": self.hint, "reason": self.reason, "violations": self.violations,
                "error": self.error, "messages": self.messages, "cost_usd": self.cost_usd,
                "priority": self.priority, "owner_reason": self.owner_reason,
                "brief": bool(self.brief)}


def _fixed(rules: SalesRules, intent_id: str, hint: str, source: str) -> Decision:
    intent = rules.intent(intent_id)
    messages = [] if intent.action == "ignore" else list(intent.messages)
    return Decision(intent_id, intent.action, guard.split_links(messages), source, hint,
                    priority=intent.priority, owner_reason=intent.reason)


def stuck(rules: SalesRules, hint: str, why: str) -> Decision:
    """The bot is not moving the conversation forward: hand it to the owner."""
    decision = _fixed(rules, "stuck", hint, "fixed")
    decision.owner_reason = f"{decision.owner_reason} ({why})"
    return decision


def parse_output(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    data = json.loads(text[text.find("{"):text.rfind("}") + 1] if "{" in text else text)
    if not isinstance(data, dict):
        raise ValueError("model output is not an object")
    messages = data.get("messages", [])
    if not isinstance(messages, list) or not all(isinstance(item, str) for item in messages):
        raise ValueError("model messages must be a list of strings")
    return data


def decide(rules: SalesRules, lead: dict, history: list[dict], text: str, llm=None,
           now: datetime | None = None, usage=None) -> Decision:
    """Pick the intent and the exact messages to send for the unanswered text."""
    now = now or datetime.now()
    hint = classifier.classify(rules, text, history, lead.get("state", ""))
    if llm is None or classifier.decisive(hint, text):
        return _fixed(rules, hint, hint, "local")
    try:
        reply = llm.complete(context.build(rules, lead, history, classifier.for_model(text),
                                           hint, now),
                             session_id=f"zaflas-sales-{lead['id']}")
    except LlmError as error:
        decision = _fixed(rules, hint, hint, "local")
        decision.error = str(error)
        return decision
    if usage is not None:
        usage({"at": now.isoformat(timespec="seconds"), "lead": lead["id"],
               "model": reply.model, "input_tokens": reply.input_tokens,
               "output_tokens": reply.output_tokens, "cost_usd": reply.cost_usd,
               "duration_ms": reply.duration_ms})
    try:
        data = parse_output(reply.content)
    except ValueError as error:
        decision = _fixed(rules, hint, hint, "local")
        decision.error = f"invalid model output: {error}"
        decision.cost_usd = reply.cost_usd
        return decision
    intent_id = data.get("intent")
    problems = []
    if not isinstance(intent_id, str) or not rules.has_intent(intent_id):
        problems.append(f"unknown intent {intent_id!r}")
        intent_id = hint
    if hint in BLOCKING:
        intent_id = hint
    elif data.get("do_not_contact") is True and intent_id not in BLOCKING:
        intent_id = "refusal"
    elif _stronger_handoff(rules, hint, intent_id):
        intent_id = hint
    intent = rules.intent(intent_id)
    reason = str(data.get("reason", ""))[:300]
    if intent.action in MODEL_TEXT_ACTIONS and data.get("handoff") is True:
        decision = Decision(intent_id, "handoff", rules.handoff_messages(), "fixed", hint,
                            reason, priority="needed",
                            owner_reason=f"O modelo pediu ajuda: {reason or intent_id}")
    elif intent.fixed or intent.action not in MODEL_TEXT_ACTIONS:
        decision = _fixed(rules, intent_id, hint, "fixed")
        decision.reason = reason
    else:
        messages = guard.split_links([item for item in data.get("messages", []) if item.strip()])
        problems += guard.violations(rules, messages)
        if problems:
            decision = _fixed(rules, intent_id, hint, "template")
        else:
            decision = Decision(intent_id, intent.action, messages, "model", hint)
        decision.reason = reason
    if hint == "bot_question" and decision.intent != "bot_question" and decision.messages:
        honest = list(rules.intent("bot_question").messages)
        decision.messages = honest + [item for item in decision.messages if item not in honest]
    decision.violations = problems
    decision.cost_usd = reply.cost_usd
    return decision
