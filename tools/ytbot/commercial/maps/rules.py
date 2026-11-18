"""Load and validate the versioned Google Maps research data (`maps_rules.toml`)."""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RULES_PATH = Path(__file__).with_name("maps_rules.toml")
REQUIRED_SELECTORS = (
    "search_box", "search_button", "feed", "listing_link", "detail_root",
    "detail_name", "address", "phone",
    "website", "category", "rating", "reviews", "hours", "photos", "reviews_tab",
    "reviews_sort", "login_link", "account_button", "challenge_frame", "search_result_title",
)
REQUIRED_LIMITS = ("daily_businesses", "max_results_per_query", "max_scrolls")
REQUIRED_PACING = (
    "between_businesses_min_seconds", "between_businesses_max_seconds",
    "between_searches_min_seconds", "between_searches_max_seconds", "scroll_min_seconds",
    "scroll_max_seconds", "settle_seconds", "page_timeout_seconds", "typing_min_ms",
    "typing_max_ms",
)
REQUIRED_CONFIRMATION = (
    "search_url", "timeout_seconds", "max_page_bytes", "max_search_candidates", "user_agent",
    "domain_tlds", "ignore_domains", "parking_markers", "name_stopwords",
)


class RulesError(ValueError):
    """The research data file is missing a field or holds an unsafe value."""


