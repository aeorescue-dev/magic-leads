"""Ingestao de licencas publicas de empreiteiros (dados de governo, $0 de API).

Primeira fonte: NYC DCWP `Issued Licenses` (Socrata w7w3-xahh), categoria
`Home Improvement Contractor`, apenas `Active` e `Premises` (empresa, nao o
individuo qualificador). Traz `contact_phone`, que o `corroborate()` usa como
sinal mais forte para aceitar um dominio — a licenca aumenta a pool E melhora
a precisao do enriquecimento.

O dataset muda devagar: corre semanalmente e e' idempotente (dedupe por
licenca/nome). Nunca levanta: devolve contagens e loga.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Optional

from ..utils.logger import logger
from . import self_healing
from .contractor_entities import is_usable_company_name
from .contractor_ingest import record_entities
from .resilient_fetch import ResilientFetcher

# Ultimo estado de fetch por fonte: usado para gravar `ingestion_runs` com
# success/partial/failed em vez de mascarar dados parciais como sucesso.
_FETCH_STATUS: dict[str, str] = {}

NYC_DCWP_URL = "https://data.cityofnewyork.us/resource/w7w3-xahh.json"
NYC_LICENSE_SOURCE = "nyc_dcwp"
NYC_SELECT = (
    "business_name,dba_trade_name,license_nbr,contact_phone,"
    "address_city,address_state,address_zip,license_creation_date"
)
NYC_WHERE = (
    "business_category='Home Improvement Contractor' "
    "AND license_status='Active' AND license_type='Premises'"
)
MAX_ROWS = 20000

# NYC DOB License Info (Socrata t8hj-ruu2): a única fonte pública que diz o
# ofício da empresa (MASTER PLUMBER, ELECTRICAL FIRM, ELEVATOR AGENCY, ...).
NYC_DOB_URL = "https://data.cityofnewyork.us/resource/t8hj-ruu2.json"
NYC_DOB_SOURCE = "nyc_dob_licenses"
NYC_DOB_SELECT = (
    "business_name,business_phone_number,license_business_city,"
    "business_state,license_number,license_type,license_status"
)
NYC_DOB_LICENSE_TRADES: dict[str, str] = {
    "MASTER PLUMBER": "plumbing",
    "ELECTRICAL FIRM": "electrical",
    "ELECTRICAL CONTRACTOR": "electrical",
    "ELEVATOR AGENCY / INSPECTOR": "elevator",
    "OIL BURNER INSTALLER": "hvac",
    "SIGN HANGER": "signage",
}
NYC_DOB_WHERE = (
    "license_status='ACTIVE' AND business_phone_number IS NOT NULL "
    "AND license_type IN ("
    + ",".join(f"'{name}'" for name in NYC_DOB_LICENSE_TRADES)
    + ")"
)

# DSNY/BIC Trade Waste Hauler Licensees (Socrata 867j-5pgi): telefone e
# licença. O dataset tem centenas de milhares de linhas históricas; só
# interessam licenças com expiration_date futura.
DSNY_TRADE_WASTE_URL = "https://data.cityofnewyork.us/resource/867j-5pgi.json"
DSNY_TRADE_WASTE_SOURCE = "dsny_trade_waste"
DSNY_TRADE_WASTE_SELECT = (
    "bic_number,account_name,trade_name,address,city,state,postcode,phone,"
    "application_type,effective_date,expiration_date"
)
NYC_BOROUGHS = (
    "NEW YORK",
    "BROOKLYN",
    "QUEENS",
    "BRONX",
    "STATEN ISLAND",
    "MANHATTAN",
    "NYC",
)

# Texas TDLR: ficheiros CSV publicos, atualizados diariamente. Nao ha
# licenciamento estadual de canalizadores (e' outro board), por isso entram
# A/C, eletricistas, sign e elevadores.
TDLR_BASE = "https://www.tdlr.texas.gov/dbproduction2/"
TDLR_FILES: dict[str, str] = {
    "ac_contractors": "ltairref.csv",
    "electrical_contractors": "Lteecele.csv",
    "electrical_sign_contractors": "Ltescele.csv",
    "elevator_contractors": "ltelectr.csv",
}
TDLR_TRADE: dict[str, str] = {
    "ac_contractors": "hvac",
    "electrical_contractors": "electrical",
    "electrical_sign_contractors": "signage",
    "elevator_contractors": "elevator",
}
# Metro Dallas (entity city = DALLAS para a esteira de NYC/CHI/BOS/DAL).
DFW_CITIES = {
    "DALLAS", "IRVING", "GARLAND", "MESQUITE", "CARROLLTON", "RICHARDSON",
    "PLANO", "ADDISON", "FARMERS BRANCH", "GRAND PRAIRIE", "DESOTO",
    "DUNCANVILLE", "LEWISVILLE", "COPPELL", "FLOWER MOUND", "CEDAR HILL",
    "LANCASTER", "BALCH SPRINGS", "ROWLETT", "SACHSE", "WYLIE", "ALLEN",
    "FRISCO", "MCKINNEY", "DENTON", "ARLINGTON", "EULESS", "BEDFORD",
    "HURST", "GRAPEVINE", "KELLER", "SOUTHLAKE", "NORTH RICHLAND HILLS",
    "MANSFIELD", "MIDLOTHIAN", "WAXAHACHIE", "FORNEY", "ROCKWALL",
}
DALLAS_CITY_RE = re.compile(r"^(.*?)[,\s]+TX[,\s]+(\d{5})", re.IGNORECASE)

# Illinois IDFPR (data.illinois.gov pzzh-kp68): unica base estadual com
# contractor de construcao - ROOFING CONTRACTOR (Chicago: ~1.265 ativos).
IL_LICENSE_URL = "https://data.illinois.gov/resource/pzzh-kp68.json"
IL_ROOFING_WHERE = (
    "license_type='ROOFING CONTRACTOR' AND license_status='ACTIVE' "
    "AND city='CHICAGO'"
)
# Chicago Business Licenses (uupf-x98q): poucos contractors de oficio (a
# licenca de canalizador/eletricista e' estadual), mas os de construcao geral
# valem a pena e sao gratuitos.
CHI_LICENSE_URL = "https://data.cityofchicago.org/resource/uupf-x98q.json"
CHI_WHERE = (
    "license_status='AAI' AND ("
    "upper(business_activity) like '%CONSTRUCTION%' OR "
    "upper(business_activity) like '%CONTRACT%' OR "
    "upper(business_activity) like '%ELECTRIC%')"
)




def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _phone(value: object) -> Optional[str]:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def extract_nyc_licenses(rows: Iterable[dict]) -> list[dict]:
    """Linhas do DCWP -> entidades de contractor (puro, testavel)."""
    out: list[dict] = []
    for row in rows or []:
        name = _clean(row.get("business_name"))
        license_no = _clean(row.get("license_nbr"))
        if not name or not license_no or not is_usable_company_name(name):
            continue
        rec = {
            "legal_name": name,
            "city": "NYC",
            "state": "NY",
            "role": "contractor",
            "license": license_no,
            "source": NYC_LICENSE_SOURCE,
            "external_id": license_no,
            "phone": _phone(row.get("contact_phone")),
        }
        out.append(rec)
    return out


def _mark_fetch(source: str, status: str) -> None:
    previous = _FETCH_STATUS.get(source)
    if previous == "failed":
        return
    if previous == "partial" and status != "failed":
        return
    _FETCH_STATUS[source] = status


def _record_ingest(
    source: str, rows: int, records: int, result: dict, started: str
) -> None:
    status = _FETCH_STATUS.get(source, "success")
    self_healing.record_ingestion_run(
        source,
        status,
        rows_fetched=rows,
        rows_parsed=records,
        rows_upserted=int(result.get("saved") or 0),
        error_code=None if status == "success" else "partial_fetch",
        error_detail=None if status == "success" else f"fetch status={status}",
        started_at=started,
    )


async def fetch_nyc_licenses(limit: int = 5000) -> list[dict]:
    """Licencas ativas (paginado) direto do Socrata, sem chave.

    Pagina com `$offset` ate' esgotar ou atingir `limit`: sem isto, duas
    execucoes seguidas traziam sempre as mesmas 4.000 primeiras linhas.
    """
    limit = max(1, min(int(limit), MAX_ROWS))
    page = 5000
    out: list[dict] = []
    offset = 0
    fetcher = ResilientFetcher(NYC_LICENSE_SOURCE)
    _FETCH_STATUS.pop(NYC_LICENSE_SOURCE, None)
    while len(out) < limit:
        params = {
            "$select": NYC_SELECT,
            "$where": NYC_WHERE,
            "$order": "license_creation_date DESC",
            "$limit": str(min(page, limit - len(out))),
            "$offset": str(offset),
        }
        result = await fetcher.get_json(NYC_DCWP_URL, params=params)
        if not result.ok:
            logger.warning(
                "[LICENSES] NYC HTTP %s (%s)",
                result.http_status,
                result.error_class,
            )
            _mark_fetch(NYC_LICENSE_SOURCE, "partial" if out else "failed")
            break
        data = result.data
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < page:
            break
        offset += len(data)
    _mark_fetch(NYC_LICENSE_SOURCE, "success")
    return out


def extract_nyc_dob_licenses(rows: Iterable[dict]) -> list[dict]:
    """Linhas do DOB License Info -> entidades com trade explícito (puro)."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        if _clean(row.get("license_status")).upper() != "ACTIVE":
            continue
        name = _clean(row.get("business_name"))
        license_no = _clean(row.get("license_number"))
        license_type = " ".join(
            _clean(row.get("license_type")).upper().split()
        )
        trade = NYC_DOB_LICENSE_TRADES.get(license_type)
        phone = _phone(row.get("business_phone_number"))
        if (
            not name
            or not license_no
            or not phone
            or not trade
            or not is_usable_company_name(name)
        ):
            continue
        key = f"{license_type}:{license_no}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "legal_name": name,
                # Manter NYC canónico: Brooklyn/Queens/etc. não são cidades
                # separadas para a campanha de voz.
                "city": "NYC",
                "state": "NY",
                "role": "contractor",
                "license": key,
                "source": NYC_DOB_SOURCE,
                "external_id": key,
                "phone": phone,
                "niche_key": trade,
            }
        )
    return out


