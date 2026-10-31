"""Fase 2: normalização, dedupe e ciclo de vida das entidades."""

from __future__ import annotations

import pytest

from backend.services.contractor_entities import (
    entity_key,
    is_usable_company_name,
    normalize_company_name,
    normalize_role,
)
from backend.services.db import db_service, get_connection


@pytest.fixture()
def clean_entities():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM contractor_entity_sources")
        conn.execute("DELETE FROM contractor_entities")
        conn.commit()
    finally:
        conn.close()
    yield
    conn = get_connection()
    try:
        conn.execute("DELETE FROM contractor_entity_sources")
        conn.execute("DELETE FROM contractor_entities")
        conn.commit()
    finally:
        conn.close()


def test_normaliza_sufixos_acentos_e_pontuacao():
    assert normalize_company_name("Ações & Obras, L.L.C.") == "ACOES AND OBRAS"
    assert normalize_company_name("ACME CONSTRUCTION LLC") == "ACME CONSTRUCTION"
    assert normalize_company_name("Turner Construction Company") == "TURNER CONSTRUCTION"
    assert normalize_company_name("  Skender  ") == "SKENDER"
    assert entity_key("Acme Construction LLC", "NY") == entity_key(
        "ACME CONSTRUCTION, L.L.C.", "ny"
    )


def test_rejeita_placeholders():
    assert not is_usable_company_name("UNAVAILABLE OWNER")
    assert not is_usable_company_name("N/A")
    assert not is_usable_company_name("")
    assert is_usable_company_name("Walsh Group LLC")


def test_normaliza_papeis():
    assert normalize_role("General Contractor") == "contractor"
    assert normalize_role("OWNER") == "owner"
    assert normalize_role("Filing Representative") == "expediter"
    assert normalize_role(None) is None


def test_dedupe_por_nome_e_estado(clean_entities):
    svc = db_service._service
    one = svc.upsert_contractor_entity(
        "Acme Construction LLC",
        "NYC",
        state="NY",
        role="contractor",
        source="nyc_dob_permits",
        external_id="job-1",
    )
    two = svc.upsert_contractor_entity(
        "ACME CONSTRUCTION, L.L.C.",
        "NYC",
        state="NY",
        role="applicant",
        source="nyc_dob_permits",
        external_id="job-2",
    )
    assert one and two
    assert one["id"] == two["id"]
    rows = svc.list_contractor_entities(city="NYC")
    assert len(rows) == 1
    assert rows[0]["role"] == "contractor"  # não sobrescreve o primeiro papel
    conn = get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) c FROM contractor_entity_sources WHERE entity_id=?",
            (one["id"],),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert n == 2


def test_licenca_e_chave_forte(clean_entities):
    svc = db_service._service
    a = svc.upsert_contractor_entity(
        "North Build Corp", "NYC", state="NY", license="GC-123"
    )
    b = svc.upsert_contractor_entity(
        "North Builders Inc", "NYC", state="NY", license="GC-123"
    )
    assert a["id"] == b["id"]
    assert svc.contractor_entity_counts("NYC")["total"] == 1


def test_ciclo_domain_e_email(clean_entities):
    svc = db_service._service
    row = svc.upsert_contractor_entity("Wight & Company", "CHICAGO", state="IL")
    assert row["status"] == "new"
    assert svc.set_contractor_entity_domain(row["id"], "wightco.com", 0.9)
    row = svc.list_contractor_entities(city="CHICAGO")[0]
    assert row["domain"] == "wightco.com"
    assert row["status"] == "domain"
    assert svc.set_contractor_entity_email(row["id"], "info@wightco.com", "valid")
    row = svc.list_contractor_entities(city="CHICAGO")[0]
    assert row["status"] == "ready"
    assert svc.set_contractor_entity_email(row["id"], "x@y.com", "catch_all")
    row = svc.list_contractor_entities(city="CHICAGO")[0]
    assert row["status"] == "quarantined"


def test_placeholders_nao_criam_entidade(clean_entities):
    svc = db_service._service
    assert svc.upsert_contractor_entity("UNAVAILABLE OWNER", "NYC", state="NY") is None
    assert svc.contractor_entity_counts("NYC")["total"] == 0
