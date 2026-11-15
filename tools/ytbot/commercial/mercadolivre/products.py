"""Search Mercado Livre affiliate products and copy their share links."""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from ...accounts_store import private_directory, write_private

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


def _download(url: str, directory: Path, product_id: str, index: int) -> str:
    suffix = ".webp" if ".webp" in url.split("?", 1)[0].lower() else ".jpg"
    destination = directory / f"{product_id}-{index}{suffix}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(6 * 1024 * 1024 + 1)
    if len(data) > 6 * 1024 * 1024:
        raise RuntimeError("product image exceeds 6 MB")
    destination.write_bytes(data)
    destination.chmod(0o600)
    return str(destination)


def _details(page, product_url: str, image_dir: Path) -> dict:
    page.goto(product_url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(7000)
    product_id_match = re.search(r"/p/(MLB\d+)", product_url)
    product_id = product_id_match.group(1) if product_id_match else "product"
    ld = None
    for item in page.locator('script[type="application/ld+json"]').all():
        try:
            value = json.loads(item.inner_text())
        except (ValueError, TypeError):
            continue
        if value.get("@type") in ("Product", "ProductGroup"):
            ld = value
            break
    variant = {}
    variants = []
    if ld:
        variants = ld.get("hasVariant") or []
        variant = next((item for item in variants if item.get("productID") == product_id or item.get("sku") == product_id), {})
        if not variant and variants:
            variant = variants[0]
    offers = variant.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    title = variant.get("name") or (ld.get("name") if ld else "") or page.locator("h1").first.inner_text()
    image = variant.get("image") or ""
    if not image:
        meta = page.locator('meta[property="og:image"]')
        image = meta.first.get_attribute("content") if meta.count() else ""
    gallery = []
    for element in page.locator("img").all():
        try:
            src = element.get_attribute("src") or ""
            alt = element.get_attribute("alt") or ""
        except Exception:
            continue
        if ("mlstatic.com" in src and ("D_NQ_NP" in src or "D_NQ_NP_2X" in src)
                and src not in gallery and (not alt or len(alt) > 8)):
            gallery.append(src)
        if len(gallery) >= 4:
            break
    if image and image not in gallery:
        gallery.insert(0, image)
    photos = []
    image_dir = private_directory(image_dir)
    for index, src in enumerate(gallery[:4], 1):
        try:
            photos.append(_download(src, image_dir, product_id, index))
        except Exception as error:
            log(f"image download failed {src[:80]}: {error}")
    seller = ""
    box = page.locator('[class*="ui-pdp-seller"]').first
    if box.count():
        lines = [line.strip() for line in box.inner_text().splitlines() if line.strip()]
        if "Vendido por" in lines:
            idx = lines.index("Vendido por")
            seller = lines[idx + 1] if idx + 1 < len(lines) else ""
    long_description = ""
    description_box = page.locator('[class*="ui-pdp-description"]').first
    if description_box.count():
        text = description_box.inner_text().strip()
        long_description = text.split("\n", 1)[1].strip() if "\n" in text else text
    specs = []
    for prop in variant.get("additionalProperty") or []:
        if isinstance(prop, dict) and prop.get("name"):
            specs.append({"name": prop["name"], "value": prop.get("value", "")})
    meta_price = page.locator('[itemprop="price"]')
    return {
        "product_id": product_id,
        "canonical_url": variant.get("url") or product_url,
        "brand": (ld.get("brand") or {}).get("name", "") if ld else "",
        "model": ld.get("model", "") if ld else "",
        "price": offers.get("price"),
        "currency": offers.get("priceCurrency", "BRL"),
        "availability": offers.get("availability", "").rsplit("/", 1)[-1],
        "meta_price": meta_price.first.get_attribute("content") if meta_price.count() else "",
        "seller": seller,
        "long_description": long_description,
        "specs": specs,
        "variants": variants if ld else [],
        "photos": photos,
        "gallery": gallery[:4],
    }


def search(page, query: str, *, limit: int = 5, share: bool = True,
           details: bool = True, image_dir: Path | None = None) -> list[dict]:
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
    if details:
        for row in rows:
            try:
                row.update(_details(page, row["product_url"], image_dir or Path(".")))
            except Exception as error:
                row["details_error"] = str(error)
                log(f"details failed for {row['title'][:50]}: {error}")
    return rows


def save(path, query: str, rows: list[dict]) -> None:
    write_private(path, {
        "schema": 1,
        "query": query,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "products": rows,
    })
