"""One-tab Google Maps driver: typed search, feed scroll, one listing at a time, back.

Live Google is never touched by the tests. Every public step is read-only and the driver stops
on a challenge or an unknown layout instead of guessing or bypassing it.
"""

from __future__ import annotations

import random
import time
from datetime import datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from . import extract, score, verify
from .record import Run, identity as listing_identity, url_key
from .rules import MapsRules, normalize


class ResearchError(RuntimeError):
    """Base error that carries the evidence the owner needs to act."""

    stage = "research"

    def __init__(self, reason: str, evidence: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.evidence = evidence or {}


class ChallengeError(ResearchError):
    stage = "challenge"


class LayoutError(ResearchError):
    stage = "unknown-layout"


class LoginRequired(ResearchError):
    stage = "login"


def _pause(sleep, rng, low: float, high: float) -> None:
    sleep(rng.uniform(low, max(low, high)))


def _check_page(page, rules: MapsRules, stage: str) -> str:
    content = page.content()
    if extract.detect_challenge(content, page.url, rules):
        raise ChallengeError("desafio do Google", {"url": page.url, "stage": stage})
    return content


def _wait_for(page, rules: MapsRules, stage: str, ready, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        content = _check_page(page, rules, stage)
        if ready(content):
            return content
        page.wait_for_timeout(700)
    raise LayoutError("layout desconhecido", {"url": page.url, "stage": stage})


def _search(page, rules: MapsRules, query: str, rng) -> None:
    box = page.locator(rules.selector("search_box"))
    if not box.count():
        raise LayoutError("campo de busca não encontrado", {"url": page.url, "stage": "search"})
    delay = int(rng.uniform(float(rules.pacing["typing_min_ms"]),
                            float(rules.pacing["typing_max_ms"])))
    box.first.click()
    box.first.fill("")
    box.first.press_sequentially(query, delay=delay)
    button = page.locator(rules.selector("search_button"))
    if button.count():
        button.first.click()
    else:
        page.keyboard.press("Enter")
    page.wait_for_timeout(int(float(rules.pacing["settle_seconds"]) * 1000))


def _results_ready(content: str, rules: MapsRules) -> bool:
    return bool(extract.parse_place_links(content, rules)) or extract.no_results(content, rules)


def _collect(page, rules: MapsRules, rng, sleep) -> list[str]:
    links: list[str] = []
    limit = int(rules.limits["max_results_per_query"])
    for _ in range(int(rules.limits["max_scrolls"])):
        content = _check_page(page, rules, "results")
        for link in extract.parse_place_links(content, rules):
            if link not in links:
                links.append(link)
        if len(links) >= limit:
            break
        feed = page.locator(rules.selector("feed"))
        if not feed.count():
            break
        feed.first.evaluate("el => el.scrollTo(0, el.scrollHeight)")
        _pause(sleep, rng, rules.pacing["scroll_min_seconds"],
               rules.pacing["scroll_max_seconds"])
        content = _check_page(page, rules, "results")
        found = extract.parse_place_links(content, rules)
        if len(found) <= len(links):
            break
        for link in found:
            if link not in links:
                links.append(link)
    return links[:limit]


def _detail(page, rules: MapsRules, timeout: float) -> tuple[dict, str]:
    content = _check_page(page, rules, "listing")
    listing = extract.parse_listing(content, page.url, rules)
    if not listing["name"]:
        content = _wait_for(page, rules, "listing",
                            lambda html: bool(extract.parse_listing(html, page.url,
                                                                    rules)["name"]), timeout)
        listing = extract.parse_listing(content, page.url, rules)
    return listing, page.url


def _review_age(page, rules: MapsRules) -> int | None:
    """Newest review in the reviews panel; optional when Google changes that sub-layout."""
    settle = int(float(rules.pacing["settle_seconds"]) * 1000)
    try:
        for _ in range(2):
            trigger = page.get_by_text(rules.labels["reviews_sort"][0], exact=True)
            if trigger.count() and trigger.first.is_visible():
                trigger.first.click()
                page.wait_for_timeout(settle)
                option = page.get_by_role("menuitemradio",
                                          name=rules.labels["newest_reviews"][0], exact=False)
                if option.count():
                    option.first.click()
                    page.wait_for_timeout(settle)
                    break
            tab = page.locator(rules.selector("reviews_tab"))
            if not tab.count():
                break
            tab.first.click()
            page.wait_for_timeout(settle)
        panel = page.locator(rules.selector("detail_root"))
        text = panel.first.inner_text() if panel.count() else page.locator("body").inner_text()
        return extract.newest_review_age(text)
    except Exception:
        return None


def inspect(page, rules: MapsRules) -> dict:
    page.goto(rules.browser["login_url"], wait_until="domcontentloaded",
              timeout=float(rules.pacing["page_timeout_seconds"]) * 1000)
    page.wait_for_timeout(int(float(rules.pacing["settle_seconds"]) * 1000))
    content = page.content()
    if extract.detect_challenge(content, page.url, rules):
        state = "challenge"
    else:
        state = extract.login_state(content, rules)
    return {"state": state, "layout": extract.layout(content, rules), "url": page.url}


def _open_links(page, run: Run, rules: MapsRules, query: str, group: str, links: list[str],
                limit: int, attempted: set[str], log, sleep, rng) -> tuple[int, int]:
    opened = 0
    remaining = max(0, int(limit))
    for link in links:
        if remaining <= 0:
            break
        key = verify_key(link)
        if key in attempted:
            continue
        run.append_listing({"state": "opening", "maps_url": link, "query": query,
                            "group": group, "city": run.city, "state_code": run.state,
                            "at": datetime.now(ZoneInfo(rules.timezone)).isoformat(
                                timespec="seconds")})
        attempted.add(key)
        page.goto(link, wait_until="domcontentloaded",
                  timeout=float(rules.pacing["page_timeout_seconds"]) * 1000)
        listing, place_url = _detail(page, rules, float(rules.pacing["page_timeout_seconds"]))
        listing["last_review_days"] = _review_age(page, rules)
        listing.update({
            "state": "read", "query": query, "group": group, "city": run.city,
            "state_code": run.state, "maps_url": place_url,
            "read_at": datetime.now(ZoneInfo(rules.timezone)).isoformat(timespec="seconds"),
        })
        run.append_listing(listing)
        attempted.add(verify_key(place_url))
        attempted.add(listing_identity(listing))
        remaining -= 1
        opened += 1
        log(f"[maps] {listing['name']} (lida agora)")
        try:
            page.go_back()
        except Exception:
            pass
        page.wait_for_timeout(int(float(rules.pacing["settle_seconds"]) * 1000))
        if not page.locator(rules.selector("feed")).count():
            _search(page, rules, query, rng)
            _wait_for(page, rules, "results",
                      lambda html, rules=rules: _results_ready(html, rules),
                      float(rules.pacing["page_timeout_seconds"]))
        _pause(sleep, rng, rules.pacing["between_businesses_min_seconds"],
               rules.pacing["between_businesses_max_seconds"])
    return opened, remaining


def research(page, run: Run, rules: MapsRules, searches, limit: int, now: datetime,
             log=print, sleep=time.sleep, rng=random) -> dict:
    """Walk the category catalog in one tab until the limit; every step is resumable."""
    page.set_default_timeout(float(rules.pacing["page_timeout_seconds"]) * 1000)
    attempted = run.attempted()
    done_rows = {normalize(entry.get("query", "")): entry for entry in run.queries()
                 if entry.get("status") == "done"}
    remaining = max(0, int(limit))
    opened = 0
    previous_search = False
    for search in searches:
        if remaining <= 0:
            break
        query = f"{search.query} em {run.city} - {run.state}"
        row = done_rows.get(normalize(query))
        if row is None:
            if previous_search:
                _pause(sleep, rng, rules.pacing["between_searches_min_seconds"],
                       rules.pacing["between_searches_max_seconds"])
            previous_search = True
            run.append_query({"query": query, "group": search.group, "status": "started",
                              "at": now.isoformat(timespec="seconds")})
            _search(page, rules, query, rng)
            _wait_for(page, rules, "results",
                      lambda html, rules=rules: _results_ready(html, rules),
                      float(rules.pacing["page_timeout_seconds"]))
            links = _collect(page, rules, rng, sleep)
            run.append_query({"query": query, "group": search.group, "status": "done",
                              "found": len(links), "links": links,
                              "at": datetime.now(ZoneInfo(rules.timezone)).isoformat(
                                  timespec="seconds")})
            log(f"[maps] {query}: {len(links)} empresas na lista")
        else:
            links = list(row.get("links") or [])
            log(f"[maps] {query}: retomando {len(links)} empresas da lista")
        count, remaining = _open_links(page, run, rules, query, search.group, links,
                                       remaining, attempted, log, sleep, rng)
        opened += count
    return {"opened": opened, "remaining": remaining}


def verify_key(url: str) -> str:
    return url_key(url)


def verify_run(page, run: Run, rules: MapsRules, log=print,
               sleep=time.sleep, rng=random, fetcher=verify.fetch) -> dict:
    """Confirmation Google searches in the same tab, then the bounded own-site checks."""
    pending = [listing for listing in run.pending_checks()
               if score.city_matches(listing, run.city)]
    page.set_default_timeout(float(rules.pacing["page_timeout_seconds"]) * 1000)
    first = True
    done = 0
    for listing in pending:
        if not first:
            _pause(sleep, rng, rules.pacing["between_searches_min_seconds"],
                   rules.pacing["between_searches_max_seconds"])
        first = False
        listing["city"] = run.city
        query = f'"{listing["name"]}" {run.city}'
        url = rules.confirmation["search_url"].format(query=quote_plus(query))
        page.goto(url, wait_until="domcontentloaded",
                  timeout=float(rules.pacing["page_timeout_seconds"]) * 1000)
        content = _check_page(page, rules, "confirmation")
        results = extract.parse_search_results(content, rules)
        if not results and not extract.no_search_results(content, rules) and extract.layout(
                content, rules) != "google-search":
            raise LayoutError("layout desconhecido na busca de confirmação",
                              {"url": page.url, "stage": "confirmation"})
        check = verify.confirm(listing, results, rules, fetcher=fetcher)
        check.update({
            "identity": listing["identity"], "name": listing.get("name", ""),
            "maps_url": listing.get("maps_url", ""),
            "at": datetime.now(ZoneInfo(rules.timezone)).isoformat(timespec="seconds"),
        })
        run.append_check(check)
        done += 1
        log(f"[maps] confirmado: {listing.get('name')} -> {check['outcome']}")
    return {"checked": done, "pending": len(pending) - done}
