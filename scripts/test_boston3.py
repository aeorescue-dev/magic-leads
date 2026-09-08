import httpx, json, asyncio

async def test_boston_resource():
    resource_id = 'bdb17c2b-e9ab-44e4-a070-bf804a0e1a7f'  # Property Assessment 2015
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.boston.gov/api/3/action/datastore_search', params={'resource_id': resource_id, 'limit': '3'})
        print('Status:', r.status_code)
        data = r.json()
        if data.get('success'):
            fields = data['result']['fields']
            print('All fields:')
            for f in fields:
                name = f.get('id', '')
                if any(x in name.lower() for x in ['own', 'mail', 'phone', 'email', 'addr', 'street', 'zip', 'unit', 'city', 'state']):
                    print(f'  {name}: {f.get("type")}')
            if data['result']['records']:
                print('\nSample:')
                for k, v in data['result']['records'][0].items():
                    if any(x in k.lower() for x in ['own', 'mail', 'phone', 'email', 'addr', 'street', 'zip', 'unit', 'city', 'state']):
                        print(f'  {k}: {v}')

asyncio.run(test_boston_resource())