"""Fase 2.2: extratores de empreiteiros (NYC, Chicago, Boston)."""

from __future__ import annotations

import pytest

from backend.services.contractor_ingest import (
    extract_boston_permits,
    extract_chicago_permits,
    extract_dallas_permits,
    extract_nyc_permits,
)


def test_nyc_extrai_empresa_licenca_e_fonte():
    rows = [
        {
            "job_filing_number": "J1",
            "work_permit": "P1",
            "applicant_business_name": "Walsh Group LLC",
            "applicant_license": "GC-123",
        },
        {
            "job_filing_number": "J2",
            "applicant_business_name": "UNAVAILABLE OWNER",
        },
        {"job_filing_number": "J3", "applicant_business_name": "Turner Construction"},
    ]
    out = extract_nyc_permits(rows)
    assert len(out) == 2
    assert out[0]["legal_name"] == "Walsh Group LLC"
    assert out[0]["license"] == "GC-123"
    assert out[0]["role"] == "contractor"
    assert out[0]["external_id"] == "J1~P1"
    assert all(r["source"] == "nyc_dob_permits" for r in out)


def test_chicago_so_contratantes_e_separa_licenca_do_nome():
    row = {
        "id": "B1",
        "contact_1_type": "ARCHITECT",
        "contact_1_name": "SULLIVAN, MARK J",
        "contact_2_type": "CONTRACTOR-ELECTRICAL",
        "contact_2_name": "CURRAGH ELECTRIC CO.",
        "contact_3_type": "CONTRACTOR-PLUMBER/PLUMBING",
        "contact_3_name": "PL058130279-LONE STAR PLUMBING",
        "contact_4_type": "OWNER",
        "contact_4_name": "2622 NHALSTED ST LLC",
        "contact_5_type": "MASON - BRICK AND CONCRETE",
        "contact_5_name": "WINDY CITY MASONRY, INC.",
        "contact_6_type": "ELECTRICAL CONTRACTOR",
        "contact_6_name": "BRIGHTLINE ELECTRIC INC",
        "contact_7_type": "OWNER AS GENERAL CONTRACTOR",
        "contact_7_name": "SELF BUILDER LLC",
    }
    out = extract_chicago_permits([row])
    names = {r["legal_name"] for r in out}
    assert "CURRAGH ELECTRIC CO." in names
    assert "LONE STAR PLUMBING" in names
    assert "WINDY CITY MASONRY, INC." in names
    assert "BRIGHTLINE ELECTRIC INC" in names
    assert "2622 NHALSTED ST LLC" not in names  # owner não é alvo
    assert "SULLIVAN, MARK J" not in names
    plumbing = next(r for r in out if r["legal_name"] == "LONE STAR PLUMBING")
    assert plumbing["license"] == "PL058130279"
    assert all(r["source"] == "chi_permits" for r in out)


def test_dallas_separa_nome_da_morada_e_telefone():
    rows = [
        {"permit_number": "P1",
         "contractor": "ALL MASTERS PLUMBING 7501 US HWY 287, SuiteC4, ARLINGTON, TX 76001 (817) 969-5050"},
        {"permit_number": "P2",
         "contractor": "ACM PLUMBING CO. PO BOX 210864, DALLAS, TX 75211 (469) 360-6479"},
        {"permit_number": "P3",
         "contractor": "JOHN SMITH 123 MAIN ST, DALLAS, TX 75201 (214) 555-0101"},
        {"permit_number": "P4",
         "contractor": "HARVEY CONSTRUCTION 113 SCENIC DR, HEATH, TX 75032 (469) 438-7316"},
    ]
    out = extract_dallas_permits(rows)
    assert [r["legal_name"] for r in out] == [
        "ALL MASTERS PLUMBING",
        "ACM PLUMBING CO.",
        "HARVEY CONSTRUCTION",
    ]
    assert all(r["source"] == "dallas_permits" for r in out)
    assert all(r["city"] == "DALLAS" and r["state"] == "TX" for r in out)


def test_boston_so_empresas_nao_pessoas():
    rows = [
        {"permitnumber": "A1", "applicant": "ACME CONSTRUCTION LLC"},
        {"permitnumber": "A2", "applicant": "MICHEAL TOBIN"},
        {"permitnumber": "A3", "applicant": "NAPLES CONSTRUCTION CO INC"},
        {"permitnumber": "A4", "applicant": "JOHN QUINCI"},
    ]
    out = extract_boston_permits(rows)
    assert [r["legal_name"] for r in out] == [
        "ACME CONSTRUCTION LLC",
        "NAPLES CONSTRUCTION CO INC",
    ]
    assert all(r["source"] == "boston_permits" for r in out)


@pytest.mark.asyncio
async def test_record_entities_deduplica_na_bd():
    from backend.main import _record_contractor_entities
    from backend.services.db import db_service, get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM contractor_entity_sources")
        conn.execute("DELETE FROM contractor_entities")
        conn.commit()
    finally:
        conn.close()

    records = extract_nyc_permits(
        [
            {
                "job_filing_number": "D1",
                "work_permit": "P1",
                "applicant_business_name": "Dedupe Construction LLC",
                "applicant_license": "GC-999",
            },
            {
                "job_filing_number": "D2",
                "work_permit": "P2",
                "applicant_business_name": "DEDUPE CONSTRUCTION, L.L.C.",
                "applicant_license": "GC-999",
            },
        ]
    )
    result = await _record_contractor_entities(records)
    assert result["saved"] == 2
    assert db_service._service.contractor_entity_counts("NYC")["total"] == 1

    conn = get_connection()
    try:
        conn.execute("DELETE FROM contractor_entity_sources")
        conn.execute("DELETE FROM contractor_entities")
        conn.commit()
    finally:
        conn.close()
