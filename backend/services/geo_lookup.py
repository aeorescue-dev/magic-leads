"""Geolocalizacao gratuita de imoveis de NYC via BBL -> PLUTO (B3).

O dataset de DOB Violations (`3h2n-5cm9`) publica `boro`, `block`, `lot` e
`bin`, mas **nao** coordenadas. O PLUTO (`64uk-42ks`) mapeia BBL ->
`latitude`/`longitude`. Compor o BBL a partir de boro+block+lot e' deterministico
e a resolucao cabe num punhado de chamadas: zero custo, 100% dados abertos.

Regras:
- cache local permanente em `bbl_coords` (hit e miss), para nao repetir queries;
- miss fica em cache 30 dias (o imovel pode entrar no PLUTO depois);
- nunca inventa coordenadas: sem BBL valido, o lead fica sem distancia.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from ..utils.logger import logger
from .db import db_service

PLUTO_DOMAIN = "data.cityofnewyork.us"
PLUTO_DATASET = "64uk-42ks"
BATCH_SIZE = 200
MISS_TTL_DAYS = 30

# Boro numerico e as variantes alfabeticas que a DOB usa nos registos antigos.
_BORO_CODES = {
    "1": "1", "2": "2", "3": "3", "4": "4", "5": "5",
    "M": "1", "X": "2", "B": "3", "Q": "4", "S": "5", "R": "5",
}


def compose_bbl(boro: str | None, block: str | None, lot: str | None) -> str | None:
    """Monta o BBL de 10 digitos (boro + block 5 + lot 4).

    Devolve None quando algum componente falta ou nao e' numerico — melhor sem
    distancia do que com uma coordenada de outro imovel.
    """
    code = _BORO_CODES.get(str(boro or "").strip().upper())
    if not code:
        return None
    blk = "".join(ch for ch in str(block or "") if ch.isdigit())
    lt = "".join(ch for ch in str(lot or "") if ch.isdigit())
    if not blk or not lt:
        return None
    try:
        return f"{code}{int(blk):05d}{int(lt):04d}"
    except ValueError:
        return None


def _normalize_bbl(raw: object) -> str | None:
    """Normaliza o BBL do PLUTO.

    O PLUTO devolve o campo como numero formatado (`3074130059.00000000`).
    Sem normalizar, a chave nao casava com o BBL de 10 digitos que compomos e
    todos os leads ficavam sem distancia.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return f"{int(float(text)):010d}"
    except (TypeError, ValueError):
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits.zfill(10) if digits else None


def _is_stale(ts: str | None, days: int) -> bool:
    if not ts:
        return True
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - parsed > timedelta(days=days)


async def _fetch_from_pluto(bbls: Iterable[str]) -> dict[str, tuple[float, float]]:
    """Consulta o PLUTO em lotes e devolve {bbl: (lat, lng)}.

    Uma falha de rede num lote nao aborta os restantes: os leads desse lote
    ficam sem distancia e serao tentados de novo mais tarde.
    """
    from ..scrapers.socrata_311 import socrata_scraper

    unique = list(dict.fromkeys(b for b in bbls if b))
    out: dict[str, tuple[float, float]] = {}
    for start in range(0, len(unique), BATCH_SIZE):
        chunk = unique[start:start + BATCH_SIZE]
        where = "bbl in(" + ",".join(f"'{b}'" for b in chunk) + ")"
        try:
            rows = await socrata_scraper._fetch_all_pages(
                domain=PLUTO_DOMAIN,
                dataset=PLUTO_DATASET,
                select="bbl,latitude,longitude",
                where=where,
                order="bbl",
                page_size=1000,
                max_pages=1,
            )
        except Exception as e:  # rede/limite: nao perder o resto
            logger.warning("[GEO] PLUTO falhou no lote %s-%s: %s", start, start + len(chunk), e)
            continue
        for row in rows or []:
            bbl = _normalize_bbl(row.get("bbl"))
            if not bbl:
                continue
            try:
                lat = float(row.get("latitude"))
                lng = float(row.get("longitude"))
            except (TypeError, ValueError):
                continue
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
                continue
            if lat == 0.0 and lng == 0.0:  # placeholders do PLUTO
                continue
            out[bbl] = (lat, lng)
    return out


