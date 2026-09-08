#!/usr/bin/env python
"""
Hourly scheduler to keep leads database updated.
Run via: Windows Task Scheduler / cron / systemd timer
Usage: python hourly_updater.py
"""
import sys
import asyncio
import logging
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from backend.scrapers.socrata_311 import socrata_scraper
from backend.scrapers.socrata_discovery import socrata_discovery
from backend.services.enrichment import owner_enrichment
from backend.services.db import db_service
import backend.services.db as dbmod
from backend.models.schemas import EnrichedLead, IssueCategory, UrgencyLevel, SourceType
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Cities to scrape (configure as needed)
TARGET_CITIES = [
    {"domain": "data.cityofnewyork.us", "dataset": "erm2-nwe9", "city": "NYC", "state": "NY", "hours": 24},
    {"domain": "data.cityofnewyork.us", "dataset": "wvxf-dwi5", "city": "NYC", "state": "NY", "hours": 48},  # HPD Violations
    {"domain": "data.cityofchicago.org", "dataset": "v6vf-nfxy", "city": "Chicago", "state": "IL", "hours": 24},
    {"domain": "www.dallasopendata.com", "dataset": "d7e7-envw", "city": "Dallas", "state": "TX", "hours": 24},
    # {"domain": "data.nj.gov", "dataset": "w9se-dmra", "city": "Newark", "state": "NJ", "hours": 168},  # NJ permits - schema diferente, sem endereço de rua
    # Boston uses CKAN datastore API
    {"type": "ckan", "domain": "data.boston.gov", "resource_id": "1a0b420d-99f1-4887-9851-990b2a5a6e17", "city": "Boston", "state": "MA", "hours": 24},
]

async def scrape_boston():
    """Scrape Boston 311 via CKAN datastore API."""
    logger.info("Scraping Boston...")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            # Get recent records sorted by date, filter client-side
            resp = await client.get(
                "https://data.boston.gov/api/3/action/datastore_search",
                params={
                    "resource_id": "1a0b420d-99f1-4887-9851-990b2a5a6e17",
                    "limit": 5000,
                    "sort": "open_dt DESC",
                }
            )
            data = resp.json()
            if not data.get("success"):
                logger.error(f"Boston CKAN API error: {data}")
                return 0
            
            records = data["result"]["records"]
            logger.info(f"Boston: fetched {len(records)} records")
            
            # Filter last 24h client-side
            since = datetime.now() - timedelta(hours=24)
            recent_records = []
            for rec in records:
                open_dt_str = rec.get("open_dt")
                if open_dt_str:
                    try:
                        open_dt = datetime.fromisoformat(str(open_dt_str).replace("Z", "+00:00").replace("T", " "))
                        if open_dt >= since:
                            recent_records.append(rec)
                    except:
                        pass
            
            logger.info(f"Boston: {len(recent_records)} records in last 24h")
            
            inserted = 0
            for rec in recent_records:
                # Map Boston fields to our schema
                external_id = str(rec.get("case_enquiry_id") or rec.get("_id") or "")
                if not external_id:
                    continue
                
                address = rec.get("location") or rec.get("location_street_name") or "Boston, MA"
                zip_code = str(rec.get("location_zipcode")) if rec.get("location_zipcode") else None
                
                enriched = EnrichedLead(
                    external_id=external_id,
                    source_type=SourceType.SERVICE_311,
                    address=f"{address}, Boston, MA" if address else "Boston, MA",
                    city="Boston",
                    state="MA",
                    zip_code=zip_code,
                    lat=rec.get("latitude"),
                    lng=rec.get("longitude"),
                    county=rec.get("county"),
                    address_unit=None,
                    address_type=None,
                    address_street=rec.get("location_street_name"),
                    address_city="Boston",
                    address_state="MA",
                    address_zip=zip_code,
                    issue_category=IssueCategory.GRASS,  # will be overridden by keyword mapping
                    issue_description=rec.get("case_title") or rec.get("reason") or rec.get("type") or "",
                    urgency_level=UrgencyLevel.MEDIUM,
                    owner_name=None,
                    owner_phone=None,
                    owner_email=None,
                    owner_status=None,
                    date_reported=datetime.fromisoformat(str(rec.get("open_dt")).replace("Z", "+00:00").replace("T", " ")) if rec.get("open_dt") else datetime.now(),
                    image_url=None,
                    source_url=None,
                    # Historical details from Boston 311
                    case_title=rec.get("case_title"),
                    subject=rec.get("subject"),
                    reason=rec.get("reason"),
                    type=rec.get("type"),
                    queue=rec.get("queue"),
                    department=rec.get("department"),
                    closure_reason=rec.get("closure_reason"),
                    case_status=rec.get("case_status"),
                    on_time=rec.get("on_time"),
                    sla_target_dt=rec.get("sla_target_dt"),
                    closed_dt=rec.get("closed_dt"),
                    submitted_photo=rec.get("submitted_photo"),
                    closed_photo=rec.get("closed_photo"),
                    source=rec.get("source"),
                    neighborhood=rec.get("neighborhood"),
                    ward=rec.get("ward"),
                    precinct=rec.get("precinct"),
                    descriptor=None,
                    resolution_description=rec.get("closure_reason"),
                    resolution_action_updated_date=rec.get("closed_dt"),
                )
                
                # Map issue category from case_title/reason
                desc = (enriched.issue_description or "").lower()
                if any(k in desc for k in ["roof", "gutter", "shingle"]):
                    enriched.issue_category = IssueCategory.ROOF
                elif any(k in desc for k in ["plumb", "water", "leak", "pipe", "sewer", "drain"]):
                    enriched.issue_category = IssueCategory.PLUMBING
                elif any(k in desc for k in ["paint", "plaster", "graffiti", "façade", "facade"]):
                    enriched.issue_category = IssueCategory.PAINT
                elif any(k in desc for k in ["structur", "foundation", "wall", "collapse", "crack"]):
                    enriched.issue_category = IssueCategory.STRUCTURE
                elif any(k in desc for k in ["grass", "weed", "vegetation", "overgrown", "litter", "trash", "garbage", "debris", "dirty", "unsanitary", "abandoned vehicle"]):
                    enriched.issue_category = IssueCategory.GRASS
                
                enriched.urgency_level = socrata_scraper._infer_urgency(enriched.issue_description)
                
                if await db_service.insert_lead(enriched):
                    inserted += 1
            
            logger.info(f"Boston: inserted {inserted} new leads")
            return inserted
    except Exception as e:
        logger.error(f"Error scraping Boston: {e}")
        return 0

