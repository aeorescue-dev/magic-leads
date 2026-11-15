from backend.scripts.import_ma_licenses import _norm_header, load_rows


def test_norm_header():
    assert _norm_header("License Number") == "license_number"
    assert _norm_header("Business Name") == "business_name"
    assert _norm_header("  City/Town  ") == "city_town"


def test_load_rows_normalizes_opsi_csv(tmp_path):
    path = tmp_path / "opsi.csv"
    path.write_text(
        "License Number,Business Name,City,State,License Type\n"
        "CS-123,Acme Roofing LLC,Boston,MA,Construction Supervisor\n"
        "HIC-456,Build Right Inc,Cambridge,MA,Home Improvement Contractor\n",
        encoding="utf-8",
    )
    records, skipped = load_rows(str(path))
    assert skipped == 0
    assert len(records) == 2
    first = records[0]
    assert first["legal_name"] == "Acme Roofing LLC"
    assert first["city"] == "BOSTON"
    assert first["state"] == "MA"
    assert first["license"] == "CS-123"
    assert first["license_type"] == "Construction Supervisor"
    assert first["source"] == "ma_licensing_csv"
