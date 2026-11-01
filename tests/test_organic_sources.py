"""Licencas publicas (NYC DCWP) e extract OSM: extratores puros."""
from __future__ import annotations

import pytest

from backend.services.licensing_sources import extract_nyc_licenses
from backend.services.osm_extract import (
    _in_bbox,
    build_entity,
    is_contractor_poi,
)


def test_nyc_license_extrai_empresa_telefone_e_licenca():
    rows = [
        {
            "business_name": "TRI-BORO INSULATING & ROOFING COMPANY, INC.",
            "license_nbr": "0673029-DCA",
            "contact_phone": "(718) 792-9100",
            "address_city": "BRONX",
            "address_state": "NY",
        },
        {
            "business_name": "AGREST ALUMINUM & SHADE CO. INC.",
            "license_nbr": "0673525-DCA",
            "contact_phone": "718-835-5658",
        },
        {"business_name": "N/A", "license_nbr": "1", "contact_phone": "123"},
        {"business_name": "", "license_nbr": "2"},
    ]
    out = extract_nyc_licenses(rows)
    assert len(out) == 2
    assert out[0]["phone"] == "7187929100"
    assert out[0]["city"] == "NYC" and out[0]["state"] == "NY"
    assert out[0]["source"] == "nyc_dcwp"
    assert out[0]["license"] == "0673029-DCA"
    assert out[1]["phone"] == "7188355658"


def test_nyc_license_telefone_invalido_fica_none():
    out = extract_nyc_licenses([
        {"business_name": "ACME CONSTRUCTION LLC", "license_nbr": "X1",
         "contact_phone": "555"},
    ])
    assert out and out[0]["phone"] is None


@pytest.mark.asyncio
async def test_record_entities_deduplica_e_guarda_telefone():
    from backend.services.contractor_ingest import record_entities
    from backend.services.db import db_service, get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM contractor_entity_sources WHERE entity_id IN "
                     "(SELECT id FROM contractor_entities WHERE city='TESTORG')")
        conn.execute("DELETE FROM contractor_entities WHERE city='TESTORG'")
        conn.commit()
    finally:
        conn.close()
    records = [
        {"legal_name": "ACME PLUMBING LLC", "city": "TESTORG", "state": "NY",
         "role": "contractor", "license": "L1", "source": "nyc_dcwp",
         "external_id": "L1", "phone": "7185550100"},
        {"legal_name": "ACME PLUMBING LLC", "city": "TESTORG", "state": "NY",
         "role": "contractor", "license": "L1", "source": "nyc_dcwp",
         "external_id": "L1", "phone": "7185550100"},
    ]
    result = await record_entities(records)
    assert result["saved"] == 1
    rows = db_service._service.list_contractor_entities("TESTORG")
    assert len(rows) == 1
    assert rows[0]["phone"] == "7185550100"
    assert rows[0]["license"] == "L1"


@pytest.mark.asyncio
async def test_fila_prioriza_quem_tem_telefone_e_licenca():
    from backend.services.db import db_service, get_connection

    svc = db_service._service
    conn = get_connection()
    try:
        conn.execute("DELETE FROM contractor_entities WHERE city='TESTORG'")
        conn.commit()
    finally:
        conn.close()
    svc.upsert_contractor_entity("PLAIN CONTRACTING", "TESTORG", state="NY",
                                 role="contractor")
    svc.upsert_contractor_entity("LICENSED CONTRACTING", "TESTORG", state="NY",
                                 role="contractor", license="L2")
    svc.upsert_contractor_entity("PHONE CONTRACTING", "TESTORG", state="NY",
                                 role="contractor", license="L3",
                                 phone="7185550199")
    jobs = svc.list_entities_for_domain("TESTORG", limit=3)
    assert [j["legal_name"] for j in jobs] == [
        "PHONE CONTRACTING", "LICENSED CONTRACTING", "PLAIN CONTRACTING",
    ]
    conn = get_connection()
    try:
        conn.execute("DELETE FROM contractor_entity_sources WHERE entity_id IN "
                     "(SELECT id FROM contractor_entities WHERE city='TESTORG')")
        conn.execute("DELETE FROM contractor_entities WHERE city='TESTORG'")
        conn.commit()
    finally:
        conn.close()


def test_osm_reconhece_oficios_e_ignora_resto():
    assert is_contractor_poi({"craft": "plumber", "name": "A"})
    assert is_contractor_poi({"office": "construction_company"})
    assert not is_contractor_poi({"office": "company"})
    assert not is_contractor_poi({"shop": "supermarket"})
    assert not is_contractor_poi({"amenity": "cafe"})


def test_osm_build_entity_com_site_e_telefone():
    ent = build_entity(
        {"name": "Hogan Plumbing", "craft": "plumber",
         "website": "https://www.hoganplumbing.com/", "phone": "+1 773 555 0100"},
        "CHICAGO",
    )
    assert ent and ent["domain"] == "hoganplumbing.com"
    assert ent["state"] == "IL" and ent["city"] == "CHICAGO"
    assert ent["phone"] == "+1 773 555 0100"


def test_osm_build_entity_rejeita_diretorio_sem_nome():
    assert build_entity({"craft": "plumber"}, "NYC") is None
    ent = build_entity(
        {"name": "Acme Roofing", "craft": "roofer",
         "website": "https://www.yelp.com/biz/acme"},
        "NYC",
    )
    assert ent is not None and ent["domain"] is None


def test_osm_bbox_filtra_estado_inteiro():
    assert _in_bbox("BOSTON", 42.36, -71.06) is True
    assert _in_bbox("BOSTON", 42.60, -72.50) is False  # western MA
    assert _in_bbox("NYC", 40.75, -73.98) is True