async def scrape_city(city_config: dict):
    """Scrape a single city's 311/permits data."""
    logger.info(f"Scraping {city_config['city']}...")
    try:
        # Handle CKAN (Boston)
        if city_config.get("type") == "ckan":
            return await scrape_boston()
        
        # Get field names first
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://{city_config['domain']}/resource/{city_config['dataset']}.json",
                params={"$limit": 5}
            )
            if resp.status_code != 200:
                logger.error(f"Failed to fetch sample from {city_config['city']}: {resp.status_code}")
                return 0
            sample = resp.json()
            if not sample:
                logger.warning(f"No data returned from {city_config['city']}")
                return 0
            field_names = list(sample[0].keys())
        
        # Scrape using generic fetcher
        leads = await socrata_scraper.fetch_from_dataset(
            domain=city_config["domain"],
            dataset_id=city_config["dataset"],
            city=city_config["city"],
            state=city_config["state"],
            field_names=field_names,
            hours=city_config["hours"],
            limit=5000,
        )
        
        # Convert and insert
        inserted = 0
        for lead in leads:
            enriched = _raw_to_enriched(lead)
            if await db_service.insert_lead(enriched):
                inserted += 1
        
        logger.info(f"{city_config['city']}: inserted {inserted} new leads")
        return inserted
    except Exception as e:
        logger.error(f"Error scraping {city_config['city']}: {e}")
        return 0

