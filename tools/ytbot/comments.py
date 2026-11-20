"""Like, heart and answer unanswered comments on every channel before new videos."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import account, channels, config, runtime
from .accounts_store import AccountStore, private_directory, read_private, write_private

THREAD = "ytcp-comment-thread"
TOP_COMMENT = "ytcp-comment#comment"
DEFAULT_LIMIT = 25

FILTER = [
    {"isDisabled": False, "isPinned": True, "name": "SORT_BY", "value": "SORT_BY_MOST_RELEVANT"},
    {"name": "ENGAGED_STATUS", "value": ["COMMENT_CATEGORY_NOT_ENGAGED"]},
    {"name": "PARENT_ENTITY_CONTENT_TYPE", "value": [
        "PARENT_ENTITY_CONTENT_TYPE_WATCH",
        "PARENT_ENTITY_CONTENT_TYPE_SHORT",
        "PARENT_ENTITY_CONTENT_TYPE_CREATOR_POST",
    ]},
]

LIKE = (
    "Gostei", "Like",
)
HEART = (
    "Amei", "Heart",
)
REPLY = (
    "Responder", "Reply",
)

VOICE = {
    "zaflas": {
        "pt-BR": "Aqui no Zaflas a gente fala de campo, solo e gestão rural de verdade 🌱🚜",
        "en": "Here on Zaflas we talk about real farm work, soil and rural management 🌱🚜",
    },
    "fallem-prince": {
        "en": "Here on the channel we build dark, cinematic fantasy worlds 🖤⚔️",
        "pt-BR": "Aqui no canal a gente constrói mundos de fantasia sombrios e cinematográficos 🖤⚔️",
    },
    "whispers-from-heaven": {
        "en": "This channel exists to bring a little peace to your day 🕊️🙏",
        "pt-BR": "Este canal existe para trazer um pouco de paz ao seu dia 🕊️🙏",
    },
    "reflection": {
        "en": "The Word of Reflection walks with you through Scripture ✨🙏",
        "pt-BR": "O Word of Reflection caminha com você pelas Escrituras ✨🙏",
    },
    "infinite-random-worlds": {
        "en": "Every episode opens a new world to explore 🌌🚀",
        "pt-BR": "Cada episódio abre um mundo novo para explorar 🌌🚀",
    },
    "vocal-pages": {
        "en": "Vocal Pages is made for quiet listening and long stories 📖🎧",
        "pt-BR": "Vocal Pages é feito para ouvir com calma e acompanhar longas histórias 📖🎧",
    },
    "zanata": {
        "en": "zanata turns big books into clear, useful ideas 📚✨",
        "pt-BR": "O zanata transforma grandes livros em ideias claras e úteis 📚✨",
    },
}

TEXT = {
    "pt-BR": {
        "praise": (
            "Oi, {author}! Muito obrigado pelo carinho, isso motiva demais! {voice} "
            "Volte sempre que quiser conversar por aqui 😊💚"
        ),
        "question": (
            "Oi, {author}! Que boa pergunta, adorei! 🙌 {voice} "
            "Vou anotar sua ideia para os próximos vídeos. Obrigado por participar 😊"
        ),
        "criticism": (
            "Oi, {author}! Obrigado por dizer isso com honestidade, levo seu retorno a sério 🙏 "
            "{voice} Vou revisar esse ponto; se quiser detalhar o que te incomodou, eu leio por aqui 💬"
        ),
    },
    "en": {
        "praise": (
            "Hi, {author}! Thank you so much for the kindness, it really keeps me going! {voice} "
            "Come back any time, I love talking with you here 😊💚"
        ),
        "question": (
            "Hi, {author}! Great question, I love it! 🙌 {voice} "
            "I will note your idea for the next videos. Thanks for joining in 😊"
        ),
        "criticism": (
            "Hi, {author}! Thank you for saying this honestly, I take your feedback seriously 🙏 "
            "{voice} I will review that point; if you want to tell me what bothered you, I read it here 💬"
        ),
    },
}

CRITICISM = (
    "hate", "worst", "bad", "boring", "fake", "scam", "lie", "clickbait", "stupid",
    "waste", "dislike", "wrong", "terrible", "awful", "ruim", "péssimo", "pessimo",
    "lixo", "mentira", "chato", "errado", "horrível", "horrivel", "não gostei",
    "nao gostei", "fracasso", "vergonha", "propaganda",
)
PT_HINTS = (
    "você", "voce", "não", "nao", "muito", "muita", "gostei", "vídeo", "video",
    "canal", "obrigado", "obrigada", "conteúdo", "conteudo", "explica", "aula",
    "aqui", "isso", "mais", "também", "tambem", "cara", "mano", "beleza",
)
EN_HINTS = (
    "the", "this", "that", "you", "your", "video", "great", "thanks", "love",
    "good", "best", "awesome", "keep", "work", "very", "much", "what", "why",
    "how", "and", "is", "are", "for", "with", "please", "channel", "content",
)


def log(message: str) -> None:
    print(f"[comments] {message}", flush=True)


def inbox_url(channel_id: str) -> str:
    return (f"https://studio.youtube.com/channel/{channel_id}/comments/inbox"
            f"?filter={quote(json.dumps(FILTER, separators=(',', ':')))}")


def detect_language(text: str, default: str = "en") -> str:
    """Accents or Portuguese words win, then English hints, then the channel language."""
    lowered = text.lower()
    if re.search(r"[ãõçáéíóúâêôà]", lowered):
        return "pt-BR"
    words = set(re.findall(r"[a-záàâãéêíóôõúüç']+", lowered))
    portuguese = len(words & set(PT_HINTS))
    english = len(words & set(EN_HINTS))
    if portuguese == english:
        return default if default in TEXT else "en"
    return "pt-BR" if portuguese > english else "en"


def tone(text: str) -> str:
    lowered = text.lower()
    if any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", lowered) for word in CRITICISM):
        return "criticism"
    if "?" in text or "？" in text:
        return "question"
    return "praise"


def author_name(href: str) -> str:
    handle = href.rstrip("/").rsplit("/", 1)[-1] if href else ""
    return handle if handle.startswith("@") else ""


def reply_text(comment: str, author: str, channel_slug: str, language: str,
               default_language: str = "en") -> str:
    language = language if language in TEXT else default_language
    language = language if language in TEXT else "en"
    voice = VOICE.get(channel_slug, {}).get(language, "")
    template = TEXT[language][tone(comment)]
    name = author or ("amigo" if language == "pt-BR" else "friend")
    return template.format(author=name, voice=voice).strip()


def _journal_path() -> Path:
    slug = config.CHANNEL.slug if config.CHANNEL else "channel"
    return config.ROOT / ".local/ytbot/comments" / f"{slug}.json"


def journal() -> dict:
    return read_private(_journal_path(), {}) or {}


def _record(comment_id: str, entry: dict) -> None:
    path = _journal_path()
    private_directory(path.parent)
    data = journal()
    data[comment_id] = entry
    write_private(path, data)


def _entry(comment_id: str) -> dict:
    return journal().get(comment_id, {})


def collect(page) -> list[dict]:
    """Read the unanswered inbox rows that are already rendered."""
    return page.evaluate(
        """() => [...document.querySelectorAll('ytcp-comment-thread')].map((thread) => {
          const top = thread.querySelector('ytcp-comment#comment[comment-id]')
            || thread.querySelector('[comment-id]');
          const text = thread.querySelector('#content-text');
          const avatar = thread.querySelector('#author-thumbnail a#avatar');
          return {
            id: top ? top.getAttribute('comment-id') : '',
            text: text ? text.innerText : '',
            href: avatar ? avatar.getAttribute('href') : '',
          };
        }).filter((item) => item.id)""",
    )


def _load_more(page, rounds: int = 6) -> None:
    page.mouse.move(640, 600)
    count = page.locator(THREAD).count()
    for _ in range(rounds):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1500)
        current = page.locator(THREAD).count()
        if current == count:
            return
        count = current


def _click(page, thread, labels: tuple[str, ...]) -> bool:
    for label in labels:
        button = thread.get_by_role("button", name=label, exact=True)
        if button.count():
            button.first.click()
            page.wait_for_timeout(1200)
            return True
    return False


def _open_reply(page, thread) -> bool:
    if not _click(page, thread, REPLY):
        return False
    try:
        page.locator("#reply-dialog-id").wait_for(state="visible", timeout=15000)
        return True
    except Exception:
        return False


def _fill_reply(page, text: str) -> bool:
    box = page.locator("#reply-dialog-id")
    if not box.count():
        return False
    box.locator("textarea").fill(text)
    page.wait_for_timeout(600)
    return True


def _submit_reply(page) -> bool:
    box = page.locator("#reply-dialog-id")
    submit = box.locator("#submit-button")
    if not submit.count():
        return False
    submit.first.click()
    page.wait_for_timeout(4000)
    try:
        page.locator("#reply-dialog-id").wait_for(state="detached", timeout=15000)
        return True
    except Exception:
        return False


def _thread(page, comment_id: str):
    return page.locator(f'{THREAD}:has(ytcp-comment[comment-id="{comment_id}"])').first


def answer_page(page, channel, limit: int = DEFAULT_LIMIT, dry_run: bool = False) -> dict:
    _load_more(page)
    items = collect(page)
    result = {"replied": 0, "skipped": 0, "failed": 0, "seen": len(items)}
    for item in items:
        if result["replied"] + result["failed"] >= limit:
            break
        entry = _entry(item["id"])
        if entry.get("state") in ("replied", "started", "unconfirmed"):
            result["skipped"] += 1
            continue
        author = author_name(item["href"])
        language = detect_language(item["text"], channel.language)
        text = reply_text(item["text"], author, channel.slug, language, channel.language)
        if dry_run:
            log(f"would answer {item['id']} in {language}: {text}")
            result["replied"] += 1
            continue
        thread = _thread(page, item["id"])
        if not thread.count():
            result["failed"] += 1
            continue
        if not _open_reply(page, thread):
            result["failed"] += 1
            log(f"reply box did not open for {item['id']}")
            continue
        if not _fill_reply(page, text):
            result["failed"] += 1
            log(f"reply box closed before typing for {item['id']}")
            continue
        # Reply text is ready before any engagement: liking hides the comment from the
        # unanswered filter, so the answer must never depend on a later click.
        if entry.get("state") != "engaged":
            _click(page, thread, LIKE)
            _click(page, thread, HEART)
            _record(item["id"], {"state": "engaged", "comment": item["text"][:500],
                                 "language": language,
                                 "at": datetime.now().isoformat(timespec="seconds")})
        _record(item["id"], {"state": "started", "reply": text, "language": language,
                             "at": datetime.now().isoformat(timespec="seconds")})
        if not _submit_reply(page):
            _record(item["id"], {"state": "unconfirmed", "reply": text,
                                 "language": language,
                                 "at": datetime.now().isoformat(timespec="seconds")})
            result["failed"] += 1
            log(f"reply was not confirmed for {item['id']}; inspect before retrying")
            continue
        _record(item["id"], {"state": "replied", "reply": text, "language": language,
                             "at": datetime.now().isoformat(timespec="seconds")})
        result["replied"] += 1
        log(f"answered {author} in {language}")
    remaining = len(items) - result["replied"] - result["skipped"] - result["failed"]
    if remaining > 0:
        log(f"{remaining} comment(s) stay for the next visit")
    return result


def open_inbox(page, channel=None) -> None:
    channel = channel or config.CHANNEL
    page.goto(inbox_url(channel.channel_id), timeout=120000)
    page.wait_for_timeout(9000)


def answer(context, limit: int = DEFAULT_LIMIT, dry_run: bool = False) -> dict:
    """Answer the active channel's unanswered inbox in an open Studio context."""
    channel = config.CHANNEL
    if channel is None:
        raise RuntimeError("select a channel before checking comments")
    page = context.new_page()
    try:
        open_inbox(page, channel)
        result = answer_page(page, channel, limit, dry_run)
        log(f"{channel.slug}: {result}")
        return result
    finally:
        page.close()


def account_for(store: AccountStore, slug: str) -> str:
    binding = store.load()["bindings"].get(slug)
    return binding["account_id"] if binding else "legacy"


def answer_all(slugs=None, limit: int = DEFAULT_LIMIT, dry_run: bool = False) -> dict:
    """Visit every channel's Studio comments inbox before a new production run."""
    from playwright.sync_api import sync_playwright

    store = AccountStore()
    results = {}
    failures = []
    for slug in slugs or list(channels.CHANNELS):
        identifier = account_for(store, slug)
        try:
            with store.profile_lock(identifier):
                store.activate(identifier)
                channel = channels.apply(slug)
                runtime.start_hidden_chrome()
                with sync_playwright() as playwright:
                    browser = playwright.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{store.account(identifier)['cdp_port']}", timeout=60000)
                    context = browser.contexts[0]
                    account.ensure_channel(context)
                    results[slug] = answer(context, limit, dry_run)
                    # The legacy profile is the shared generation browser; closing
                    # it here kills the ChatGPT page a batch is about to use.
                    if identifier != "legacy":
                        browser.close()
        except Exception as error:
            failures.append((slug, str(error)))
            log(f"{slug}: {error}")
    if failures:
        log(f"channels not checked: {failures}")
    return results
