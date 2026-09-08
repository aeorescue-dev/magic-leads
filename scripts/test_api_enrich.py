import sys
sys.path.insert(0, 'C:\\Users\\Fabio\\Documents\\Default Project\\garimpador-leads')
import asyncio
from backend.services import db as dbmod
from backend.services.enrichment import owner_enrichment

async def test():
    conn = dbmod.get_connection()
    rows = conn.execute(
        "SELECT id, address, city FROM leads "
        "WHERE (owner_name IS NULL OR owner_name = '') AND city = ? "
        "ORDER BY date_reported DESC LIMIT ?",
        ('NYC', 3),
    ).fetchall()
    conn.close()
    
    print(f"Found {len(rows)} leads")
    for row in rows:
        print(f"  Lead {row['id']}: {row['address']}")
        result = await owner_enrichment.enrich(row['address'], row['city'])
        if result and result.get('owner_name'):
            print(f"    Found owner: {result['owner_name']}")
        else:
            print(f"    No owner found")

asyncio.run(test())