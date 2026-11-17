"""WhatsApp Web commercial session."""

LOGIN_URL = "https://web.whatsapp.com/"
CDP_PORT = 9325
BACKGROUND_DISPLAY = ":93"
CHAT_LIST = "#pane-side"
SEARCH = 'input[placeholder="Search or start a new chat"]'
COMPOSER = 'div[data-testid="conversation-compose-box-input"]'


def inspect(page) -> dict:
    page.goto(LOGIN_URL, timeout=90000)
    page.wait_for_timeout(9000)
    if page.locator(CHAT_LIST).count():
        return {"state": "logged-in"}
    if page.locator("canvas").count():
        return {"state": "login-required"}
    return {"state": "unknown"}
