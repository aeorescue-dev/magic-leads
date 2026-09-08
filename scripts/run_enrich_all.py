import sys
sys.path.insert(0, 'C:\\Users\\Fabio\\Documents\\Default Project\\garimpador-leads')
import asyncio
from backend.services import db as dbmod
from backend.services.enrichment import owner_enrichment
from backend.services.skip_trace import skip_trace_service

async def enrich_all(limit_per_city=50):
    cities = ['NYC', 'Boston', 'Dallasopendata', 'Dallas', 'Norfolk']
    total_processed = 0
    total_owners_found = 0
    total_mailing_found = 0
    total_phones_found = 0
    total_emails_found = 0
    results_by_city = {}
    
    for city in cities:
        print(f"\n=== Enriquecendo {city} ===")
        
        conn = dbmod.get_connection()
        rows = conn.execute(
            "SELECT id, address, city FROM leads "
            "WHERE city = ? "
            "AND (owner_name IS NULL OR owner_name = '' "
            "   OR mailing_address IS NULL OR mailing_address = '' "
            "   OR owner_phone IS NULL OR owner_phone = '' "
            "   OR owner_email IS NULL OR owner_email = '') "
            "ORDER BY date_reported DESC LIMIT ?",
            (city, limit_per_city),
        ).fetchall()
        conn.close()
        
        if not rows:
            print(f"  No leads to enrich")
            results_by_city[city] = {"processed": 0, "message": "No leads to enrich"}
            continue
        
        city_processed = 0
        city_owners = 0
        city_mailing = 0
        city_phones = 0
        city_emails = 0
        
        address_city_pairs = [(row["address"], row["city"]) for row in rows]
        enrichment_results = await owner_enrichment.enrich_batch(address_city_pairs)
        
        for row in rows:
            key = f"{row['city']}:{row['address']}"
            enrich_result = enrichment_results.get(key)
            
            updates = {}
            if enrich_result and enrich_result.get("owner_name"):
                updates["owner_name"] = enrich_result["owner_name"]
                city_owners += 1
            if enrich_result and enrich_result.get("mailing_address"):
                updates["mailing_address"] = enrich_result["mailing_address"]
                city_mailing += 1
            
            # Skip trace for phone/email (only if we have owner_name)
            if enrich_result and enrich_result.get("owner_name"):
                phone = await skip_trace_service.find_owner_phone(
                    row["address"], enrich_result["owner_name"], row["city"]
                )
                email = await skip_trace_service.find_owner_email(
                    row["address"], enrich_result["owner_name"], row["city"]
                )
                if phone:
                    updates["owner_phone"] = phone
                    city_phones += 1
                if email:
                    updates["owner_email"] = email
                    city_emails += 1
            
            if updates:
                for field, value in updates.items():
                    if field == "owner_name":
                        dbmod.DatabaseService().update_owner(row["id"], value)
                    elif field == "mailing_address":
                        dbmod.DatabaseService().update_mailing_address(row["id"], value)
                    elif field == "owner_phone":
                        dbmod.DatabaseService().update_owner_phone(row["id"], value)
                    elif field == "owner_email":
                        dbmod.DatabaseService().update_owner_email(row["id"], value)
                city_processed += 1
            
            total_processed += 1
        
        results_by_city[city] = {
            "processed": city_processed,
            "owners_found": city_owners,
            "mailing_found": city_mailing,
            "phones_found": city_phones,
            "emails_found": city_emails,
        }
        
        total_owners_found += city_owners
        total_mailing_found += city_mailing
        total_phones_found += city_phones
        total_emails_found += city_emails
    
    print(f"\n=== RESUMO ===")
    print(f"Total processados: {total_processed}")
    print(f"Owners encontrados: {total_owners_found}")
    print(f"Mailing addresses: {total_mailing_found}")
    print(f"Phones: {total_phones_found}")
    print(f"Emails: {total_emails_found}")
    print(f"Por cidade: {results_by_city}")

asyncio.run(enrich_all(50))