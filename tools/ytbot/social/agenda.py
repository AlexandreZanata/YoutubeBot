"""Private promotion agenda and idempotent posting journal."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .store import SocialStore

SCHEMA = 1
FORMATS = ("text", "image", "thread", "poll", "video")
STATUSES = ("draft", "reviewed", "approved")
URL_TOKEN = "{url}"
URL_PATTERN = re.compile(r"https?://\S+")


class AgendaError(ValueError):
    """The agenda is not safe to use."""


def load_agenda(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA or not isinstance(data.get("items"), list):
        raise AgendaError("unsupported agenda schema")
    seen: set[str] = set()
    for item in data["items"]:
        required = ("id", "date", "product", "format", "text", "destination",
                    "campaign", "content", "status")
        if any(not item.get(field) for field in required):
            raise AgendaError(f"agenda item is missing a required field: {item.get('id', '?')}")
        if item["id"] in seen:
            raise AgendaError(f"duplicate agenda id: {item['id']}")
        seen.add(item["id"])
        date.fromisoformat(item["date"])
        if item["format"] not in FORMATS:
            raise AgendaError(f"unsupported format: {item['format']}")
        if item["status"] not in STATUSES:
            raise AgendaError(f"unsupported status: {item['status']}")
        if not item["destination"].startswith(("https://", "http://")):
            raise AgendaError(f"invalid destination for {item['id']}")
        if item["format"] in ("text", "image") and URL_TOKEN not in item["text"]:
            raise AgendaError(f"{item['id']} needs a {URL_TOKEN} placeholder")
    return data


def item_by_id(agenda: dict, identifier: str) -> dict:
    for item in agenda["items"]:
        if item["id"] == identifier:
            return item
    raise AgendaError(f"agenda item not found: {identifier}")


def tracked_url(item: dict) -> str:
    parts = urlsplit(item["destination"])
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({
        "utm_source": "x",
        "utm_medium": "organic_social",
        "utm_campaign": item["campaign"],
        "utm_content": item["content"],
    })
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def render_text(item: dict) -> str:
    text = item["text"].replace(URL_TOKEN, tracked_url(item))
    if URL_TOKEN in text:
        raise AgendaError(f"unresolved URL token in {item['id']}")
    return text


def x_length(text: str) -> int:
    """Approximate X's weighted length; every URL counts as 23 characters."""
    return len(URL_PATTERN.sub("x" * 23, text))


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def posts_path(store: SocialStore, network: str) -> Path:
    return store.network(network) / "posts.json"


def read_posts(store: SocialStore, network: str) -> dict:
    from ..accounts_store import read_private

    return read_private(posts_path(store, network), {"schema": SCHEMA, "posts": {}})


def write_posts(store: SocialStore, network: str, data: dict) -> None:
    from ..accounts_store import write_private

    write_private(posts_path(store, network), data)


def save_post(store: SocialStore, network: str, identifier: str, record: dict) -> None:
    data = read_posts(store, network)
    data.setdefault("posts", {})[identifier] = record
    write_posts(store, network, data)


def already_posted(store: SocialStore, network: str, identifier: str, digest: str) -> dict | None:
    posts = read_posts(store, network).get("posts", {})
    current = posts.get(identifier)
    if current:
        return current
    for other_id, record in posts.items():
        if record.get("text_sha256") == digest and record.get("state") in ("started", "posted", "unconfirmed"):
            return {"id": other_id, **record}
    return None
