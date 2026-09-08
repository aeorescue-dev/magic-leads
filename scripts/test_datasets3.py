import httpx, json, asyncio

async def test_dallas_alt():
    print("=== DALLAS jk5c-7csb ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://www.dallasopendata.com/resource/jk5c-7csb.json', params={'$limit': '3'})
        print(f"Status: {r.status_code}")
        data = r.json()
        if isinstance(data, list) and data:
            keys = sorted(data[0].keys())
            print(f"All keys ({len(keys)}):")
            for k in keys:
                print(f"  {k}: {data[0][k]}")

async def test_norfolk_assessment():
    print("\n=== NORFOLK qva7-tzrf (FY27) ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.norfolk.gov/resource/qva7-tzrf.json', params={'$limit': '3'})
        print(f"Status: {r.status_code}")
        data = r.json()
        if isinstance(data, list) and data:
            keys = sorted(data[0].keys())
            owner_keys = [k for k in keys if any(x in k.lower() for x in ['own', 'mail', 'phone', 'email', 'addr'])]
            print(f"Owner/contact fields: {owner_keys}")
            for k in owner_keys:
                print(f"  {k}: {data[0][k]}")
            print(f"All keys ({len(keys)}): {keys[:30]}")

async def test_norfolk_delinquent():
    print("\n=== NORFOLK 7qie-z5gv (Delinquent) ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.norfolk.gov/resource/7qie-z5gv.json', params={'$limit': '3'})
        print(f"Status: {r.status_code}")
        data = r.json()
        if isinstance(data, list) and data:
            keys = sorted(data[0].keys())
            owner_keys = [k for k in keys if any(x in k.lower() for x in ['own', 'mail', 'phone', 'email', 'addr'])]
            print(f"Owner/contact fields: {owner_keys}")
            for k in owner_keys:
                print(f"  {k}: {data[0][k]}")

async def test_nyc_proper_match():
    print("\n=== NYC PROPER MATCH TEST ===")
    base = 'https://data.cityofnewyork.us/resource/8y4t-faws.json'
    async with httpx.AsyncClient(timeout=30) as c:
        # Try with number as integer (no quotes)
        r = await c.get(base, params={
            '$where': "housenum_lo = 2563 AND street_name like '%TIEMANN%'",
            '$limit': '3',
            '$select': 'owner,housenum_lo,street_name,zip_code'
        })
        print(f"Status: {r.status_code}")
        data = r.json()
        if isinstance(data, list):
            print(f"Found: {len(data)}")
            for d in data:
                print(f"  {d}")
        
        # Try street only
        r2 = await c.get(base, params={
            '$where': "street_name like '%TIEMANN%'",
            '$limit': '5',
            '$select': 'owner,housenum_lo,street_name,zip_code'
        })
        print(f"\nStreet only - Status: {r2.status_code}")
        data2 = r2.json()
        if isinstance(data2, list):
            print(f"Found: {len(data2)}")
            for d in data2:
                print(f"  {d}")

async def test_boston_arcgis():
    print("\n=== BOSTON ARCGIS ===")
    async with httpx.AsyncClient(timeout=30) as c:
        # Boston uses ArcGIS Open Data
        try:
            r = await c.get('https://bostonopendata-boston.opendata.arcgis.com/api/views.json')
            data = r.json()
            prop = [d for d in data if 'propert' in d.get('name', '').lower() or 'parcel' in d.get('name', '').lower() or 'assess' in d.get('name', '').lower()]
            for d in prop[:10]:
                print(f"  {d.get('id')}: {d.get('name')}")
        except Exception as e:
            print(f"Error: {e}")

asyncio.run(test_dallas_alt())
asyncio.run(test_norfolk_assessment())
asyncio.run(test_norfolk_delinquent())
asyncio.run(test_nyc_proper_match())
asyncio.run(test_boston_arcgis())