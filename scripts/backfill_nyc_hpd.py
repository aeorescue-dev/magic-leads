"""
Backfill dos leads de NYC a partir das fontes abertas da cidade.

Problema que este script corrige
-------------------------------
Os leads de NYC na base vieram de duas fontes e ambas gravaram enderecos
incompletos:

  * HPD Housing Maintenance Code Violations (wvxf-dwi5), `external_id` na gama
    1925xxxx. O select antigo trazia `housenumber` sem `streetname`, e o
    parser generico caia no `or` e gravava so o numero ("140, NYC, NY").
  * 311 Service Requests (erm2-nwe9), `external_id` na gama 705xxxxx. O mesmo
    problema: `incident_address` as vezes so traz o numero e a `street_name`
    nao era requisitada.

Resultado no inventario: 93,4% dos leads de NYC sem nome de rua, nenhum com
`bbl` (identificador canonico de imovel) e todos classificados como
`source_type = '311'`, o que os escondia do filtro "Obrigacao legal".

O que este script faz
---------------------
Para cada lead de NYC, re-busca o registo original na fonte correcta
(identificada pela faixa do `external_id`) e reconstroi:

  * endereco completo (numero + rua + apartamento quando existe)
  * `bbl`, que permite casar o proprietario de forma exacta no PLUTO
  * `source_type` correcto: `hpd_violation` para o HPD, `311` para o 311
  * `owner_name` via PLUTO, usando o `bbl` como chave de casamento exacto

E idempotente: so escreve onde falta informacao, por isso pode ser corrido
varias vezes. Registos que ja nao existem em dataset aberto sao deixados
intactos e reportados no fim.

Uso:
    python scripts/backfill_nyc_hpd.py            # dry-run, nao escreve
    python scripts/backfill_nyc_hpd.py --apply    # escreve na base
"""
import argparse
import asyncio
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from backend.services.db import get_connection
from backend.services.enrichment import owner_enrichment
from backend.scrapers.socrata_311 import socrata_scraper
from backend.utils.logger import logger

DOMAIN = "data.cityofnewyork.us"
HPD_DATASET = "wvxf-dwi5"
NYC_311_DATASET = "erm2-nwe9"

HPD_FIELDS = [
    "violationid", "housenumber", "lowhousenumber", "highhousenumber",
    "streetname", "apartment", "boro", "zip", "bbl", "latitude", "longitude",
    "novdescription", "currentstatus", "inspectiondate",
]

NYC_311_FIELDS = [
    "unique_key", "incident_address", "street_name", "intersection_street_1",
    "incident_zip", "borough", "bbl", "latitude", "longitude",
    "complaint_type", "created_date",
]

BORO_MAP = {
    "1": "MANHATTAN", "2": "BRONX", "3": "BROOKLYN",
    "4": "QUEENS", "5": "STATEN ISLAND",
}

CHUNK_SIZE = 40
NYC_CITIES = ("NYC", "New York")

FIELDS_BY_DATASET = {
    HPD_DATASET: HPD_FIELDS,
    NYC_311_DATASET: NYC_311_FIELDS,
}


def build_hpd_address(row: dict) -> str | None:
    """Monta o endereço completo a partir das colunas do HPD.

    `housenumber` vem vazio em prédios registados por faixa, pelo que se
    recorre a `lowhousenumber`/`highhousenumber`. Sem nome de rua não há
    endereço utilizável e a resposta é None (não inventar rua).
    """
    street = str(row.get("streetname") or "").strip()
    if not street:
        return None

    number = str(row.get("housenumber") or "").strip()
    if not number:
        low = str(row.get("lowhousenumber") or "").strip()
        high = str(row.get("highhousenumber") or "").strip()
        number = f"{low}-{high}" if low and high else (low or high)

    address = f"{number} {street}".strip()

    apartment = str(row.get("apartment") or "").strip()
    if apartment:
        address = f"{address}, APT {apartment}"

    zip_code = str(row.get("zip") or "").strip()
    borough = BORO_MAP.get(str(row.get("boro") or "").strip(), "")
    tail = ", ".join(p for p in (borough, f"NY {zip_code}" if zip_code else "") if p)

    return f"{address}, NYC" + (f", {tail}" if tail else "")


def get_nyc_leads_without_street():
    """Leads de NYC que ainda não têm nome de rua recuperável."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, external_id, address, bbl, owner_name
            FROM leads
            WHERE city IN (?, ?)
              AND (
                    bbl IS NULL OR bbl = ''
                 OR address IS NULL OR address = ''
                 OR address NOT LIKE '%STREET%'
                    AND address NOT LIKE '% AVENUE%'
                    AND address NOT LIKE '% ROAD%'
                    AND address NOT LIKE '% PLACE%'
                    AND address NOT LIKE '%DRIVE%'
                    AND address NOT LIKE '% BOULEVARD%'
                    AND address NOT LIKE '% LANE%'
                    AND address NOT LIKE '% COURT%'
                    AND address NOT LIKE '% TERRACE%'
                    AND address NOT LIKE '% PARKWAY%'
                    AND address NOT LIKE '% HIGHWAY%'
                    AND address NOT LIKE '% SQUARE%'
                    AND address NOT LIKE '%WALK%'
                    AND address NOT LIKE '%CREST%'
                    AND address NOT LIKE '%CENTER%'
                    AND address NOT LIKE '%PLAZA%'
              )
            ORDER BY id
            """,
            NYC_CITIES,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


