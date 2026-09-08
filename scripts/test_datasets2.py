import httpx, json, asyncio

async def test_dallas():
    print("=== DALLAS ue8j-d4q6 ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://www.dallasopendata.com/resource/ue8j-d4q6.json', params={'$limit': '3'})
        print(f"Status: {r.status_code}")
        data = r.json()
        if isinstance(data, list) and data:
            keys = sorted(data[0].keys())
            print(f"All keys ({len(keys)}):")
            for k in keys:
                print(f"  {k}: {data[0][k]}")

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
                print(f"  {d.get('owner')}: {d.get('housenum_lo')} {d.get('street_name')} {d.get('zip_code')}")

async def test_boston_parcels():
    print("\n=== BOSTON parcels ===")
    async with httpx.AsyncClient(timeout=30) as c:
        # Try different Boston datasets
        for ds in ['parcels-2015', 'assessing-online', 'bostontaxparcel']:
            try:
                r = await c.get(f'https://data.boston.gov/api/views/{ds}/rows.json?limit=2')
                print(f"\n{ds}: Status {r.status_code}")
                if r.status_code == 200:
                    data = r.json()
                    if data.get('data'):
                        cols = [c.get('name','') for c in data['meta']['view']['columns']]
                        owner_cols = [c for c in cols if any(x in c.lower() for x in ['own', 'mail', 'phone', 'email', 'addr'])]
                        print(f"  Owner fields: {owner_cols}")
                        print(f"  All cols ({len(cols)}): {cols[:25]}")
            except Exception as e:
                print(f"  {ds}: {e}")

async def test_norfolk():
    print("\n=== NORFOLK ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.norfolk.gov/api/views.json')
        data = r.json()
        prop = [d for d in data if 'propert' in d.get('name', '').lower() or 'tax' in d.get('name', '').lower() or 'delinquent' in d.get('name', '').lower()]
        for d in prop[:15]:
            print(f"  {d.get('id')}: {d.get('name')}")

async def test_nyc_number_match():
    print("\n=== NYC NUMBER MATCH ===")
    base = 'https://data.cityofnewyork.us/resource/8y4t-faws.json'
    async with httpx.AsyncClient(timeout=30) as c:
        # Try exact number match
        r = await c.get(base, params={
            '$where': "housenum_lo = 2563 AND street_name = 'TIEMANN AVENUE'",
            '$limit': '3',
            '$select': 'owner,housenum_lo,street_name,zip_code'
        })
        print(f"Status: {r.status_code}")
        data = r.json()
        if isinstance(data, list):
            print(f"Found: {len(data)}")
            for d in data:
                print(f"  {d}")

asyncio.run(test_dallas())
asyncio.run(test_nyc_fulltext())
asyncio.run(test_boston_parcels())
asyncio.run(test_norfolk())
asyncio.run(test_nyc_number_match())