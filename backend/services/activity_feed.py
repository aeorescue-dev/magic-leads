"""Recent, privacy-safe opportunity activity for the public landing ticker.

Returns only trade, city, neighborhood/place, ZIP and relative time. Never
returns owner names, phones, street addresses or lead ids.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

CITY_LABELS = {
    "NYC": "New York",
    "Boston": "Boston",
    "Dallas": "Dallas",
    "Chicago": "Chicago",
}
_CITY_ALIASES = {
    "new york": "NYC",
    "new-york": "NYC",
    "nyc": "NYC",
    "boston": "Boston",
    "dallas": "Dallas",
    "chicago": "Chicago",
}
_CACHE_TTL_SECONDS = 30
_cache: dict[tuple[str, int], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _parse_ts(value: object) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_city(city: Optional[str]) -> Optional[str]:
    if not city:
        return None
    key = " ".join(str(city).strip().lower().split())
    return _CITY_ALIASES.get(key)


def get_activity(city: Optional[str] = None, limit: int = 8) -> dict:
    city_key = _normalize_city(city)
    if city and not city_key:
        raise ValueError("invalid_city")
    limit = max(1, min(int(limit), 12))

    cache_key = (city_key or "", limit)
    now_mono = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now_mono - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

    from .db import get_connection

    city_keys = [city_key] if city_key else list(CITY_LABELS.keys())
    now = datetime.now(timezone.utc)
    by_city: dict[str, list[dict]] = {}

    conn = get_connection()
    try:
        for key in city_keys:
            rows = conn.execute(
                """
                SELECT city, neighborhood, zip_code, issue_category,
                       created_at, updated_at
                FROM leads
                WHERE city = ? COLLATE NOCASE
                  AND created_at IS NOT NULL
                  AND datetime(created_at) >= datetime('now', '-7 days')
                  AND is_qualified = 1
                  AND COALESCE(is_junk, 0) = 0
                  AND LOWER(COALESCE(case_status, '')) NOT IN ('closed', 'resolved', 'solved', 'archived', 'duplicated')
                ORDER BY created_at DESC
                LIMIT 18
                """,
                (key,),
            ).fetchall()

            seen: set[tuple[str, str]] = set()
            per_city: list[dict] = []
            for row in rows:
                created = _parse_ts(row["created_at"])
                updated = _parse_ts(row["updated_at"])
                if not created:
                    continue
                captured_recently = (now - created).total_seconds() <= 48 * 3600
                refreshed_recently = (
                    updated is not None
                    and (now - updated).total_seconds() <= 24 * 3600
                    and (updated - created).total_seconds() > 3600
                )
                if captured_recently:
                    action = "captured"
                    occurred = created
                elif refreshed_recently:
                    action = "updated"
                    occurred = updated
                else:
                    continue

                trade = (row["issue_category"] or "").strip()
                if not trade:
                    continue
                neighborhood = (row["neighborhood"] or "").strip()
                place = (
                    neighborhood.title()
                    if neighborhood and neighborhood.upper() not in {"UNKNOWN", "N/A", "NONE"}
                    else CITY_LABELS[key]
                )
                dedupe_key = (trade, place)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                zip_code = (row["zip_code"] or "").strip()
                minutes_ago = max(0, int((now - occurred).total_seconds() // 60))
                per_city.append(
                    {
                        "trade": trade,
                        "city": CITY_LABELS[key],
                        "place": place,
                        "zip": zip_code if len(zip_code) == 5 and zip_code.isdigit() else None,
                        "action": action,
                        "minutes_ago": minutes_ago,
                        "occurred_at": occurred.isoformat(),
                    }
                )
            by_city[key] = per_city[:4]

        # Interleave the four operating cities so the ticker rotates across
        # all of them instead of being dominated by the busiest city.
        ordered: list[dict] = []
        max_len = max((len(bucket) for bucket in by_city.values()), default=0)
        for index in range(max_len):
            for key in city_keys:
                bucket = by_city.get(key, [])
                if index < len(bucket):
                    ordered.append(bucket[index])

        payload = {
            "city": CITY_LABELS.get(city_key) if city_key else None,
            "events": ordered[:limit],
            "generated_at": now.isoformat(),
        }
    finally:
        conn.close()

    with _cache_lock:
        _cache[cache_key] = (now_mono, payload)
    return payload
