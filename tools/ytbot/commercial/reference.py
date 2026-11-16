"""Fast local SQLite reference index and price-history comparator for VPS commerce offers."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

_MLB_RE = re.compile(r"\b(MLB\d{6,14})\b", re.IGNORECASE)


def _sibling_zaturo_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root.parent / "ZaturoBot"


def resolve_sync_script(override: Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    env_script = os.environ.get("PROCURALI_SYNC_SCRIPT", "").strip()
    if env_script:
        return Path(env_script)
    return _sibling_zaturo_dir() / "scripts" / "procurali-local-sync.sh"


def resolve_reference_json_path(
    network: str,
    network_dir: Path | None = None,
    override: Path | None = None,
) -> Path:
    if override is not None:
        return Path(override)
    env_path = os.environ.get("PROCURALI_VPS_REFERENCE_FILE", "").strip()
    if env_path:
        return Path(env_path)
    if network_dir is not None:
        local_copy = Path(network_dir) / "vps-reference.json"
        if local_copy.is_file():
            return local_copy
    _ = network
    return _sibling_zaturo_dir() / ".secrets" / "procurali-local-bot" / "vps-reference.json"


def resolve_reference_db_path(network_dir: Path) -> Path:
    return Path(network_dir) / "vps-reference.sqlite3"


def format_brl_cents(cents: int | None) -> str:
    if cents is None:
        return "N/D"
    negative = cents < 0
    abs_cents = abs(int(cents))
    whole = abs_cents // 100
    frac = abs_cents % 100
    whole_txt = f"{whole:,}".replace(",", ".")
    prefix = "-" if negative else ""
    return f"{prefix}R$ {whole_txt},{frac:02d}"


def price_to_cents(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value * 100
    if isinstance(value, float):
        return round(value * 100)
    raw = str(value).strip()
    if not raw:
        return None
    cleaned = raw.replace("R$", "").replace("\u00a0", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return round(float(cleaned) * 100)
    except ValueError:
        return None


def refresh_from_vps(sync_script: Path | None = None) -> dict[str, Any]:
    script = resolve_sync_script(sync_script)
    if not script.is_file():
        raise FileNotFoundError(
            f"Sync script not found at {script}. Configure PROCURALI_SYNC_SCRIPT or sibling ZaturoBot."
        )
    proc = subprocess.run(
        ["bash", str(script), "--sync-reference"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[:300]
        raise RuntimeError(f"VPS reference sync failed (exit {proc.returncode}): {detail}")
    return json.loads(proc.stdout)


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        CREATE TABLE IF NOT EXISTS ref_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ref_products (
            product_id TEXT PRIMARY KEY,
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            brand TEXT NOT NULL,
            category_slug TEXT NOT NULL,
            subcategory_slug TEXT NOT NULL,
            seller_name TEXT NOT NULL,
            state TEXT NOT NULL,
            current_price_cents INTEGER NOT NULL,
            pix_price_cents INTEGER NOT NULL,
            reference_price_cents INTEGER,
            discount_pct INTEGER NOT NULL,
            lowest_price_30d_cents INTEGER NOT NULL,
            average_price_30d_cents INTEGER NOT NULL,
            highest_price_30d_cents INTEGER NOT NULL,
            previous_price_cents INTEGER,
            price_delta_cents INTEGER NOT NULL,
            price_delta_pct INTEGER NOT NULL,
            observation_count INTEGER NOT NULL,
            price_trend TEXT NOT NULL,
            price_level TEXT NOT NULL,
            price_level_label TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            observed_at_ms INTEGER NOT NULL,
            official_affiliate_url TEXT NOT NULL,
            short_summary TEXT NOT NULL,
            telegram_published_count INTEGER NOT NULL,
            telegram_last_status TEXT,
            search_blob TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ref_cat
            ON ref_products(category_slug, subcategory_slug);
        CREATE INDEX IF NOT EXISTS idx_ref_trend
            ON ref_products(price_trend, observed_at_ms DESC);
        """
    )