async def resolve_bbl_coords(
    bbls: Iterable[str], *, allow_network: bool = True, force: bool = False
) -> dict[str, tuple[float, float]]:
    """Resolve BBLs para coordenadas usando cache local + PLUTO."""
    unique = sorted({str(b).strip() for b in bbls if str(b or "").strip()})
    if not unique:
        return {}

    cached = await db_service.get_bbl_coords(unique)
    out: dict[str, tuple[float, float]] = {}
    missing: list[str] = []
    for bbl in unique:
        row = cached.get(bbl)
        if row:
            lat, lng = row.get("lat"), row.get("lng")
            if lat is not None and lng is not None:
                out[bbl] = (float(lat), float(lng))
                continue
            if not force and not _is_stale(row.get("updated_at"), MISS_TTL_DAYS):
                continue
        missing.append(bbl)

    if not missing or not allow_network:
        return out

    fetched = await _fetch_from_pluto(missing)
    upserts: list[dict] = []
    for bbl in missing:
        coord = fetched.get(bbl)
        if coord:
            out[bbl] = coord
            upserts.append({"bbl": bbl, "lat": coord[0], "lng": coord[1], "source": "pluto"})
        else:
            upserts.append({"bbl": bbl, "lat": None, "lng": None, "source": "pluto_miss"})
    if upserts:
        await db_service.upsert_bbl_coords(upserts)
    logger.info(
        "[GEO] BBL: %s pedido(s), %s em cache, %s resolvido(s) no PLUTO",
        len(unique), len(unique) - len(missing), len(fetched),
    )
    return out


DOB_VIOLATIONS_DATASET = "3h2n-5cm9"
DOB_BATCH_SIZE = 150


async def backfill_dob_bbl_from_source(batch: int = 150, max_batches: int = 40) -> dict:
    """Recupera o BBL dos leads DOB antigos a partir do dataset de origem.

    Os leads de DOB Violations foram gravados antes de o scraper pedir
    `block`/`lot`, por isso `leads.bbl` esta a NULL nos 6.101 existentes. Sem
    este passo, o PLUTO nao tinha chave para procurar. Consulta por
    `violation_number` (o `external_id` do lead), em lotes.
    """
    from ..scrapers.socrata_311 import socrata_scraper

    total = 0
    filled = 0
    after_id = 0
    for _ in range(max(1, int(max_batches))):
        rows = await db_service.get_dob_leads_missing_bbl(batch, after_id)
        if not rows:
            break
        total += len(rows)
        after_id = int(rows[-1]["id"])
        by_external: dict[str, int] = {}
        for r in rows:
            ext = str(r.get("external_id") or "").strip()
            if ext:
                by_external[ext] = int(r["id"])
        if not by_external:
            continue
        chunk = list(by_external.keys())
        where = "violation_number in(" + ",".join(
            "'" + v.replace("'", "''") + "'" for v in chunk
        ) + ")"
        try:
            fetched = await socrata_scraper._fetch_all_pages(
                domain=PLUTO_DOMAIN,
                dataset=DOB_VIOLATIONS_DATASET,
                select="violation_number,ecb_number,boro,block,lot",
                where=where,
                order="issue_date DESC",
                page_size=1000,
                max_pages=1,
            )
        except Exception as e:
            logger.warning("[GEO] DOB origem falhou no lote: %s", e)
            continue
        updates: list[tuple] = []
        seen: set[int] = set()
        for row in fetched or []:
            bbl = compose_bbl(row.get("boro"), row.get("block"), row.get("lot"))
            if not bbl:
                continue
            for key in (row.get("violation_number"), row.get("ecb_number")):
                ext = str(key or "").strip()
                lead_id = by_external.get(ext)
                if lead_id and lead_id not in seen:
                    updates.append((bbl, lead_id))
                    seen.add(lead_id)
        if updates:
            await db_service.set_leads_bbl(updates)
            filled += len(updates)
    return {"candidates": total, "bbl_filled": filled}


async def backfill_missing_coords(batch: int = 500, max_batches: int = 40) -> dict:
    """Preenche lat/lng dos leads com BBL e sem coordenadas (idempotente).

    `max_batches` limita o trabalho por chamada para nao bloquear o event loop
    num endpoint HTTP; correr de novo continua de onde parou.
    """
    total_candidates = 0
    total_resolved = 0
    after_id = 0
    for _ in range(max(1, int(max_batches))):
        rows = await db_service.get_leads_missing_coords_with_bbl(batch, after_id)
        if not rows:
            break
        total_candidates += len(rows)
        after_id = int(rows[-1]["id"])
        coords = await resolve_bbl_coords([r["bbl"] for r in rows])
        updates = []
        for r in rows:
            coord = coords.get(str(r["bbl"]))
            if coord:
                updates.append((coord[0], coord[1], r["id"]))
        if updates:
            await db_service.set_leads_coords(updates)
            total_resolved += len(updates)
    return {
        "candidates": total_candidates,
        "resolved": total_resolved,
        "missing": max(0, total_candidates - total_resolved),
    }
