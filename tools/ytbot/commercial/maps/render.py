"""Write `candidatos.csv`, `ajuste-maps.csv` and `report.md` from one finished run."""

from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import datetime
from pathlib import Path

from ...accounts_store import private_directory
from ..whatsapp.sales.store import CSV_FIELDS, phone_key
from .extract import city_from_address
from . import score, verify
from .record import Run
from .rules import MapsRules


def _write_text(path: Path, text: str) -> None:
    private_directory(path.parent)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _csv_text(rows: list[dict]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n",
                            extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _row(listing: dict, website: str = "") -> dict:
    details = score.phone_details(listing.get("phone", ""))
    return {"name": listing.get("name", ""),
            "phone": details["display"] if details else listing.get("phone", ""),
            "city": listing.get("city", ""), "category": listing.get("category", ""),
            "maps_url": listing.get("maps_url", ""), "website": website,
            "note": listing.get("note", "")}


def _report(run: Run, listings: list[dict], excluded: list[dict],
            candidates: list[dict], adjustments: list[dict], exported: set[str],
            pending: int, scores: dict[str, dict], now: datetime) -> str:
    reasons = Counter(item["reason"] for item in excluded)
    outcomes = Counter(listing.get("outcome") for listing in listings)
    tiers = Counter(scores[listing["identity"]]["tier"] for listing in listings
                    if listing["identity"] in scores)
    places_checks = sum(1 for entry in run.checks() if entry.get("method") == "places")
    lines = [
        f"# Pesquisa Google Maps — {run.city} - {run.state} ({run.day})",
        "",
        f"Gerado em {now.isoformat(timespec='seconds')}. Somente dados públicos do anúncio; "
        "nada foi importado ou enviado.",
        "",
    ]
    if places_checks:
        lines += [
            f"> Confirmação limitada: {places_checks} empresa(s) tiveram só a checagem direta "
            "de site (Places API), sem busca no Google. Um site próprio fora do Maps pode "
            "existir; confira os nomes do lote antes de importar.",
            "",
        ]
    lines += [
        "## Etapas",
        "",
        "| Etapa | Quantidade |",
        "| --- | --- |",
        f"| Buscas concluídas | {sum(1 for q in run.queries() if q.get('status') == 'done')} |",
        f"| Empresas lidas | {len(listings)} |",
        f"| Confirmações pendentes | {pending} |",
        f"| Sem site | {outcomes.get('no-site', 0)} |",
        f"| Site fora do Maps | {outcomes.get('site-not-on-maps', 0)} |",
        f"| Site fraco | {outcomes.get('weak-site', 0)} |",
        f"| Já tem site | {outcomes.get('has-site', 0)} |",
        f"| Candidatos A/B | {len(candidates)} |",
        f"| Ajuste do Google Maps A/B | {len(adjustments)} |",
        f"| Fora do corte (C) | {tiers.get('C', 0)} |",
        "",
        "## Melhores candidatos",
        "",
    ]
    ranked = sorted(candidates, key=lambda item: (-scores[item["identity"]]["total"],
                                                  item.get("name", "")))
    if ranked:
        for listing in ranked[:20]:
            details = score.phone_details(listing.get("phone", ""))
            lines.append(f"- **{listing.get('name', '')}** — "
                         f"{details['display'] if details else listing.get('phone', '')} — "
                         f"{listing.get('note', '')} — {listing.get('maps_url', '')}")
    else:
        lines.append("Nenhum candidato A/B.")

    lines += ["", "## Ajuste do Google Maps", ""]
    if adjustments:
        for listing in sorted(adjustments, key=lambda item: item.get("name", "")):
            lines.append(f"- **{listing.get('name', '')}** — {listing.get('website', '')} — "
                         f"{listing.get('note', '')}")
    else:
        lines.append("Nenhuma empresa nesta lista.")

    lines += ["", "## Fora do corte (C)", ""]
    below = [listing for listing in listings
             if scores.get(listing["identity"], {}).get("tier") == "C"
             and listing["identity"] not in exported]
    if below:
        for listing in sorted(below, key=lambda item: item.get("name", "")):
            lines.append(f"- {listing.get('name', '')} — "
                         f"{scores[listing['identity']]['total']} pontos")
    else:
        lines.append("Nenhuma.")

    lines += ["", "## Exclusões", ""]
    if excluded:
        for item in excluded:
            lines.append(f"- **{item['name']}** — {item['reason']}")
    else:
        lines.append("Nenhuma.")
    if reasons:
        lines += ["", "Resumo: " + ", ".join(f"{reason} ({count})"
                                             for reason, count in reasons.most_common())]
    lines.append("")
    return "\n".join(lines)


def _dedupe(items: list[dict], scores: dict[str, dict], excluded: list[dict]) -> list[dict]:
    """One lead per phone: two Maps listings of the same business must not open twice."""
    best: dict[str, dict] = {}
    for item in items:
        key = phone_key(item.get("phone", "")) or item["identity"]
        if key not in best:
            best[key] = item
            continue
        loser = item
        if scores[item["identity"]]["total"] > scores[best[key]["identity"]]["total"]:
            loser, best[key] = best[key], item
        excluded.append({"name": loser.get("name", ""), "reason": "duplicado (mesmo telefone)",
                         "identity": loser["identity"]})
    return list(best.values())


def export_run(run: Run, rules: MapsRules, now: datetime, lead_keys: set[str],
               dnc_keys: set[str], mobile_only: bool = False) -> dict:
    """Merge checks, apply filters and score; the only step that produces owner files."""
    checks = {entry["identity"]: verify.reclassify(entry, rules)
              for entry in run.checks()}
    listings = run.read_listings()
    excluded, candidates, adjustments = [], [], []
    scores = {}
    exported = set()
    pending = 0
    for listing in listings:
        listing["city"] = (city_from_address(listing.get("address", ""))
                            or listing.get("city") or run.city)
        listing["target_city"] = run.city
        if not score.city_matches(listing, run.city,
                                  tuple(rules.limits.get("nearby_cities") or ())):
            excluded.append({"name": listing.get("name", ""),
                             "reason": f"fora da cidade: {listing['city']}",
                             "identity": listing["identity"]})
            continue
        reason = score.exclusion_reason(listing, rules, lead_keys, dnc_keys)
        if reason:
            excluded.append({"name": listing.get("name", ""), "reason": reason,
                             "identity": listing["identity"]})
            continue
        check = checks.get(listing["identity"])
        if check is None:
            pending += 1
            continue
        listing["outcome"] = check.get("outcome")
        listing["own_url"] = check.get("own_url", "")
        listing["weak_url"] = check.get("weak_url", "")
        reason = score.exclusion_reason(listing, rules, lead_keys, dnc_keys)
        if reason:
            excluded.append({"name": listing.get("name", ""), "reason": reason,
                             "identity": listing["identity"]})
            continue
        details = score.phone_details(listing.get("phone", ""))
        if details is None:
            excluded.append({"name": listing.get("name", ""), "reason": "telefone inválido",
                             "identity": listing["identity"]})
            continue
        if mobile_only and not details["mobile"]:
            excluded.append({"name": listing.get("name", ""),
                             "reason": "telefone fixo (filtro WhatsApp)",
                             "identity": listing["identity"]})
            continue
        result = score.score_listing(listing, rules)
        scores[listing["identity"]] = result
        listing["note"] = score.note(listing, result, rules)
        if result["tier"] not in rules.tiers["export"]:
            continue
        exported.add(listing["identity"])
        if listing["outcome"] == "no-site":
            candidates.append(listing)
        elif listing["outcome"] in score.ADJUST_OUTCOMES:
            listing["website"] = listing.get("own_url") or listing.get("weak_url") or ""
            adjustments.append(listing)

    candidate_path = run.path / "candidatos.csv"
    adjust_path = run.path / "ajuste-maps.csv"
    report_path = run.path / "report.md"
    candidates = _dedupe(candidates, scores, excluded)
    adjustments = _dedupe(adjustments, scores, excluded)
    _write_text(candidate_path, _csv_text([_row(listing) for listing in candidates]))
    _write_text(adjust_path,
                _csv_text([_row(listing, listing["website"]) for listing in adjustments]))
    _write_text(report_path, _report(run, listings, excluded, candidates, adjustments,
                                     exported, pending, scores, now))
    return {
        "run": run.id,
        "read": len(listings),
        "pending": pending,
        "candidates": len(candidates),
        "adjustments": len(adjustments),
        "excluded": len(excluded),
        "candidatos_csv": str(candidate_path),
        "ajuste_maps_csv": str(adjust_path),
        "report": str(report_path),
    }
