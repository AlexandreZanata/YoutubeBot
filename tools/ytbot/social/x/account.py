"""X (Twitter) login detection and private account record."""

from __future__ import annotations

import re

LOGIN_URL = "https://x.com/home"
CDP_PORT = 9322
BACKGROUND_DISPLAY = ":90"

HANDLE = re.compile(r"@([A-Za-z0-9_]{1,15})\b")
TRAILING_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
RESERVED = {"home", "explore", "notifications", "messages", "i", "settings",
            "compose", "search", "login", "logout"}


def parse_handle(text: str = "", href: str = "") -> str:
    match = HANDLE.search(text)
    if match:
        return match.group(1)
    candidate = href.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    if candidate.lower() in RESERVED:
        return ""
    return candidate if TRAILING_HANDLE.fullmatch(candidate) else ""


def parse_display_name(text: str) -> str:
    for line in text.splitlines():
        value = " ".join(line.split())
        if value and not value.startswith("@") and not value.lower().startswith("mais"):
            return value[:100]
    return ""


def inspect(page) -> dict:
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    url = page.url
    if "/account/access" in url or "challenge" in url:
        return {"state": "challenge", "url": url}
    if ("accounts.google.com" in url or "/i/flow/login" in url
            or page.locator('input[name="text"]').count()
            or page.get_by_role("button", name="Entrar").count()
            or page.get_by_role("button", name="Sign in").count()):
        return {"state": "login-required", "url": url}

    account = page.locator('[data-testid="SideNav_AccountSwitcher_Button"]')
    if account.count():
        text = account.first.inner_text()
        handle = parse_handle(text)
        if handle:
            return {"state": "logged-in", "handle": handle,
                    "display_name": parse_display_name(text)}

    profile = page.locator('a[data-testid="AppTabBar_Profile_Link"]')
    if profile.count():
        handle = parse_handle(href=profile.first.get_attribute("href") or "")
        if handle:
            return {"state": "logged-in", "handle": handle, "display_name": ""}

    return {"state": "unknown", "url": url}
