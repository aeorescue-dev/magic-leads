import httpx, json, asyncio

async def test_nyc():
    print("=== NYC 8y4t-faws ===")
    base = 'https://data.cityofnewyork.us/resource/8y4t-faws.json'
    async with httpx.AsyncClient(timeout=30) as c:
        # Try without params
        r = await c.get(base)
        print(f"Status: {r.status_code}")
        data = r.json()
        print(f"Type: {type(data)}")
        if isinstance(data, list):
            print(f"Length: {len(data)}")
            if data:
                print(f"Keys: {sorted(data[0].keys())}")
                for k, v in sorted(data[0].items()):
                    print(f"  {k}: {v}")
        else:
            print(f"Data: {str(data)[:500]}")

async def test_dallas():
    print("\n=== DALLAS SEARCH ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://www.dallasopendata.com/api/views.json')
        data = r.json()
        prop = [d for d in data if 'propert' in d.get('name', '').lower() or 'assess' in d.get('name', '').lower() or 'owner' in d.get('name', '').lower() or 'account' in d.get('name', '').lower()]
        for d in prop[:15]:
            print(f"  {d.get('id')}: {d.get('name')}")

async def test_boston():
    print("\n=== BOSTON assessing-online ===")
    async with httpx.AsyncClient(timeout=30) as c:
        # Try Socrata format
        r = await c.get('https://data.boston.gov/resource/assessing-online.json', params={'$limit': '2'})
        print(f"Status: {r.status_code}")
        data = r.json()
        if isinstance(data, list) and data:
            print(f"Keys: {sorted(data[0].keys())}")
            owner_keys = [k for k in data[0].keys() if any(x in k.lower() for x in ['own', 'mail', 'phone', 'email', 'addr'])]
            print(f"Owner fields: {owner_keys}")

async def test_norfolk():
    print("\n=== NORFOLK SEARCH ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.norfolk.gov/api/views.json')
        data = r.json()
        prop = [d for d in data if 'propert' in d.get('name', '').lower() or 'tax' in d.get('name', '').lower() or 'delinquent' in d.get('name', '').lower()]
        for d in prop[:15]:
            print(f"  {d.get('id')}: {d.get('name')}")

async def test_nyc_fulltext():
    print("\n=== NYC FULLTEXT SEARCH ===")
    base = 'https://data.cityofnewyork.us/resource/8y4t-faws.json'
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(base, params={'$q': 'FIELDSTON', '$limit': '3'})
        print(f"Status: {r.status_code}")
        data = r.json()
        if isinstance(data, list):
            print(f"Found: {len(data)}")
            for d in data[:3]:
                print(f"  {d.get('owner')}: {d.get('housenum_lo')} {d.get('street_name')}")

asyncio.run(test_nyc())
asyncio.run(test_dallas())
asyncio.run(test_boston())
asyncio.run(test_norfolk())
asyncio.run(test_nyc_fulltext())