async def fetch_nyc_dob_licenses(limit: int = 5000) -> list[dict]:
    """Licenças DOB ativas com telefone, paginadas (sem chave)."""
    limit = max(1, min(int(limit), MAX_ROWS))
    page = 5000
    out: list[dict] = []
    offset = 0
    source = "nyc_dob_licenses"
    fetcher = ResilientFetcher(source)
    _FETCH_STATUS.pop(source, None)
    while len(out) < limit:
        params = {
            "$select": NYC_DOB_SELECT,
            "$where": NYC_DOB_WHERE,
            "$order": "license_number DESC",
            "$limit": str(min(page, limit - len(out))),
            "$offset": str(offset),
        }
        result = await fetcher.get_json(NYC_DOB_URL, params=params)
        if not result.ok:
            logger.warning(
                "[LICENSES] DOB HTTP %s (%s)",
                result.http_status,
                result.error_class,
            )
            _mark_fetch(source, "partial" if out else "failed")
            break
        data = result.data
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < page:
            break
        offset += len(data)
    _mark_fetch(source, "success")
    return out


async def ingest_nyc_dob_licenses(limit: int = 5000) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    rows = await fetch_nyc_dob_licenses(limit)
    records = extract_nyc_dob_licenses(rows)
    result = await record_entities(records, max_records=max(limit, len(records)))
    result["fetched"] = len(rows)
    result["extracted"] = len(records)
    _record_ingest("nyc_dob_licenses", len(rows), len(records), result, started)
    logger.info(
        "[LICENSES] DOB: fetched=%s extraidas=%s guardadas=%s",
        len(rows),
        len(records),
        result.get("saved"),
    )
    return result


