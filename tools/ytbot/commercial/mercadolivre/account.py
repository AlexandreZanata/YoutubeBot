"""Mercado Livre affiliate hub login detection."""

from __future__ import annotations

LOGIN_URL = "https://www.mercadolivre.com.br/afiliados/hub"
OPEN_URL = "https://www.mercadolivre.com.br/afiliados/hub"
CDP_PORT = 9324
BACKGROUND_DISPLAY = ":92"


def inspect(page) -> dict:
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    url = page.url
    body = page.locator("body").inner_text()
    lower = body.lower()
    if "afiliados" in url and any(marker in lower for marker in (
            "painel", "produtos", "campanhas", "comiss", "afiliad")):
        if not any(marker in lower for marker in ("iniciar sessão", "entrar com", "criar conta")):
            return {"state": "logged-in", "url": url}
    if any(marker in lower for marker in ("iniciar sessão", "entrar com", "criar conta")):
        return {"state": "login-required", "url": url}
    return {"state": "unknown", "url": url}
