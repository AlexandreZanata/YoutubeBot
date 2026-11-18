"""Context model for the reply model: rules, lead profile and the full conversation memory.

Only business data reaches the model: the public business name, category and city from the
owner's Maps list, the conversation texts and the rules. Phone numbers never leave the PC.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from string import Template

from .rules import SalesRules

TEMPLATE_PATH = Path(__file__).with_name("context.md")
# Generous bound; DeepSeek V4.1 Flash takes 1M tokens, a sales chat is far smaller.
MAX_HISTORY = 300


def effective(history: list[dict]) -> list[dict]:
    """Memory entries in order, dropping list previews later replaced by the full text."""
    replaced: set[str] = set()
    for entry in history:
        value = entry.get("replaces")
        replaced.update(value if isinstance(value, list) else [value] if value else [])
    return [entry for entry in history
            if not (entry.get("event") and entry.get("event") in replaced)]


def render_history(history: list[dict], agent_name: str) -> str:
    lines = []
    for entry in effective(history)[-MAX_HISTORY:]:
        if entry.get("dir") not in ("in", "out"):
            continue
        if entry.get("dir") == "out" and entry.get("state", "sent") != "sent":
            continue
        speaker = agent_name if entry["dir"] == "out" else "Cliente"
        if entry.get("media") == "audio":
            speaker += " (áudio transcrito)"
        elif entry.get("media"):
            speaker += f" (enviou {entry['media']})"
        when = str(entry.get("at", ""))[:16].replace("T", " ")
        lines.append(f"[{when}] {speaker}: {entry.get('text', '')}")
    return "\n".join(lines) or "(sem mensagens anteriores)"


def _intents(rules: SalesRules) -> str:
    lines = []
    for intent in rules.intents:
        kind = "texto fixo" if intent.fixed else "referência"
        sample = " / ".join(intent.messages) or "(sem mensagem)"
        lines.append(f"- {intent.id} | {intent.action} | {intent.when} | {kind}: {sample}")
    return "\n".join(lines)


def system_prompt(rules: SalesRules) -> str:
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    links = list(rules.raw["opening"]["links"])
    for item in rules.raw["brief"].get("domain_messages", []):
        if item.startswith("https://") and item not in links:
            links.append(item)
    return template.safe_substitute(
        agent_name=rules.raw.get("agent_name", "Alexandre"), company=rules.company,
        max_messages=rules.limits["max_messages_per_reply"],
        max_chars=rules.limits["max_message_chars"], facts=rules.facts_text(),
        links="\n".join(f"- {link}" for link in links),
        intents=_intents(rules))


def build(rules: SalesRules, lead: dict, history: list[dict], text: str, hint: str,
          now: datetime) -> list[dict]:
    profile = " — ".join(part for part in (lead.get("name", ""), lead.get("category", ""),
                                           lead.get("city", "")) if part)
    user = "\n".join([
        f"EMPRESA: {profile or '(sem nome)'}",
        f"ESTADO DA CONVERSA: {lead.get('state', '')}",
        f"CLASSIFICADOR LOCAL SUGERE: {hint}",
        f"HORA LOCAL: {now.strftime('%Y-%m-%d %H:%M')}",
        "",
        "HISTÓRICO (mais antigo primeiro):",
        render_history(history, rules.raw.get("agent_name", "Alexandre")),
        "",
        "NOVA MENSAGEM DO CLIENTE:",
        text.strip(),
    ])
    return [{"role": "system", "content": system_prompt(rules)},
            {"role": "user", "content": user}]
