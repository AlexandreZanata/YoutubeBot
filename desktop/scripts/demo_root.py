#!/usr/bin/env python3
"""Build a synthetic project root for screenshots and manual review of the desktop manager.

Every title, contact, product and link is invented; nothing is read from `.local/`. Slots are
placed around the current day in America/Cuiaba so the month always has published, scheduled
and empty channels.

    python3 desktop/scripts/demo_root.py /tmp/ytbot-demo
    YTBOT_ROOT=/tmp/ytbot-demo desktop/target/debug/manager-app
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

NOW = datetime.now(ZoneInfo("America/Cuiaba")).replace(tzinfo=None, second=0, microsecond=0)

CHANNEL_IDS = {
    "fallem-prince": "UCc288lF54UDCCGhTKIkr7BQ",
    "whispers-from-heaven": "UCEE9qAtucy5OZcjvcyytu4w",
    "zaflas": "UCi2aftoK7vlS3A6OozMHXKg",
    "infinite-random-worlds": "UCY3Zp50I6Y6semQQccJxRPg",
    "vocal-pages": "UCm13oIPS1W43j9BYo0kewcQ",
    "zanata": "UCx0AE-elCyDhfY0d1hQIwdw",
    "reflection": "UCISw6UDaFINPRuuMr0s7tpA",
}

TITLES = {
    "fallem-prince": [
        "Why Silence Feels Louder at Night", "The Quiet Cost of Always Being Ready",
        "Can a Habit Outlive Its Reason?", "What We Owe the People We Forget",
        "The Map You Keep Redrawing", "When Patience Becomes Avoidance",
        "The Letter Nobody Sends", "How Small Rooms Shape Big Choices",
    ],
    "whispers-from-heaven": [
        "Ruth in the Barley Field: Loyalty Without Guarantees",
        "Elijah Under the Broom Tree: Rest Before the Next Step",
        "Hannah at Shiloh: Praying Without Words",
    ],
    "zaflas": [
        "Rotação de Culturas: Quando a Troca Paga a Conta", "Irrigação por Gotejamento no Café",
        "Como Planejar a Silagem para a Seca", "Manejo de Pastagem Rotacionada na Prática",
        "Análise Foliar: O Que Ela Revela Antes da Colheita",
    ],
    "infinite-random-worlds": [
        "A Lighthouse Keeper on a Planet Without Oceans",
        "The Archive City Where Every Door Remembers",
    ],
    "vocal-pages": ["The Kitchen Table Conversation We Keep Postponing"],
    "zanata": [],
    "reflection": ["Jonah at Nineveh: When Mercy Feels Unfair", "Martha in the Kitchen: Busy Hands, Quiet Heart"],
}

SHORTS = [
    "Quanto custa um hectare de soja?", "Pasto degradado: 3 sinais", "Bebedouro limpo rende mais leite",
    "Hora certa de colher o milho", "Calcário antes da chuva?",
]


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:60]


def run(runs: Path, title: str, slot: datetime, index: int, scheduled: bool = True) -> Path:
    directory = runs / slug(title)
    video_id = f"demo{index:07d}"
    write(directory / "upload.json", {
        "videoId": video_id, "url": f"https://youtu.be/{video_id}",
        "slot": slot.strftime("%Y-%m-%d %H:%M"), "visibility": "scheduled",
        "endScreen": True, "scheduled": scheduled,
    })
    write(directory / "metadata.json", {"title": title, "description": "Demo.", "tags": "demo"})
    return directory


def thumbnail(path: Path, index: int) -> None:
    image = Image.new("RGB", (540, 960), (24 + index * 18, 64 + index * 10, 40))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 600, 500, 900), fill=(236, 214, 120))
    draw.ellipse((150, 160, 390, 400), fill=(250, 250, 240))
    image.save(path)


def channels(root: Path) -> None:
    base = root / ".local" / "ytbot"
    counter = 0
    for name, titles in TITLES.items():
        data = base if name == "fallem-prince" else base / "channels" / name
        hours = 12 if name != "fallem-prince" else 0
        for position, title in enumerate(titles):
            counter += 1
            offset = position - len(titles) // 2
            slot = (NOW + timedelta(days=offset)).replace(hour=hours, minute=0)
            run(data / "runs", title, slot, counter)
        if titles:
            (data / "runs" / "in-production-topic").mkdir(parents=True, exist_ok=True)
        if name == "zaflas":
            for position, title in enumerate(SHORTS):
                counter += 1
                slot = (NOW + timedelta(days=position - 2)).replace(hour=9 if position % 2 else 18, minute=0)
                directory = run(data / "shorts", title, slot, counter)
                if position != 3:
                    thumbnail(directory / "thumbnail.png", position)
        history = [
            {"state": "started", "topic": titles[0] if titles else "", "at": (NOW - timedelta(days=1)).isoformat()},
            {"state": "posted", "topic": titles[0] if titles else "", "at": (NOW - timedelta(days=1, minutes=-2)).isoformat()},
        ]
        if name == "vocal-pages":
            history.append({"state": "unconfirmed", "topic": titles[0], "at": (NOW - timedelta(hours=3)).isoformat()})
        if name != "zanata":
            write(data / "community-history.jsonl", "".join(json.dumps(entry) + "\n" for entry in history))
    first = (NOW - timedelta(days=NOW.day - 1)).replace(hour=0)
    run(base / "runs", "Draft Without a Confirmed Schedule", first, 999, scheduled=False)


def accounts(root: Path) -> None:
    accounts = {
        "zaflas": "Zaflas", "youtube-2": "Whispers", "infinite": "Infinite",
        "vocal": "Vocal Pages", "zanata": "zanata", "reflection": "Reflection",
    }
    bindings = {
        "zaflas": "zaflas", "whispers-from-heaven": "youtube-2", "infinite-random-worlds": "infinite",
        "vocal-pages": "vocal", "zanata": "zanata", "reflection": "reflection",
    }
    write(root / ".local/accounts/registry.json", {
        "schema": 1,
        "accounts": {key: {"id": key, "label": label, "cdp_port": 9300 + index, "browser_mode": "system"}
                     for index, (key, label) in enumerate(accounts.items())},
        "bindings": {slug_: {"account_id": account, "channel_id": CHANNEL_IDS[slug_]}
                     for slug_, account in bindings.items()},
    })


def networks(root: Path) -> None:
    stamp = (NOW - timedelta(hours=2)).isoformat()
    for scope, key, name in (("social", "x", "Demo no X"), ("social", "instagram", "Demo"),
                             ("commercial", "whatsapp", "WhatsApp Web"), ("commercial", "mercadolivre", "Loja Demo")):
        write(root / ".local" / scope / key / "account.json", {
            "network": key, "state": "logged-in" if key != "instagram" else "login-required",
            "handle": "@demo" if scope == "social" else key, "display_name": name, "verified_at": stamp,
        })
    x = root / ".local/social/x"
    posts = {}
    agenda = []
    for index, text in enumerate([
        "Três números que todo produtor deveria anotar antes de vender a safra.",
        "Abastecer na hora certa economiza mais do que trocar de posto.",
        "Treino curto e constante vence o treino perfeito que nunca acontece.",
    ], start=1):
        item = f"P{index:02d}"
        posts[item] = {"state": "posted", "item_id": item, "text_sha256": "demo",
                       "tweet_url": f"https://x.com/demo/status/{1000 + index}",
                       "posted_at": (NOW - timedelta(days=3 - index, hours=2)).isoformat()}
        agenda.append({"id": item, "text": text})
    write(x / "posts.json", {"schema": 1, "posts": posts})
    write(root / ".local/promotion/agenda.json", {"schema": 1, "items": agenda})
    write(x / "replies.json", {"schema": 1, "replies": {
        str(index): {"state": "posted" if index % 7 else "unconfirmed", "for_post": "P01",
                     "posted_at": (NOW - timedelta(hours=index * 3)).isoformat()}
        for index in range(1, 19)}})
    write(x / "discovery.json", {"schema": 1, "created_at": stamp, "items": [{"text": "demo"}] * 7})

    whatsapp = root / ".local/commercial/whatsapp"
    write(whatsapp / "rules.json", {"mode": "allow", "contacts": ["Cliente Demo A", "Fornecedor Demo"]})
    events = [
        ("Cliente Demo A", "Bom dia! O pedido de ontem já saiu?", True, 50),
        ("Fornecedor Demo", "Segue a tabela nova de preços para dezembro.", True, 120),
        ("Contato Demo", "Oi, vi o anúncio do mouse sem fio.", False, 300),
        ("Cliente Demo A", "Obrigado, chegou certinho.", True, 20),
    ]
    write(whatsapp / "events.jsonl", "".join(json.dumps({
        "id": f"e{index}", "at": (NOW - timedelta(minutes=minutes)).isoformat(),
        "message_at": (NOW - timedelta(minutes=minutes)).strftime("%H:%M"), "chat": chat,
        "text": text, "unread": False, "allowed": allowed}) + "\n"
        for index, (chat, text, allowed, minutes) in enumerate(events)))
    write(whatsapp / "journal.jsonl", json.dumps({"key": "k1", "to": "Cliente Demo A", "state": "dry-run",
                                                  "at": stamp}) + "\n")
    write(root / ".local/commercial/mercadolivre/products.json", {
        "schema": 1, "query": "mouse sem fio", "captured_at": (NOW - timedelta(days=1)).isoformat(),
        "products": [
            {"title": title, "price": price, "currency": "BRL", "commission": commission, "brand": brand,
             "share_link": f"https://example.com/p/{index}"}
            for index, (title, price, commission, brand) in enumerate([
                ("Mouse sem fio silencioso 1600 DPI", 49.9, "12%", "Marca Demo"),
                ("Teclado mecânico compacto ABNT2", 219.0, "10%", "Marca Demo"),
                ("Suporte articulado para monitor", 1299.9, "8%", "Linha Exemplo"),
                ("Hub USB-C 7 em 1", 139.5, "11%", "Linha Exemplo"),
            ])
        ],
    })


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1]).resolve()
    if (root / ".local").exists():
        print(f"refusing to write into an existing .local: {root}", file=sys.stderr)
        return 1
    channels(root)
    accounts(root)
    networks(root)
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
