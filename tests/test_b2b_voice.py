"""Fase 1 do módulo de voz B2B: schema, gate can_call e importação."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services import b2b_voice as voice

NOW = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)  # 11:00 em Massachusetts


@pytest.fixture(autouse=True)
def _clean_voice_db(monkeypatch):
    monkeypatch.setenv("VOICE_NOW_ISO", NOW.isoformat())
    voice.init()
    conn = voice.get_conn()
    try:
        for table in (
            "call_attempts",
            "voice_suppressions",
            "dnc_checks",
            "prospect_companies",
            "prospect_sources",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()
    yield


def _csv(
    phone: str = "+16175550123",
    state: str = "MA",
    permits: int = 4,
    company: str = "Example Roofing LLC",
) -> str:
    return (
        "company_name,contact_name,phone,city,state,license_status,trade,"
        "permit_count,permit_value_usd,years_active,employee_estimate\n"
        f"{company},John Smith,{phone},Boston,{state},active,Roofing,"
        f"{permits},250000,12,8\n"
    )


def _company(phone: str) -> dict:
    conn = voice.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM prospect_companies WHERE phone=?", (phone,)
        ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def test_import_dedupe_por_telefone_e_score():
    first = voice.import_licenses_csv(_csv(permits=2))
    assert first["imported"] == 1
    assert first["updated"] == 0

    second = voice.import_licenses_csv(_csv(permits=10))
    assert second["imported"] == 0
    assert second["updated"] == 1

    conn = voice.get_conn()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM prospect_companies"
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()

    company = _company("+16175550123")
    assert company["permit_count"] == 10
    assert company["score"] >= 60
    assert company["entity_type"] == "business"


def test_can_call_fail_closed_sem_dnc():
    voice.import_licenses_csv(_csv())
    company = _company("+16175550123")
    result = voice.can_call(company, now=NOW)
    assert result["allowed"] is False
    assert "dnc_not_checked" in result["reasons"]


def test_can_call_libera_com_dnc_limpo():
    voice.import_licenses_csv(_csv())
    voice.check_dnc("+16175550123", listed=False, source="pytest")
    result = voice.can_call(_company("+16175550123"), now=NOW)
    assert result["allowed"] is True, result
    assert result["reasons"] == []
    assert result["checks"]["within_hours"] is True


def test_can_call_bloqueia_dnc_listado():
    voice.import_licenses_csv(_csv())
    voice.check_dnc("+16175550123", listed=True, source="pytest")
    result = voice.can_call(_company("+16175550123"), now=NOW)
    assert result["allowed"] is False
    assert "dnc_listed" in result["reasons"]


def test_can_call_bloqueia_dnc_expirado():
    voice.import_licenses_csv(_csv())
    voice.check_dnc("+16175550123", listed=False, source="pytest")
    conn = voice.get_conn()
    try:
        conn.execute(
            "UPDATE dnc_checks SET expires_at='2020-01-01T00:00:00+00:00' "
            "WHERE phone=?",
            ("+16175550123",),
        )
        conn.commit()
    finally:
        conn.close()
    result = voice.can_call(_company("+16175550123"), now=NOW)
    assert result["allowed"] is False
    assert "dnc_stale" in result["reasons"]


def test_can_call_bloqueia_supressao_interna():
    voice.import_licenses_csv(_csv())
    voice.check_dnc("+16175550123", listed=False, source="pytest")
    voice.suppress("+16175550123", reason="pedido do contacto")
    result = voice.can_call(_company("+16175550123"), now=NOW)
    assert result["allowed"] is False
    assert "suppressed" in result["reasons"]


def test_can_call_bloqueia_fora_do_horario():
    voice.import_licenses_csv(_csv())
    voice.check_dnc("+16175550123", listed=False, source="pytest")
    outside = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)  # 22:00 ET
    result = voice.can_call(_company("+16175550123"), now=outside)
    assert result["allowed"] is False
    assert "outside_hours" in result["reasons"]


def test_can_call_bloqueia_estado_fora_do_piloto():
    voice.import_licenses_csv(_csv(phone="+12125550199", state="NY"))
    voice.check_dnc("+12125550199", listed=False, source="pytest")
    result = voice.can_call(_company("+12125550199"), now=NOW)
    assert result["allowed"] is False
    assert "state_not_enabled" in result["reasons"]


def test_limite_de_tentativas_7_dias():
    voice.import_licenses_csv(_csv())
    voice.check_dnc("+16175550123", listed=False, source="pytest")
    company = _company("+16175550123")
    for _ in range(3):
        voice.log_attempt(company["id"], 1, "no_answer", notes="pytest")
    result = voice.can_call(_company("+16175550123"), now=NOW)
    assert result["allowed"] is False
    assert "attempt_cap" in result["reasons"]


def test_wrong_number_suprime_automaticamente():
    voice.import_licenses_csv(_csv())
    company = _company("+16175550123")
    result = voice.log_attempt(company["id"], 1, "wrong_number", notes="pytest")
    assert result["status"] == "do_not_call"
    updated = _company("+16175550123")
    assert updated["status"] == "do_not_call"
    conn = voice.get_conn()
    try:
        suppression = conn.execute(
            "SELECT reason FROM voice_suppressions WHERE value=?",
            ("+16175550123",),
        ).fetchone()
        assert suppression is not None
        assert suppression["reason"] == "wrong_number"
    finally:
        conn.close()


def test_import_normaliza_estado_e_entity_type():
    csv_text = (
        "company_name,phone,state,entity_type\n"
        "Bay Builders,+16175550111,Massachusetts,LLC\n"
    )
    voice.import_licenses_csv(csv_text)
    company = _company("+16175550111")
    assert company["state"] == "MA"
    assert company["entity_type"] == "business"


def test_import_dnc_csv_normaliza_e_marca_listados():
    result = voice.import_dnc_csv(
        "phone,listed\n(617) 555-0147,yes\n6175550148,no\n", source="pytest"
    )
    assert result["imported"] == 2
    assert result["listed"] == 1
    conn = voice.get_conn()
    try:
        row = conn.execute(
            "SELECT listed FROM dnc_checks WHERE phone=?",
            ("+16175550147",),
        ).fetchone()
        assert row is not None and row["listed"] == 1
    finally:
        conn.close()
