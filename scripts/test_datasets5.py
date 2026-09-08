import httpx, json, asyncio

async def test_boston_property_assessment():
    print("=== BOSTON property-assessment ===")
    async with httpx.AsyncClient(timeout=30) as c:
        # Use CKAN datastore_search
        r = await c.get('https://data.boston.gov/api/3/action/datastore_search', params={
            'resource_id': 'property-assessment', 
            'limit': '3'
        })
        print(f"Status: {r.status_code}")
        data = r.json()
        if data.get('success'):
            fields = data['result']['fields']
            for f in fields:
                name = f.get('id', '')
                if any(x in name.lower() for x in ['own', 'mail', 'phone', 'email', 'addr', 'street', 'zip']):
                    print(f"  {name}: {f.get('type')}")
            if data['result']['records']:
                print(f"\nSample record:")
                for k, v in data['result']['records'][0].items():
                    if any(x in k.lower() for x in ['own', 'mail', 'phone', 'email', 'addr', 'street', 'zip']):
                        print(f"  {k}: {v}")

async def test_nyc_acris_search():
    print("\n=== NYC ACRIS SEARCH ===")
    async with httpx.AsyncClient(timeout=30) as c:
        # Search for ACRIS datasets
        r = await c.get('https://data.cityofnewyork.us/api/views.json')
        data = r.json()
        acris = [d for d in data if 'acris' in d.get('name', '').lower() or 'property record' in d.get('name', '').lower() or 'deed' in d.get('name', '').lower()]
        for d in acris[:10]:
            print(f"  {d.get('id')}: {d.get('name')}")

async def test_nyc_dob_search():
    print("\n=== NYC DOB SEARCH ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.cityofnewyork.us/api/views.json')
        data = r.json()
        dob = [d for d in data if 'dob' in d.get('name', '').lower() or 'permit' in d.get('name', '').lower() or 'building' in d.get('name', '').lower()]
        for d in dob[:10]:
            print(f"  {d.get('id')}: {d.get('name')}")

async def test_nyc_voter_search():
    print("\n=== NYC VOTER SEARCH ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.cityofnewyork.us/api/views.json')
        data = r.json()
        voter = [d for d in data if 'voter' in d.get('name', '').lower() or 'registration' in d.get('name', '').lower() or 'boe' in d.get('name', '').lower()]
        for d in voter[:10]:
            print(f"  {d.get('id')}: {d.get('name')}")

async def test_nyc_number_match_variations():
    print("\n=== NYC NUMBER MATCH VARIATIONS ===")
    base = 'https://data.cityofnewyork.us/resource/8y4t-faws.json'
    async with httpx.AsyncClient(timeout=30) as c:
        # Test different query formats
        tests = [
            ("housenum_lo = '2563'", "housenum_lo = '2563' AND street_name like '%TIEMANN%'"),
            ("housenum_lo = 2563", "housenum_lo = 2563 AND street_name like '%TIEMANN%'"),
            ("CAST(housenum_lo AS INTEGER) = 2563", "CAST(housenum_lo AS INTEGER) = 2563 AND street_name like '%TIEMANN%'"),
        ]
        for name, where in tests:
            try:
                r = await c.get(base, params={'$where': where, '$limit': '1', '$select': 'owner,housenum_lo,street_name'})
                print(f"  {name}: Status {r.status_code}, Found {len(r.json()) if isinstance(r.json(), list) else 'N/A'}")
            except Exception as e:
                print(f"  {name}: Error {e}")

asyncio.run(test_boston_property_assessment())
asyncio.run(test_nyc_acris_search())
asyncio.run(test_nyc_dob_search())
asyncio.run(test_nyc_voter_search())
asyncio.run(test_nyc_number_match_variations())