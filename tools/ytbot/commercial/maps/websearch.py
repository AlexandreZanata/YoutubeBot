"""Free web search for the site confirmation, without Google's challenge.

Two public result pages are read once per business, at a human pace: DuckDuckGo Lite first,
Bing as the fallback. Only the first page counts; the same `verify.evaluate` decides whether
one of the found URLs is really the business's own site.
"""

from __future__ import annotations

import base64
import random
import re
import time
from datetime import datetime
from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit
from zoneinfo import ZoneInfo

from . import verify
from .record import Run
from .rules import MapsRules

DDG_LINK = re.compile(r'href="(//duckduckgo\.com/l/\?uddg=[^"]+)"', re.IGNORECASE)
DDG_DIRECT = re.compile(r"class=['\"]result-link['\"][^>]*href=['\"](https?://[^'\"]+)", re.IGNORECASE)
BING_LINK = re.compile(r'href="(https://www\.bing\.com/ck/a\?[^"]+)"', re.IGNORECASE)


def _ddg_results(text: str) -> list[dict]:
    urls = []
    for href in DDG_LINK.findall(text):
        value = parse_qs(urlsplit("https:" + unescape(href)).query).get("uddg", [""])[0]
        if value:
            urls.append(unquote(value))
    urls.extend(DDG_DIRECT.findall(text))
    return [{"url": url, "title": ""} for url in urls]


def _bing_results(text: str) -> list[dict]:
    urls = []
    for href in BING_LINK.findall(text):
        value = parse_qs(urlsplit(unescape(href)).query).get("u", [""])[0]
        if not value.startswith("a1"):
            continue
        payload = value[2:]
        try:
            raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            url = raw.decode("utf-8", "replace")
        except (ValueError, UnicodeDecodeError):
            continue
        if url.startswith("http"):
            urls.append(url)
    return [{"url": url, "title": ""} for url in urls]


def _clean(results: list[dict]) -> list[dict]:
    seen = set()
    kept = []
    for result in results:
        url = (result.get("url") or "").strip()
        host = urlsplit(url).hostname or ""
        if not url.startswith("http") or not host:
            continue
        if host.endswith(("duckduckgo.com", "bing.com", "microsoft.com", "msn.com")):
            continue
        if url in seen:
            continue
        seen.add(url)
        kept.append({"url": url, "title": result.get("title", "")})
    return kept


def search(query: str, rules: MapsRules, fetcher=verify.fetch) -> list[dict]:
    """First page of one query; the first engine that answers with links wins."""
    settings = rules.websearch
    engines = (
        (str(settings["ddg_url"]), _ddg_results),
        (str(settings["bing_url"]), _bing_results),
    )
    for template, parser in engines:
        url = template.format(query=quote_plus(query))
        page = fetcher(url, rules)
        if page.status != 200 or page.error:
            continue
        results = _clean(parser(page.text))
        if results:
            return results
    return []


def verify_run(run: Run, rules: MapsRules, log=print, fetcher=verify.fetch,
               recheck: bool = False, limit: int | None = None,
               mobile_only: bool = False, sleep=time.sleep, rng=random) -> dict:
    """Search + direct probes for the pending listings, with no Google request."""
    pending = verify.select_pending(run, rules, recheck=recheck, mobile_only=mobile_only)
    checks = {entry.get("identity"): entry for entry in run.checks()}
    pending = [listing for listing in pending
               if not verify.confirmed_by_browser(checks, listing)]
    if limit is not None:
        pending = pending[:max(0, int(limit))]
    settings = rules.websearch
    done = 0
    first = True
    for listing in pending:
        if not first:
            sleep(rng.uniform(float(settings["between_queries_min_seconds"]),
                              float(settings["between_queries_max_seconds"])))
        first = False
        listing["city"] = run.city
        results = search(f'"{listing.get("name", "")}" {run.city}', rules, fetcher=fetcher)
        check = verify.confirm(listing, results, rules, fetcher=fetcher)
        check.update({
            "identity": listing["identity"],
            "name": listing.get("name", ""),
            "maps_url": listing.get("maps_url", ""),
            "method": "web",
            "at": datetime.now(ZoneInfo(rules.timezone)).isoformat(timespec="seconds"),
        })
        run.append_check(check)
        done += 1
        log(f"[maps] confirmado: {listing.get('name')} -> {check['outcome']} "
            f"({len(results)} resultados)")
    return {"checked": done, "pending": len(pending) - done, "method": "web"}
