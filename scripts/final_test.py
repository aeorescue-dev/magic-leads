import httpx, asyncio, json

async def test():
    async with httpx.AsyncClient(timeout=30) as c:
        # Test stats
        r = await c.get('http://127.0.0.1:8000/api/leads/stats')
        print('Stats:', r.status_code)
        data = r.json()
        print(f'  Total: {data["total"]}, With Owner: {data["with_owner"]}')
        print(f'  Categories: {data["by_category"]}')
        
        # Test cities
        r = await c.get('http://127.0.0.1:8000/api/leads/cities')
        print('Cities:', r.json())
        
        # Test recent
        r = await c.get('http://127.0.0.1:8000/api/leads/recent?limit=3')
        data = r.json()
        print(f'Recent leads: {len(data["leads"])}')
        for lead in data['leads']:
            print(f'  {lead["id"]}: {lead["city"]} - {lead["issue_category"]} - {lead["issue_description"][:50]}')

asyncio.run(test())