def normalize(text: str) -> str:
    """Lowercase, strip accents and collapse spaces, the form every label is matched on."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", plain.casefold()).strip()


def host_of(url: str) -> str:
    """`https://www.exemplo.com.br/x` -> `exemplo.com.br`; empty for a missing URL."""
    value = (url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "//" + value
    try:
        host = urlsplit(value).hostname or ""
    except ValueError:
        return ""
    host = host.casefold().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _strings(value, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip()
                                              for item in value):
        raise RulesError(f"{name} must be a string or a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _positive(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise RulesError(f"{name} must be a number") from error
    if number <= 0:
        raise RulesError(f"{name} must be positive")
    return number


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    weight: int
    offer: str
    short: str


@dataclass(frozen=True)
class Search:
    group: str
    query: str


@dataclass(frozen=True)
class MapsRules:
    path: Path
    version: int
    timezone: str
    limits: dict
    pacing: dict
    browser: dict
    selectors: dict[str, tuple[str, ...]]
    labels: dict[str, tuple[str, ...]]
    website: dict[str, tuple[str, ...]]
    confirmation: dict
    offers: dict
    scoring: dict
    tiers: dict
    groups: dict[str, Group]
    searches: tuple[Search, ...]
    exclusions: dict[str, tuple[str, ...]]
    raw: dict

    def selector(self, name: str) -> str:
        return self.selectors[name][0]

    def daily_businesses(self) -> int:
        return int(self.limits["daily_businesses"])


def _group(value) -> Group:
    try:
        key = str(value["key"])
        label = str(value["label"])
        weight = int(value["weight"])
        offer = str(value["offer"])
        short = str(value["short"])
    except (KeyError, TypeError, ValueError) as error:
        raise RulesError("every [[groups]] entry needs key, label, weight, offer and short") \
            from error
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", key):
        raise RulesError(f"invalid group key {key!r}")
    if not 0 <= weight <= 50:
        raise RulesError(f"group {key} weight must be between 0 and 50")
    return Group(key, label, weight, offer, short)


def load(path: Path | None = None) -> MapsRules:
    path = Path(path) if path else RULES_PATH
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as error:
        raise RulesError(f"cannot read {path}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise RulesError(f"invalid TOML in {path}: {error}") from error

    for section in ("limits", "pacing", "browser", "selectors", "labels", "website",
                    "confirmation", "offers", "scoring", "tiers", "exclusions"):
        if not isinstance(raw.get(section), dict):
            raise RulesError(f"missing [{section}] section")

    limits = raw["limits"]
    for key in REQUIRED_LIMITS:
        limits[key] = int(_positive(limits.get(key), f"limits.{key}"))
    pacing = raw["pacing"]
    for key in REQUIRED_PACING:
        pacing[key] = _positive(pacing.get(key), f"pacing.{key}")
    for low, high in (("between_businesses_min_seconds", "between_businesses_max_seconds"),
                      ("between_searches_min_seconds", "between_searches_max_seconds"),
                      ("scroll_min_seconds", "scroll_max_seconds"),
                      ("typing_min_ms", "typing_max_ms")):
        if pacing[low] > pacing[high]:
            raise RulesError(f"pacing.{low} cannot be greater than pacing.{high}")

    selectors = {key: _strings(value, f"selectors.{key}")
                 for key, value in raw["selectors"].items()}
    for key in REQUIRED_SELECTORS:
        if key not in selectors:
            raise RulesError(f"selectors.{key} is required")
    labels = {key: _strings(value, f"labels.{key}") for key, value in raw["labels"].items()}
    for key in ("unclaimed", "closed_permanently", "closed_temporarily", "no_results",
                "challenge", "login", "account", "newest_reviews", "reviews_sort",
                "photos", "search_no_results"):
        if not labels.get(key):
            raise RulesError(f"labels.{key} is required")
    website = {}
    for key in ("social", "marketplace", "free_builder"):
        if key not in raw["website"]:
            raise RulesError(f"website.{key} is required")
        website[key] = _strings(raw["website"][key], f"website.{key}")

    browser = raw["browser"]
    for key in ("login_url", "cdp_port", "background_display"):
        if key not in browser:
            raise RulesError(f"browser.{key} is required")
    browser["cdp_port"] = int(_positive(browser["cdp_port"], "browser.cdp_port"))

    confirmation = raw["confirmation"]
    for key in REQUIRED_CONFIRMATION:
        if key not in confirmation:
            raise RulesError(f"confirmation.{key} is required")
    confirmation["timeout_seconds"] = _positive(confirmation["timeout_seconds"],
                                                "confirmation.timeout_seconds")
    confirmation["max_page_bytes"] = int(_positive(confirmation["max_page_bytes"],
                                                    "confirmation.max_page_bytes"))
    confirmation["max_search_candidates"] = int(
        _positive(confirmation["max_search_candidates"],
                  "confirmation.max_search_candidates"))
    confirmation["search_url"] = str(confirmation["search_url"])
    if "{query}" not in confirmation["search_url"]:
        raise RulesError("confirmation.search_url must contain {query}")
    confirmation["user_agent"] = str(confirmation["user_agent"]).strip()
    if not confirmation["user_agent"]:
        raise RulesError("confirmation.user_agent cannot be empty")
    for key in ("domain_tlds", "ignore_domains", "parking_markers", "name_stopwords"):
        confirmation[key] = _strings(confirmation[key], f"confirmation.{key}")

    offers = {key: str(raw["offers"].get(key) or "") for key in ("adjust", "redesign")}
    if not all(offers.values()):
        raise RulesError("[offers] needs adjust and redesign")

    scoring = raw["scoring"]
    thresholds = scoring.get("thresholds")
    if not isinstance(thresholds, dict):
        raise RulesError("missing [scoring.thresholds]")
    for key in ("rating_excellent", "rating_good", "reviews_many", "reviews_some",
                "reviews_few", "recent_ninety_days", "recent_year", "photos_many"):
        if key not in thresholds:
            raise RulesError(f"missing scoring.thresholds.{key}")
        try:
            thresholds[key] = float(thresholds[key])
        except (TypeError, ValueError) as error:
            raise RulesError(f"scoring.thresholds.{key} must be a number") from error
    if thresholds["rating_excellent"] < thresholds["rating_good"]:
        raise RulesError("scoring.thresholds.rating_excellent must be >= rating_good")
    for section, keys in {
        "rating": ("excellent", "good"),
        "reviews": ("many", "some", "few"),
        "recent_review": ("ninety_days", "year"),
        "website": ("social-only", "none", "marketplace", "free-builder", "own"),
        "mobile": ("mobile", "landline"),
        "gaps": ("unclaimed", "no_hours", "few_photos"),
        "photos": ("ten_or_more",),
    }.items():
        if not isinstance(scoring.get(section), dict):
            raise RulesError(f"missing [scoring.{section}]")
        for key in keys:
            if key not in scoring[section]:
                raise RulesError(f"missing scoring.{section}.{key}")
            try:
                int(scoring[section][key])
            except (TypeError, ValueError) as error:
                raise RulesError(f"scoring.{section}.{key} must be an integer") from error

    groups = {}
    for entry in raw.get("groups") or []:
        group = _group(entry)
        if group.key in groups:
            raise RulesError(f"duplicate group {group.key}")
        groups[group.key] = group
    if not groups:
        raise RulesError("at least one [[groups]] entry is required")

    searches = []
    seen = set()
    for entry in raw.get("searches") or []:
        try:
            search = Search(str(entry["group"]), str(entry["query"]).strip())
        except (KeyError, TypeError) as error:
            raise RulesError("every [[searches]] entry needs group and query") from error
        if search.group not in groups:
            raise RulesError(f"search {search.query!r} uses unknown group {search.group}")
        if not search.query:
            raise RulesError("search query cannot be empty")
        if normalize(search.query) in seen:
            raise RulesError(f"duplicate search {search.query!r}")
        seen.add(normalize(search.query))
        searches.append(search)
    if not searches:
        raise RulesError("at least one [[searches]] entry is required")

    tiers = raw["tiers"]
    tiers["a"] = int(tiers.get("a", 70))
    tiers["b"] = int(tiers.get("b", 50))
    tiers["export"] = _strings(tiers.get("export", ["A", "B"]), "tiers.export")
    if tiers["a"] <= tiers["b"]:
        raise RulesError("tiers.a must be greater than tiers.b")
    if any(tier not in ("A", "B", "C") for tier in tiers["export"]):
        raise RulesError("tiers.export accepts only A, B and C")

    exclusions = {key: _strings(raw["exclusions"].get(key), f"exclusions.{key}")
                  for key in ("category_terms", "name_terms")}

    timezone = str(raw.get("timezone") or "America/Cuiaba")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise RulesError(f"invalid timezone {timezone!r}") from error

    return MapsRules(
        path=path, version=int(raw.get("version", 0)), timezone=timezone,
        limits=limits, pacing=pacing, browser=raw["browser"], selectors=selectors,
        labels=labels, website=website, confirmation=confirmation, offers=offers,
        scoring=raw["scoring"], tiers=tiers, groups=groups, searches=tuple(searches),
        exclusions=exclusions, raw=raw,
    )
