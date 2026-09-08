import httpx, asyncio, json

async def test():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('http://127.0.0.1:8000/api/leads/recent?limit=20')
        print('Status:', r.status_code)
        data = r.json()
        print(f'Total: {data["total"]}, Leads: {len(data["leads"])}')
        for lead in data['leads'][:3]:
            print(f'  {lead["id"]}: {lead["city"]} - {lead["issue_category"]} - {lead["issue_description"][:50]}')
            print(f'    Address: {lead["address"][:80]}')

asyncio.run(test())