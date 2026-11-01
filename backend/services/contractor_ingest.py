"""Extratores de empreiteiros a partir dos registos públicos (Fase 2.2).

Funções puras: recebem as linhas cruas do portal e devolvem registos de
entidade prontos para `db_service.upsert_contractor_entity`. Nenhuma faz I/O,
por isso são testáveis com fixtures reais.

Regras:
  * NYC: `applicant_business_name` (+ `applicant_license`); papel contractor.
  * Chicago: `contact_N_type`/`contact_N_name`, só tipos `CONTRACTOR-*` e
    `MASON*`; o prefixo de licença (`PL058130279-`) é separado do nome.
  * Boston: o portal de permits só traz `applicant` (pessoa), sem empresa nem
    licença; só entra se o nome tiver indicador empresarial.
  * Owners/architects ficam de fora: não são o alvo comercial.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from ..utils.logger import logger
from .contractor_entities import is_usable_company_name, normalize_role
from .db import db_service

_COMPANY_HINT_RE = re.compile(
    r"\b(LLC|L L C|INC|CORP|CORPORATION|CO|CONSTRUCTION|CONTRACTING|BUILDERS|"
    r"BUILDING|ENTERPRISES|COMPANY|LTD|SERVICES|MECHANICAL|ELECTRIC|"
    r"ELECTRICAL|PLUMBING|ROOFING|MASONRY|HVAC|HEATING|AIR|RESTORATION|"
    r"REMODELING|SCAFFOLD|TUCKPOINT|SIGNS)\b"
)
_CHI_LICENSE_RE = re.compile(r"^([A-Z]{2}\d{6,})\s*-\s*(.+)$")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _record(
    *,
    legal_name: str,
    city: str,
    state: str,
    role: Optional[str],
    license: Optional[str],
    source: str,
    external_id: str,
) -> Optional[dict]:
    name = _clean(legal_name)
    if not name or not is_usable_company_name(name):
        return None
    return {
        "legal_name": name,
        "city": city,
        "state": state,
        "role": normalize_role(role),
        "license": (_clean(license) or None),
        "source": source,
        "external_id": _clean(external_id),
    }


def extract_nyc_permits(rows: Iterable[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows or []:
        name = _clean(row.get("applicant_business_name"))
        if not name:
            continue
        job = _clean(row.get("job_filing_number"))
        permit = _clean(row.get("work_permit"))
        if not job:
            continue
        rec = _record(
            legal_name=name,
            city="NYC",
            state="NY",
            role="contractor",
            license=row.get("applicant_license"),
            source="nyc_dob_permits",
            external_id=f"{job}~{permit}" if permit else job,
        )
        if rec:
            out.append(rec)
    return out


def extract_chicago_permits(rows: Iterable[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows or []:
        permit_id = _clean(row.get("id"))
        if not permit_id:
            continue
        for idx in range(1, 16):
            ctype = _clean(row.get(f"contact_{idx}_type")).upper()
            if not ctype:
                continue
            # "ELECTRICAL CONTRACTOR" (261k) e "SIGN CONTRACTOR" ficavam de
            # fora com o filtro antigo (startswith CONTRACTOR); "OWNER AS
            # GENERAL CONTRACTOR" e' o proprietario, nao uma empresa.
            if ctype.startswith("OWNER"):
                continue
            if "CONTRACTOR" not in ctype and not ctype.startswith("MASON"):
                continue
            raw_name = _clean(row.get(f"contact_{idx}_name"))
            if not raw_name:
                continue
            license = None
            name = raw_name
            match = _CHI_LICENSE_RE.match(raw_name)
            if match:
                license, name = match.group(1), match.group(2)
            rec = _record(
                legal_name=name,
                city="CHICAGO",
                state="IL",
                role="contractor",
                license=license,
                source="chi_permits",
                external_id=f"{permit_id}:{idx}",
            )
            if rec:
                out.append(rec)
    return out


def _looks_like_company(name: str) -> bool:
    return bool(_COMPANY_HINT_RE.search(_clean(name).upper()))


# Dallas: o campo `contractor` vem com nome + morada + telefone numa so'
# string ("ACME PLUMBING 123 MAIN ST, DALLAS, TX 75211 (469) 360-6479").
_DALLAS_PHONE_RE = re.compile(r"\(\d{3}\)\s*\d{3}-\d{4}")
_DALLAS_STREET_RE = re.compile(r"\s+\d{1,6}\s+[A-Z0-9]")
_DALLAS_POBOX_RE = re.compile(r"\bP\.?\s*O\.?\s*BOX\b", re.I)


def _dallas_contractor_name(raw: object) -> str:
    text = _clean(raw)
    if not text:
        return ""
    text = _DALLAS_PHONE_RE.split(text)[0]
    text = _DALLAS_POBOX_RE.split(text)[0]
    match = _DALLAS_STREET_RE.search(text)
    if match:
        text = text[: match.start()]
    return _clean(text).strip(" ,-")


def extract_dallas_permits(rows: Iterable[dict]) -> list[dict]:
    """Empreiteiros dos Building Permits de Dallas (dataset e7gq-4sah).

    O `contractor` e' o unico campo com identidade de empresa. Nomes de pessoa
    fisica sao descartados por `_looks_like_company` (mesmo criterio de Boston).
    """
    out: list[dict] = []
    for row in rows or []:
        name = _dallas_contractor_name(row.get("contractor"))
        permit = _clean(row.get("permit_number"))
        if not name or not permit or not _looks_like_company(name):
            continue
        rec = _record(
            legal_name=name,
            city="DALLAS",
            state="TX",
            role="contractor",
            license=None,
            source="dallas_permits",
            external_id=permit,
        )
        if rec:
            out.append(rec)
    return out


async def record_entities(records: list[dict], max_records: int = 2000) -> dict:
    """Deduplica e grava entidades de contractor; nunca levanta.

    Vive no servico (e nao no main) para o scheduler poder ingerir licencas e
    OSM sem import circular. O scrape nunca cai por causa de uma linha ma.
    """
    if not records:
        return {"saved": 0, "failed": 0, "total": 0, "unique": 0}
    free_mb = await db_service.data_free_mb()
    if free_mb < 120:
        logger.warning(
            "[ENTITIES] disco quase cheio (%s MB livres): ingestao adiada", free_mb
        )
        return {"saved": 0, "failed": 0, "total": len(records),
                "unique": 0, "skipped": "disk_full"}
    seen: set[tuple] = set()
    unique: list[dict] = []
    for rec in records:
        key = (
            (rec.get("license") or "").upper(),
            (rec.get("legal_name") or "").upper(),
            (rec.get("state") or "").upper(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(rec)
        if len(unique) >= max_records:
            break
    saved = 0
    failed = 0
    for rec in unique:
        try:
            if await db_service.upsert_contractor_entity(**rec):
                saved += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning(
                "[ENTITIES] falha ao gravar %r: %s", rec.get("legal_name"), exc
            )
    logger.info(
        "[ENTITIES] %s/%s guardadas (unicas=%s, falhas=%s)",
        saved, len(records), len(unique), failed,
    )
    return {
        "saved": saved, "failed": failed,
        "total": len(records), "unique": len(unique),
    }


def extract_boston_permits(rows: Iterable[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows or []:
        name = _clean(row.get("applicant"))
        permit = _clean(row.get("permitnumber"))
        if not name or not permit or not _looks_like_company(name):
            continue
        rec = _record(
            legal_name=name,
            city="BOSTON",
            state="MA",
            role="applicant",
            license=None,
            source="boston_permits",
            external_id=permit,
        )
        if rec:
            out.append(rec)
    return out
