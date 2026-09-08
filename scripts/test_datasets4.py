import httpx, json, asyncio

async def test_boston_ckan():
    print("=== BOSTON CKAN DATASETS ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.boston.gov/api/3/action/package_search', params={'q': 'property', 'rows': '20'})
        data = r.json()
        if data.get('success'):
            for pkg in data['result']['results'][:15]:
                print(f"  {pkg.get('name')}: {pkg.get('title')}")

async def test_boston_parcels_detail():
    print("\n=== BOSTON parcels DETAIL ===")
    async with httpx.AsyncClient(timeout=30) as c:
        # Try the parcel dataset via datastore_search
        r = await c.get('https://data.boston.gov/api/3/action/datastore_search', params={'resource_id': 'parcels-2015', 'limit': '2'})
        print(f"Status: {r.status_code}")
        data = r.json()
        if data.get('success'):
            fields = data['result']['fields']
            for f in fields:
                name = f.get('id', '')
                if any(x in name.lower() for x in ['own', 'mail', 'phone', 'email', 'addr']):
                    print(f"  {name}: {f.get('type')}")
            if data['result']['records']:
                print(f"Sample: {data['result']['records'][0]}")

async def test_nyc_dob_permits():
    print("\n=== NYC DOB PERMITS (b5qi-6dus) ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://data.cityofnewyork.us/resource/b5qi-6dus.json', params={'$limit': '3'})
        print(f"Status: {r.status_code}")
        data = r.json()
        if isinstance(data, list) and data:
            keys = sorted(data[0].keys())
            contact_keys = [k for k in keys if any(x in k.lower() for x in ['applicant', 'contact', 'phone', 'email', 'owner', 'mail', 'addr'])]
            print(f"Contact/applicant fields: {contact_keys}")
            for k in contact_keys[:15]:
                print(f"  {k}: {data[0][k]}")
            print(f"All keys ({len(keys)}): {keys[:40]}")

async def test_nyc_acris():
    print("\n=== NYC ACRIS (Property Records) ===")
    async with httpx.AsyncClient(timeout=30) as c:
        # ACRIS datasets - there are several
        for ds in ['n5rb-qc6r', 'kr7v-fp5d', '4b8d-7v8b']:  # Known ACRIS dataset IDs
            try:
                r = await c.get(f'https://data.cityofnewyork.us/resource/{ds}.json', params={'$limit': '1'})
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list) and data:
                        keys = sorted(data[0].keys())
                        owner_keys = [k for k in keys if any(x in k.lower() for x in ['party', 'name', 'mail', 'phone', 'email', 'addr'])]
                        print(f"  {ds}: {owner_keys[:15]}")
            except:
                pass

async def test_nyc_number_fixed():
    print("\n=== NYC NUMBER MATCH FIXED ===")
    base = 'https://data.cityofnewyork.us/resource/8y4t-faws.json'
    async with httpx.AsyncClient(timeout=30) as c:
        # Try with string number in where clause
        r = await c.get(base, params={
            '$where': "housenum_lo = '2563' AND street_name like '%TIEMANN%'",
            '$limit': '3',
            '$select': 'owner,housenum_lo,street_name,zip_code'
        })
        print(f"Status: {r.status_code}")
        data = r.json()
        if isinstance(data, list):
            print(f"Found: {len(data)}")
            for d in data:
                print(f"  {d}")

async def test_dallas_dallasopendata():
    print("\n=== DALLAS OPENDATA (separate city?) ===")
    # Our data has "Dallasopendata" as a separate city
    # Check if it's the same as Dallas or different
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://www.dallasopendata.com/resource/vvus-y44q.json', params={'$limit': '2'})
        print(f"vvus-y44q: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                print(f"Keys: {sorted(data[0].keys())}")

asyncio.run(test_boston_ckan())
asyncio.run(test_boston_parcels_detail())
asyncio.run(test_nyc_dob_permits())
asyncio.run(test_nyc_acris())
asyncio.run(test_nyc_number_fixed())
asyncio.run(test_dallas_dallasopendata())