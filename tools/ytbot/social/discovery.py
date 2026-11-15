"""Search recent X posts and curate contextual promotion opportunities."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

from ..accounts_store import write_private
from .store import SocialStore

PRODUCTS = {
    "abastevo": {
        "label": "Abastevo",
        "queries": (
            "etanol ou gasolina",
            "consumo gasolina",
            "preço gasolina posto",
            "custo por km combustível",
            "calculadora combustível",
        ),
        "terms": ("etanol", "gasolina", "combustível", "posto", "consumo", "preço", "km"),
        "exclude": ("lula", "bolsonaro", "governo", "petrobras", "eleição", "guerra", "irã",
                    "morte", "matar", "porra", "caralho", "merda", "sorteio", "follow"),
        "link": "https://abastevo.com.br/guias/como-e-formado-o-preco-da-gasolina/",
        "campaign": "abastevo_preco_202611",
    },
    "sorrifit": {
        "label": "SorriFit",
        "queries": (
            "academia carga treino",
            "progressão de carga",
            "descanso treino academia",
            "calistenia progressão",
            "treino academia dúvida",
        ),
        "terms": ("treino", "academia", "carga", "série", "descanso", "calistenia", "repetição"),
        "exclude": ("lula", "bolsonaro", "governo", "eleição", "guerra", "morte", "matar",
                    "porra", "caralho", "merda", "sorteio", "follow", "emagrecer 20"),
        "link": "https://sorrifit.com/?idioma=pt",
        "campaign": "sorrifit_treino_202611",
    },
    "zaflas": {
        "label": "Zaflas",
        "queries": (
            "produtor rural safra",
            "gestão agrícola",
            "agricultura de precisão",
            "NDVI lavoura",
            "talhão lavoura",
        ),
        "terms": ("safra", "talhão", "lavoura", "produtor", "agrícola", "ndvi", "fazenda"),
        "exclude": ("lula", "bolsonaro", "governo", "eleição", "guerra", "morte", "matar",
                    "porra", "caralho", "merda", "sorteio", "follow"),
        "link": "https://zaflas.com.br/funcionalidades/producao/",
        "campaign": "zaflas_operacao_202611",
    },
    "dev": {
        "label": "GitHub",
        "queries": (
            "validar CNPJ",
            "validação CPF TypeScript",
            "open source brasileiro",
            "Rust jogo open source",
            "yt-dlp app",
        ),
        "terms": ("cnpj", "cpf", "typescript", "open source", "rust", "yt-dlp", "validação"),
        "exclude": ("lula", "bolsonaro", "governo", "eleição", "guerra", "morte", "matar",
                    "porra", "caralho", "merda", "sorteio", "follow"),
        "link": "https://github.com/open-data-brazil/br-validators",
        "campaign": "dev_prova_202611",
    },
}

PORTUGUESE = re.compile(r"\b(que|para|com|não|mais|isso|aqui|preço|treino|safra|carro)\b", re.I)
STATUS = re.compile(r"/status/(\d+)")


def log(message: str) -> None:
    print(f"[discovery] {message}", flush=True)


def _number(label: str) -> int:
    match = re.search(r"\d+", label.replace(".", ""))
    return int(match.group()) if match else 0


def _rows(page) -> list[dict]:
    return page.evaluate("""() => Array.from(document.querySelectorAll('article')).map((article) => {
        const text = article.querySelector('[data-testid="tweetText"]');
        const time = article.querySelector('time');
        const link = time ? time.closest('a') : null;
        const user = article.querySelector('[data-testid="User-Name"]');
        const like = article.querySelector('[data-testid="like"]');
        return {
            text: text ? text.innerText : '',
            published_at: time ? time.getAttribute('datetime') : '',
            href: link ? link.getAttribute('href') : '',
            author_text: user ? user.innerText : '',
            like_label: like ? (like.getAttribute('aria-label') || '') : '',
            body: article.innerText || '',
        };
    })""")


def _parse(row: dict) -> dict | None:
    if not row.get("text") or not row.get("href") or not STATUS.search(row["href"]):
        return None
    handle = re.search(r"@([A-Za-z0-9_]{1,15})", row.get("author_text", ""))
    return {
        "text": row["text"].strip(),
        "url": "https://x.com" + row["href"],
        "status_id": STATUS.search(row["href"]).group(1),
        "author": handle.group(1) if handle else "",
        "published_at": row.get("published_at", ""),
        "likes": _number(row.get("like_label", "")),
        "is_reply": "Em resposta a" in row.get("body", "") or "Replying to" in row.get("body", ""),
    }


def search(page, query: str, *, days: int = 7, own_handle: str = "") -> list[dict]:
    page.goto(f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    page.mouse.wheel(0, 1800)
    page.wait_for_timeout(3000)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    found = []
    for row in _rows(page):
        item = _parse(row)
        if not item:
            continue
        try:
            published = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if published < cutoff or published > datetime.now(timezone.utc) + timedelta(minutes=10):
            continue
        if own_handle and item["author"].lower() == own_handle.lower():
            continue
        if not PORTUGUESE.search(item["text"]):
            continue
        item["published_at"] = published.isoformat()
        item["query"] = query
        found.append(item)
    return found


def score(item: dict, spec: dict) -> int | None:
    text = item["text"].lower()
    if any(term in text for term in spec["exclude"]):
        return None
    matches = sum(1 for term in spec["terms"] if term in text)
    if not matches:
        return None
    value = matches * 2
    if "?" in item["text"]:
        value += 3
    if not item["is_reply"]:
        value += 2
    if item["likes"] >= 5:
        value += 1
    if 80 <= len(item["text"]) <= 280:
        value += 1
    age = datetime.now(timezone.utc) - datetime.fromisoformat(item["published_at"])
    if age <= timedelta(days=2):
        value += 1
    return value


def curate(page, product: str, *, days: int = 7, limit: int = 10,
           own_handle: str = "") -> list[dict]:
    spec = PRODUCTS[product]
    candidates: dict[str, dict] = {}
    for query in spec["queries"]:
        for item in search(page, query, days=days, own_handle=own_handle):
            value = score(item, spec)
            if value is None:
                continue
            current = candidates.get(item["status_id"])
            if current is None or value > current["score"]:
                candidates[item["status_id"]] = {**item, "product": product,
                                                  "score": value, "query": query}
    return sorted(candidates.values(), key=lambda row: (-row["score"], row["published_at"]))[:limit]


def save_candidates(store: SocialStore, network: str, product: str, rows: list[dict]) -> Path:
    path = store.network(network) / "discovery.json"
    write_private(path, {"schema": 1, "product": product,
                         "created_at": datetime.now().isoformat(timespec="seconds"),
                         "items": rows})
    return path
