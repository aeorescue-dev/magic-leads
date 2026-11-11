"""Aggregated live inventory for the public landing trade grid (P1).

Only counts are returned - no lead ids, addresses or owner data. The query
mirrors the dashboard summary: qualified leads reported in the last 7 days.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

TRADE_KEYS: tuple[str, ...] = (
    "Roof",
    "Structure",
    "Plumbing",
    "Grass",
    "Paint",
    "Permit_Rejected",
    "Heating",
    "Electrical",
    "Elevator",
    "Gas",
    "Rodent",
    "Mold",
    "Lead",
    "Unsanitary",
    "Door_Window",
    "Debris",
)

_CITY_ALIASES = {
    "new york": "NYC",
    "new-york": "NYC",
    "nyc": "NYC",
    "boston": "Boston",
    "dallas": "Dallas",
    "chicago": "Chicago",
}
_CITY_LABELS = {
    "NYC": "New York",
    "Boston": "Boston",
    "Dallas": "Dallas",
    "Chicago": "Chicago",
}

_CACHE_TTL_SECONDS = 60
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _normalize_city(city: Optional[str]) -> Optional[str]:
    if not city:
        return None
    key = " ".join(str(city).strip().lower().split())
    return _CITY_ALIASES.get(key)


def _normalize_zip(zip_code: Optional[str]) -> Optional[str]:
    if not zip_code:
        return None
    digits = "".join(ch for ch in str(zip_code) if ch.isdigit())
    if len(digits) != 5:
        raise ValueError("invalid_zip")
    return digits


def get_trade_grid(city: Optional[str] = None, zip_code: Optional[str] = None) -> dict:
    """Return aggregated counts for the P1 landing grid.

    `city` accepts the display name (New York) or the DB key (NYC).
    `zip_code` must be 5 digits and takes precedence over city.
    """
    city_key = _normalize_city(city)
    if city and not city_key:
        raise ValueError("invalid_city")
    zip_key = _normalize_zip(zip_code)

    cache_key = (city_key or "", zip_key or "")
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

    # Imported lazily to avoid a circular import at module load time.
    from .db import get_connection

    where = [
        "date_reported IS NOT NULL",
        "datetime(date_reported) >= datetime('now', '-7 days')",
        "is_qualified = 1",
        "COALESCE(is_junk, 0) = 0",
        "LOWER(COALESCE(case_status, '')) NOT IN ('closed', 'resolved', 'solved', 'archived', 'duplicated')",
    ]
    params: list = []
    if zip_key:
        where.append("zip_code = ?")
        params.append(zip_key)
    elif city_key:
        where.append("city = ? COLLATE NOCASE")
        params.append(city_key)

    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT issue_category, COUNT(*) AS n
            FROM leads
            WHERE {' AND '.join(where)}
            GROUP BY issue_category
            """,
            params,
        ).fetchall()
        trades = {key: 0 for key in TRADE_KEYS}
        for row in rows:
            key = (row["issue_category"] or "").strip()
            if key in trades:
                trades[key] = int(row["n"] or 0)

        city_rows = conn.execute(
            """
            SELECT city, COUNT(*) AS n
            FROM leads
            WHERE date_reported IS NOT NULL
              AND datetime(date_reported) >= datetime('now', '-7 days')
              AND is_qualified = 1
              AND COALESCE(is_junk, 0) = 0
              AND LOWER(COALESCE(case_status, '')) NOT IN ('closed', 'resolved', 'solved', 'archived', 'duplicated')
            GROUP BY city
            """
        ).fetchall()
    finally:
        conn.close()

    city_counts: dict[str, int] = {}
    for row in city_rows:
        label = _CITY_LABELS.get((row["city"] or "").strip())
        if label:
            city_counts[label] = city_counts.get(label, 0) + int(row["n"] or 0)
    cities = [
        {"key": label.lower().replace(" ", "-"), "label": label, "count": count}
        for label, count in sorted(city_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    payload = {
        "region": {
            "city": _CITY_LABELS.get(city_key, city_key) if city_key else None,
            "zip": zip_key,
        },
        "window_days": 7,
        "total": sum(trades.values()),
        "trades": trades,
        "cities": cities,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with _cache_lock:
        _cache[cache_key] = (now, payload)
    return payload
