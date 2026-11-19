"""Google Places API (New) research path: the same listing schema, no browser tab.

The owner's key lives in the private tree (`.local/`) or in the environment and never
reaches Git, a log line or a report. The browser path stays the default; this one exists
because Google throttles the one-tab flow and the contract allows the paid API with the
owner's key instead of scaling the browser.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import score, verify
from .record import Run, identity, url_key
from .rules import MapsRules

FIELD_MASK = ",".join((
    "places.id",
    "places.displayName",
    "places.primaryTypeDisplayName",
    "places.formattedAddress",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.regularOpeningHours",
    "places.photos",
    "places.businessStatus",
    "places.googleMapsUri",
    "nextPageToken",
))
STATUS_TEXT = {
    "CLOSED_PERMANENTLY": "Fechado permanentemente",
    "CLOSED_TEMPORARILY": "Fechado temporariamente",
}
REPO_ROOT = Path(__file__).resolve().parents[4]


class PlacesError(RuntimeError):
    """The API refused the call or the key is missing; never retried blindly."""


def api_key(rules: MapsRules) -> str:
    settings = rules.places
    env_name = str(settings.get("key_env") or "")
    if env_name:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    path = Path(str(settings["key_file"]))
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise PlacesError(
            f"Google Places key not found at {path}; save it there or set "
            f"{env_name or 'the configured variable'}") from error
    if not value:
        raise PlacesError(f"Google Places key file {path} is empty")
    return value


def post(body: dict, key: str, rules: MapsRules) -> dict:
    """One bounded POST; the key travels only in the header and is never logged."""
    settings = rules.places
    request = urllib.request.Request(
        str(settings["endpoint"]),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        method="POST",
    )
    timeout = float(settings["timeout_seconds"])
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read(300).decode("utf-8", errors="replace")
        except OSError:
            pass
        raise PlacesError(f"Places API HTTP {error.code}: {detail}".strip()) from error
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise PlacesError(f"Places API request failed: {error}") from error


def search_places(term: str, rules: MapsRules, key: str | None = None,
                  poster=post) -> list[dict]:
    """Up to `max_pages` pages of one text query, in the contract's search order."""
    settings = rules.places
    key = key or api_key(rules)
    page_size = int(settings["page_size"])
    places: list[dict] = []
    token = ""
    for _ in range(int(settings["max_pages"])):
        body = {
            "textQuery": term,
            "languageCode": "pt-BR",
            "regionCode": "BR",
            "pageSize": page_size,
        }
        if token:
            body["pageToken"] = token
        data = poster(body, key, rules)
        places.extend(data.get("places") or [])
        token = str(data.get("nextPageToken") or "")
        if not token:
            break
    return places


def listing(place: dict, city: str, state: str, group: str, query: str,
            rules: MapsRules, now: datetime) -> dict:
    """Map one API place to the fields `read` rows already carry."""
    name = str((place.get("displayName") or {}).get("text") or "").strip()
    website = str(place.get("websiteUri") or "").strip()
    website_kind = score.website_class(website, rules)
    photos = len(place.get("photos") or [])
    if photos >= 10:
        photos_bucket = "10+"
    elif photos:
        photos_bucket = "1-9"
    else:
        photos_bucket = "0"
    value = {
        "name": name,
        "category": str((place.get("primaryTypeDisplayName") or {}).get("text") or ""),
        "address": str(place.get("formattedAddress") or ""),
        "city": city,
        "state_code": state,
        "phone": str(place.get("nationalPhoneNumber") or ""),
        "website_field": website,
        "social": [website] if website_kind == "social-only" else [],
        "rating": place.get("rating"),
        "reviews": place.get("userRatingCount"),
        # The API does not expose the age of the newest review; the score treats it as unknown.
        "last_review_days": None,
        "hours": bool(place.get("regularOpeningHours")),
        "photos": photos,
        "photos_bucket": photos_bucket,
        "unclaimed": False,
        "status": STATUS_TEXT.get(str(place.get("businessStatus") or ""), ""),
        "maps_url": str(place.get("googleMapsUri") or ""),
        "place_id": str(place.get("id") or ""),
        "source": "places",
        "query": query,
        "group": group,
        "at": now.isoformat(timespec="seconds"),
    }
    return value


def research(run: Run, rules: MapsRules, searches, limit: int, now: datetime,
             log=print, searcher=search_places) -> dict:
    """Walk the same category catalog through the API until `limit` new businesses."""
    attempted = run.attempted()
    remaining = max(0, int(limit))
    opened = 0
    key = api_key(rules)
    for search in searches:
        if remaining <= 0:
            break
        query = f"{search.query} em {run.city} - {run.state}"
        run.append_query({"query": query, "group": search.group, "status": "started",
                          "source": "places", "at": now.isoformat(timespec="seconds")})
        found = searcher(query, rules, key)
        run.append_query({"query": query, "group": search.group, "status": "done",
                          "found": len(found), "source": "places",
                          "at": now.isoformat(timespec="seconds")})
        log(f"[maps] {query}: {len(found)} empresas na lista (Places API)")
        for place in found:
            if remaining <= 0:
                break
            value = listing(place, run.city, run.state, search.group, query, rules, now)
            if not value["name"]:
                continue
            key_identity = identity(value)
            if key_identity in attempted:
                continue
            value.update({"state": "read",
                          "read_at": datetime.now(ZoneInfo(rules.timezone))
                          .isoformat(timespec="seconds")})
            run.append_listing(value)
            attempted.add(key_identity)
            if value.get("maps_url"):
                attempted.add(url_key(value["maps_url"]))
            remaining -= 1
            opened += 1
            log(f"[maps] {value['name']} (lida agora)")
    return {"opened": opened, "remaining": remaining, "source": "places"}


def verify_run(run: Run, rules: MapsRules, log=print, fetcher=verify.fetch,
               recheck: bool = False, limit: int | None = None,
               mobile_only: bool = False) -> dict:
    """Direct site probes only: no Google search, so an unlisted site can still exist."""
    pending = verify.select_pending(run, rules, recheck=recheck, mobile_only=mobile_only)
    checks = {entry.get("identity"): entry for entry in run.checks()}
    pending = [listing for listing in pending
               if not verify.confirmed_by_browser(checks, listing)]
    if limit is not None:
        pending = pending[:max(0, int(limit))]
    done = 0
    for value in pending:
        value["city"] = run.city
        check = verify.confirm(value, [], rules, fetcher=fetcher)
        check.update({
            "identity": value["identity"],
            "name": value.get("name", ""),
            "maps_url": value.get("maps_url", ""),
            "method": "places",
            "at": datetime.now(ZoneInfo(rules.timezone)).isoformat(timespec="seconds"),
        })
        run.append_check(check)
        done += 1
        log(f"[maps] confirmado: {value.get('name')} -> {check['outcome']}")
    return {"checked": done, "pending": len(pending) - done, "method": "places"}