def ensure_local_reference_db(json_path: Path, db_path: Path) -> bool:
    """Syncs `db_path` from `json_path` only when mtime+size changed. Returns True if rebuilt."""
    json_file = Path(json_path)
    if not json_file.is_file():
        raise FileNotFoundError(
            f"VPS reference catalog not found at {json_file}. Run with --refresh first."
        )
    stat = json_file.stat()
    source_sig = f"{stat.st_mtime_ns}:{stat.st_size}"

    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_file) as conn:
        _init_schema(conn)
        row = conn.execute(
            "SELECT value FROM ref_meta WHERE key = 'source_sig'"
        ).fetchone()
        if row is not None and row[0] == source_sig:
            return False

        payload = json.loads(json_file.read_text(encoding="utf-8"))
        items = payload.get("items") or []
        records = []
        for item in items:
            pid = str(item.get("productId") or "").strip().upper()
            if not pid:
                continue
            title = str(item.get("title") or "")
            brand = str(item.get("brand") or "")
            cat = str(item.get("categorySlug") or "")
            subcat = str(item.get("subcategorySlug") or "")
            summary = str(item.get("shortSummary") or "")
            seller = str(item.get("sellerName") or "")
            search_blob = f"{pid} {title} {brand} {cat} {subcat} {seller} {summary}".lower()
            records.append(
                (
                    pid,
                    str(item.get("slug") or ""),
                    title,
                    brand,
                    cat,
                    subcat,
                    seller,
                    str(item.get("state") or "approved"),
                    int(item.get("currentPriceCents") or 0),
                    int(item.get("pixPriceCents") or 0),
                    item.get("referencePriceCents"),
                    int(item.get("discountPct") or 0),
                    int(item.get("lowestPrice30dCents") or 0),
                    int(item.get("averagePrice30dCents") or 0),
                    int(item.get("highestPrice30dCents") or 0),
                    item.get("previousPriceCents"),
                    int(item.get("priceDeltaCents") or 0),
                    int(item.get("priceDeltaPct") or 0),
                    int(item.get("observationCount") or 1),
                    str(item.get("priceTrend") or "new"),
                    str(item.get("priceLevel") or "good_price"),
                    str(item.get("priceLevelLabel") or ""),
                    str(item.get("observedAt") or ""),
                    int(item.get("observedAtMs") or 0),
                    str(item.get("officialAffiliateUrl") or ""),
                    summary,
                    int(item.get("telegramPublishedCount") or 0),
                    item.get("telegramLastStatus"),
                    search_blob,
                )
            )

        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM ref_products")
        conn.executemany(
            """
            INSERT INTO ref_products (
                product_id, slug, title, brand, category_slug, subcategory_slug,
                seller_name, state, current_price_cents, pix_price_cents,
                reference_price_cents, discount_pct, lowest_price_30d_cents,
                average_price_30d_cents, highest_price_30d_cents,
                previous_price_cents, price_delta_cents, price_delta_pct,
                observation_count, price_trend, price_level, price_level_label,
                observed_at, observed_at_ms, official_affiliate_url,
                short_summary, telegram_published_count, telegram_last_status,
                search_blob
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            records,
        )
        meta_rows = [
            ("source_sig", source_sig),
            ("generated_at", str(payload.get("generatedAt") or "")),
            ("cache_generation", str(payload.get("cacheGeneration") or 0)),
            ("total_products", str(len(records))),
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO ref_meta(key, value) VALUES (?, ?)",
            meta_rows,
        )
        conn.commit()
    return True


def _row_to_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "product_id": row["product_id"],
        "slug": row["slug"],
        "title": row["title"],
        "brand": row["brand"],
        "category_slug": row["category_slug"],
        "subcategory_slug": row["subcategory_slug"],
        "seller_name": row["seller_name"],
        "current_price_cents": row["current_price_cents"],
        "price_brl": format_brl_cents(row["current_price_cents"]),
        "lowest_price_30d_cents": row["lowest_price_30d_cents"],
        "lowest_30d_brl": format_brl_cents(row["lowest_price_30d_cents"]),
        "average_price_30d_cents": row["average_price_30d_cents"],
        "avg_30d_brl": format_brl_cents(row["average_price_30d_cents"]),
        "highest_price_30d_cents": row["highest_price_30d_cents"],
        "previous_price_cents": row["previous_price_cents"],
        "price_delta_cents": row["price_delta_cents"],
        "price_delta_pct": row["price_delta_pct"],
        "observation_count": row["observation_count"],
        "price_trend": row["price_trend"],
        "price_level_label": row["price_level_label"],
        "discount_pct": row["discount_pct"],
        "observed_at": row["observed_at"],
        "official_affiliate_url": row["official_affiliate_url"],
        "telegram_published_count": row["telegram_published_count"],
        "telegram_last_status": row["telegram_last_status"],
        "short_summary": row["short_summary"],
    }


def query_reference_db(
    db_path: Path,
    *,
    query: str = "",
    product_id: str = "",
    category: str = "",
    trend: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Runs sub-millisecond SQLite lookups against the synced VPS catalog DB."""
    started = time.perf_counter()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        meta = dict(conn.execute("SELECT key, value FROM ref_meta").fetchall())
        cat_counts = [
            {"category_slug": r["category_slug"], "count": r["cnt"]}
            for r in conn.execute(
                "SELECT category_slug, COUNT(*) AS cnt "
                "FROM ref_products GROUP BY category_slug ORDER BY cnt DESC, category_slug ASC"
            ).fetchall()
        ]
        drop_count = conn.execute(
            "SELECT COUNT(*) FROM ref_products WHERE price_trend = 'down'"
        ).fetchone()[0]
        tg_count = conn.execute(
            "SELECT COUNT(*) FROM ref_products WHERE telegram_published_count > 0"
        ).fetchone()[0]

        clauses: list[str] = []
        params: list[Any] = []
        if product_id.strip():
            clauses.append("product_id = ?")
            params.append(product_id.strip().upper())
        if category.strip():
            cat_l = category.strip().lower()
            clauses.append("(LOWER(category_slug) = ? OR LOWER(subcategory_slug) = ?)")
            params.extend([cat_l, cat_l])
        if trend.strip():
            clauses.append("LOWER(price_trend) = ?")
            params.append(trend.strip().lower())
        for token in query.lower().split():
            clauses.append("search_blob LIKE ?")
            params.append(f"%{token}%")

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total_matches = conn.execute(
            f"SELECT COUNT(*) FROM ref_products {where_sql}",
            params,
        ).fetchone()[0]

        cap = max(1, int(limit))
        rows = conn.execute(
            f"""
            SELECT * FROM ref_products
            {where_sql}
            ORDER BY (price_trend = 'down') DESC,
                     discount_pct DESC,
                     observation_count DESC,
                     observed_at_ms DESC
            LIMIT ?
            """,
            [*params, cap],
        ).fetchall()

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "overview": {
            "total_products": int(meta.get("total_products") or 0),
            "cache_generation": int(meta.get("cache_generation") or 0),
            "generated_at": meta.get("generated_at") or "",
            "price_drop_count": int(drop_count),
            "telegram_published_products": int(tg_count),
            "categories": cat_counts,
            "query_ms": elapsed_ms,
        },
        "total_matches": int(total_matches),
        "items": [_row_to_view(r) for r in rows],
    }


