"""Local reading of a WhatsApp order: items, quantities, extras, notes and order fields.

The parser only returns catalog ids. It never returns a price: `order.py` does the arithmetic.
A model can help when this parser finds nothing (see `interpreter.py`), but its answer passes
the same catalog validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rules import Item, RestaurantRules, normalize

NUMBER_WORDS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
                "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10}
NUMBER = re.compile(r"(?<![\d,.])(\d{1,3}|" + "|".join(NUMBER_WORDS) + r")(?![\d,.])")
REMOVE_CUE = re.compile(r"\b(tira|tirar|remove|remover|retira|retirar|sem|nao quero|cancela|"
                        r"exclui|excluir)\b")
REMOVE_TAIL = re.compile(r"\b(tira|tirar|remove|remover|retira|retirar|sem|nao quero|cancela|"
                         r"exclui|excluir)\s+(?:(?:a|o|as|os|um|uma|uns|umas|dois|duas|"
                         r"\d{1,2})\s+)?$")
ADD_CUE = re.compile(r"\b(quero|queria|me ve|me manda|manda|adiciona|acrescenta|poe|coloca|"
                     r"vou querer|vou de|para mim|mais|com)\b")
MODIFY_CUE = re.compile(r"\b(adiciona|acrescenta|poe|coloca|tira|tirar|remove|remover|retira|"
                       r"retirar)\b")
QUESTION_CUE = re.compile(r"\b(quanto|qual|quais|preco|valor|custa|sai|tem|vem|ingredientes|"
                          r"o que e|como e)\b")
ADDRESS_CUE = re.compile(r"\b(rua|avenida|av|travessa|alameda|rodovia|estrada|passagem|"
                         r"beco|quadra|lote|setor|bairro|jardim|centro|casa|apto|"
                         r"apartamento|bloco|condominio|residencial|vila)\b")
NAME = re.compile(r"^[\wÀ-ÿ' .-]{2,120}$")
NON_NAME_WORDS = {
    "sim", "s", "nao", "n", "ok", "okay", "oi", "ola", "bom", "boa", "dia", "tarde",
    "noite", "entrega", "retirada", "delivery", "retirar", "pix", "cartao", "dinheiro",
    "debito", "credito", "fechar", "pode", "obrigado", "obrigada", "valeu", "beleza", "blz",
}
FORBIDDEN_NOTE = re.compile(r"\b(desconto|cupom|promocao|promo|gratis|gratuito|de graca|"
                            r"brinde|garantia|reembolso|senha|cpf|cnpj|"
                            r"safad[oa]s?|gostos[oa]s?|maior salsicha|se e que me entende)\b")
DISH_FLAVOR_PREFIX = re.compile(
    r"\b(?:pizza|pastel|esfiha|empada|coxinha|torta|risole|kalzone|calzone)\s+(?:de\s+)?$"
)
CONDIMENT_FOOD = re.compile(
    r"\b(?:molh\w*|creme\w*|tempero\w*|pimenta\w*|ketchup|catchup|mostarda|barbecue|"
    r"vinagrete|farofa|pate)\b"
    r"(?:\s+(?:de|da|do|com)\s+[a-z]{2,}(?:\s+[a-z]{2,})?|"
    r"\s+(?!especial\b|da\s+casa\b)[a-z]{4,})?"
)
DISH_FOOD = re.compile(
    r"\b(?:suco\s+de\s+(?!(?:laranja|maracuja)\b)[a-z]{2,}(?:\s+[a-z]{2,})?|"
    r"pizza(?:\s+de\s+[a-z]{2,})?|pastel(?:\s+de\s+[a-z]{2,})?|"
    r"esfiha(?:\s+de\s+[a-z]{2,})?|coxinha(?:\s+de\s+[a-z]{2,})?|"
    r"empada(?:\s+de\s+[a-z]{2,})?|lasanha|macarrao|temaki|sushi|"
    r"cerveja|chopp|chop|vinho|energetico|nuggets?|sorvete|torta|brownie|"
    r"refrigerante\s+de\s+[a-z]{2,})\b"
)
INDEPENDENT_ITEM = re.compile(
    r"^(?:um|uma|dois|duas|tres|quatro|cinco|mais|\d+)\s+[a-z]{3,}"
)
TRAILING_QTY = re.compile(r"^\s*(?:x\s*(\d{1,2})|(\d{1,2})\s*x)\b")
DRINK_VARIANT = re.compile(
    r"^\s*(zero|diet|light|sem acucar|\d+\s*l(?:itros?)?|litros?|600\s*ml|garrafa|pet|grande)\b")
# A generic noun ("um lanche", "uma bebida") that names no catalog item: the customer gets the
# options of that category instead of the noun being ignored.
CATEGORY_NOUNS = {
    "burgers": re.compile(r"\b(?:lanche|lanches|hamburg\w*|burger\w*|sanduiche\w*)\b"),
    "combos": re.compile(r"\bcombos?\b"),
    "portions": re.compile(r"\bporc(?:ao|oes)\b"),
    "desserts": re.compile(r"\b(?:sobremesas?|doces?)\b"),
    "drinks": re.compile(r"\b(?:bebidas?|refrigerantes?|refris?|sucos?)\b"),
}
PAYMENT_WORDS = ("pix", "cartao", "dinheiro", "debito", "credito", "maquininha", "troco",
                 "transferencia", "especie")


@dataclass
class ParsedItem:
    item_id: str
    qty: int = 1
    extras: list[str] = field(default_factory=list)
    note: str = ""
    remove: bool = False


@dataclass
class Parsed:
    items: list[ParsedItem] = field(default_factory=list)
    remove_extras: list[str] = field(default_factory=list)
    fields: dict = field(default_factory=dict)
    done: bool = False
    cancel: bool = False
    question_items: list[str] = field(default_factory=list)
    unknown_parts: list[str] = field(default_factory=list)
    unknown_wants_extras: bool = False
    generic_categories: list[str] = field(default_factory=list)
    unknown_category: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.items or self.remove_extras)


def numbers(text: str) -> list[int]:
    values = []
    for match in NUMBER.finditer(text):
        raw = match.group(1)
        values.append(int(raw) if raw.isdigit() else NUMBER_WORDS[raw])
    return values


def quantity(prefix: str) -> int:
    """The last quantity written just before the item ("quero 2 x-bacon")."""
    values = numbers(re.sub(r"r\$\s*\d+(?:[,.]\d+)?", " ", prefix))
    return values[-1] if values else 1


def item_mentions(rules: RestaurantRules, plain: str) -> list[tuple[int, int, Item]]:
    """Every item mentioned once, longest alias first and without overlapping spans."""
    found: list[tuple[int, int, Item]] = []
    for item in rules.items:
        for match in item.pattern.finditer(plain):
            before = plain[max(0, match.start() - 24):match.start()]
            if DISH_FLAVOR_PREFIX.search(before):
                continue
            found.append((match.start(), match.end(), item))
    found.sort(key=lambda entry: (entry[0], -(entry[1] - entry[0])))
    kept: list[tuple[int, int, Item]] = []
    for entry in found:
        if kept and entry[0] < kept[-1][1]:
            continue
        kept.append(entry)
    return kept


def _extra_matches(rules: RestaurantRules, item: Item, segment: str) -> list[str]:
    """Extras explicitly asked in the segment; "sem bacon" removes, it does not add."""
    extras = []
    for extra in rules.extras_for(item.category):
        for match in extra.pattern.finditer(segment):
            prefix = segment[max(0, match.start() - 12):match.start()]
            if REMOVE_CUE.search(prefix):
                continue
            if extra.id == "molho-especial":
                after = segment[match.end():match.end() + 24]
                if re.match(r"^\s+(?:de|da|do|sabor)\s+(?!(?:casa|especial)\b)[a-z]{2,}", after):
                    continue
            # "com cheddar", "mais bacon", "extra de queijo": a bare extra after "e" is
            # still accepted ("x-bacon e bacon"), because the customer named it.
            extras.append(extra.id)
            break
    return list(dict.fromkeys(extras))


NOTE_STOP = {"entrega", "retirada", "pix", "dinheiro", "cartao", "hoje", "amanha",
             "agora", "favor", "por", "para", "mim", "mesa", "balcao", "delivery"}


def _known_phrases(rules: RestaurantRules, item: Item) -> set[str]:
    known = {normalize(alias) for extra in rules.extras_for(item.category)
             for alias in extra.aliases}
    known |= {normalize(alias) for menu_item in rules.items for alias in menu_item.aliases}
    known |= {normalize(extra.name) for extra in rules.extras_for(item.category)}
    return known


def _note(segment: str, rules: RestaurantRules, item: Item) -> str:
    """Short customer notes ("sem cebola", "de chocolate", "bem passado")."""
    notes = []
    known = _known_phrases(rules, item)
    for part in re.split(r"\s*(?:,|;|\n|\+|\be\b)\s*", segment):
        clean_part = normalize(part)
        if not clean_part:
            continue
        if (INDEPENDENT_ITEM.match(clean_part)
                and not re.search(r"\b(?:sem|bem passado|mal passado|ao ponto)\b", clean_part)):
            continue
        for cue in re.findall(r"\bsem\s+([a-z]{3,}(?:\s+(?!com\b)[a-z]{3,}){0,2})", clean_part):
            if not FORBIDDEN_NOTE.search(cue):
                notes.append("sem " + re.sub(r"\br\$?\s*\d+(?:[,.]\d+)?\b", "", cue).strip())
        for cue in re.findall(r"\b(?:de|com|sabor)\s+([a-z]{3,}(?:\s+(?!sem\b|com\b|e\b)"
                              r"[a-z]{3,}){0,2})", clean_part):
            plain = normalize(cue)
            if plain in known or plain.split()[0] in NOTE_STOP or plain in NOTE_STOP:
                continue
            if FORBIDDEN_NOTE.search(plain):
                continue
            notes.append(cue.strip())
        for cue in re.findall(r"\b(bem passado|mal passado|ao ponto|pouco molho|"
                              r"sem molho|pouca cebola)\b", clean_part):
            notes.append(cue)
    return "; ".join(dict.fromkeys(notes))[:60]


def _money_cents(raw: str, cents: str | None) -> int:
    return int(raw) * 100 + (int((cents or "0").ljust(2, "0")) if cents else 0)


def parse_change(text: str) -> tuple[int | None, bool]:
    """(change_for_cents, exact) from "troco para 100", "nota de 50" or "sem troco"."""
    plain = normalize(text)
    if any(re.search(pattern, plain) for pattern in
           (r"sem troco", r"nao preciso de troco", r"valor exato", r"tenho o valor exato",
            r"pago o valor exato")):
        return None, True
    if "troco" not in plain and "nota" not in plain and "para" not in plain and "pra" not in plain:
        return None, False
    match = re.search(r"(?:troco\s+pa?ra|nota\s+de|pa?ra|tenho|pago\s+com|paguei\s+com)\s*"
                      r"r?\$?\s*(\d{1,4})(?:[,.](\d{1,2}))?", plain)
    if not match:
        return None, False
    return _money_cents(match.group(1), match.group(2)), False


PAY_PLACE = re.compile(
    r"\b(?:pag\w*|paga\w*|cartao|dinheiro|pix|debito|credito)\s+(?:\w+\s+){0,2}?"
    r"(?:na|no|em)\s+(?:entrega|retirada|balcao)\b")


def parse_kind(text: str) -> str:
    # "pago na entrega no débito" says WHEN to pay, not that the order is a delivery.
    plain = PAY_PLACE.sub(" ", normalize(text))
    if re.search(r"\b(retirar|retirada|retiro|retira|buscar|busco|balcao|vou pegar|pego ai|"
                 r"passo ai)\b", plain):
        return "pickup"
    if re.search(r"\b(entrega|entregar|delivery|entregam|mandar em casa|levar em casa)\b", plain):
        return "delivery"
    return ""


def parse_payment(rules: RestaurantRules, text: str) -> str:
    plain = normalize(text)
    found = []
    for payment in rules.payments:
        if payment.pattern.search(plain):
            found.append(payment.id)
    return found[0] if len(set(found)) == 1 else ""


NAME_PREFIXES = ("o meu nome e", "o nome e", "meu nome e", "nome e", "nome:", "aqui e",
                 "pode colocar no nome de", "pode colocar no nome do", "pode colocar no nome da",
                 "pode por no nome de", "pode por no nome do", "pode por no nome da",
                 "coloca no nome de", "coloca no nome do", "coloca no nome da",
                 "no nome de", "no nome do", "no nome da", "me chamo",
                 "sou o", "sou a", "pode ser", "e o", "e a")
ADDRESS_PREFIXES = ("para entrega", "meu endereco e", "endereco e", "endereco:", "entrega em",
                    "entregar em", "moro na", "moro no", "moro em", "e na", "e no", "pode ser na",
                    "pode ser no", "pode entregar na", "pode entregar no",
                    "pode mandar na", "pode mandar no", "pode mandar em")
TRAILING_PAYMENT_RE = re.compile(
    r"(?:\s*(?:,|;|\s+-|\s+e)\s*|\s+(?:no|na|em|com|pagamento)\s+)"
    r"(?:(?:forma\s+de\s+)?pagamento\s*:?\s*(?:no|na|em|com)?\s*)?"
    r"(?:pix|dinheiro(?:\s*,?\s*(?:sem\s+troco|troco\s+(?:pa?ra\s*)?r?\$?\s*\d+(?:[,.]\d+)?))?|"
    r"cart[aã]o(?:\s+(?:de\s+)?(?:d[eé]bito|cr[eé]dito))?|d[eé]bito|cr[eé]dito)"
    r"(?:\s*,?\s*(?:sem\s+troco|troco\s+(?:pa?ra\s*)?r?\$?\s*\d+(?:[,.]\d+)?))?.*$",
    re.IGNORECASE,
)


def _collapse_repeated_lines(text: str) -> str:
    kept: list[str] = []
    seen_norm: set[str] = set()
    for line in (text or "").splitlines():
        clean = re.sub(r"\s+", " ", line.strip())
        if not clean:
            continue
        norm = normalize(clean)
        if norm and norm in seen_norm:
            continue
        if norm:
            seen_norm.add(norm)
        kept.append(clean)
    return "\n".join(kept).strip()


def _strip_prefix(value: str, prefixes: tuple[str, ...]) -> str:
    plain = normalize(value)
    for prefix in sorted(prefixes, key=len, reverse=True):
        if plain.startswith(prefix):
            rest = value[len(prefix):].strip(" .,:;-*")
            if rest:
                return rest
    return value.strip(" .,:;-*")


def _single_name(candidate: str) -> str:
    stripped = re.sub(r"\s+", " ", candidate.strip(" .,:;-*_~\"'!?"))
    if not stripped:
        return ""
    stripped = _strip_prefix(stripped, NAME_PREFIXES)
    stripped = TRAILING_PAYMENT_RE.sub("", stripped).strip(" .,:;-*_~\"'!?")
    plain = normalize(stripped)
    if not stripped or len(stripped) > 120 or not NAME.match(stripped):
        return ""
    if set(plain.split()) <= NON_NAME_WORDS:
        return ""
    if ADD_CUE.search(plain) or QUESTION_CUE.search(plain) or REMOVE_CUE.search(plain):
        return ""
    if ADDRESS_CUE.search(plain):
        return ""
    if any(word in plain.split() for word in PAYMENT_WORDS) or numbers(plain):
        return ""
    return stripped[:120]


def parse_name(text: str) -> str:
    collapsed = _collapse_repeated_lines(text)
    if not collapsed:
        return ""
    direct = _single_name(re.sub(r"\s+", " ", collapsed))
    if direct:
        return direct
    for line in collapsed.splitlines():
        found = _single_name(line)
        if found:
            return found
    clauses = [part for part in re.split(r"[,;]+", collapsed) if part.strip()]
    if len(clauses) > 1:
        found = _single_name(clauses[0])
        if found and not STREET_WORDS.search(normalize(found)):
            return found
    explicit = re.match(
        r"^(?:(?:o\s+)?meu\s+nome\s+[eé]|nome:|me\s+chamo|sou\s+[oa])\s+([^,\n;]+)",
        collapsed,
        re.IGNORECASE,
    )
    if explicit:
        return _single_name(explicit.group(1))
    return ""


STREET_WORDS = re.compile(
    r"\b(rua|avenida|av|travessa|alameda|rodovia|estrada|passagem|beco)\b")
ADDRESS_STOP = re.compile(r"\b(pix|dinheiro|cartao|debito|credito|troco|pagamento|pagar)\b")


def _address_clause(clause: str) -> str:
    """The clause stripped of its lead-in ("entrega em", "moro na") when it looks like a street."""
    stripped = _strip_prefix(clause.strip(" .,:;-"), ADDRESS_PREFIXES)
    plain = normalize(stripped)
    if len(stripped) < 3 or not ADDRESS_CUE.search(plain):
        return ""
    if STREET_WORDS.search(plain) or re.search(r"\d", stripped):
        return stripped
    return ""


def parse_address(text: str) -> str:
    """The address inside a free message: from the first street-like clause up to the
    payment/kind clauses, so "2 x-bacon, entrega, rua A 10, centro, pix" keeps only the street."""
    collapsed = _collapse_repeated_lines(text)
    if not collapsed:
        return ""
    clauses = [part.strip(" .,:;-") for part in re.split(r"[\n;,]+", collapsed)
               if part.strip(" .,:;-")]
    for index, clause in enumerate(clauses):
        first = _address_clause(clause)
        if not first:
            continue
        parts = [first]
        for follow in clauses[index + 1:]:
            plain = normalize(follow)
            if ADDRESS_STOP.search(plain) or parse_kind(follow) and len(plain.split()) <= 3:
                break
            parts.append(follow)
        address = TRAILING_PAYMENT_RE.sub("", ", ".join(parts)).strip(" .,:;-")
        if 5 <= len(address) <= 200:
            return address
    return ""


def parse(rules: RestaurantRules, text: str) -> Parsed:
    plain = normalize(text).replace("-", " ")
    result = Parsed()
    if not plain:
        return result

    replacement = re.search(r"\b(troca|trocar|substitui\w*)\b(.*?)\bpor\b(.*)", plain)
    if replacement:
        before = item_mentions(rules, replacement.group(2))
        after = item_mentions(rules, replacement.group(3))
        if before and after:
            result.items.append(ParsedItem(after[0][2].id,
                                           quantity(replacement.group(3)[:after[0][0]])))
            result.items.append(ParsedItem(before[0][2].id, remove=True))
        return result

    mentions = item_mentions(rules, plain)
    variant_parts: list[str] = []
    for index, (start, end, item) in enumerate(mentions):
        previous_end = mentions[index - 1][1] if index else 0
        before = plain[previous_end:start]
        next_start = mentions[index + 1][0] if index + 1 < len(mentions) else len(plain)
        segment = plain[end:next_start]
        remove = bool(REMOVE_TAIL.search(before[-28:]))
        variant = None if remove else DRINK_VARIANT.match(segment)
        if variant and item.category == "drinks":
            # "coca zero", "guaraná 2 litros": the catalog has only the listed size, so the
            # customer is told instead of silently receiving a different product.
            variant_parts.append(f"{plain[start:end]} {variant.group(1)}".strip())
            result.unknown_category = item.category
            continue
        qty = quantity(before)
        if not numbers(re.sub(r"r\$\s*\d+(?:[,.]\d+)?", " ", before)):
            trailing = TRAILING_QTY.match(segment)
            if trailing:
                qty = int(trailing.group(1) or trailing.group(2))
        segment_extras = [] if remove else _extra_matches(rules, item, segment)
        before_extras = []
        modify = False
        if not remove and MODIFY_CUE.search(before):
            for extra in rules.extras_for(item.category):
                for match in extra.pattern.finditer(before):
                    prefix = before[max(0, match.start() - 16):match.start()]
                    if REMOVE_CUE.search(prefix):
                        if extra.id not in result.remove_extras:
                            result.remove_extras.append(extra.id)
                    else:
                        before_extras.append(extra.id)
                    modify = True
        for extra in rules.extras_for(item.category):
            for match in extra.pattern.finditer(segment):
                if REMOVE_CUE.search(segment[max(0, match.start() - 16):match.start()]):
                    if extra.id not in result.remove_extras:
                        result.remove_extras.append(extra.id)
        result.items.append(ParsedItem(
            item.id, 0 if modify else qty,
            [] if remove else list(dict.fromkeys(segment_extras + before_extras)),
            "" if remove else _note(segment, rules, item), remove))

    if not mentions:
        for extra in rules.extras:
            for match in extra.pattern.finditer(plain):
                prefix = plain[max(0, match.start() - 24):match.start()]
                if REMOVE_CUE.search(prefix):
                    result.remove_extras.append(extra.id)
                elif ADD_CUE.search(prefix):
                    result.items.append(ParsedItem("", 0, [extra.id]))
                break

    if QUESTION_CUE.search(plain) and mentions:
        result.question_items = list(dict.fromkeys(item.id for _, _, item in mentions))

    for category, pattern in CATEGORY_NOUNS.items():
        for match in pattern.finditer(plain):
            if not any(start <= match.start() < end for start, end, _ in mentions):
                result.generic_categories.append(category)
                break

    result.fields = {
        "kind": parse_kind(text),
        "payment": parse_payment(rules, text),
        "name": parse_name(text),
        "address": parse_address(text),
    }
    change, exact = parse_change(text)
    if change is not None:
        result.fields["change_for_cents"] = change
    if exact:
        result.fields["change_exact"] = True
    clauses = [plain] + [part.strip() for part in re.split(r"\s*(?:,|;|\n)\s*", plain) if part.strip()]
    if any(re.search(pattern, part) for pattern in rules.context.get("done", []) for part in clauses):
        result.done = True
    if any(re.search(pattern, plain) for pattern in rules.context.get("cancel", [])):
        result.cancel = True
    result.unknown_parts, result.unknown_wants_extras = _extract_unknown_parts(
        rules, plain, mentions, result)
    if variant_parts:
        result.unknown_parts = list(dict.fromkeys(variant_parts + result.unknown_parts))
    return result


GENERIC_NOUNS = {"lanche", "lanches", "burger", "hamburguer", "hamburger", "item", "itens",
                 "bebida", "bebidas", "refrigerante", "refri", "suco", "sucos", "sobremesa",
                 "doce", "combo", "combos", "porcao", "porcoes", "sanduiche",
                 "coisa", "coisas", "pessoa", "pessoas", "unidade", "unidades", "nota"}


def _clean_unknown_fragment(fragment: str) -> str:
    cleaned = re.sub(
        r"\b(?:safad[oa]s?|gostos[oa]s?|gostosona|se e que me entende.*)\b",
        " ",
        fragment,
    )
    cleaned = re.sub(r"\br?\$?\s*\d+(?:[,.]\d+)?\b", " ", cleaned)
    cleaned = FORBIDDEN_NOTE.sub(" ", cleaned)
    cleaned = re.sub(r"[@%]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" .,:;-!?")


def _extract_unknown_parts(rules: RestaurantRules, plain: str,
                           mentions: list[tuple[int, int, Item]],
                           result: Parsed) -> tuple[list[str], bool]:
    """Capture unrecognized secondary food/condiment requests without inventing items."""
    if not mentions and result.fields.get("address"):
        return [], False
    slices: list[str] = []
    cursor = 0
    for start, end, _ in mentions:
        slices.append(plain[cursor:start])
        cursor = end
    slices.append(plain[cursor:])
    known_notes = {normalize(item.note) for item in result.items if item.note}
    known_extras = {alias for extra in rules.extras for alias in extra.aliases}
    parts: list[str] = []
    wants_extras = False
    for chunk in slices:
        for clause in re.split(r"\s*(?:,|;|\n|\+|\be\b)\s*", chunk):
            raw_clause = normalize(clause)
            if not raw_clause:
                continue
            if any(note and note in raw_clause for note in known_notes):
                continue
            if parse_kind(raw_clause) or parse_payment(rules, raw_clause):
                continue
            if any(re.search(p, raw_clause) for p in rules.context.get("done", [])):
                continue
            if any(re.search(p, raw_clause) for p in rules.context.get("cancel", [])):
                continue
            stripped = re.sub(
                r"^(?:quero|queria|me ve|me manda|manda|adiciona|acrescenta|coloca|poe|"
                r"mais|com|tambem|tem)\s+",
                "",
                raw_clause,
            ).strip()
            stripped = _clean_unknown_fragment(stripped)
            cond = CONDIMENT_FOOD.search(stripped)
            if cond:
                phrase = _clean_unknown_fragment(cond.group(0))
                if phrase and not any(phrase == normalize(a) for a in known_extras):
                    parts.append(phrase)
                    wants_extras = True
                continue
            dish = DISH_FOOD.search(stripped)
            if dish:
                phrase = _clean_unknown_fragment(dish.group(0))
                if phrase:
                    parts.append(phrase)
                continue
            if mentions:
                tail_match = re.match(
                    r"^(?:um|uma|dois|duas|tres|\d+)\s+"
                    r"([a-z]{3,}(?:\s+(?:de|da|do)\s+[a-z]{2,}){0,2})",
                    stripped,
                )
                if tail_match:
                    phrase = _clean_unknown_fragment(tail_match.group(1))
                    words = phrase.split()
                    if phrase and words[0] not in GENERIC_NOUNS \
                            and words[0] not in NOTE_STOP \
                            and not any(re.search(p, phrase) for p in rules.context.get("done", [])):
                        parts.append(phrase[:40])
    return list(dict.fromkeys(parts)), wants_extras


__all__ = ["Parsed", "ParsedItem", "item_mentions", "numbers", "parse", "parse_address",
           "parse_change", "parse_kind", "parse_name", "parse_payment", "quantity"]
