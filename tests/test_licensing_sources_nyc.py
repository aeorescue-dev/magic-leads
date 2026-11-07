"""Extratores NYC DOB e DSNY/BIC: trade explícito e telefone."""
from __future__ import annotations

from backend.services import licensing_sources as src


def test_dob_master_plumber_entra_com_niche_key():
    rows = [
        {
            "license_status": "ACTIVE",
            "business_name": "Paragon Plumbing & Heating",
            "license_number": "2643",
            "license_type": "MASTER PLUMBER",
            "business_phone_number": "7182312639",
            "license_business_city": "BR",
            "business_state": "NY",
        }
    ]
    out = src.extract_nyc_dob_licenses(rows)
    assert len(out) == 1
    assert out[0]["niche_key"] == "plumbing"
    assert out[0]["phone"] == "7182312639"
    assert out[0]["city"] == "NYC"


def test_dob_ignora_inativo_sem_telefone_e_tipo_desconhecido():
    rows = [
        {
            "license_status": "INACTIVE",
            "business_name": "Old Plumber",
            "license_number": "1",
            "license_type": "MASTER PLUMBER",
            "business_phone_number": "7180000000",
        },
        {
            "license_status": "ACTIVE",
            "business_name": "No Phone Electric",
            "license_number": "2",
            "license_type": "ELECTRICAL FIRM",
            "business_phone_number": "",
        },
        {
            "license_status": "ACTIVE",
            "business_name": "Some Rigger",
            "license_number": "3",
            "license_type": "RIGGER",
            "business_phone_number": "7180000001",
        },
    ]
    assert src.extract_nyc_dob_licenses(rows) == []


def test_dob_elevator_e_sign_hanger():
    rows = [
        {
            "license_status": "ACTIVE",
            "business_name": "Dobe Elevator Inc",
            "license_number": "610078",
            "license_type": "ELEVATOR AGENCY / INSPECTOR",
            "business_phone_number": "2123931111",
        },
        {
            "license_status": "ACTIVE",
            "business_name": "Valles Signs & Awnings",
            "license_number": "219",
            "license_type": "SIGN HANGER",
            "business_phone_number": "3475272599",
        },
    ]
    out = src.extract_nyc_dob_licenses(rows)
    trades = {row["niche_key"] for row in out}
    assert trades == {"elevator", "signage"}


def test_dsny_extrai_debris_e_deduplica():
    rows = [
        {
            "account_name": "Big Apple Junk Removal",
            "bic_number": "BIC-1",
            "phone": "(800) 505-9521",
            "expiration_date": "2099-01-01T00:00:00.000",
            "city": "BROOKLYN",
        },
        {
            "account_name": "Big Apple Junk Removal",
            "bic_number": "BIC-1",
            "phone": "(800) 505-9521",
            "expiration_date": "2099-01-01T00:00:00.000",
            "city": "BROOKLYN",
        },
        {
            "account_name": "Expired Hauler",
            "bic_number": "BIC-2",
            "phone": "(718) 000-0000",
            "expiration_date": "2020-01-01T00:00:00.000",
            "city": "BROOKLYN",
        },
    ]
    out = src.extract_dsny_trade_waste(rows)
    assert len(out) == 1
    assert out[0]["niche_key"] == "debris_removal"
    assert out[0]["license"] == "BIC-1"


def test_upsert_nao_colide_licenca_tdlr_entre_tipos():
    import asyncio

    from backend.services.db import db_service, get_connection

    asyncio.run(
        db_service.upsert_contractor_entity(
            "PURVIS AIR CONDITIONING & REFRIGERATION",
            "DALLAS",
            state="TX",
            license="20724",
            license_type="ac_contractors",
            source="tdlr_tx",
            external_id="tdlr:ac_contractors:20724",
        )
    )
    asyncio.run(
        db_service.upsert_contractor_entity(
            "INTEGRITY COMMERCIAL FLOORING LLC",
            "DALLAS",
            state="TX",
            license="20724",
            license_type="elevator_contractors",
            source="tdlr_tx",
            external_id="tdlr:elevator_contractors:20724",
        )
    )
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT legal_name, license_type FROM contractor_entities "
            "WHERE license='20724' ORDER BY legal_name"
        ).fetchall()
    finally:
        conn.close()
    names = [(r["legal_name"], r["license_type"]) for r in rows]
    assert ("PURVIS AIR CONDITIONING & REFRIGERATION", "ac_contractors") in names
    assert ("INTEGRITY COMMERCIAL FLOORING LLC", "elevator_contractors") in names