async def backfill_historical():
    """Backfill dos campos históricos para leads já existentes.
    Para cada cidade Socrata: lê os external_ids do banco, busca esses registros
    no dataset, e atualiza os campos históricos (ON CONFLICT garante update).
    """
    logger.info("Backfill histórico: buscando registros existentes no Socrata...")
    total = 0
    import httpx
    for cfg in TARGET_CITIES:
        if cfg.get("type") == "ckan":
            continue
        city = cfg["city"]
        state = cfg["state"]
        try:
            # external_ids existentes no banco
            conn_for_ids = dbmod.get_connection()
            rows = conn_for_ids.execute(
                "SELECT external_id FROM leads WHERE city=?", (city,)
            ).fetchall()
            conn_for_ids.close()
            existing_ids = [str(r["external_id"]) for r in rows]
            if not existing_ids:
                logger.info(f"{city}: nenhum lead existente — pulando backfill")
                continue

            # descobre colunas
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"https://{cfg['domain']}/resource/{cfg['dataset']}.json",
                    params={"$limit": 5},
                )
                if resp.status_code != 200 or not resp.json():
                    logger.warning(f"{city}: falha ao obter metadados — pulando")
                    continue
                field_names = list(resp.json()[0].keys())

            cols = socrata_scraper._guess_columns(field_names)
            if not cols["_has_date"] or not cols["ext"]:
                logger.warning(f"{city}: colunas insuficientes — pulando")
                continue

            ext_col = cols["ext"]

            # busca em batches de 100 (evita WHERE IN gigante)
            updated = 0
            BATCH = 100
            for i in range(0, len(existing_ids), BATCH):
                batch_ids = existing_ids[i : i + BATCH]
                ids_sql = ", ".join(f"'{eid}'" for eid in batch_ids)
                where = f"{ext_col} IN ({ids_sql})"

                # monta select com todos os campos base + histórico
                select_fields = [c for c in [cols["date"], cols["desc"], cols["lat"], cols["lng"], cols["ext"], cols["addr"], cols["zip"]] if c]
                for col in cols["hist"].values():
                    if col and col not in select_fields:
                        select_fields.append(col)
                if not select_fields:
                    select_fields = ["*"]

                rows = await socrata_scraper._fetch_soql(
                    domain=cfg["domain"],
                    dataset=cfg["dataset"],
                    select=", ".join(select_fields),
                    where=where,
                    order=f"{cols['date']} DESC",
                    limit=5000,
                )
                for row in rows:
                    lead = socrata_scraper._parse_generic_row(row, cols, city, state)
                    if not lead:
                        continue
                    enriched = _raw_to_enriched(lead)
                    if await db_service.update_lead_historical(lead.external_id, city, enriched):
                        updated += 1
            logger.info(f"{city} backfill: {updated}/{len(existing_ids)} leads atualizados")
            total += updated
        except Exception as e:
            logger.error(f"Backfill error {city}: {e}")
            import traceback; traceback.print_exc()
    logger.info(f"Backfill histórico: total={total} leads atualizados")
    return total

def _raw_to_enriched(lead) -> EnrichedLead:
    """Converte um RawLead311 (com campos históricos) em EnrichedLead."""
    return EnrichedLead(
        external_id=lead.external_id,
        source_type=SourceType.SERVICE_311,
        address=lead.address,
        city=lead.city,
        state=lead.state,
        zip_code=lead.zip_code,
        lat=lead.lat,
        lng=lead.lng,
        county=None,
        address_unit=None,
        address_type=None,
        address_street=None,
        address_city=None,
        address_state=None,
        address_zip=None,
        issue_category=lead.issue_category,
        issue_description=lead.issue_description,
        urgency_level=socrata_scraper._infer_urgency(lead.issue_description),
        owner_name=None,
        owner_phone=None,
        owner_email=None,
        owner_status=None,
        date_reported=lead.created_at,
        image_url=None,
        source_url=None,
        case_title=lead.case_title,
        subject=lead.subject,
        reason=lead.reason,
        type=lead.type,
        queue=lead.queue,
        department=lead.department,
        closure_reason=lead.closure_reason,
        case_status=lead.case_status,
        on_time=lead.on_time,
        sla_target_dt=lead.sla_target_dt,
        closed_dt=lead.closed_dt,
        submitted_photo=lead.submitted_photo,
        closed_photo=lead.closed_photo,
        source=lead.source,
        neighborhood=lead.neighborhood,
        ward=lead.ward,
        precinct=lead.precinct,
        descriptor=lead.descriptor,
        resolution_description=lead.resolution_description,
        resolution_action_updated_date=lead.resolution_action_updated_date,
    )