def load_reference_index_by_id(
    db_path: Path,
    product_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if product_ids:
            clean_ids = sorted({pid.strip().upper() for pid in product_ids if pid.strip()})
            if not clean_ids:
                return {}
            placeholders = ",".join("?" for _ in clean_ids)
            rows = conn.execute(
                f"SELECT * FROM ref_products WHERE product_id IN ({placeholders})",
                clean_ids,
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM ref_products").fetchall()
    return {row["product_id"]: _row_to_view(row) for row in rows}


def _row_product_id(row: dict[str, Any]) -> str:
    pid = str(row.get("product_id") or "").strip().upper()
    if pid:
        return pid
    for key in ("canonical_url", "url", "share_link"):
        url = str(row.get(key) or "").strip()
        if url:
            match = _MLB_RE.search(url)
            if match:
                return match.group(1).upper()
    return ""


def compare_with_store_reference(
    network_dir: Path,
    network: str,
    rows: list[dict[str, Any]],
    *,
    refresh: bool = False,
    json_override: Path | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    """Compares captured rows against the local reference DB if available."""
    if refresh:
        refresh_from_vps()
    json_path = resolve_reference_json_path(
        network, network_dir=network_dir, override=json_override
    )
    if not json_path.is_file():
        return False, []
    db_path = resolve_reference_db_path(network_dir)
    ensure_local_reference_db(json_path, db_path)
    pids = [_row_product_id(r) for r in rows if _row_product_id(r)]
    ref_by_id = load_reference_index_by_id(db_path, pids) if pids else {}
    return True, compare_products_with_reference(rows, ref_by_id)


def compare_products_with_reference(
    rows: list[dict[str, Any]],
    ref_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compares freshly captured product rows against the cached VPS reference DB."""
    comparisons: list[dict[str, Any]] = []
    for row in rows:
        pid = _row_product_id(row)
        captured_cents = price_to_cents(row.get("price"))
        title = str(row.get("title") or "")
        existing = ref_by_id.get(pid) if pid else None
        if existing is None:
            comparisons.append(
                {
                    "product_id": pid,
                    "title": title,
                    "status": "new",
                    "captured_price_cents": captured_cents,
                    "captured_price_brl": format_brl_cents(captured_cents),
                    "comparison_summary": "NOVO — ainda nao cadastrado na VPS",
                }
            )
            continue

        vps_cents = int(existing["current_price_cents"])
        if captured_cents is None or vps_cents <= 0:
            status = "unknown_price"
            delta_cents = 0
            delta_pct = 0
            summary = f"JA EXISTE na VPS ({existing['short_summary']})"
        else:
            delta_cents = captured_cents - vps_cents
            delta_pct = round((delta_cents / vps_cents) * 100)
            if delta_cents < 0:
                status = "price_drop"
                summary = (
                    f"BAIXOU {abs(delta_pct)}% ({format_brl_cents(vps_cents)} -> "
                    f"{format_brl_cents(captured_cents)}) · Mín 30d: {existing['lowest_30d_brl']}"
                )
            elif delta_cents > 0:
                status = "price_increase"
                summary = (
                    f"SUBIU +{delta_pct}% ({format_brl_cents(vps_cents)} -> "
                    f"{format_brl_cents(captured_cents)}) · Mín 30d: {existing['lowest_30d_brl']}"
                )
            else:
                status = "unchanged"
                summary = (
                    f"IGUAL a VPS ({format_brl_cents(vps_cents)} · "
                    f"{existing['observation_count']} obs · Mín 30d: {existing['lowest_30d_brl']})"
                )

        comparisons.append(
            {
                "product_id": pid,
                "title": title or existing["title"],
                "status": status,
                "captured_price_cents": captured_cents,
                "captured_price_brl": format_brl_cents(captured_cents),
                "vps_current_price_cents": vps_cents,
                "vps_current_price_brl": format_brl_cents(vps_cents),
                "delta_cents": delta_cents,
                "delta_pct": delta_pct,
                "lowest_price_30d_cents": existing["lowest_price_30d_cents"],
                "lowest_30d_brl": existing["lowest_30d_brl"],
                "average_price_30d_cents": existing["average_price_30d_cents"],
                "avg_30d_brl": existing["avg_30d_brl"],
                "observation_count": existing["observation_count"],
                "telegram_published_count": existing["telegram_published_count"],
                "telegram_last_status": existing["telegram_last_status"],
                "vps_summary": existing["short_summary"],
                "comparison_summary": summary,
            }
        )
    return comparisons
