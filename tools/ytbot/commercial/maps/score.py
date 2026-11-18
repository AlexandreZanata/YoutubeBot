"""Classify the Maps website field, apply the hard filters and score a listing."""

from __future__ import annotations

import re

from ..whatsapp.sales.store import canonical_phone, dnc_hash, phone_key
from .extract import city_from_address
from .rules import MapsRules, host_of, normalize

ADJUST_OUTCOMES = ("site-not-on-maps", "weak-site")


def phone_details(raw: str) -> dict | None:
    """Canonical digits, mobile flag and the `(DD) NNNNN-NNNN` form used in the CSV."""
    canonical = canonical_phone(raw)
    if canonical is None:
        return None
    national = canonical[2:]
    mobile = len(national) == 11 and national[2] == "9"
    if len(national) == 11:
        display = f"({national[:2]}) {national[2:7]}-{national[7:]}"
    else:
        display = f"({national[:2]}) {national[2:6]}-{national[6:]}"
    return {"canonical": canonical, "mobile": mobile, "display": display}


def _domain_in(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == item or host.endswith("." + item) for item in domains)


def website_class(url: str, rules: MapsRules) -> str:
    host = host_of(url)
    if not host:
        return "none"
    if _domain_in(host, rules.website["free_builder"]):
        return "free-builder"
    if _domain_in(host, rules.website["social"]):
        return "social-only"
    if _domain_in(host, rules.website["marketplace"]):
        return "marketplace"
    return "own"


def _excluded_terms(text: str, terms: tuple[str, ...]) -> str:
    for term in terms:
        if re.search(rf"(?<!\w){re.escape(normalize(term))}(?!\w)", text):
            return term
    return ""


def city_matches(listing: dict, target: str) -> bool:
    """The listing belongs to the researched city, not a nearby one Google also returned."""
    address = listing.get("address", "")
    actual = city_from_address(address) or listing.get("city") or ""
    if actual:
        return normalize(actual) == normalize(target)
    return normalize(target) in normalize(address)


def exclusion_reason(listing: dict, rules: MapsRules, lead_keys: set[str],
                     dnc_keys: set[str]) -> str | None:
    """First hard filter that drops the business, in the contract's order."""
    target = listing.get("target_city")
    actual = city_from_address(listing.get("address", "")) or listing.get("city") or ""
    if target and not city_matches(listing, target):
        return f"fora da cidade: {actual or 'não identificada'}"

    status = normalize(listing.get("status", ""))
    if status and any(normalize(label) in status
                      for label in rules.labels["closed_permanently"]):
        return "fechado permanentemente"
    if status and any(normalize(label) in status
                      for label in rules.labels["closed_temporarily"]):
        return "fechado temporariamente"

    details = phone_details(listing.get("phone", ""))
    if not (listing.get("phone") or "").strip():
        return "sem telefone"
    if details is None:
        return "telefone inválido"

    text = normalize(f"{listing.get('category', '')} {listing.get('name', '')}")
    term = _excluded_terms(text, rules.exclusions["category_terms"])
    if term:
        return f"categoria excluída: {term}"
    term = _excluded_terms(text, rules.exclusions["name_terms"])
    if term:
        return f"rede ou franquia: {term}"

    key = phone_key(details["canonical"])
    if key in lead_keys:
        return "já é um lead"
    if dnc_hash(details["canonical"]) in dnc_keys:
        return "lista de não contatar"

    if listing.get("outcome") == "has-site":
        return "já tem site funcionando"
    return None


def score_listing(listing: dict, rules: MapsRules) -> dict:
    """Points from the contract table; the group weight comes from `[[groups]]`."""
    scoring = rules.scoring
    thresholds = scoring["thresholds"]
    points = {}

    rating = listing.get("rating")
    if rating is not None and rating >= float(thresholds["rating_excellent"]):
        points["rating"] = int(scoring["rating"]["excellent"])
    elif rating is not None and rating >= float(thresholds["rating_good"]):
        points["rating"] = int(scoring["rating"]["good"])
    else:
        points["rating"] = 0

    reviews = int(listing.get("reviews") or 0)
    if reviews >= int(thresholds["reviews_many"]):
        points["reviews"] = int(scoring["reviews"]["many"])
    elif reviews >= int(thresholds["reviews_some"]):
        points["reviews"] = int(scoring["reviews"]["some"])
    elif reviews >= int(thresholds["reviews_few"]):
        points["reviews"] = int(scoring["reviews"]["few"])
    else:
        points["reviews"] = 0

    age = listing.get("last_review_days")
    if age is not None and age <= int(thresholds["recent_ninety_days"]):
        points["recent_review"] = int(scoring["recent_review"]["ninety_days"])
    elif age is not None and age <= int(thresholds["recent_year"]):
        points["recent_review"] = int(scoring["recent_review"]["year"])
    else:
        points["recent_review"] = 0

    outcome = listing.get("outcome")
    group = rules.groups.get(listing.get("group", ""))
    if group is not None:
        points["group"] = group.weight
    else:
        points["group"] = 0

    effective_class = outcome if outcome in ADJUST_OUTCOMES else website_class(
        listing.get("website_field", ""), rules)
    points["website"] = int(scoring["website"].get(effective_class, 0))

    details = phone_details(listing.get("phone", ""))
    points["phone"] = int(scoring["mobile"]["mobile"] if details and details["mobile"]
                          else scoring["mobile"]["landline"])

    points["unclaimed"] = int(scoring["gaps"]["unclaimed"]) if listing.get("unclaimed") else 0
    points["no_hours"] = int(scoring["gaps"]["no_hours"]) if not listing.get("hours") else 0
    photos = listing.get("photos")
    if photos is None:
        points["photos"] = 0
    elif photos >= int(thresholds["photos_many"]):
        points["photos"] = int(scoring["photos"]["ten_or_more"])
    else:
        points["photos"] = int(scoring["gaps"]["few_photos"])

    total = sum(points.values())
    if total >= int(rules.tiers["a"]):
        tier = "A"
    elif total >= int(rules.tiers["b"]):
        tier = "B"
    else:
        tier = "C"
    return {"points": points, "total": total, "tier": tier, "class": effective_class,
            "outcome": outcome}


def suggested_product(listing: dict, rules: MapsRules) -> str:
    outcome = listing.get("outcome")
    if outcome == "site-not-on-maps":
        return rules.offers["adjust"]
    if outcome == "weak-site":
        return rules.offers["redesign"]
    group = rules.groups.get(listing.get("group", ""))
    return group.offer if group is not None else "site"


def short_product(listing: dict, rules: MapsRules) -> str:
    outcome = listing.get("outcome")
    if outcome == "site-not-on-maps":
        return "ajuste do Google Maps"
    if outcome == "weak-site":
        return "redesign"
    group = rules.groups.get(listing.get("group", ""))
    return group.short if group is not None else "site"


def rating_text(listing: dict) -> str:
    rating = listing.get("rating")
    if rating is None:
        return "sem nota"
    reviews = listing.get("reviews")
    return f"{rating:.1f}" if reviews is None else f"{rating:.1f} ({reviews})"


def note(listing: dict, score: dict, rules: MapsRules) -> str:
    """`A 84 · social-only · 4.8 (134) · agendamento`, the owner's quick review line."""
    return " · ".join((f"{score['tier']} {score['total']}", score["class"],
                       rating_text(listing), short_product(listing, rules)))
