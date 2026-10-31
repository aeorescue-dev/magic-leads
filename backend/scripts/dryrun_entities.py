"""Dry-run dos extratores contra uma CÓPIA da base de dados.

Uso (no contentor):
    cp /data/leads.db /tmp/audit.db
    LEADS_DB_PATH=/tmp/audit.db python -m backend.scripts.dryrun_entities
    rm -f /tmp/audit.db

Lê amostras públicas de NYC/Chicago/Boston, extrai entidades e grava-as na BD
apontada por LEADS_DB_PATH. Nunca deve ser apontado à BD de produção.
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx

from ..services.contractor_ingest import (
    extract_boston_permits,
    extract_chicago_permits,
    extract_nyc_permits,
)
from ..services.db import db_service


async def _fetch() -> dict[str, list[dict]]:
    async with httpx.AsyncClient(timeout=40) as c:
        nyc = (
            await c.get(
                "https://data.cityofnewyork.us/resource/rbx6-tga4.json",
                params={
                    "$limit": 100,
                    "$select": "job_filing_number,work_permit,applicant_business_name,applicant_license",
                    "$order": "approved_date DESC",
                },
            )
        ).json()
        chi_fields = ["id"] + [
            f"contact_{i}_{s}" for i in range(1, 16) for s in ("type", "name")
        ]
        chi = (
            await c.get(
                "https://data.cityofchicago.org/resource/ydr8-5enu.json",
                params={"$limit": 100, "$select": ",".join(chi_fields)},
            )
        ).json()
        bos = (
            await c.get(
                "https://data.boston.gov/api/3/action/datastore_search",
                params={
                    "resource_id": "6ddcd912-32a0-43df-9908-63574f8c7e77",
                    "limit": 100,
                },
            )
        ).json()
    bos_rows = (
        ((bos.get("result") or {}).get("records") or [])
        if bos.get("success")
        else []
    )
    return {
        "NYC": extract_nyc_permits(nyc if isinstance(nyc, list) else []),
        "CHICAGO": extract_chicago_permits(chi if isinstance(chi, list) else []),
        "BOSTON": extract_boston_permits(bos_rows),
    }


async def main() -> None:
    if not (os.getenv("LEADS_DB_PATH") or "").strip():
        raise SystemExit("defina LEADS_DB_PATH para uma cópia; nunca a produção")
    records = await _fetch()
    for city, recs in records.items():
        saved = 0
        for rec in recs:
            if await db_service.upsert_contractor_entity(**rec):
                saved += 1
        print(
            json.dumps(
                {
                    "city": city,
                    "extracted": len(recs),
                    "saved": saved,
                    "db": db_service._service.contractor_entity_counts(city),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
