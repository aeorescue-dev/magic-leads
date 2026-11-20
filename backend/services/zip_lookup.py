"""Resolução de ZIP para oportunidades de Chicago.

O dataset de violações não publica ZIP, mas publica latitude/longitude. Este
módulo resolve o ZIP por três caminhos, sempre com a origem registada em
`zip_source`:

1. `centroid` — ZIP mais próximo a partir de uma tabela local de centroides
   (gerada a partir dos próprios leads), com limite de distância.
2. `address` — correspondência exata do endereço normalizado nos leads 311 de
   Chicago que já têm ZIP (fallback quando não há coordenadas utilizáveis).
3. `contact` — ZIP de contacto de um alvará, apenas como último recurso.
4. `unresolved` — não foi possível; nunca se inventa um ZIP.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .db import get_connection

_CENTROIDS_PATH = Path(__file__).resolve().parents[1] / "data" / "chicago_zip_centroids.json"
_MAX_CENTROID_KM = 8.0
_CHICAGO_ZIP = re.compile(r"^60[678]\d{2}$")


def _normalize_address(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().upper()
    # Remove sufixos comuns que não fazem parte da rua.
    text = re.sub(r",?\s*(CHICAGO|IL|ILLINOIS)\s*$", "", text)
    text = re.sub(r"\s+\d{5}(?:-\d{4})?\s*$", "", text)
    return text.strip(" ,")


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def _centroids() -> dict[str, tuple[float, float]]:
    if not _CENTROIDS_PATH.exists():
        return {}
    try:
        raw = json.loads(_CENTROIDS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    out: dict[str, tuple[float, float]] = {}
    for zip_code, coords in raw.items():
        if (
            isinstance(coords, (list, tuple))
            and len(coords) == 2
            and _CHICAGO_ZIP.match(str(zip_code))
        ):
            try:
                out[str(zip_code)] = (float(coords[0]), float(coords[1]))
            except (TypeError, ValueError):
                continue
    return out


def zip_from_coordinates(lat: object, lng: object) -> tuple[Optional[str], Optional[float]]:
    """ZIP mais próximo dentro do limite; devolve (zip, distância_km)."""
    try:
        latitude = float(lat)
        longitude = float(lng)
    except (TypeError, ValueError):
        return None, None
    if not (41.0 <= latitude <= 43.0 and -88.5 <= longitude <= -87.0):
        return None, None
    best_zip = None
    best_distance = None
    for zip_code, (clat, clng) in _centroids().items():
        distance = _haversine_km(latitude, longitude, clat, clng)
        if best_distance is None or distance < best_distance:
            best_zip, best_distance = zip_code, distance
    if best_zip is None or best_distance is None or best_distance > _MAX_CENTROID_KM:
        return None, best_distance
    return best_zip, best_distance


def zip_from_address(address: object) -> Optional[str]:
    normalized = _normalize_address(address)
    if not normalized:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT zip_code, COUNT(*) AS c
            FROM leads
            WHERE city = 'Chicago'
              AND LENGTH(TRIM(COALESCE(zip_code, ''))) = 5
              AND UPPER(TRIM(address)) = ?
            GROUP BY zip_code
            ORDER BY c DESC
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    zip_code = str(row["zip_code"] or "").strip()
    return zip_code if _CHICAGO_ZIP.match(zip_code) else None


def resolve_chicago_zip(
    *,
    address: object = None,
    lat: object = None,
    lng: object = None,
    contact_zip: object = None,
) -> tuple[Optional[str], str]:
    """Devolve (zip, origem). `origem` é centroid|address|contact|unresolved."""
    by_coordinates, _ = zip_from_coordinates(lat, lng)
    if by_coordinates:
        return by_coordinates, "centroid"

    by_address = zip_from_address(address)
    if by_address:
        return by_address, "address"

    digits = re.sub(r"\D", "", str(contact_zip or ""))
    if len(digits) >= 5:
        candidate = digits[:5]
        if _CHICAGO_ZIP.match(candidate):
            return candidate, "contact"

    return None, "unresolved"