async def fetch_source_rows(dataset: str, id_field: str, external_ids: list[str]) -> dict[str, dict]:
    """Busca registos por uma chave textual, em lotes."""
    found: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=90) as client:
        for start in range(0, len(external_ids), CHUNK_SIZE):
            chunk = external_ids[start:start + CHUNK_SIZE]
            where = "%s in (%s)" % (
                id_field, ",".join("'%s'" % str(v).replace("'", "") for v in chunk)
            )
            try:
                resp = await client.get(
                    f"https://{DOMAIN}/resource/{dataset}.json",
                    params={"$select": ",".join(FIELDS_BY_DATASET[dataset]), "$where": where,
                            "$limit": 500},
                )
            except httpx.HTTPError as exc:
                logger.warning(f"{dataset} lote {start}: erro de rede {exc}")
                continue
            if resp.status_code != 200:
                logger.warning(f"{dataset} lote {start}: HTTP {resp.status_code} {resp.text[:160]}")
                continue
            for row in resp.json():
                key = str(row.get(id_field) or "").strip()
                if key:
                    found[key] = row
            logger.info(f"{dataset} lote {start}-{start + len(chunk)}: {len(found)} acumulados")
    return found


def build_nyc311_address(row: dict) -> str | None:
    """Endereco do 311 de NYC a partir de incident_address + street_name."""
    street = socrata_scraper._compose_address_parts(
        row.get("incident_address"),
        row.get("street_name"),
        row.get("intersection_street_1"),
    )
    if not street:
        return None
    zip_code = str(row.get("incident_zip") or "").strip()
    return f"{street}, NYC" + (f", NY {zip_code}" if zip_code else "")


def update_lead(lead_id: int, address: str, bbl: str, source_type: str, owner: str | None):
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE leads
            SET address = ?,
                city = 'NYC',
                state = 'NY',
                bbl = ?,
                source_type = ?,
                owner_name = COALESCE(NULLIF(?, ''), owner_name)
            WHERE id = ?
            """,
            (address, bbl, source_type, owner, lead_id),
        )
        conn.commit()
    finally:
        conn.close()


async def main(apply_changes: bool) -> int:
    leads = get_nyc_leads_without_street()
    total = len(leads)
    print(f"Leads de NYC a reconstruir: {total}")

    if not total:
        print("Nada a fazer.")
        return 0

    external_ids = [str(r["external_id"]) for r in leads if r.get("external_id")]

    # A fonte depende da faixa do external_id: 1925xxxx = violationid do HPD,
    # 705xxxxx = unique_key do 311. Tentar as duas garante cobertura de
    # inventario que veio de fontes diferentes.
    hpd_ids = [e for e in external_ids if e.startswith("19")]
    nyc311_ids = [e for e in external_ids if e not in hpd_ids]

    source: dict[str, tuple[str, dict]] = {}
    if hpd_ids:
        print(f"Fonte HPD: {len(hpd_ids)} leads")
        for key, row in (await fetch_source_rows(HPD_DATASET, "violationid", hpd_ids)).items():
            source[key] = (HPD_DATASET, row)
    if nyc311_ids:
        print(f"Fonte 311 NYC: {len(nyc311_ids)} leads")
        for key, row in (await fetch_source_rows(NYC_311_DATASET, "unique_key", nyc311_ids)).items():
            source[key] = (NYC_311_DATASET, row)

    rebuilt = no_source = no_bbl = 0
    owners_found = 0
    missing: list[str] = []
    by_source: dict[str, int] = {}

    for lead in leads:
        ext = str(lead.get("external_id") or "").strip()
        hit = source.get(ext)
        if not hit:
            no_source += 1
            missing.append(ext)
            continue

        dataset, row = hit
        if dataset == HPD_DATASET:
            address = build_hpd_address(row)
            source_type = "hpd_violation"
        else:
            address = build_nyc311_address(row)
            source_type = "311"
        if not address:
            no_source += 1
            missing.append(ext)
            continue

        bbl = socrata_scraper._clean_bbl(row.get("bbl"))
        if not bbl:
            # Sem BBL ainda se reconstroi a morada, mas o proprietario fica por
            # resolver: nunca usar o fallback por substring para adivinhar.
            no_bbl += 1

        owner_name = None
        if bbl:
            result = await owner_enrichment.enrich(address, "NYC", bbl=bbl)
            owner_name = (result or {}).get("owner_name")
            if owner_name:
                owners_found += 1

        if apply_changes:
            update_lead(lead["id"], address, bbl or "", source_type, owner_name)
        rebuilt += 1
        by_source[source_type] = by_source.get(source_type, 0) + 1

    mode = "ESCRITO" if apply_changes else "DRY-RUN (nada escrito)"
    print()
    print(f"=== {mode} ===")
    print(f"  endereco reconstruido : {rebuilt}/{total}")
    for source_type, count in sorted(by_source.items()):
        print(f"    source_type={source_type:<15} {count}")
    print(f"  owner via BBL         : {owners_found}")
    print(f"  sem BBL               : {no_bbl}")
    print(f"  sem registo na fonte  : {no_source}")
    if missing:
        preview = ", ".join(missing[:10])
        print(f"  exemplos indisponiveis: {preview}{' ...' if len(missing) > 10 else ''}")

    if not apply_changes:
        print("\nReexecutar com --apply para gravar.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill de leads NYC (HPD violations)")
    parser.add_argument("--apply", action="store_true", help="gravar as alteracoes")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.apply)))
