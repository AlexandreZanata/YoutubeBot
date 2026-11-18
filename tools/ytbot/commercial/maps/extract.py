"""Read listing, feed and Google result pages from saved HTML, never from a live request."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlsplit

from . import html
from .rules import MapsRules, host_of, normalize

NUMBER = re.compile(r"\d[\d.\s]*")


def _number(text: str) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", text or "")
    if not match:
        return None
    value = match.group(0)
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def _count(text: str) -> int | None:
    match = re.search(r"\d[\d.]*", text or "")
    if not match:
        return None
    try:
        return int(match.group(0).replace(".", ""))
    except ValueError:
        return None


def _label_value(text: str) -> str:
    value = (text or "").strip()
    if ":" in value:
        head, rest = value.split(":", 1)
        if len(head) <= 24:
            value = rest.strip()
    return value


def _first(nodes: list[html.Node]) -> html.Node | None:
    return nodes[0] if nodes else None


def _labeled_text(node: html.Node | None) -> str:
    if node is None:
        return ""
    return _label_value(node.get("aria-label") or node.text)


def _website_field(node: html.Node | None) -> str:
    if node is None:
        return ""
    href = node.get("href")
    if href:
        return unwrap_google(href)
    text = _label_value(node.text)
    return text if "." in text or text.startswith("http") else ""


def unwrap_google(url: str) -> str:
    """`/url?q=https://...` links from Google pages return the destination."""
    value = (url or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.path in ("/url", "/url/"):
        target = parse_qs(parsed.query).get("q", [""])[0]
        return unquote(target) or value
    return value


def _social_links(root: html.Node, rules: MapsRules) -> list[str]:
    found = []
    for node in root.select("a[href]"):
        href = node.get("href")
        host = host_of(href)
        if not host or not any(host == item or host.endswith("." + item)
                               for item in rules.website["social"]):
            continue
        value = unwrap_google(href)
        if value and value not in found:
            found.append(value)
    return found


def _photos(node: html.Node | None) -> tuple[int | None, str]:
    if node is None:
        return None, "0"
    label = f"{node.get('aria-label')} {node.text}"
    count = _count(label)
    if count is None:
        return None, "unknown"
    if count >= 10:
        return count, "10+"
    if count >= 1:
        return count, "1-9"
    return 0, "0"


def _has_label(root: html.Node, labels: tuple[str, ...]) -> bool:
    text = normalize(root.text)
    return any(normalize(label) in text for label in labels)


def _status(root: html.Node, rules: MapsRules) -> str:
    text = normalize(root.text)
    if any(normalize(label) in text for label in rules.labels["closed_permanently"]):
        return "Fechado permanentemente"
    if any(normalize(label) in text for label in rules.labels["closed_temporarily"]):
        return "Fechado temporariamente"
    return ""


def parse_listing(page_html: str, url: str, rules: MapsRules) -> dict:
    """Fields the listing panel shows, plus the place URL the one tab is on."""
    root = html.parse(page_html)
    name_node = _first(root.select(rules.selector("detail_name")))
    category_node = _first(root.select(rules.selector("category")))
    address_node = _first(root.select(rules.selector("address")))
    phone_node = _first(root.select(rules.selector("phone")))
    website_node = _first(root.select(rules.selector("website")))

    phone = ""
    if phone_node is not None:
        tel = phone_node.get("href")
        if tel.startswith("tel:"):
            phone = unquote(tel[4:])
        phone = _label_value(phone_node.get("aria-label") or phone_node.text) or phone

    rating_node = _first(root.select(rules.selector("rating")))
    rating = None
    if rating_node is not None:
        rating = _number(rating_node.get("aria-label") or rating_node.text)

    reviews = None
    for selector in rules.selectors["reviews"]:
        node = _first(root.select(selector))
        if node is not None:
            label = f"{node.get('aria-label')} {node.text}"
            if "avalia" in normalize(label) and "estrelas" not in normalize(label):
                reviews = _count(label)
                if reviews is not None:
                    break
    if reviews is None:
        match = re.search(r"(\d[\d.]*)\s*avalia", normalize(root.text))
        reviews = int(match.group(1).replace(".", "")) if match else None

    website = _website_field(website_node)
    photos, photos_bucket = _photos(_first(root.select(rules.selector("photos"))))
    hours = any(root.select(selector) for selector in rules.selectors["hours"])
    if not hours:
        hours = "horario de funcionamento" in normalize(root.text)

    return {
        "name": html.text_of(name_node),
        "category": html.text_of(category_node),
        "address": _labeled_text(address_node),
        "phone": phone,
        "website_field": website,
        "social": _social_links(root, rules),
        "rating": rating,
        "reviews": reviews,
        "last_review_days": None,
        "hours": hours,
        "photos": photos,
        "photos_bucket": photos_bucket,
        "unclaimed": _has_label(root, rules.labels["unclaimed"]),
        "status": _status(root, rules),
        "maps_url": url,
    }


def parse_place_links(page_html: str, rules: MapsRules) -> list[str]:
    """Place links in the results feed, document order, deduplicated."""
    root = html.parse(page_html)
    links = []
    for selector in rules.selectors["listing_link"]:
        for node in root.select(selector):
            href = unwrap_google(node.get("href"))
            if href.startswith("/"):
                href = "https://www.google.com" + href
            if href and "/maps/place/" in href and href not in links:
                links.append(href)
    return links


def parse_search_results(page_html: str, rules: MapsRules) -> list[dict]:
    """First-page Google results: title and destination, ignoring Google's own links."""
    root = html.parse(page_html)
    results = []
    seen = set()
    for node in root.select(rules.selector("search_result_title")):
        anchor = next((item for item in node.ancestors()
                       if item.tag == "a" and item.get("href")), None)
        url = unwrap_google(anchor.get("href")) if anchor is not None else ""
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        results.append({"title": node.text, "url": url})
    return results