def extract_dsny_trade_waste(rows: Iterable[dict]) -> list[dict]:
    """Licenças DSNY/BIC ativas -> entidades de debris removal (puro)."""
    today = datetime.now(timezone.utc).date().isoformat()
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        expiration = _clean(row.get("expiration_date"))[:10]
        if not expiration or expiration < today:
            continue
        name = _clean(row.get("account_name") or row.get("trade_name"))
        phone = _phone(row.get("phone"))
        bic = _clean(row.get("bic_number"))
        if not name or not phone or not is_usable_company_name(name):
            continue
        key = bic or phone
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "legal_name": name,
                "city": "NYC",
                "state": "NY",
                "role": "contractor",
                "license": key,
                "source": DSNY_TRADE_WASTE_SOURCE,
                "external_id": key,
                "phone": phone,
                "niche_key": "debris_removal",
            }
        )
    return out


async def fetch_dsny_trade_waste(limit: int = 5000) -> list[dict]:
    """Licenças DSNY/BIC ativas em NYC, paginadas (sem chave)."""
    limit = max(1, min(int(limit), MAX_ROWS))
    page = 5000
    out: list[dict] = []
    offset = 0
    today = datetime.now(timezone.utc).date().isoformat()
    where = (
        f"expiration_date > '{today}T00:00:00.000' "
        "AND phone IS NOT NULL AND upper(city) IN ("
        + ",".join(f"'{name}'" for name in NYC_BOROUGHS)
        + ")"
    )
    source = DSNY_TRADE_WASTE_SOURCE
    fetcher = ResilientFetcher(source)
    _FETCH_STATUS.pop(source, None)
    while len(out) < limit:
        params = {
            "$select": DSNY_TRADE_WASTE_SELECT,
            "$where": where,
            "$order": "account_name ASC",
            "$limit": str(min(page, limit - len(out))),
            "$offset": str(offset),
        }
        result = await fetcher.get_json(DSNY_TRADE_WASTE_URL, params=params)
        if not result.ok:
            logger.warning(
                "[LICENSES] DSNY HTTP %s (%s)",
                result.http_status,
                result.error_class,
            )
            _mark_fetch(source, "partial" if out else "failed")
            break
        data = result.data
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < page:
            break
        offset += len(data)
    _mark_fetch(source, "success")
    return out


