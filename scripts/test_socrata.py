import httpx, asyncio

async def test():
    async with httpx.AsyncClient(timeout=30) as c:
        # Test the exact query being used
        r = await c.get('https://data.cityofnewyork.us/resource/8y4t-faws.json', params={
            '$select': 'owner,housenum_lo,street_name,zip_code',
            '$limit': '5',
            '$where': "street_name like '%FIELDSTON%' AND housenum_lo = '3727'"
        })
        print('Status:', r.status_code)
        data = r.json()
        print('Found:', len(data))
        for d in data:
            print('  ', d)

asyncio.run(test())