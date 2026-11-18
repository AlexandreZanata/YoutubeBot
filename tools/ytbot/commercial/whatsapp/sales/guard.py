"""Checks a model-written reply against the rules before anything is sent."""

from __future__ import annotations

import re

from .rules import NUMBER, SalesRules, link_key, links_in, money_values, normalize


def _term(term: str) -> re.Pattern:
    return re.compile(rf"(?<![a-z0-9]){re.escape(normalize(term))}(?![a-z0-9])")


def split_links(messages: list[str]) -> list[str]:
    """Put every link in its own message so WhatsApp renders the preview card."""
    result = []
    for message in messages:
        text = message.strip()
        found = [match for match in re.finditer(r"https?://\S+", text)]
        if not found or (len(found) == 1 and found[0].group(0) == text):
            if text:
                result.append(text)
            continue
        cursor = 0
        for match in found:
            before = text[cursor:match.start()].strip(" \n:-")
            if before:
                result.append(before)
            result.append(match.group(0).rstrip(".,;)"))
            cursor = match.end()
        after = text[cursor:].strip(" \n.-")
        if after:
            result.append(after)
    return result


def is_link(message: str) -> bool:
    return bool(re.fullmatch(r"https?://\S+", message.strip()))


def violations(rules: SalesRules, messages: list[str]) -> list[str]:
    """Every reason the messages may not be sent; empty means safe."""
    problems = []
    limits = rules.limits
    texts = [message for message in messages if not is_link(message)]
    if not messages:
        problems.append("no messages")
    if len(texts) > int(limits["max_messages_per_reply"]):
        problems.append(f"more than {limits['max_messages_per_reply']} messages")
    forbidden = [(term, _term(term)) for term in rules.raw["guard"]["forbidden"]]
    claims = [re.compile(pattern) for pattern in rules.raw["guard"]["human_claims"]]
    offer = re.compile(rules.context["offer_question"])
    promises = [re.compile(pattern) for pattern in rules.raw["guard"]["quote_promises"]]
    sentences = [sentence for message in messages
                 for sentence in re.findall(r"[^.!?]+[.!?]*", normalize(message))]
    systems = [re.compile(pattern) for pattern in rules.raw["guard"]["system_words"]]
    for sentence in sentences:
        money = money_values(sentence)
        days = bool(re.search(r"\d+\s*dias?", sentence))
        priced = bool(money or days)
        if "dominio" in sentence and money == {"40.00"} and not days:
            priced = False
        if (priced and "institucional" not in sentence
                and any(pattern.search(sentence) for pattern in systems)):
            problems.append("site price next to an app or system")
    if any(offer.search(sentence) for sentence in sentences):
        for sentence in sentences:
            if not offer.search(sentence) and any(p.search(sentence) for p in promises):
                problems.append("promises the quote and also offers it")
    for message in messages:
        plain = normalize(message)
        if not plain:
            problems.append("empty message")
            continue
        if len(message) > int(limits["max_message_chars"]):
            problems.append(f"message longer than {limits['max_message_chars']} characters")
        for link in links_in(message):
            if link_key(link) not in rules.allowed_links:
                problems.append(f"link not in the rules: {link_key(link)}")
        without_links = re.sub(r"https?://\S+", " ", plain)
        for value in money_values(without_links):
            if value not in rules.allowed_money:
                problems.append(f"money value not in the rules: {value}")
        for number in NUMBER.findall(without_links):
            if number not in rules.allowed_numbers:
                problems.append(f"number not in the rules: {number}")
        if "%" in plain:
            problems.append("percentage")
        if "@" in plain:
            problems.append("e-mail or handle")
        for term, pattern in forbidden:
            if pattern.search(plain):
                problems.append(f"forbidden term: {term}")
        for pattern in claims:
            if pattern.search(plain):
                problems.append("claims to be human")
    return sorted(set(problems))
