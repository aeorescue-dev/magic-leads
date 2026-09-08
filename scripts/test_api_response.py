import httpx, asyncio, json

async def test():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('http://127.0.0.1:8000/api/leads/today?city=Boston&include_incomplete=true&limit=3')
        print(f'Status: {r.status_code}')
        data = r.json()
        for lead in data['leads'][:2]:
            print(f'  ID: {lead["id"]}')
            print(f'    address: {lead["address"]}')
            print(f'    owner_name: {lead.get("owner_name")}')
            print(f'    mailing_address: {lead.get("mailing_address")}')
            print(f'    owner_phone: {lead.get("owner_phone")}')
            print(f'    owner_email: {lead.get("owner_email")}')

asyncio.run(test())