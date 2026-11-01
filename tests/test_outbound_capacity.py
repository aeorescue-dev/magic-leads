"""Cartao Capacidade vs Inventario: estoque, fluxo e cobertura."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.db import db_service, get_connection

CITY = "BOSTON"


def _clean():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM contractor_entities WHERE entity_key LIKE 'cap-%'")
        conn.execute("DELETE FROM sending_mailboxes WHERE email = 'cap-test@example.com'")
        conn.commit()
    finally:
        conn.close()


def test_endpoint_exige_admin():
    client = TestClient(app)
    assert client.get("/api/admin/outbound/capacity").status_code in (401, 403)


def test_capacidade_vs_inventario():
    _clean()
    svc = db_service._service
    before = svc.outbound_capacity(7)
    svc.upsert_sending_mailbox(
        email="cap-test@example.com", provider="gmail", transport="gmail_api",
        daily_cap=10, enabled=1,
    )
    conn = get_connection()
    try:
        for i in range(6):
            conn.execute(
                "INSERT INTO contractor_entities "
                "(entity_key, legal_name, normalized_name, city, state, email, "
                "status, bridged_at) "
                "VALUES (?, ?, ?, ?, 'MA', ?, 'ready', CURRENT_TIMESTAMP)",
                (f"cap-{i}", f"Ready Co {i}", f"ready co {i}", CITY,
                 f"ready{i}@cap-test.com"),
            )
        conn.commit()
    finally:
        conn.close()

    after = svc.outbound_capacity(7)
    boston_before = next(c for c in before["cities"] if c["city"] == CITY)
    boston_after = next(c for c in after["cities"] if c["city"] == CITY)
    # `produced` = fluxo do robo (entidades com e-mail que passaram a ready).
    assert boston_after["produced"] >= boston_before["produced"] + 6
    assert after["capacity_per_day"] >= before["capacity_per_day"] + 10
    assert after["days_of_cover"] is None or after["days_of_cover"] >= 0
    _clean()
