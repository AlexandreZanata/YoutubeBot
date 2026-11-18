"""Saved Google Maps/search HTML and small builders for the off-line tests."""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).with_name("maps_fixtures")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def listing(**overrides) -> dict:
    """A complete read listing with values that reach tier A in the default rules."""
    value = {
        "name": "Clínica Exemplo",
        "category": "Clínica odontológica",
        "address": "Av. Brasil, 123 - Centro, Lucas do Rio Verde - MT",
        "phone": "(65) 90000-0001",
        "website_field": "",
        "rating": 4.8,
        "reviews": 134,
        "last_review_days": 20,
        "hours": True,
        "photos": 24,
        "photos_bucket": "10+",
        "unclaimed": True,
        "status": "",
        "group": "saude",
        "city": "Lucas do Rio Verde",
        "maps_url": "https://www.google.com/maps/place/Clinica+Exemplo/data=!4m2",
        "outcome": "no-site",
    }
    value.update(overrides)
    return value