def detect_challenge(page_html: str, url: str, rules: MapsRules) -> bool:
    if "/sorry/" in (url or ""):
        return True
    root = html.parse(page_html)
    if any(root.select(selector) for selector in rules.selectors["challenge_frame"]):
        return True
    return _has_label(root, rules.labels["challenge"])


def no_results(page_html: str, rules: MapsRules) -> bool:
    return _has_label(html.parse(page_html), rules.labels["no_results"])


def no_search_results(page_html: str, rules: MapsRules) -> bool:
    return _has_label(html.parse(page_html), rules.labels["search_no_results"])


def login_state(page_html: str, rules: MapsRules) -> str:
    root = html.parse(page_html)
    if any(root.select(selector) for selector in rules.selectors["account_button"]):
        return "logged-in"
    if any(root.select(selector) for selector in rules.selectors["login_link"]):
        return "login-required"
    if _has_label(root, rules.labels["account"]):
        return "logged-in"
    if _has_label(root, rules.labels["login"]):
        return "login-required"
    return "unknown"


def layout(page_html: str, rules: MapsRules) -> str:
    root = html.parse(page_html)
    if any(root.select(rules.selector(key))
           for key in ("search_box", "feed", "detail_name")):
        return "maps"
    if root.select(rules.selector("search_result_title")):
        return "google-search"
    return "unknown"


AGE = re.compile(r"\bha\s+(?:(um|uma|1)\s+)?(\d+)?\s*(dia|dias|semana|semanas|mes|meses|"
                 r"ano|anos)\b")


def _unit_days(unit: str) -> int:
    if unit.startswith("dia"):
        return 1
    if unit.startswith("semana"):
        return 7
    if unit.startswith("mes"):
        return 30
    return 365


def review_age_days(text: str) -> int | None:
    """`há 2 semanas` -> 14; `hoje` -> 0; `ontem` -> 1."""
    plain = normalize(text)
    if "hoje" in plain:
        return 0
    if "ontem" in plain:
        return 1
    match = AGE.search(plain)
    if not match:
        return None
    amount = match.group(2)
    number = 1 if amount is None else int(amount)
    return number * _unit_days(match.group(3))


def newest_review_age(text: str) -> int | None:
    """The freshest relative age in a reviews panel, or None when no date is shown."""
    plain = normalize(text)
    ages = []
    if "hoje" in plain:
        ages.append(0)
    if "ontem" in plain:
        ages.append(1)
    for match in AGE.finditer(plain):
        amount = match.group(2)
        number = 1 if amount is None else int(amount)
        ages.append(number * _unit_days(match.group(3)))
    return min(ages) if ages else None
