import asyncio
from backend.services.enrichment import owner_enrichment

async def test():
    result = await owner_enrichment.enrich('3727 FIELDSTON ROAD, NYC, NY', 'NYC')
    print('Result:', result)

asyncio.run(test())