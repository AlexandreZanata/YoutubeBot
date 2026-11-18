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
SYSTEM_PROMPT_PATH = Path(__file__).with_name("dossier_system.md")
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
    "kind": "site",
}
# Apps and systems: the requirements the bot interviews for (owner, 2026-11-18).
SYSTEM_SCHEMA = {
    "empresa": {"nome": None, "segmento": None, "cidade": None, "sobre_e_diferenciais": None},
    "projeto": {"tipo": None, "objetivo": None, "problema_atual": None, "como_faz_hoje": None,
                "usuarios": [], "quantidade_de_usuarios": None, "funcionalidades": [],
                "plataformas": [], "integracoes": [], "dados_e_relatorios": [],
                "referencias": [], "prazo_desejado": None, "identidade_visual": None},
    "materiais_citados": [], "duvidas_do_cliente": [], "observacoes": [], "resumo": "",
    "confirmacao": "", "faltando": [], "cliente_terminou": False, "proxima_pergunta": "",
}
EMPTY_SYSTEM = {**SYSTEM_SCHEMA, "kind": "sistema"}


def kind_of(lead: dict) -> str:
    """"system" once the lead is in the app/system requirements interview, else "site"."""
    return "system" if lead.get("brief_kind") == "system" else "site"


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
            usage=None, kind: str | None = None) -> tuple[dict, str]:
    """The brief from the conversation; ("", error) never raises.

    `kind` "system" uses the app/system requirements schema; the default follows the lead.
    """
    kind = kind or kind_of(lead)
    empty = EMPTY_SYSTEM if kind == "system" else EMPTY_BRIEF
    if llm is None:
        return json.loads(json.dumps(empty)), "no model"
    agent_name = rules.raw.get("agent_name", "Alexandre")
    settings = rules.brief_system if kind == "system" else rules.brief
    path = SYSTEM_PROMPT_PATH if kind == "system" else PROMPT_PATH
    schema = SYSTEM_SCHEMA if kind == "system" else PROMPT_SCHEMA
    system = Template(path.read_text(encoding="utf-8")).safe_substitute(
        company=rules.company, agent_name=agent_name,
        required="\n".join(f"- {item}" for item in settings["required"]),
        optional="\n".join(f"- {item}" for item in settings["optional"]),
        schema=json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
    user = "\n".join([f"EMPRESA NO GOOGLE MAPS: {lead.get('name', '')} — {lead.get('category', '')}"
                      f" — {lead.get('city', '')}", "", "CONVERSA:",
                      *transcript(history, agent_name)])
    try:
        reply = llm.complete([{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                             session_id=f"zaflas-brief-{lead['id']}", long=True)
    except Exception as error:  # the brief must never stop the conversation
        return json.loads(json.dumps(empty)), str(error)[:300]
    if usage is not None:
        usage({"at": now.isoformat(timespec="seconds"), "lead": lead["id"], "kind": "brief",
               "model": reply.model, "input_tokens": reply.input_tokens,
               "output_tokens": reply.output_tokens, "cost_usd": reply.cost_usd})
    try:
        text = reply.content.strip()
        data = json.loads(text[text.find("{"):text.rfind("}") + 1])
    except ValueError:
        return json.loads(json.dumps(empty)), "invalid brief output"
    brief = _merge(empty, data)
    if kind != "system":
        brief = approximate_brief(brief)
    for key in ("proxima_pergunta", "confirmacao"):
        text = (brief.get(key) or "").strip()
        if text and guard.violations(rules, guard.split_links([text])):
            brief[key] = ""
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


def sections(lead: dict, brief: dict) -> list[tuple[str, list[tuple[str, object]]]]:
    """The ficha as (title, [(label, value)]) for ficha.md and the desktop Central."""
    company = brief.get("empresa") or {}
    head = [("Empresa", [
        ("Nome", company.get("nome") or lead.get("name")),
        ("Segmento", company.get("segmento") or lead.get("category")),
        ("Cidade / região", company.get("cidade") or lead.get("city")),
        ("Sobre / diferenciais", company.get("sobre_e_diferenciais")),
    ])]
    if brief.get("kind") == "sistema":
        project = brief.get("projeto") or {}
        return head + [
            ("O problema e o objetivo", [
                ("Tipo", project.get("tipo")),
                ("Objetivo", project.get("objetivo")),
                ("Problema hoje", project.get("problema_atual")),
                ("Como faz hoje", project.get("como_faz_hoje")),
            ]),
            ("Quem usa", [
                ("Usuários", project.get("usuarios")),
                ("Quantidade", project.get("quantidade_de_usuarios")),
            ]),
            ("Funções pedidas", [("Funções", project.get("funcionalidades")),
                                 ("Dados e relatórios", project.get("dados_e_relatorios"))]),
            ("Onde vai rodar e integrações", [
                ("Plataformas", project.get("plataformas")),
                ("Integrações", project.get("integracoes")),
            ]),
            ("Referências, prazo e marca", [
                ("Referências", project.get("referencias")),
                ("Prazo desejado", project.get("prazo_desejado")),
                ("Logo e cores", project.get("identidade_visual")),
            ]),
        ]
    order = brief.get("pedido") or {}
    visual = brief.get("identidade_visual") or {}
    domain = brief.get("dominio") or {}
    contact = brief.get("contato_no_site") or {}
    head[0][1].append(("Público-alvo", company.get("publico_alvo")))
    return head + [
        ("O site / projeto", [
            ("Tipo", order.get("tipo")),
            ("Objetivo", order.get("objetivo")),
            ("Serviços ou produtos", order.get("servicos_ou_produtos")),
            ("Mostrar preços no site", order.get("mostrar_precos")),
            ("Páginas / seções", order.get("paginas")),
            ("Funcionalidades", order.get("funcionalidades")),
        ]),
        ("Identidade visual e marca", [
            ("Cores principais da marca", visual.get("cores_principais")
             or order.get("estilo_e_cores")),
            ("Estilo visual desejado", visual.get("estilo_visual")),
            ("Preferência de fundo (claro/escuro)", visual.get("preferencia_fundo")),
            ("Possui logotipo", visual.get("possui_logo")),
            ("Fotos e vídeos", visual.get("fotos_e_videos")),
            ("Referências / inspirações", visual.get("referencias") or order.get("referencias")),
        ]),
        ("Domínio (endereço na internet)", [
            ("Já possui domínio", domain.get("ja_possui")),
            ("Nome desejado (registro.br)", domain.get("nome_desejado")
             or order.get("nome_do_site_ou_dominio")),
            ("Opção de compra / configuração", domain.get("opcao_compra")),
        ]),
        ("Contato e redes que vão no site", [
            ("WhatsApp", contact.get("whatsapp")),
            ("Telefone", contact.get("telefone")),
            ("E-mail", contact.get("email")),
            ("Endereço", contact.get("endereco")),
            ("Horário", contact.get("horario")),
            ("Redes sociais", contact.get("redes_sociais")),
        ]),
    ]


def render(lead: dict, brief: dict, files: list[dict], status: str, now: datetime) -> str:
    company = brief.get("empresa") or {}
    system = brief.get("kind") == "sistema"
    lines = [
        f"# Ficha do cliente — {company.get('nome') or lead.get('name', '')}",
        "",
        f"- Tipo de projeto: **{'aplicativo ou sistema' if system else 'site'}**",
        f"- Status: **{status}**",
        f"- Gerada em: {now.strftime('%d/%m/%Y %H:%M')}",
        f"- WhatsApp do contato: {format_phone(lead.get('phone', ''))}",
        f"- Origem: Google Maps ({lead.get('maps_url') or 'sem link'}) · lead {lead['id']}",
        "",
        "## Resumo do que o cliente quer",
        "",
        brief.get("resumo") or "—",
        "",
    ]
    for title, items in sections(lead, brief):
        lines += [f"## {title}", ""] + [f"- {label}: {_value(value)}" for label, value in items]
        lines.append("")
    lines += ["## Materiais recebidos", ""]
    lines += [f"- {item['tipo']}: [{item['arquivo']}]({item['arquivo']})"
              + (f" — {item['legenda']}" if item.get("legenda") else "") for item in files]
    if not files:
        lines.append("- Nenhum arquivo recebido ainda.")
    if brief.get("materiais_citados"):
        lines.append(f"- Citados na conversa: {_value(brief['materiais_citados'])}")
    if brief.get("duvidas_do_cliente"):
        lines += ["", "## Dúvidas do cliente (responder no orçamento)", ""]
        lines += [f"- {item}" for item in brief["duvidas_do_cliente"]]
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
              "tipo": brief.get("kind") or "site",
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
