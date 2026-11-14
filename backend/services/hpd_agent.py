"""Resolucao do Managing Agent de edificios HPD em NYC (staging).

O PLUTO (`64uk-42ks`) devolve o `ownername`, que para muitas LLCs e' apenas o
SPV do edificio. O HPD mantem duas bases uteis:

* `tesw-yqqr` — Multiple Dwelling Registrations (BBL/BIN -> registrationid);
* `feu5-w2e2` — Registration Contacts (registrationid -> Agent/CorporateOwner).

Este modulo junta as duas e devolve o Agent quando existe. Nao substitui nada
por defeito; o resultado e' anexado ao enriquecimento para a fase seguinte.
Os datasets nao expõem telefone; o telefone continua a ser on-demand.
"""
from __future__ import annotations

import re
from typing import Optional

from ..scrapers.socrata_311 import socrata_scraper
from ..utils.logger import logger

_HPD_REGISTRATIONS = "tesw-yqqr"
_HPD_CONTACTS = "feu5-w2e2"


def _clean_contact(row: dict) -> Optional[dict]:
    company = str(row.get("corporationname") or "").strip()
    first = str(row.get("firstname") or "").strip()
    last = str(row.get("lastname") or "").strip()
    person = " ".join(part for part in (first, last) if part).strip()
    name = company or person
    if not name:
        return None
    address_parts = [
        str(row.get("businesshousenumber") or "").strip(),
        str(row.get("businessstreetname") or "").strip(),
        str(row.get("businessapartment") or "").strip(),
        str(row.get("businesscity") or "").strip(),
        str(row.get("businessstate") or "").strip(),
        str(row.get("businesszip") or "").strip(),
    ]
    address = ", ".join(part for part in address_parts if part)
    return {
        "name": name,
        "contact_type": str(row.get("type") or "").strip() or None,
        "contact_description": str(row.get("contactdescription") or "").strip() or None,
        "business_address": address or None,
        "registration_id": str(row.get("registrationid") or "").strip() or None,
    }


async def resolve_managing_agent(
    *, bbl: Optional[str] = None, bin_value: Optional[str] = None
) -> Optional[dict]:
    """Devolve o Agent/CorporateOwner do HPD para o imovel, se existir."""
    bbl_digits = re.sub(r"\D", "", str(bbl or ""))
    bin_digits = re.sub(r"\D", "", str(bin_value or ""))
    if not (9 <= len(bbl_digits) <= 10) and len(bin_digits) < 6:
        return None

    where = f"bbl = '{bbl_digits}'" if 9 <= len(bbl_digits) <= 10 else f"bin = '{bin_digits}'"
    try:
        registrations = await socrata_scraper._fetch_soql(
            domain="data.cityofnewyork.us",
            dataset=_HPD_REGISTRATIONS,
            select="registrationid,buildingid,bbl,bin,boro,housenumber,streetname,zip",
            where=where,
            order=None,
            limit=5,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("HPD agent: registrations lookup falhou: %s", exc)
        return None

    registration_ids = [
        str(row.get("registrationid") or "").strip()
        for row in (registrations or [])
        if str(row.get("registrationid") or "").strip()
    ]
    if not registration_ids:
        return None

    quoted = ", ".join("'" + rid.replace("'", "''") + "'" for rid in dict.fromkeys(registration_ids))
    try:
        contacts = await socrata_scraper._fetch_soql(
            domain="data.cityofnewyork.us",
            dataset=_HPD_CONTACTS,
            select=(
                "registrationid,type,contactdescription,corporationname,"
                "firstname,lastname,businesshousenumber,businessstreetname,"
                "businessapartment,businesscity,businessstate,businesszip"
            ),
            where=f"registrationid in ({quoted})",
            order=None,
            limit=50,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("HPD agent: contacts lookup falhou: %s", exc)
        return None

    candidates = [c for c in (_clean_contact(row) for row in (contacts or [])) if c]
    if not candidates:
        return None

    # Preferir Agent; depois CorporateOwner; depois qualquer contacto com nome.
    priority = {"Agent": 0, "CorporateOwner": 1}
    candidates.sort(key=lambda c: priority.get(c.get("contact_type") or "", 9))
    agent = candidates[0]
    agent["source"] = "hpd_registration_contacts"
    return agent
