"""Client folder and brief (ficha) for a lead that accepted a quote.

`.local/commercial/whatsapp/sales/clientes/<empresa>-<lead>/` holds:
- `ficha.md` / `ficha.json`: exactly what the client asked for, organized, plus open items;
- `conversa.md`: the whole conversation, with audio transcripts and media links;
- `midia/`: the images and voice messages the client sent.

The brief is extracted by the same model, from the client's own words only: a field the
client did not mention stays empty and goes to `pendencias`. Without a model the brief keeps
the raw conversation and the media list.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from string import Template

from . import guard
from .context import effective
from .notify import format_phone
from .rules import SalesRules, normalize

PROMPT_PATH = Path(__file__).with_name("dossier.md")
PROMPT_SCHEMA = {
    "empresa": {"nome": None, "segmento": None, "cidade": None,
                "sobre_e_diferenciais": None, "publico_alvo": None},
    "pedido": {"tipo": None, "objetivo": None, "servicos_ou_produtos": [],
               "mostrar_precos": None, "paginas": [], "funcionalidades": []},
    "identidade_visual": {"cores_principais": None, "estilo_visual": None,
                          "preferencia_fundo": None, "possui_logo": None,
                          "fotos_e_videos": None, "referencias": []},
    "dominio": {"ja_possui": None, "nome_desejado": None, "opcao_compra": None},
    "contato_no_site": {"whatsapp": None, "telefone": None, "email": None, "endereco": None,
                        "horario": None, "redes_sociais": []},
    "materiais_citados": [], "observacoes": [], "resumo": "", "faltando": [],
    "pedir_dominio": False, "cliente_terminou": False, "proxima_pergunta": "",
}
EMPTY_BRIEF = {
    **PROMPT_SCHEMA,
    "pedido": {**PROMPT_SCHEMA["pedido"], "nome_do_site_ou_dominio": None,
               "estilo_e_cores": None, "referencias": []},
}


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(char for char in plain if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:40] or "cliente"


def client_dir(root: Path, lead: dict) -> Path:
    return root / "clientes" / f"{slug(lead.get('name', ''))}-{lead['id']}"


def save_media(folder: Path, data: bytes, extension: str, kind: str, now: datetime) -> Path:
    media = folder / "midia"
    media.mkdir(parents=True, exist_ok=True)
    for directory in (folder.parent.parent, folder.parent, folder, media):
        if directory.exists():
            directory.chmod(0o700)
    base = f"{now.strftime('%Y%m%d-%H%M%S')}-{kind}"
    path = media / f"{base}{extension}"
    counter = 1
    while path.exists():
        counter += 1
        path = media / f"{base}-{counter}{extension}"
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def media_files(history: list[dict]) -> list[dict]:
    return [{"tipo": entry.get("media"), "arquivo": name, "legenda": entry.get("caption", ""),
             "em": entry.get("at", "")}
            for entry in history if entry.get("dir") == "in" and entry.get("file")
            for name in entry.get("files") or [entry["file"]]]


def transcript(history: list[dict], agent_name: str) -> list[str]:
    lines = []
    for entry in effective(history):
        if entry.get("dir") not in ("in", "out") or entry.get("state", "sent") != "sent":
            continue
        speaker = agent_name if entry["dir"] == "out" else "Cliente"
        when = str(entry.get("at", ""))[:16].replace("T", " ")
        text = entry.get("text", "")
        if entry.get("media") == "audio":
            speaker += " (áudio transcrito)"
        if entry.get("file"):
            names = ", ".join(entry.get("files") or [entry["file"]])
            text = f"{text} [{entry['media']}: {names}]"
        lines.append(f"[{when}] {speaker}: {text}")
    return lines


def _merge(base: dict, data: dict) -> dict:
    merged = json.loads(json.dumps(base))
    for key, value in (data or {}).items():
        if key not in merged:
            continue
        if isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge(merged[key], value)
        elif isinstance(merged[key], list):
            merged[key] = [str(item) for item in value] if isinstance(value, list) else merged[key]
        elif isinstance(merged[key], bool):
            merged[key] = value is True
        else:
            merged[key] = None if value in (None, "") else str(value)
    return merged


def extract(rules: SalesRules, lead: dict, history: list[dict], llm, now: datetime,
            usage=None) -> tuple[dict, str]:
    """The brief from the conversation; ("", error) never raises."""
    if llm is None:
        return dict(EMPTY_BRIEF), "no model"
    template = Template(PROMPT_PATH.read_text(encoding="utf-8"))
    system = template.safe_substitute(
        company=rules.company, required="\n".join(f"- {item}" for item in rules.brief["required"]),
        optional="\n".join(f"- {item}" for item in rules.brief["optional"]),
        schema=json.dumps(PROMPT_SCHEMA, ensure_ascii=False, indent=1))
    agent_name = rules.raw.get("agent_name", "Alexandre")
    user = "\n".join([f"EMPRESA NO GOOGLE MAPS: {lead.get('name', '')} — {lead.get('category', '')}"
                      f" — {lead.get('city', '')}", "", "CONVERSA:",
                      *transcript(history, agent_name)])
    try:
        reply = llm.complete([{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                             session_id=f"zaflas-brief-{lead['id']}")
    except Exception as error:  # the brief must never stop the conversation
        return dict(EMPTY_BRIEF), str(error)[:300]
    if usage is not None:
        usage({"at": now.isoformat(timespec="seconds"), "lead": lead["id"], "kind": "brief",
               "model": reply.model, "input_tokens": reply.input_tokens,
               "output_tokens": reply.output_tokens, "cost_usd": reply.cost_usd})
    try:
        text = reply.content.strip()
        data = json.loads(text[text.find("{"):text.rfind("}") + 1])
    except ValueError:
        return dict(EMPTY_BRIEF), "invalid brief output"
    brief = approximate_brief(_merge(EMPTY_BRIEF, data))
    question = (brief.get("proxima_pergunta") or "").strip()
    if question and guard.violations(rules, guard.split_links([question])):
        brief["proxima_pergunta"] = ""
    return brief, ""


TIME = re.compile(r"\b(\d{1,2})\s*(h|:)\s*(\d{2})\b", re.IGNORECASE)


def approximate_times(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Turn impossible clock times into the nearest logical one (9h74 -> 10h14, 25h -> 1h)."""
    changes = []

    def fix(match: re.Match) -> str:
        hours, separator, minutes = int(match.group(1)), match.group(2), int(match.group(3))
        if hours < 24 and minutes < 60:
            return match.group(0)
        carried, minutes = divmod(minutes, 60)
        hours = (hours + carried) % 24
        fixed = f"{hours}h{minutes:02d}" if separator.lower() == "h" else f"{hours}:{minutes:02d}"
        changes.append((match.group(0), fixed))
        return fixed

    return TIME.sub(fix, text or ""), changes


