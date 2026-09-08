import httpx, asyncio

async def test_enrichment_steps():
    address = '3727 FIELDSTON ROAD, NYC, NY'
    city = 'NYC'
    
    # Parse address
    part = address.split(",")[0].strip()
    p = part.split(" ", 1)
    num = p[0].strip()
    street = p[1].strip()
    print(f"Parsed: num={num}, street={street}")
    
    # Normalize street
    _SUFFIX = {
        "STREET": "ST", "AVENUE": "AVE", "PLACE": "PL", "ROAD": "RD",
        "BOULEVARD": "BLVD", "LANE": "LN", "DRIVE": "DR", "TERRACE": "TER",
        "PARKWAY": "PKWY", "COURT": "CT", "SQUARE": "SQ", "HIGHWAY": "HWY",
        "CIRCLE": "CIR", "WAY": "WAY", "DR": "DR", "LN": "LN",
    }
    s = street.upper()
    words = s.split()
    out = []
    for w in words:
        cleaned = w.replace(".", "")
        if cleaned in _SUFFIX:
            cleaned = _SUFFIX[cleaned]
        out.append(cleaned)
    street_norm = " ".join(out)
    print(f"Normalized street: {street_norm}")
    
    # NYC config
    cfg = {
        "domain": "data.cityofnewyork.us",
        "dataset": "8y4t-faws",
        "owner_col": "owner",
        "num_col": "housenum_lo",
        "street_col": "street_name",
        "zip_col": "zip_code",
        "mailing_addr_col": None,
        "mailing_city_col": None,
        "mailing_zip_col": None,
        "type": "socrata",
        "number_as_string": True,
    }
    
    select_cols = [cfg["owner_col"], cfg["num_col"], cfg["street_col"], cfg["zip_col"]]
    sel = ",".join(select_cols)
    base = f"https://{cfg['domain']}/resource/{cfg['dataset']}.json"
    
    queries = []
    queries.append(f"{cfg['street_col']} like '%{street_norm}%' AND {cfg['num_col']} = '{num}'")
    queries.append(f"{cfg['street_col']} like '%{street_norm}%'")
    
    async with httpx.AsyncClient(timeout=30) as client:
        for i, where in enumerate(queries):
            print(f"\nQuery {i+1}: {where}")
            try:
                resp = await client.get(base, params={"$select": sel, "$limit": "5", "$where": where})
                print(f"  Status: {resp.status_code}")
                data = resp.json()
                print(f"  Found: {len(data)}")
                for d in data:
                    print(f"  {d}")
            except Exception as e:
                print(f"  Error: {e}")

asyncio.run(test_enrichment_steps())