async def backfill_case_history(limit_per_city: int = 40):
    """Parte B: histórico de ocorrências por imóvel.

    Para cada lead ainda sem histórico, busca no dataset 311 todos os registros do
    mesmo endereço (rua+numero, prefixo antes da 1a vírgula) e salva em
    lead_case_history — a timeline de ocorrências do imóvel exibida no modal."""
    logger.info("Backfill histórico de ocorrências por imóvel (Parte B)...")
    import httpx
    total = 0
    for cfg in TARGET_CITIES:
        if cfg.get("type") == "ckan":
            continue
        city, state = cfg["city"], cfg["state"]
        domain, dataset = cfg["domain"], cfg["dataset"]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"https://{domain}/resource/{dataset}.json", params={"$limit": 5}
                )
                if resp.status_code != 200 or not resp.json():
                    logger.warning(f"{city}: metadados indisponíveis — pulando")
                    continue
                field_names = list(resp.json()[0].keys())

            cols = socrata_scraper._guess_columns(field_names)
            if not cols["_has_date"] or not cols["addr"] or not cols["ext"]:
                logger.warning(f"{city}: colunas insuficientes para histórico — pulando")
                continue

            leads = await dbmod.db_service.list_leads_for_case_history(
                city=city, limit=limit_per_city
            )
            if not leads:
                logger.info(f"{city}: nenhum imóvel pendente")
                continue

            city_total = 0
            for lead_row in leads:
                addr_raw = (lead_row.get("address") or "").strip()
                if not addr_raw or "," not in addr_raw:
                    continue
                street = addr_raw.split(",")[0].strip().rstrip(".").strip()
                if " " not in street:
                    continue

                addr_col = cols["addr"]
                esc = street.replace("'", "''")
                where = f"{addr_col} like '{esc}%'"

                select_fields = [c for c in [cols["date"], cols["ext"], cols["addr"], cols["desc"]] if c]
                for col in cols["hist"].values():
                    if col and col not in select_fields:
                        select_fields.append(col)
                if not select_fields:
                    select_fields = ["*"]

                rows = await socrata_scraper._fetch_soql(
                    domain=domain,
                    dataset=dataset,
                    select=", ".join(select_fields),
                    where=where,
                    order=f"{cols['date']} DESC",
                    limit=200,
                    timeout=120,
                )
                if not rows:
                    continue

                def _hv(r, key):
                    col = cols["hist"].get(key)
                    if not col:
                        return None
                    v = r.get(col)
                    if v is None:
                        return None
                    s = str(v).strip()
                    return s or None

                occurrences = []
                for r in rows:
                    eid = str(r.get(cols["ext"]) or "").strip()
                    if not eid:
                        continue
                    occurrences.append({
                        "external_id": eid,
                        "case_title": _hv(r, "case_title")
                        or (str(r.get(cols["desc"]) or "").strip() or None),
                        "descriptor": _hv(r, "descriptor"),
                        "subject": _hv(r, "subject"),
                        "reason": _hv(r, "reason"),
                        "case_status": _hv(r, "case_status"),
                        "department": _hv(r, "department"),
                        "opened_at": r.get(cols["date"]),
                        "closed_at": _hv(r, "closed_dt"),
                        "resolution_description": _hv(r, "resolution_description"),
                        "closure_reason": _hv(r, "closure_reason"),
                        "source": _hv(r, "source"),
                        "source_url": f"https://{domain}/resource/{dataset}",
                    })

                saved = await dbmod.db_service.save_lead_case_history(lead_row["id"], occurrences)
                if saved:
                    city_total += saved
                    logger.info(f"{city}: imóvel {lead_row['id']} ({street}) -> {saved} ocorrências")
            logger.info(f"{city}: histórico concluído ({len(leads)} imóveis, {city_total} ocorrências salvas)")
            total += city_total
        except Exception as e:
            logger.error(f"Erro backfill histórico OCO {city}: {e}")
            import traceback; traceback.print_exc()
    logger.info(f"Backfill histórico OCO: total={total}")
    return total


async def enrich_owners(limit: int = 200):
    """Enrich owner names for leads without owner_name."""
    logger.info(f"Enriching owner names (limit={limit})...")
    try:
        from backend.services import db as dbmod
        conn = dbmod.get_connection()
        rows = conn.execute(
            "SELECT id, address, city FROM leads "
            "WHERE (owner_name IS NULL OR owner_name = '') "
            "ORDER BY date_reported DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        
        enriched = 0
        for row in rows:
            owner = await owner_enrichment.enrich(row["address"], row["city"])
            if owner:
                db_service.update_owner(row["id"], owner)
                enriched += 1
        
        logger.info(f"Owner enrichment: {enriched} names found")
        return enriched
    except Exception as e:
        logger.error(f"Error enriching owners: {e}")
        return 0

async def main():
    logger.info("=" * 50)
    logger.info("HOURLY UPDATE STARTED")
    logger.info("=" * 50)
    
    total_inserted = 0
    
    # Scrape Socrata cities
    for city in TARGET_CITIES:
        if city.get("type") == "ckan":
            continue
        inserted = await scrape_city(city)
        total_inserted += inserted
        await asyncio.sleep(2)
    
    # Scrape CKAN cities (Boston)
    for city in TARGET_CITIES:
        if city.get("type") == "ckan":
            if city["city"] == "Boston":
                inserted = await scrape_boston()
                total_inserted += inserted
                await asyncio.sleep(2)
    
    # Enrich owner names for new leads
    enriched = await enrich_owners(limit=100)

# Backfill histórico (garante que leads já existentes tenham campos históricos)
    backfilled = await backfill_historical()

    # Backfill histórico de ocorrências por imóvel (Parte B)
    occ_backfilled = await backfill_case_history(limit_per_city=40)

    logger.info(f"SUMMARY: {total_inserted} new leads, {enriched} owners enriched, "
                f"{backfilled} historical backfilled, {occ_backfilled} occurrences backfilled")
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))