def approximate_brief(brief: dict) -> dict:
    """Apply `approximate_times` to the hours and note the client's original words."""
    contact = brief.get("contato_no_site") or {}
    original = contact.get("horario")
    if original:
        fixed, changes = approximate_times(original)
        if changes:
            contact["horario"] = fixed
            said = ", ".join(before for before, _ in changes)
            brief.setdefault("observacoes", []).append(
                f"Horário aproximado: o cliente disse \"{said}\", valor impossível; registrado "
                f"como \"{fixed}\". Confirme com o cliente.")
    return brief


def client_said_done(rules: SalesRules, text: str) -> bool:
    plain = normalize(text)
    return any(re.search(pattern, plain) for pattern in rules.brief["done_patterns"])


def _value(value) -> str:
    if value in (None, "", []):
        return "—"
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value)


def render(lead: dict, brief: dict, files: list[dict], status: str, now: datetime) -> str:
    company = brief.get("empresa") or {}
    order = brief.get("pedido") or {}
    visual = brief.get("identidade_visual") or {}
    domain = brief.get("dominio") or {}
    contact = brief.get("contato_no_site") or {}
    domain_name = domain.get("nome_desejado") or order.get("nome_do_site_ou_dominio")
    colors = visual.get("cores_principais") or order.get("estilo_e_cores")
    refs = visual.get("referencias") or order.get("referencias")
    lines = [
        f"# Ficha do cliente — {company.get('nome') or lead.get('name', '')}",
        "",
        f"- Status: **{status}**",
        f"- Gerada em: {now.strftime('%d/%m/%Y %H:%M')}",
        f"- WhatsApp do contato: {format_phone(lead.get('phone', ''))}",
        f"- Origem: Google Maps ({lead.get('maps_url') or 'sem link'}) · lead {lead['id']}",
        "",
        "## Resumo do que o cliente quer",
        "",
        brief.get("resumo") or "—",
        "",
        "## Empresa",
        "",
        f"- Nome: {_value(company.get('nome') or lead.get('name'))}",
        f"- Segmento: {_value(company.get('segmento') or lead.get('category'))}",
        f"- Cidade / região: {_value(company.get('cidade') or lead.get('city'))}",
        f"- Sobre / diferenciais: {_value(company.get('sobre_e_diferenciais'))}",
        f"- Público-alvo: {_value(company.get('publico_alvo'))}",
        "",
        "## O site / projeto",
        "",
        f"- Tipo: {_value(order.get('tipo'))}",
        f"- Objetivo: {_value(order.get('objetivo'))}",
        f"- Serviços ou produtos: {_value(order.get('servicos_ou_produtos'))}",
        f"- Mostrar preços no site: {_value(order.get('mostrar_precos'))}",
        f"- Páginas / seções: {_value(order.get('paginas'))}",
        f"- Funcionalidades: {_value(order.get('funcionalidades'))}",
        "",
        "## Identidade visual e marca",
        "",
        f"- Cores principais da marca: {_value(colors)}",
        f"- Estilo visual desejado: {_value(visual.get('estilo_visual'))}",
        f"- Preferência de fundo (claro/escuro): {_value(visual.get('preferencia_fundo'))}",
        f"- Possui logotipo: {_value(visual.get('possui_logo'))}",
        f"- Fotos e vídeos: {_value(visual.get('fotos_e_videos'))}",
        f"- Referências / inspirações: {_value(refs)}",
        "",
        "## Domínio (endereço na internet)",
        "",
        f"- Já possui domínio: {_value(domain.get('ja_possui'))}",
        f"- Nome desejado (registro.br): {_value(domain_name)}",
        f"- Opção de compra / configuração: {_value(domain.get('opcao_compra'))}",
        "",
        "## Contato e redes que vão no site",
        "",
        f"- WhatsApp: {_value(contact.get('whatsapp'))}",
        f"- Telefone: {_value(contact.get('telefone'))}",
        f"- E-mail: {_value(contact.get('email'))}",
        f"- Endereço: {_value(contact.get('endereco'))}",
        f"- Horário: {_value(contact.get('horario'))}",
        f"- Redes sociais: {_value(contact.get('redes_sociais'))}",
        "",
        "## Materiais recebidos",
        "",
    ]
    lines += [f"- {item['tipo']}: [{item['arquivo']}]({item['arquivo']})"
              + (f" — {item['legenda']}" if item.get("legenda") else "") for item in files]
    if not files:
        lines.append("- Nenhum arquivo recebido ainda.")
    if brief.get("materiais_citados"):
        lines.append(f"- Citados na conversa: {_value(brief['materiais_citados'])}")
    lines += ["", "## Pendências (perguntar ao cliente)", ""]
    lines += [f"- {item}" for item in brief.get("faltando") or []] or ["- Nenhuma."]
    if brief.get("observacoes"):
        lines += ["", "## Observações", ""] + [f"- {item}" for item in brief["observacoes"]]
    lines += ["", "Conversa completa: [conversa.md](conversa.md)", ""]
    return "\n".join(lines)


def write(root: Path, lead: dict, history: list[dict], brief: dict, status: str,
          now: datetime, agent_name: str = "Alexandre") -> Path:
    """Write ficha.md, ficha.json and conversa.md; return the ficha.md path."""
    folder = client_dir(root, lead)
    folder.mkdir(parents=True, exist_ok=True)
    for directory in (folder.parent, folder):
        directory.chmod(0o700)
    files = media_files(history)
    record = {"gerada_em": now.isoformat(timespec="seconds"), "status": status,
              "lead": {key: lead.get(key) for key in ("id", "name", "city", "category",
                                                      "maps_url")},
              "whatsapp": format_phone(lead.get("phone", "")), "ficha": brief,
              "arquivos": files}
    outputs = {
        "ficha.json": json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        "ficha.md": render(lead, brief, files, status, now),
        "conversa.md": "# Conversa\n\n" + "\n".join(transcript(history, agent_name)) + "\n",
    }
    for name, content in outputs.items():
        path = folder / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
    return folder / "ficha.md"
