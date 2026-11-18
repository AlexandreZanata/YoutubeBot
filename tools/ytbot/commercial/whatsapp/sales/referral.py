"""Staff answers and referrals: who is talking, and the decision maker's number they pass on.

The number always comes from the message text (never invented) and must be a valid Brazilian
number different from the chat's own. Names come from the model when it is available and from
simple Portuguese patterns otherwise ("aqui é a Paula", "o número do Carlos é ...").
"""

from __future__ import annotations

import json
import re

from .store import canonical_phone, phone_key

PHONE = re.compile(r"(?<!\d)(?:\+?55[\s.-]*)?\(?\d{2}\)?[\s.-]*9?[\s.-]*\d{4}[\s.-]*\d{4}(?!\d)")
ROLES = {"dono", "dona", "responsavel", "responsável", "gerente", "chefe", "patrao", "patrão",
         "patroa", "proprietario", "proprietário", "proprietaria", "proprietária", "atendente",
         "funcionario", "funcionário", "funcionaria", "funcionária", "secretaria", "secretária",
         "recepcionista", "colaborador", "colaboradora", "ele", "ela", "voce", "você", "senhor",
         "senhora", "aqui", "numero", "número", "contato", "whats", "whatsapp", "zap"}
SELF = re.compile(r"(?:meu nome (?:e|é)|aqui (?:e|é|quem fala (?:e|é))(?: (?:a|o))?|eu sou (?:a|o)|"
                  r"sou (?:a|o)|quem fala (?:e|é) (?:a|o)|fala (?:a|o))\s+([A-Za-zÀ-ÿ]{2,20})",
                  re.IGNORECASE)
OTHER = re.compile(r"(?:numero|número|contato|whats(?:app)?|zap|telefone|celular)\s+(?:d[oa]|de)\s+"
                   r"(?:(?:dono|dona|gerente|responsável|responsavel|chefe|patr[aã]o|patroa)\s+)?"
                   r"([A-Za-zÀ-ÿ]{2,20})", re.IGNORECASE)
PROMPT = """Leia a mensagem de WhatsApp de um funcionário de uma empresa e devolva só JSON:
{"funcionario": "<primeiro nome de quem escreve, se ele disser>", "responsavel": "<primeiro nome de quem decide, se citado>"}
Use null quando o nome não aparecer. Nunca invente nomes."""


def phones(text: str, own: str = "") -> list[str]:
    """Valid Brazilian numbers in the text, in order, without the chat's own number."""
    found = []
    own_key = phone_key(own) if own else None
    for match in PHONE.finditer(text or ""):
        phone = canonical_phone(match.group(0))
        if phone and phone_key(phone) != own_key and phone not in found:
            found.append(phone)
    return found


def _name(match: re.Match | None) -> str:
    if not match:
        return ""
    word = match.group(1).strip()
    return "" if word.casefold() in ROLES else word[:1].upper() + word[1:].lower()


def names(text: str, llm=None, session_id: str = "") -> dict:
    """{"staff": first name of who writes, "decider": first name of the decision maker}."""
    result = {"staff": _name(SELF.search(text or "")), "decider": _name(OTHER.search(text or ""))}
    if llm is None:
        return result
    try:
        reply = llm.complete([{"role": "system", "content": PROMPT},
                              {"role": "user", "content": text}], session_id=session_id,
                             quick=True)
        data = json.loads(reply.content[reply.content.find("{"):reply.content.rfind("}") + 1])
    except Exception:
        return result
    for key, field in (("staff", "funcionario"), ("decider", "responsavel")):
        value = data.get(field)
        if isinstance(value, str) and value.strip() and value.strip().casefold() not in ROLES:
            # The model may only confirm a name that is really in the message.
            if value.strip().casefold() in (text or "").casefold():
                result[key] = value.strip().split()[0].capitalize()
    return result
