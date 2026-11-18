"""Semantic classification, harassment policy, and destructive-action detection.

All replies and candidate choices produced here format items and extras strictly from
`RestaurantRules` so prices and descriptions always stay anchored to the TOML rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..sales.rules import normalize
from .order import Line, Order
from .parser import item_mentions, numbers, quantity
from .rules import Item, RestaurantRules, brl

HARASSMENT_SEVERE = re.compile(
    r"\b(nudes?|pelad[oa]s?|sexo|transar|foder|chupar|boquete|buceta|piroca|xoxota|"
    r"rola|pau no|vai tomar no)\b"
)
HARASSMENT_MILD = re.compile(
    r"\b(safad[oa]s?|se e que me entende|maior salsicha|namora(?:r| comigo)?|"
    r"casa(?:r)? comigo|solteira|ficar comigo|sai(?:r)? comigo|me da um beijo|beijinho|"
    r"gostosona|sacanagem|putaria|tesao)\b|"
    r"\bvoce e (?:muito |toda )?(?:gostosa|linda|gata|delicia)\b|"
    r"\bsua (?:gostosa|linda|safada|delicia)\b"
)
HARASSMENT_WORDS = re.compile(
    r"\b(?:safad[oa]s?|gostos[oa]s?|gostosona|se e que me entende.*)\b"
)

CLEAR_CART = re.compile(
    r"\b(tira|tirar|remove|remover|retira|retirar|apaga|apagar|limpa|limpar|zera|zerar)"
    r"\s+tudo\b|"
    r"\b(limpa|limpar|zera|zerar|apaga|apagar)\s+(?:o\s+)?(?:carrinho|pedido)\b"
)
KEEP_ONLY = re.compile(
    r"\b(deixa(?:r)?|fica(?:r)?(?:\s+com)?|mantem|manter)\s+(?:so|apenas|somente)\s+(.+)$"
)
ONLY_SHORT = re.compile(
    r"^(?:quero\s+)?(?:so|apenas|somente)\s+"
    r"(um|uma|dois|duas|tres|quatro|cinco|\d{1,2}|esse|essa|este|esta)(?:\s+mesmo)?$"
)
WAITING_PING = re.compile(
    r"\b(cade (?:o )?atendimento|ninguem responde|demora(?:ndo)?|tem alguem|"
    r"tem gente|alguem ai|estao ai|responde ai)\b"
)
ALIVE_PING = re.compile(
    r"^(?:oi+|ola+|alo+|ei+|bom dia|boa tarde|boa noite|tudo bem|tudo bom|"
    r"cade (?:o )?atendimento|ninguem responde|tem alguem|tem gente|alguem ai)[?!.\s]*$"
)


@dataclass
class DestructiveAction:
    kind: str  # clear_cart | keep_only | ambiguous_keep | already_single
    line: Line | None = None
    qty: int = 1


@dataclass
class SemanticReply:
    messages: list[str]
    intent: str
    last_question: str = ""
    candidates: tuple[str, ...] = ()
    qty: int = 1


def harassment_level(text: str) -> int:
    """0 clean, 1 mild innuendo/flirtation, 2 severe explicit sexual content."""
    plain = normalize(text)
    if not plain:
        return 0
    if HARASSMENT_SEVERE.search(plain):
        return 2
    if HARASSMENT_MILD.search(plain):
        return 1
    return 0


def sanitize_phrase(value: str) -> str:
    """Strip inappropriate tokens before repeating an unrecognized fragment back."""
    cleaned = HARASSMENT_WORDS.sub(" ", normalize(value))
    return re.sub(r"\s+", " ", cleaned).strip()


def is_waiting_ping(text: str) -> bool:
    return bool(WAITING_PING.search(normalize(text)))


def is_alive_ping(text: str) -> bool:
    return bool(ALIVE_PING.match(normalize(text)))


def extras_menu(rules: RestaurantRules) -> str:
    lines = ["Nossos adicionais disponíveis:"]
    for extra in rules.extras:
        lines.append(f"• {extra.name} — {brl(extra.price_cents)}")
    return "\n".join(lines)


def _format_choices(items: list[Item], header: str, footer: str) -> list[str]:
    lines = [header]
    for item in items:
        desc = f" ({item.description})" if item.description else ""
        lines.append(f"• {item.name} — {item.price}{desc}")
    lines.append(footer)
    return ["\n".join(lines)]


def _top_category(rules: RestaurantRules, category: str, count: int = 2) -> list[Item]:
    return sorted(
        (item for item in rules.items if item.category == category),
        key=lambda item: item.price_cents,
        reverse=True,
    )[:count]


def _category_list(rules: RestaurantRules, category: str, header: str) -> list[str]:
    items = [item for item in rules.items if item.category == category]
    if not items:
        return []
    lines = [header]
    for item in items:
        lines.append(f"• {item.name} — {item.price}")
    lines.append("Qual você gostaria?")
    return ["\n".join(lines)]


def detect_destructive(rules: RestaurantRules, order: Order, text: str,
                       has_done: bool = False) -> DestructiveAction | None:
    """Detect whole-cart clears or ambiguous quantity reductions before mutating state."""
    if order.is_empty() or has_done:
        return None
    plain = normalize(text).replace("-", " ")
    if CLEAR_CART.search(plain):
        return DestructiveAction("clear_cart")
    match = KEEP_ONLY.search(plain)
    tail = match.group(2).strip() if match else ""
    if not match:
        short = ONLY_SHORT.match(plain)
        if not short:
            return None
        tail = plain
    mentions = item_mentions(rules, tail)
    in_cart = {line.item_id: line for line in order.lines}
    if mentions:
        matched_ids = [item.id for _, _, item in mentions if item.id in in_cart]
        if not matched_ids:
            return None
        if len(set(matched_ids)) > 1:
            return DestructiveAction("ambiguous_keep")
        line = in_cart[matched_ids[0]]
        explicit = numbers(tail)
        qty = explicit[-1] if explicit else line.qty
        qty = max(qty, 1)
        if len(order.lines) == 1 and line.qty == qty:
            return DestructiveAction("already_single", line=line, qty=qty)
        return DestructiveAction("keep_only", line=line, qty=qty)

    if len(order.lines) > 1:
        return DestructiveAction("ambiguous_keep")
    line = order.lines[0]
    qty = max(quantity(tail), 1)
    if line.qty == qty:
        return DestructiveAction("already_single", line=line, qty=qty)
    return DestructiveAction("keep_only", line=line, qty=qty)


def detect_semantic(rules: RestaurantRules, text: str) -> SemanticReply | None:
    """Resolve superlatives, recommendations and category questions using catalog items."""
    plain = normalize(text).replace("-", " ")
    if not plain:
        return None
    mentions = item_mentions(rules, plain)
    if mentions:
        return None

    vals = numbers(plain)
    qty = vals[0] if vals and 1 <= vals[0] <= int(rules.limits["max_qty_per_item"]) else 1

    big_burger = (
        re.search(
            r"\b(?:maior|mais grande|mais completo|mais recheado|gigante|monstro)\b"
            r".*\b(?:lanche|burger|hamburguer|sanduiche)\b",
            plain,
        )
        or re.search(
            r"\b(?:lanche|burger|hamburguer|sanduiche)\b.*"
            r"\b(?:maior|mais completo|mais recheado|do maior)\b",
            plain,
        )
        or re.search(r"\b(?:do maior que tem|maior que (?:voces )?tem|maior da casa)\b", plain)
    )
    if big_burger:
        choices = _top_category(rules, "burgers", 2)
        if choices:
            return SemanticReply(
                _format_choices(choices, "Os maiores lanches do cardápio são:",
                                "Qual deles você gostaria?"),
                intent="semantic_choice",
                last_question="clarify_choice",
                candidates=tuple(item.id for item in choices),
                qty=qty,
            )

    if re.search(r"\b(?:maior|mais completo|melhor)\b.*\b(?:hot dog|hotdog|cachorro quente|dog)\b"
                 r"|\b(?:hot dog|hotdog|cachorro quente)\b.*\b(?:maior|mais completo|melhor)\b",
                 plain):
        choices = _top_category(rules, "hotdogs", 2)
        if choices:
            return SemanticReply(
                _format_choices(choices, "Os hot dogs mais completos são:",
                                "Qual deles você gostaria?"),
                intent="semantic_choice",
                last_question="clarify_choice",
                candidates=tuple(item.id for item in choices),
                qty=qty,
            )

    if re.search(r"\b(?:maior|melhor)\b.*\b(?:porcao|porcoes|batata)\b", plain):
        choices = _top_category(rules, "portions", 2)
        if choices:
            return SemanticReply(
                _format_choices(choices, "Nossas maiores porções são:",
                                "Qual você gostaria?"),
                intent="semantic_choice",
                last_question="clarify_choice",
                candidates=tuple(item.id for item in choices),
                qty=qty,
            )

    if re.search(r"\b(?:qual (?:o )?melhor|mais pedido|mais vendido|recomenda|indica|"
                 r"sugestao|o que tem de bom)\b", plain):
        preferred = [item for item in rules.items
                     if item.id in ("podrao", "x-bacon", "combo-x-bacon")]
        if preferred:
            return SemanticReply(
                _format_choices(preferred, "Esses são alguns dos mais pedidos:",
                                "Qual você gostaria?"),
                intent="semantic_choice",
                last_question="clarify_choice",
                candidates=tuple(item.id for item in preferred),
                qty=qty,
            )

    if re.search(r"\b(?:adicionais|adicional|acrescimo|acrescimos)\b", plain) and \
            re.search(r"\b(?:quais|tem|ver|manda|lista|sao|quanto|quero)\b", plain):
        return SemanticReply([extras_menu(rules)], intent="extras_info",
                             last_question="menu_question")

    if re.search(r"\b(?:bebida|bebidas|refrigerante|refrigerantes|refri|para beber|tomar|"
                 r"sucos?)\b", plain):
        if "suco" in plain:
            if re.search(r"\bsuco\s+de\s+(?!(?:laranja|maracuja)\b)[a-z]+", plain):
                return None
            juices = [item for item in rules.items if item.id.startswith("suco-")]
            if juices and re.search(r"\b(?:quais|tem|sabor|sabores|sucos?)\b", plain):
                return SemanticReply(
                    _format_choices(juices, "Os sucos disponíveis são:", "Qual você gostaria?"),
                    intent="semantic_choice",
                    last_question="clarify_choice",
                    candidates=tuple(item.id for item in juices),
                    qty=qty,
                )
        msgs = _category_list(rules, "drinks", "Nossas bebidas disponíveis:")
        if msgs:
            return SemanticReply(msgs, intent="category_info", last_question="menu_question")

    category_specs = (
        ("burgers",
         r"\b(?:lanche|lanches|hamburguer\w*|burger\w*|sanduiche\w*)\b",
         "Nossos lanches (burgers artesanais):",
         True),
        ("hotdogs",
         r"\b(?:hot\s*dogs?|hotdogs?|cachorros?\s*quentes?)\b",
         "Nossos hot dogs:",
         False),
        ("combos",
         r"\bcombos?\b",
         "Nossos combos:",
         False),
        ("portions",
         r"\bporc(?:ao|oes)\b",
         "Nossas porções:",
         False),
        ("desserts",
         r"\b(?:sobremesa|sobremesas|doce|doces)\b",
         "Nossas sobremesas:",
         False),
    )
    has_modifier = bool(re.search(r"\bcom\s+[a-z]+", plain))
    browse_verb = bool(re.search(r"\b(?:quais|tem|ver|manda|lista|sao|opcoes)\b", plain))
    for cat, pat, header, guard_plural_order in category_specs:
        if not re.search(pat, plain):
            continue
        if has_modifier:
            continue
        if guard_plural_order and not browse_verb and re.search(r"\b(?:dois|duas|tres|\d+)\b", plain):
            continue
        if browse_verb or re.match(
                rf"^(?:quero(?:\s+ver)?(?:\s+(?:um|uma|o|os|as))?\s+|"
                rf"me\s+(?:ve|manda)\s+(?:(?:os|as)\s+)?)?(?:{pat.strip()})[?!.\s]*$",
                plain):
            msgs = _category_list(rules, cat, header)
            if msgs:
                return SemanticReply(msgs, intent="category_info", last_question="menu_question")

    return None


def resolve_clarify_choice(rules: RestaurantRules, candidates: list[str],
                           text: str) -> str | None:
    """Resolve "o primeiro", "o segundo", "o mais caro" against prior options."""
    valid = []
    for item_id in candidates:
        try:
            valid.append(rules.item(item_id))
        except KeyError:
            continue
    if not valid:
        return None
    plain = normalize(text)
    if re.search(r"\b(?:o )?(?:primeiro|primeira|opcao 1)\b|^1$", plain):
        return valid[0].id
    if len(valid) >= 2 and re.search(r"\b(?:o )?(?:segundo|segunda|opcao 2)\b|^2$", plain):
        return valid[1].id
    if len(valid) >= 3 and re.search(r"\b(?:o )?(?:terceiro|terceira|opcao 3)\b|^3$", plain):
        return valid[2].id
    if re.search(r"\b(?:o )?(?:mais caro|maior|maior deles|mais completo)\b", plain):
        return max(valid, key=lambda item: item.price_cents).id
    if re.search(r"\b(?:o )?(?:mais barato|menor)\b", plain):
        return min(valid, key=lambda item: item.price_cents).id
    if len(valid) == 1 and re.search(r"\b(?:esse|essa|esse mesmo|pode ser)\b", plain):
        return valid[0].id
    return None
