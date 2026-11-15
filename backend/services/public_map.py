"""Mapa vivo público da landing: contagens agregadas e anonimizadas.

Regras de privacidade (não alterar sem revisão):
- Só contagens por zona; nunca ids, moradas, proprietários, telefones ou descrições.
- Zonas com menos de ``MIN_ZONE_COUNT`` oportunidades não são expostas (entram
  em ``other``).
- ``fresh`` só é exposto a partir de ``MIN_FRESH_COUNT``.
- Centroides de zona arredondados a 3 casas (~110 m); nunca coordenadas de lead.

A população é **exatamente a do trade grid** (``is_qualified=1``, sem lixo,
7 dias, 16 ofícios), para o total do mapa coincidir com o herói e os cartões.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

MIN_ZONE_COUNT = 5
MIN_FRESH_COUNT = 3
MAX_ZONES_PER_CITY = 60
WINDOW_DAYS = 7
CACHE_TTL_SECONDS = 60
CHICAGO_CENTROID_TTL_SECONDS = 3600

CITY_ORDER = ("NYC", "Boston", "Dallas", "Chicago")
CITY_LABELS = {
    "NYC": "New York",
    "Boston": "Boston",
    "Dallas": "Dallas",
    "Chicago": "Chicago",
}
CITY_ALIASES = {
    "new york": "NYC",
    "new-york": "NYC",
    "nyc": "NYC",
    "boston": "Boston",
    "dallas": "Dallas",
    "chicago": "Chicago",
}
_OTHER_AREAS = "Other areas"

# Boston: ZIP -> bairro oficial (espelho de neighborhoods.ts).
BOSTON_ZIP_LABELS: dict[str, str] = {
    "02105": "Other areas",
    "02108": "Beacon Hill",
    "02109": "Downtown & Waterfront",
    "02110": "Downtown & Waterfront",
    "02111": "Downtown & Waterfront",
    "02113": "Downtown & Waterfront",
    "02114": "West End",
    "02115": "Fenway",
    "02116": "Back Bay",
    "02118": "South End",
    "02119": "Roxbury",
    "02120": "Mission Hill",
    "02121": "Roxbury",
    "02122": "Dorchester",
    "02124": "Dorchester",
    "02125": "Dorchester",
    "02126": "Mattapan",
    "02127": "South Boston",
    "02128": "East Boston",
    "02129": "Charlestown",
    "02130": "Jamaica Plain",
    "02131": "Roslindale",
    "02132": "West Roxbury",
    "02134": "Allston",
    "02135": "Brighton",
    "02136": "Hyde Park",
    "02163": "Allston",
    "02199": "Back Bay",
    "02210": "Seaport",
    "02215": "Fenway",
    "02467": "Chestnut Hill",
}

# Dallas: ZIP -> setor reconhecível (espelho de neighborhoods.ts).
DALLAS_ZIP_LABELS: dict[str, str] = {
    "75201": "Downtown & Uptown",
    "75202": "Downtown & Uptown",
    "75204": "Downtown & Uptown",
    "75207": "Downtown & Uptown",
    "75226": "Downtown & Uptown",
    "75203": "Oak Cliff",
    "75208": "Oak Cliff",
    "75211": "Oak Cliff",
    "75224": "Oak Cliff",
    "75233": "Oak Cliff",
    "75236": "Oak Cliff",
    "75237": "Oak Cliff",
    "75212": "West Dallas",
    "75206": "East Dallas",
    "75214": "East Dallas",
    "75218": "East Dallas",
    "75223": "East Dallas",
    "75228": "East Dallas",
    "75246": "East Dallas",
    "75238": "Lake Highlands",
    "75243": "Lake Highlands",
    "75229": "North Dallas",
    "75230": "North Dallas",
    "75231": "North Dallas",
    "75240": "North Dallas",
    "75244": "North Dallas",
    "75248": "Far North Dallas",
    "75252": "Far North Dallas",
    "75254": "Far North Dallas",
    "75287": "Far North Dallas",
    "75205": "Oak Lawn & Park Cities",
    "75209": "Oak Lawn & Park Cities",
    "75219": "Oak Lawn & Park Cities",
    "75225": "Oak Lawn & Park Cities",
    "75210": "South Dallas",
    "75215": "South Dallas",
    "75216": "South Dallas",
    "75232": "South Dallas",
    "75241": "South Dallas",
    "75249": "South Dallas",
    "75253": "South Dallas",
    "75217": "Pleasant Grove",
    "75227": "Pleasant Grove",
    "75235": "Love Field",
    "75247": "Love Field",
}

# Chicago: community areas oficiais (fonte usa o número 1-77).
CHICAGO_COMMUNITY_AREAS: dict[str, str] = {
    "1": "Rogers Park", "2": "West Ridge", "3": "Uptown",
    "4": "Lincoln Square", "5": "North Center", "6": "Lake View",
    "7": "Lincoln Park", "8": "Near North Side", "9": "Edison Park",
    "10": "Norwood Park", "11": "Jefferson Park", "12": "Forest Glen",
    "13": "North Park", "14": "Albany Park", "15": "Portage Park",
    "16": "Irving Park", "17": "Dunning", "18": "Montclare",
    "19": "Belmont Cragin", "20": "Hermosa", "21": "Avondale",
    "22": "Logan Square", "23": "Humboldt Park", "24": "West Town",
    "25": "Austin", "26": "West Garfield Park", "27": "East Garfield Park",
    "28": "Near West Side", "29": "North Lawndale", "30": "South Lawndale",
    "31": "Lower West Side", "32": "Loop", "33": "Near South Side",
    "34": "Armour Square", "35": "Douglas", "36": "Oakland",
    "37": "Fuller Park", "38": "Grand Boulevard", "39": "Kenwood",
    "40": "Washington Park", "41": "Hyde Park", "42": "Woodlawn",
    "43": "South Shore", "44": "Chatham", "45": "Avalon Park",
    "46": "South Chicago", "47": "Burnside", "48": "Calumet Heights",
    "49": "Roseland", "50": "Pullman", "51": "South Deering",
    "52": "East Side", "53": "West Pullman", "54": "Riverdale",
    "55": "Hegewisch", "56": "Garfield Ridge", "57": "Archer Heights",
    "58": "Brighton Park", "59": "McKinley Park", "60": "Bridgeport",
    "61": "New City", "62": "West Elsdon", "63": "Gage Park",
    "64": "Clearing", "65": "West Lawn", "66": "Chicago Lawn",
    "67": "West Englewood", "68": "Englewood", "69": "Greater Grand Crossing",
    "70": "Ashburn", "71": "Auburn Gresham", "72": "Beverly",
    "73": "Washington Heights", "74": "Mount Greenwood", "75": "Morgan Park",
    "76": "O'Hare", "77": "Edgewater",
}

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_ZIP_CENTROIDS: dict[str, dict[str, tuple[float, float]]] = {}


def _load_zip_centroids() -> None:
    global _ZIP_CENTROIDS
    try:
        raw = json.loads(
            (_DATA_DIR / "zip_centroids.json").read_text("utf-8-sig")
        )
    except Exception:
        _ZIP_CENTROIDS = {}
        return
    _ZIP_CENTROIDS = {
        city: {
            str(zip_code): (float(pair[0]), float(pair[1]))
            for zip_code, pair in entries.items()
        }
        for city, entries in raw.items()
    }


_load_zip_centroids()

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CHICAGO_CENTROIDS: tuple[float, dict[str, tuple[float, float]]] | None = None
_CONN: Optional[sqlite3.Connection] = None
_CONN_PATH: Optional[str] = None


def _connection() -> sqlite3.Connection:
    """Ligação de leitura persistente (o cálculo corre no máximo 1x/min)."""
    global _CONN, _CONN_PATH
    from .db import DB_PATH

    if _CONN is not None and _CONN_PATH == DB_PATH:
        return _CONN
    if _CONN is not None:
        try:
            _CONN.close()
        except Exception:
            pass
    conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000;")
    _CONN = conn
    _CONN_PATH = DB_PATH
    return conn


def _reset_connection() -> None:
    global _CONN
    if _CONN is not None:
        try:
            _CONN.close()
        except Exception:
            pass
    _CONN = None


def reset_cache() -> None:
    """Limpa caches (testes)."""
    global _CHICAGO_CENTROIDS
    with _CACHE_LOCK:
        _CACHE.clear()
    _CHICAGO_CENTROIDS = None
    _reset_connection()


def _title_case(value: str) -> str:
    return " ".join(part[:1].upper() + part[1:].lower() for part in value.split())


def _nyc_borough(zip_code: str) -> str:
    prefix = zip_code[:3]
    if prefix in {"100", "101", "102"}:
        return "Manhattan"
    if prefix == "103":
        return "Staten Island"
    if prefix == "104":
        return "Bronx"
    if prefix == "112":
        return "Brooklyn"
    if prefix in {"110", "111", "113", "114", "116"}:
        return "Queens"
    return _OTHER_AREAS


def _zone_label(city: str, kind: str, key: str) -> str:
    if kind == "none":
        return _OTHER_AREAS
    if city == "NYC":
        if kind == "nb":
            return _title_case(key)
        return _nyc_borough(key)
    if city == "Boston":
        if kind == "nb":
            return key
        return BOSTON_ZIP_LABELS.get(key, _OTHER_AREAS)
    if city == "Dallas":
        if kind == "nb":
            return key
        return DALLAS_ZIP_LABELS.get(key, _OTHER_AREAS)
    # Chicago: community area quando existe; senão área por ZIP (ZIP é
    # geografia pública e a landing já permite pesquisa por ZIP; nunca há
    # morada nem coordenada de lead).
    if kind == "nb":
        return CHICAGO_COMMUNITY_AREAS.get(key.strip(), key)
    return f"Area {key}"


def _load_chicago_centroids() -> dict[str, tuple[float, float]]:
    global _CHICAGO_CENTROIDS
    now = time.monotonic()
    if _CHICAGO_CENTROIDS and now - _CHICAGO_CENTROIDS[0] < CHICAGO_CENTROID_TTL_SECONDS:
        return _CHICAGO_CENTROIDS[1]
    conn = _connection()
    try:
        rows = conn.execute(
            "SELECT SUBSTR(TRIM(zip_code), 1, 5) AS zip, AVG(lat) AS lat, "
            "AVG(lng) AS lng FROM leads "
            "WHERE city = 'Chicago' COLLATE NOCASE "
            "AND lat IS NOT NULL AND lng IS NOT NULL "
            "AND LENGTH(TRIM(zip_code)) >= 5 GROUP BY zip"
        ).fetchall()
    except Exception:
        _reset_connection()
        raise
    centroids = {
        str(row["zip"]): (float(row["lat"]), float(row["lng"]))
        for row in rows
        if row["lat"] is not None and row["lng"] is not None
    }
    _CHICAGO_CENTROIDS = (now, centroids)
    return centroids


def _compute() -> dict:
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    trades = ",".join("?" * len(TRADE_KEYS))
    city_placeholders = ",".join("?" * len(CITY_ORDER))
    conn = _connection()
    try:
        # O planner prefere um índice antigo (is_qualified, city, issue_category)
        # que obriga a lookups; forçamos o índice parcial covering quando existe.
        # Se tivermos de recriar o índice (arranque), o fallback continua correto.
        has_public_index = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='idx_leads_public_geo'"
            ).fetchone()
            is not None
        )
        hint = " INDEXED BY idx_leads_public_geo" if has_public_index else ""
        sql = f"""
            SELECT UPPER(TRIM(l.city)) AS city_key,
                   CASE
                     WHEN TRIM(COALESCE(l.neighborhood, '')) <> '' THEN 'nb'
                     WHEN LENGTH(TRIM(COALESCE(l.zip_code, ''))) >= 5 THEN 'zip'
                     ELSE 'none'
                   END AS kind,
                   CASE
                     WHEN TRIM(COALESCE(l.neighborhood, '')) <> '' THEN TRIM(l.neighborhood)
                     WHEN LENGTH(TRIM(COALESCE(l.zip_code, ''))) >= 5
                       THEN SUBSTR(TRIM(l.zip_code), 1, 5)
                     ELSE ''
                   END AS key,
                   COUNT(*) AS n,
                   SUM(CASE WHEN datetime(l.created_at) >= datetime('now','-24 hours')
                            THEN 1 ELSE 0 END) AS fresh,
                   AVG(l.lat) AS lat,
                   AVG(l.lng) AS lng
              FROM leads l{hint}
             WHERE l.date_reported IS NOT NULL
               AND l.date_reported >= ?
               AND datetime(l.date_reported) >= datetime('now', ?)
               AND l.is_qualified = 1
               AND COALESCE(l.is_junk, 0) = 0
               AND LOWER(COALESCE(l.case_status, '')) NOT IN
                   ('closed','resolved','solved','archived','duplicated')
               AND l.issue_category IN ({trades})
               AND l.city COLLATE NOCASE IN ({city_placeholders})
             GROUP BY city_key, kind, key
        """
        params = [
            cutoff,
            f"-{WINDOW_DAYS} days",
            *TRADE_KEYS,
            *CITY_ORDER,
        ]
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        # Ligação persistente inválida (restore/rotação): reabre no próximo cálculo.
        _reset_connection()
        raise

    chicago_centroids = _load_chicago_centroids()
    grouped: dict[str, dict[str, dict]] = {
        city: {} for city in CITY_ORDER
    }
    totals: dict[str, dict[str, int]] = {
        city: {"count": 0, "fresh": 0} for city in CITY_ORDER
    }

    for row in rows:
        city_key = str(row["city_key"] or "").strip().upper()
        city = CITY_ALIASES.get(city_key.lower())
        if city is None:
            continue
        kind = str(row["kind"] or "none")
        key = str(row["key"] or "")
        label = _zone_label(city, kind, key)
        count = int(row["n"] or 0)
        fresh = int(row["fresh"] or 0)
        totals[city]["count"] += count
        totals[city]["fresh"] += fresh

        lat = row["lat"]
        lng = row["lng"]
        if lat is None or lng is None:
            fallback = _ZIP_CENTROIDS.get(city, {}).get(key)
            if fallback is None and city == "Chicago" and kind == "zip":
                fallback = chicago_centroids.get(key)
            if fallback is not None:
                lat, lng = fallback

        zone = grouped[city].get(label)
        if zone is None:
            zone = {"count": 0, "fresh": 0, "lat": 0.0, "lng": 0.0, "weight": 0}
            grouped[city][label] = zone
        zone["count"] += count
        zone["fresh"] += fresh
        if lat is not None and lng is not None:
            zone["lat"] += float(lat) * count
            zone["lng"] += float(lng) * count
            zone["weight"] += count

    cities_payload = []
    for city in CITY_ORDER:
        entries = []
        for label, zone in grouped[city].items():
            if zone["weight"] > 0:
                lat = round(zone["lat"] / zone["weight"], 3)
                lng = round(zone["lng"] / zone["weight"], 3)
            else:
                lat = None
                lng = None
            entries.append(
                {
                    "slug": re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"),
                    "label": label,
                    "count": zone["count"],
                    "fresh": zone["fresh"],
                    "lat": lat,
                    "lng": lng,
                }
            )
        entries.sort(key=lambda item: (-item["count"], item["label"]))
        visible = [
            {
                **entry,
                "fresh": entry["fresh"] if entry["fresh"] >= MIN_FRESH_COUNT else 0,
            }
            for entry in entries
            if entry["count"] >= MIN_ZONE_COUNT and entry["label"] != _OTHER_AREAS
        ][:MAX_ZONES_PER_CITY]
        city_total = totals[city]["count"]
        cities_payload.append(
            {
                "key": city.lower(),
                "label": CITY_LABELS[city],
                "totals": {
                    "count": city_total,
                    "fresh": totals[city]["fresh"],
                    "zones": len(visible),
                    "other": max(0, city_total - sum(item["count"] for item in visible)),
                },
                "zones": visible,
            }
        )

    return {
        "generated_at": now.isoformat(),
        "window_days": WINDOW_DAYS,
        "cities": cities_payload,
    }


def _is_fresh(entry: tuple[float, dict] | None) -> bool:
    return bool(entry) and (time.monotonic() - entry[0]) < CACHE_TTL_SECONDS


def get_live_map() -> dict:
    """Payload agregado, servido de cache de 60 s.

    Se o cache expirou e outro pedido já está a recalcular, devolve a versão
    anterior (stale-while-revalidate) em vez de bloquear.
    """
    cached = _CACHE.get("all")
    if _is_fresh(cached):
        return cached[1]

    if not _CACHE_LOCK.acquire(blocking=False):
        if cached is not None:
            return cached[1]
        _CACHE_LOCK.acquire()
    try:
        cached = _CACHE.get("all")
        if _is_fresh(cached):
            return cached[1]
        payload = _compute()
        _CACHE["all"] = (time.monotonic(), payload)
        return payload
    finally:
        _CACHE_LOCK.release()


def prewarm() -> dict:
    """Calcula e guarda o payload (arranque), ignorando TTL."""
    with _CACHE_LOCK:
        payload = _compute()
        _CACHE["all"] = (time.monotonic(), payload)
        return payload


def normalize_city(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return CITY_ALIASES.get(" ".join(str(value).strip().lower().split()))
