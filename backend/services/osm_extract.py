"""OSM por extract local (Geofabrik/BBBike): a unica fonte que traz o SITE.

O Overpass esta inacessivel a partir do Railway, mas os extracts .osm.pbf sao
ficheiros estaticos: descarregamos, filtramos com pyosmium e ficamos com
empreiteiros que ja' trazem `website`. Isso **salta a Brave** (o gargalo real)
e entrega o dominio diretamente ao estagio de e-mail.

Filtro: `craft` de construcao, `office=company`, `shop=trade` e um `website`
(ou contacto equivalente). Bounding box por cidade para os extracts estaduais
(Boston usa o extract de Massachusetts).
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..utils.logger import logger
from .company_discovery import registrable_domain
from .contractor_entities import is_usable_company_name

CITY_EXTRACTS: dict[str, str] = {
    "NYC": "https://download.bbbike.org/osm/bbbike/NewYork/NewYork.osm.pbf",
    "CHICAGO": "https://download.bbbike.org/osm/bbbike/Chicago/Chicago.osm.pbf",
    "DALLAS": "https://download.bbbike.org/osm/bbbike/Dallas/Dallas.osm.pbf",
    # Boston fica de fora: nao ha extract de cidade (BBBike nao tem Boston) e o
    # extract de Massachusetts custa 311 MB + ~19 min para 15 empresas.
    # Boston continua coberto por permits e, mais tarde, por associacoes.
}

# (min_lat, max_lat, min_lon, max_lon)
CITY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "NYC": (40.49, 40.92, -74.26, -73.69),
    "CHICAGO": (41.64, 42.03, -87.94, -87.52),
    "DALLAS": (32.60, 33.02, -97.00, -96.55),
    "BOSTON": (42.20, 42.40, -71.19, -70.92),
}

CRAFT_OK = {
    "electrician", "plumber", "roofer", "painter", "hvac", "builder",
    "carpenter", "mason", "general_contractor", "glaziery", "tiler",
    "insulation", "scaffolder", "stonemason", "joiner",
}
MAX_DOWNLOAD_BYTES = 900 * 1024 * 1024


def _tags_website(tags: dict) -> str:
    return str(
        tags.get("website") or tags.get("contact:website") or tags.get("url") or ""
    ).strip()


def _tags_phone(tags: dict) -> str:
    return str(tags.get("phone") or tags.get("contact:phone") or "").strip()


def is_contractor_poi(tags: dict) -> bool:
    if not tags:
        return False
    craft = str(tags.get("craft") or "").strip().lower()
    if craft in CRAFT_OK:
        return True
    office = str(tags.get("office") or "").strip().lower()
    if office == "construction_company":
        return True
    return False


def build_entity(tags: dict, city: str) -> Optional[dict]:
    """Tag OSM -> entidade (com dominio, quando existe site)."""
    name = str(tags.get("name") or "").strip()
    if not name or not is_usable_company_name(name):
        return None
    if not is_contractor_poi(tags):
        return None
    website = _tags_website(tags)
    domain = None
    if website:
        from .company_discovery import is_blocked_domain

        candidate = registrable_domain(urlparse(website).netloc)
        if candidate and not is_blocked_domain(candidate):
            domain = candidate
    state = {"NYC": "NY", "CHICAGO": "IL", "DALLAS": "TX", "BOSTON": "MA"}.get(city)
    return {
        "legal_name": name,
        "city": city,
        "state": state,
        "role": "contractor",
        "license": None,
        "source": "osm",
        "external_id": f"osm:{name.lower()}:{city}",
        "domain": domain or None,
        "phone": _tags_phone(tags) or None,
    }


def _in_bbox(city: str, lat: float, lon: float) -> bool:
    box = CITY_BBOX.get(city)
    if not box:
        return True
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


def extract_from_pbf(
    path: str, city: str, limit: int = 1500
) -> list[dict]:
    """Le o .pbf em streaming e devolve entidades (nunca carrega tudo em RAM).

    Empresas no OSM sao mapeadas como nodes; ways/relations com tags de
    empreiteiro sao raros e ficam de fora (evita guardar locations de todos os
    nodes, que e' o que torna o parse lento).
    """
    try:
        import osmium
    except Exception:  # noqa: BLE001
        logger.warning("[OSM] pyosmium indisponivel; extract ignorado")
        return []

    out: list[dict] = []
    seen: set[str] = set()

    class _Stop(Exception):
        pass

    class _Collector(osmium.SimpleHandler):
        def node(self, node) -> None:  # noqa: N802 (API do pyosmium)
            if len(out) >= limit:
                raise _Stop
            try:
                tags = {tag.k: tag.v for tag in node.tags}
                if not is_contractor_poi(tags):
                    return
                if not _in_bbox(city, node.location.lat, node.location.lon):
                    return
                ent = build_entity(tags, city)
                if not ent:
                    return
                key = ent["legal_name"].lower()
                if key in seen:
                    return
                seen.add(key)
                out.append(ent)
            except _Stop:
                raise
            except Exception:  # noqa: BLE001
                return

    try:
        _Collector().apply_file(path)
    except _Stop:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OSM] parse falhou (%s): %s", city, exc)
    return out


async def download_extract(url: str, dest: str) -> bool:
    """Descarrega o .pbf para /tmp com limite de tamanho. False em falha."""
    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    logger.warning("[OSM] HTTP %s em %s", resp.status_code, url)
                    return False
                declared = int(resp.headers.get("content-length") or 0)
                if declared > MAX_DOWNLOAD_BYTES:
                    logger.warning("[OSM] extract demasiado grande: %s", declared)
                    return False
                size = 0
                with open(dest, "wb") as fh:
                    async for chunk in resp.aiter_bytes(1024 * 256):
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            logger.warning("[OSM] limite de download excedido")
                            return False
                        fh.write(chunk)
        logger.info("[OSM] extract %s (%s MB)", url.rsplit("/", 1)[-1], size // 1_000_000)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OSM] download falhou: %s", exc)
        return False


async def ingest_osm_city(city: str, limit: int = 1500) -> dict:
    """Descarrega, filtra e grava entidades de uma cidade. Limpa o ficheiro."""
    city = city.strip().upper()
    url = CITY_EXTRACTS.get(city)
    if not url:
        return {"city": city, "status": "unsupported"}
    from .contractor_ingest import record_entities

    tmp = os.path.join(tempfile.gettempdir(), f"osm-{city.lower()}.osm.pbf")
    try:
        if not await download_extract(url, tmp):
            return {"city": city, "status": "download_failed"}
        entities = extract_from_pbf(tmp, city, limit=limit)
        result = await record_entities(entities, max_records=limit)
        result.update({"city": city, "status": "ok", "with_domain": sum(
            1 for e in entities if e.get("domain")
        )})
        logger.info(
            "[OSM] %s: entidades=%s com_site=%s guardadas=%s",
            city, len(entities), result["with_domain"], result.get("saved"),
        )
        return result
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


async def ingest_all(limit_per_city: int = 1500) -> dict:
    out = {}
    for city in CITY_EXTRACTS:
        try:
            out[city] = await ingest_osm_city(city, limit=limit_per_city)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[OSM] %s falhou: %s", city, exc)
            out[city] = {"city": city, "status": "error"}
    return out