async def ingest_dsny_trade_waste(limit: int = 5000) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    rows = await fetch_dsny_trade_waste(limit)
    records = extract_dsny_trade_waste(rows)
    result = await record_entities(records, max_records=max(limit, len(records)))
    result["fetched"] = len(rows)
    result["extracted"] = len(records)
    _record_ingest(
        DSNY_TRADE_WASTE_SOURCE, len(rows), len(records), result, started
    )
    logger.info(
        "[LICENSES] DSNY: fetched=%s extraidas=%s guardadas=%s",
        len(rows),
        len(records),
        result.get("saved"),
    )
    return result


def _split_city_zip(value: object) -> tuple[str, str]:
    text = _clean(value).upper()
    match = re.match(r"^(.*?)[,\s]+([A-Z]{2})[,\s]+(\d{5})", text)
    if not match:
        return "", ""
    return match.group(1).strip(), match.group(3)


def extract_tdlr_licenses(
    rows: Iterable[dict], niche_key: str = "", license_type: str = ""
) -> list[dict]:
    """Linhas dos CSV do TDLR -> entidades do metro de Dallas (puro)."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        name = _clean(row.get("BUSINESS NAME") or row.get("NAME"))
        license_no = _clean(row.get("LICENSE NUMBER"))
        if not name or not license_no or not is_usable_company_name(name):
            continue
        city, zip_code = _split_city_zip(
            row.get("BUSINESS CITY, STATE ZIP")
            or row.get("MAILING ADDRESS CITY, STATE ZIP")
        )
        county = _clean(
            row.get("BUSINESS COUNTY") or row.get("COUNTY")
        ).upper()
        # Muitos A/C tem a morada em branco; o condado de Dallas serve de geo.
        if city not in DFW_CITIES and county != "DALLAS":
            continue
        if not city:
            city = "DALLAS"
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "legal_name": name,
            "city": "DALLAS",
            "state": "TX",
            "role": "contractor",
            "license": license_no,
            "license_type": license_type or None,
            "source": "tdlr_tx",
            "external_id": f"tdlr:{license_type}:{license_no}" if license_type else f"tdlr:{license_no}",
            "niche_key": niche_key or None,
            "phone": _phone(
                row.get("BUSINESS PHONE") or row.get("PHONE NUMBER")
            ),
        })
    return out


async def fetch_tdlr_file(filename: str) -> list[dict]:
    """Descarrega e faz parse de um CSV do TDLR (sem chave, ~4 MB)."""
    import csv
    import io

    result = await ResilientFetcher(
        "tdlr_tx", retries=4, timeout=120.0
    ).get_text(TDLR_BASE + filename)
    if not result.ok:
        logger.warning(
            "[LICENSES] TDLR %s HTTP %s (%s)",
            filename,
            result.http_status,
            result.error_class,
        )
        return []
    text = str(result.data or "").lstrip("\ufeff")
    return list(csv.DictReader(io.StringIO(text)))


async def ingest_tdlr(limit: int = 12000) -> dict:
    """Ingere os ficheiros de contractor do TDLR e filtra o metro de Dallas."""
    started = datetime.now(timezone.utc).isoformat()
    records: list[dict] = []
    per_file: dict[str, int] = {}
    total_rows = 0
    failed_files = 0
    for label, filename in TDLR_FILES.items():
        rows = await fetch_tdlr_file(filename)
        total_rows += len(rows)
        if not rows:
            failed_files += 1
        extracted = extract_tdlr_licenses(
            rows,
            niche_key=TDLR_TRADE.get(label, ""),
            license_type=label,
        )
        per_file[label] = len(extracted)
        records.extend(extracted)
        logger.info(
            "[LICENSES] TDLR %s: rows=%s dallas=%s", label, len(rows), len(extracted)
        )
    result = await record_entities(records, max_records=max(limit, len(records)))
    # O upsert usa COALESCE e não sobrescreve tags antigas. Para o TDLR a
    # licença é a fonte de verdade, por isso forçamos o niche_key correto.
    from .db import get_connection

    conn = get_connection()
    try:
        for rec in records:
            if not rec.get("niche_key"):
                continue
            conn.execute(
                "UPDATE contractor_entities SET niche_key=?, "
                "license_type=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE license=? AND legal_name=? AND state='TX'",
                (
                    rec["niche_key"],
                    rec.get("license_type"),
                    rec.get("license"),
                    rec.get("legal_name"),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    result["extracted"] = len(records)
    result["per_file"] = per_file
    if failed_files == 0:
        _FETCH_STATUS["tdlr_tx"] = "success"
    elif total_rows:
        _FETCH_STATUS["tdlr_tx"] = "partial"
    else:
        _FETCH_STATUS["tdlr_tx"] = "failed"
    _record_ingest("tdlr_tx", total_rows, len(records), result, started)
    logger.info(
        "[LICENSES] TDLR: extraidas=%s guardadas=%s", len(records), result.get("saved")
    )
    return result


def extract_il_roofing(rows: Iterable[dict]) -> list[dict]:
    """IDFPR -> entidades de roofing em Chicago."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        name = _clean(
            row.get("business_name")
            or row.get("businessdba")
            or f"{row.get('first_name') or ''} {row.get('last_name') or ''}"
        )
        license_no = _clean(row.get("license_number"))
        if not name or not license_no or not is_usable_company_name(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "legal_name": name,
            "city": "CHICAGO",
            "state": "IL",
            "role": "contractor",
            "license": license_no,
            "source": "il_idfpr",
            "external_id": f"il:{license_no}",
        })
    return out


