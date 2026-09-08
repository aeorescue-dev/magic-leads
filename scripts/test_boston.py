import httpx, json, asyncio

async def test_boston():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.boston.gov/api/3/action/datastore_search', params={'resource_id': 'property-assessment', 'limit': '3'})
        print('Status:', r.status_code)
        data = r.json()
        if data.get('success'):
            fields = data['result']['fields']
            for f in fields:
                name = f.get('id', '')
                if any(x in name.lower() for x in ['own', 'mail', 'phone', 'email', 'addr', 'street', 'zip', 'unit']):
                    print(f'  {name}: {f.get("type")}')
            if data['result']['records']:
                print('\nSample:')
                for k, v in data['result']['records'][0].items():
                    if any(x in k.lower() for x in ['own', 'mail', 'phone', 'email', 'addr', 'street', 'zip', 'unit']):
                        print(f'  {k}: {v}')

asyncio.run(test_boston())