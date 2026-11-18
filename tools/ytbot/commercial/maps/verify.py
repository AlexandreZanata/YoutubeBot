"""Confirmation search and the bounded own-site check, with no live access in tests."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import unescape

from . import score
from .rules import MapsRules, host_of, normalize


@dataclass(frozen=True)
class Fetched:
    url: str
    final_url: str
    status: int
    title: str
    text: str
    error: str
    https: bool
    parking: bool


TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _decode(raw: bytes, charset: str) -> str:
    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def fetch(url: str, rules: MapsRules) -> Fetched:
    """One bounded GET, the normal browser user agent, no cookies and no redirect surprises."""
    confirmation = rules.confirmation
    request = urllib.request.Request(url, headers={
        "User-Agent": confirmation["user_agent"],
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml",
    })
    timeout = float(confirmation["timeout_seconds"])
    limit = int(confirmation["max_page_bytes"])
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(limit)
            status = response.status
            final_url = response.geturl()
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as error:
        try:
            raw = error.read(limit)
        except OSError:
            raw = b""
        status = error.code
        final_url = error.geturl() or url
        charset = (error.headers.get_content_charset() if error.headers else None) or "utf-8"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        return Fetched(url, url, 0, "", "", str(error), url.startswith("https://"), False)

    text = _decode(raw, charset)
    match = TITLE.search(text)
    title = re.sub(r"<[^>]+>", " ", unescape(match.group(1))).strip() if match else ""
    parking = any(normalize(marker) in normalize(text)
                  for marker in rules.confirmation["parking_markers"])
    return Fetched(url, final_url, status, re.sub(r"\s+", " ", title), text, "",
                   final_url.startswith("https://"), parking)


def _with_scheme(url: str) -> str:
    return url if "://" in url else "https://" + url


def domain_urls(name: str, rules: MapsRules) -> list[str]:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(name)).strip("-")
    if not slug:
        return []
    return [f"https://{slug}{tld}" for tld in rules.confirmation["domain_tlds"]]


def probe_domain(url: str, rules: MapsRules, fetcher=fetch) -> Fetched:
    """HTTPS first; a working HTTP-only copy still shows the business but counts as weak."""
    fetched = fetcher(url, rules)
    if fetched.status == 0 and url.startswith("https://"):
        alternative = "http://" + url[len("https://"):]
        fallback = fetcher(alternative, rules)
        if fallback.status and fallback.status < 400:
            return fallback
    return fetched


def ignored(url: str, rules: MapsRules) -> bool:
    host = host_of(url)
    return not host or any(host == item or host.endswith("." + item)
                           for item in rules.confirmation["ignore_domains"])


def _tokens(name: str, rules: MapsRules) -> list[str]:
    stopwords = {normalize(item) for item in rules.confirmation["name_stopwords"]}
    return [token for token in re.split(r"[^a-z0-9]+", normalize(name))
            if len(token) > 2 and token not in stopwords]


def _name_signal(name: str, fetched: Fetched, url: str, rules: MapsRules) -> bool:
    tokens = _tokens(name, rules)
    haystack = normalize(f"{host_of(url)} {fetched.final_url} {fetched.title}")
    if not tokens:
        return normalize(name) in haystack
    hits = sum(1 for token in tokens if token in haystack)
    if len(tokens) == 1:
        return hits == 1 and len(tokens[0]) >= 4
    return hits >= 2


def _city_signal(city: str, text: str) -> bool:
    plain = normalize(text)
    if normalize(city) and normalize(city) in plain:
        return True
    tokens = [token for token in re.split(r"[^a-z0-9]+", normalize(city)) if len(token) >= 4]
    return len(tokens) >= 2 and sum(1 for token in tokens if token in plain) >= 2


def _phone_signal(phone: str, text: str) -> bool:
    details = score.phone_details(phone)
    if details is None:
        return False
    return details["canonical"][-8:] in re.sub(r"\D", "", text)


def _page_signal(city: str, phone: str, fetched: Fetched) -> bool:
    return _city_signal(city, fetched.text) or _phone_signal(phone, fetched.text)


def evaluate(name: str, city: str, phone: str, maps_website: str,
             search_results: list[dict], rules: MapsRules, fetcher=fetch) -> dict:
    """Outcome and evidence for one business after the confirmation requests."""
    maps_class = score.website_class(maps_website, rules)
    candidates = []
    for result in search_results:
        if len(candidates) >= int(rules.confirmation["max_search_candidates"]):
            break
        url = result.get("url", "")
        if url.startswith("http") and not ignored(url, rules):
            candidates.append(("search", url))
    for url in domain_urls(name, rules):
        candidates.append(("domain", url))
    if maps_class == "own":
        candidates.append(("maps", maps_website))

    seen = set()
    evidence = []
    own_url = weak_url = ""
    for source, raw_url in candidates:
        url = _with_scheme(raw_url)
        if url in seen:
            continue
        seen.add(url)
        fetched = probe_domain(url, rules, fetcher)
        name_signal = _name_signal(name, fetched, url, rules) or source in ("domain", "maps")
        page_signal = _page_signal(city, phone, fetched)
        working = (fetched.status == 200 and not fetched.error and not fetched.parking)
        if source == "maps":
            is_own = working and fetched.https
            is_weak = not is_own
        elif source == "domain" and fetched.status == 0:
            # An unregistered obvious domain is not a site that exists and is broken.
            is_own = False
            is_weak = False
        else:
            is_own = working and fetched.https and name_signal and page_signal
            is_weak = name_signal and (not is_own and (not working or fetched.parking
                                                       or (page_signal and not fetched.https)))
        evidence.append({
            "source": source, "url": url, "final_url": fetched.final_url,
            "status": fetched.status, "https": fetched.https, "title": fetched.title[:200],
            "name_signal": name_signal, "page_signal": page_signal,
            "parking": fetched.parking, "error": fetched.error,
        })
        if is_own and not own_url:
            own_url = fetched.final_url or url
        if is_weak and not weak_url:
            weak_url = fetched.final_url or url

    if own_url:
        outcome = "has-site" if maps_class == "own" else "site-not-on-maps"
    elif weak_url:
        outcome = "weak-site"
    else:
        outcome = "no-site"
    return {"outcome": outcome, "maps_class": maps_class, "own_url": own_url,
            "weak_url": weak_url, "evidence": evidence}


def reclassify(check: dict, rules: MapsRules) -> dict:
    """Apply the current ignore lists to saved evidence, without another Google request."""
    if not check.get("evidence"):
        return check
    maps_class = check.get("maps_class") or "none"
    own_url = weak_url = ""
    for item in check.get("evidence") or []:
        source = item.get("source")
        url = item.get("url") or item.get("final_url") or ""
        if not url or ignored(url, rules):
            continue
        if source == "maps" and maps_class != "own":
            continue
        status = int(item.get("status") or 0)
        https = bool(item.get("https"))
        parking = bool(item.get("parking"))
        name_signal = bool(item.get("name_signal"))
        page_signal = bool(item.get("page_signal"))
        working = status == 200 and not item.get("error") and not parking
        if source == "maps":
            is_own = working and https
            is_weak = not is_own
        elif source == "domain" and status == 0:
            is_own = False
            is_weak = False
        else:
            is_own = working and https and name_signal and page_signal
            is_weak = name_signal and (not is_own and (not working or parking
                                                       or (page_signal and not https)))
        if is_own and not own_url:
            own_url = item.get("final_url") or url
        if is_weak and not weak_url:
            weak_url = item.get("final_url") or url
    if own_url:
        outcome = "has-site" if maps_class == "own" else "site-not-on-maps"
    elif weak_url:
        outcome = "weak-site"
    else:
        outcome = "no-site"
    return {**check, "outcome": outcome, "own_url": own_url, "weak_url": weak_url}


def confirm(listing: dict, search_results: list[dict], rules: MapsRules,
            fetcher=fetch) -> dict:
    return evaluate(listing.get("name", ""), listing.get("city", ""),
                    listing.get("phone", ""), listing.get("website_field", ""),
                    search_results, rules, fetcher=fetcher)