async def ingest_il_roofing(limit: int = 5000) -> dict:
    source = "il_idfpr"
    started = datetime.now(timezone.utc).isoformat()
    _FETCH_STATUS.pop(source, None)
    fetched = await ResilientFetcher(source).get_json(
        IL_LICENSE_URL,
        params={
            "$select": "business_name,businessdba,first_name,last_name,"
            "license_number,zip,city",
            "$where": IL_ROOFING_WHERE,
            "$limit": str(max(1, min(limit, 50000))),
        },
    )
    if not fetched.ok:
        logger.warning(
            "[LICENSES] IL IDFPR HTTP %s (%s)",
            fetched.http_status,
            fetched.error_class,
        )
        _mark_fetch(source, "failed")
        result = {"status": "http_error", "code": fetched.http_status, "saved": 0}
        _record_ingest(source, 0, 0, result, started)
        return result
    rows = fetched.data
    records = extract_il_roofing(rows if isinstance(rows, list) else [])
    result = await record_entities(records, max_records=max(limit, len(records)))
    result["fetched"] = len(rows) if isinstance(rows, list) else 0
    result["extracted"] = len(records)
    _record_ingest(source, result["fetched"], len(records), result, started)
    logger.info(
        "[LICENSES] IL roofing: fetched=%s extraidas=%s guardadas=%s",
        result["fetched"], len(records), result.get("saved"),
    )
    return result


