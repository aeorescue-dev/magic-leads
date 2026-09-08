import httpx, json, asyncio

async def test_boston_package():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.boston.gov/api/3/action/package_show', params={'id': 'property-assessment'})
        print('Status:', r.status_code)
        data = r.json()
        if data.get('success'):
            pkg = data['result']
            print('Resources:')
            for res in pkg.get('resources', []):
                print(f"  {res.get('id')}: {res.get('name')} - {res.get('format')}")
                if res.get('datastore_active'):
                    print(f"    -> datastore_active: True, resource_id: {res.get('id')}")

asyncio.run(test_boston_package())