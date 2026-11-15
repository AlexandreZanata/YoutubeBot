"""Search Mercado Livre affiliate products and copy their share links."""

from __future__ import annotations

import json
import re
from datetime import datetime

from ...accounts_store import write_private

PRODUCT_CARD = "li.poly-card"
SEARCH_INPUT = 'input[placeholder="Busque produtos"]'
SHARE_TITLE = "Compartilhe para ganhar dinheiro"
AFFILIATE_DOMAIN = "https://meli.la/"


def log(message: str) -> None:
    print(f"[mercadolivre] {message}", flush=True)


def _clipboard(page) -> str:
    try:
        return page.evaluate("navigator.clipboard.readText()")
    except Exception:
        return ""


def _share(page, card) -> dict:
    card.get_by_text("Compartilhar", exact=True).first.click()
    dialog = page.locator('[role="dialog"]').filter(has_text=SHARE_TITLE).first
    dialog.wait_for(state="visible", timeout=30000)
    result = {}
    for label, key in (("Copiar link", "share_link"), ("Copiar ID", "share_id"),
                       ("Copiar informação", "share_text")):
        button = dialog.get_by_role("button", name=label, exact=True)
        if not button.count():
            raise RuntimeError(f"share action not found: {label}")
        button.first.click()
        page.wait_for_timeout(1000)
        result[key] = _clipboard(page).strip()
    page.keyboard.press("Escape")
    page.wait_for_timeout(700)
    if not result.get("share_link", "").startswith(AFFILIATE_DOMAIN):
        raise RuntimeError("Mercado Livre did not return a meli.la affiliate link")
    return result


def search(page, query: str, *, limit: int = 5, share: bool = True) -> list[dict]:
    page.goto("https://www.mercadolivre.com.br/afiliados/hub",
              wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(7000)
    field = page.locator(SEARCH_INPUT).last
    if not field.count():
        raise RuntimeError("affiliate product search field was not found")
    field.fill(query)
    field.press("Enter")
    page.wait_for_timeout(7000)
    cards = page.locator(PRODUCT_CARD)
    if not cards.count():
        raise RuntimeError("Mercado Livre returned no affiliate products")
    rows = []
    for index in range(min(cards.count(), limit)):
        card = cards.nth(index)
        link = card.locator('a[href*="/p/"]').first
        if not link.count():
            continue
        text = card.inner_text()
        commission = re.search(r"GANHOS(?:\s+EXTRAS)?\s+(\d+%?)", text)
        row = {
            "position": index + 1,
            "title": (link.inner_text() or "").strip(),
            "product_url": link.get_attribute("href") or "",
            "image": (card.locator("img").first.get_attribute("src") or "") if card.locator("img").count() else "",
            "card_text": text,
            "commission": commission.group(1) if commission else "",
            "sponsored": "Patrocinado por" in text,
        }
        if share:
            row.update(_share(page, card))
        rows.append(row)
        log(f"{index + 1}/{limit}: {row['title'][:60]}")
    return rows


def save(path, query: str, rows: list[dict]) -> None:
    write_private(path, {
        "schema": 1,
        "query": query,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "products": rows,
    })