def extract_chicago_licenses(rows: Iterable[dict]) -> list[dict]:
    """Business Licenses de Chicago -> entidades de construcao."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        name = _clean(
            row.get("legal_name") or row.get("doing_business_as_name")
        )
        license_no = _clean(row.get("license_number"))
        if not name or not license_no or not is_usable_company_name(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "legal_name": name,
            "city": "CHICAGO",
            "state": "IL",
            "role": "contractor",
            "license": license_no,
            "source": "chi_business_license",
            "external_id": f"chi:{license_no}",
        })
    return out


async def ingest_chicago_licenses(limit: int = 2000) -> dict:
    source = "chi_business_license"
    started = datetime.now(timezone.utc).isoformat()
    _FETCH_STATUS.pop(source, None)
    fetched = await ResilientFetcher(source).get_json(
        CHI_LICENSE_URL,
        params={
            "$select": "legal_name,doing_business_as_name,license_number",
            "$where": CHI_WHERE,
            "$limit": str(max(1, min(limit, 20000))),
        },
    )
    if not fetched.ok:
        logger.warning(
            "[LICENSES] Chicago HTTP %s (%s)",
            fetched.http_status,
            fetched.error_class,
        )
        _mark_fetch(source, "failed")
        result = {"status": "http_error", "code": fetched.http_status, "saved": 0}
        _record_ingest(source, 0, 0, result, started)
        return result
    rows = fetched.data
    records = extract_chicago_licenses(rows if isinstance(rows, list) else [])
    result = await record_entities(records, max_records=max(limit, len(records)))
    result["fetched"] = len(rows) if isinstance(rows, list) else 0
    result["extracted"] = len(records)
    _record_ingest(source, result["fetched"], len(records), result, started)
    logger.info(
        "[LICENSES] Chicago: fetched=%s extraidas=%s guardadas=%s",
        result["fetched"], len(records), result.get("saved"),
    )
    return result


async def ingest_nyc_licenses(limit: int = 2000) -> dict:
    """Busca + grava. Idempotente; devolve {fetched, extracted, saved, ...}."""
    started = datetime.now(timezone.utc).isoformat()
    rows = await fetch_nyc_licenses(limit=limit)
    records = extract_nyc_licenses(rows)
    result = await record_entities(records, max_records=max(limit, len(records)))
    result["fetched"] = len(rows)
    result["extracted"] = len(records)
    _record_ingest("nyc_dcwp", len(rows), len(records), result, started)
    logger.info(
        "[LICENSES] NYC: fetched=%s extracted=%s saved=%s",
        result["fetched"], result["extracted"], result.get("saved"),
    )
    return result
