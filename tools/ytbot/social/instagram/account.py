"""Instagram login detection and private account record."""

from __future__ import annotations

import re

LOGIN_URL = "https://www.instagram.com/"
OPEN_URL = "https://www.instagram.com/accounts/login/"
CDP_PORT = 9323
BACKGROUND_DISPLAY = ":91"

HANDLE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
ALT_HANDLE = re.compile(r"(?:de|of)\s+([A-Za-z0-9._]{1,30})", re.I)
RESERVED = {
    "about", "accounts", "api", "challenge", "developer", "direct", "emails",
    "explore", "graphql", "legal", "oauth", "p", "privacy", "reel", "reels",
    "session", "stories", "terms", "tv", "web",
}


def parse_handle(text: str = "", href: str = "") -> str:
    match = ALT_HANDLE.search(text)
    if match:
        return match.group(1)
    parts = [part for part in href.split("?", 1)[0].split("/") if part]
    if any(part.lower() in RESERVED for part in parts[:-1]):
        return ""
    candidate = parts[-1] if parts else ""
    if candidate.lower() in RESERVED:
        return ""
    return candidate if HANDLE.fullmatch(candidate) else ""


def _logged_in_handle(page) -> str:
    marker = page.locator('a[href="/direct/inbox/"], svg[aria-label="Página inicial"], '
                          'svg[aria-label="Home"]')
    if not marker.count():
        return ""
    rows = page.evaluate("""() => Array.from(document.querySelectorAll('a[href^="/"]')).map((a) => ({
        href: a.getAttribute('href') || '',
        alt: a.querySelector('img') ? (a.querySelector('img').alt || '') : '',
    }))""")
    for row in rows:
        alt = row.get("alt", "").lower()
        if "perfil" in alt or "profile" in alt:
            handle = parse_handle(text=row["alt"], href=row["href"])
            if handle:
                return handle
    for row in rows:
        handle = parse_handle(href=row.get("href", ""))
        if handle:
            return handle
    return ""


def inspect(page) -> dict:
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    url = page.url
    if "/challenge/" in url or "/checkpoint/" in url:
        return {"state": "challenge", "url": url}
    handle = _logged_in_handle(page)
    if handle:
        return {"state": "logged-in", "handle": handle, "display_name": ""}
    if ("/accounts/login" in url or page.locator('input[name="username"]').count()
            or page.get_by_role("button", name="Entrar").count()
            or page.get_by_role("button", name="Log in").count()
            or page.get_by_role("link", name="Entrar").count()
            or page.get_by_role("link", name="Log in").count()):
        return {"state": "login-required", "url": url}
    return {"state": "unknown", "url": url}
