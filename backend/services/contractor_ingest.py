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

from .contractor_entities import is_usable_company_name, normalize_role

_COMPANY_HINT_RE = re.compile(
    r"\b(LLC|L L C|INC|CORP|CORPORATION|CONSTRUCTION|CONTRACTING|BUILDERS|"
    r"BUILDING|ENTERPRISES|COMPANY|LTD|SERVICES|MECHANICAL|ELECTRIC|"
    r"ELECTRICAL|PLUMBING|ROOFING|MASONRY)\b"
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
            if not (ctype.startswith("CONTRACTOR") or ctype.startswith("MASON")):
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
