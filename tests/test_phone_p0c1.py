"""P0-C1: ZIP, transporte, name_match, inversao e L3.

Cada teste fixa uma das 6 decisoes aprovadas em 2026-10-29:
  1. ZIP 4 -> 5 digitos antes da chamada.
  2. Resposta vazia/nao-JSON = transport_error, NAO faturada, com retry.
  3. `name_match >= 0.6` para entregar e marcar `verified`.
  4. Inversao condicional LAST FIRST.
  5. L3 sem nome so com flag; entrega `verified=False`.
  6. Telemetria por lead/classe/camada.
"""
from __future__ import annotations

import json

import pytest

from backend.services.db import get_connection
from backend.services.metrics import searchbug_metrics
from backend.services.searchbug import (
    PhoneLookupService,
    normalize_zip,
    split_person_name,
)


class _Response:
    def __init__(self, payload=None, text=None, status_code=200):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _service(monkeypatch):
    import backend.services.searchbug as sb

    monkeypatch.setattr(sb.settings, "SEARCHBUG_ACCOUNT_CODE", "test-code", raising=False)
    monkeypatch.setattr(sb.settings, "SEARCHBUG_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(sb.settings, "PHONE_TRANSPORT_RETRY_DELAY_S", 0.01, raising=False)
    svc = PhoneLookupService()
    svc._phone_cache.clear()
    svc._transport_failures = 0
    svc._circuit_open_until = 0.0
    return svc


def _patch(monkeypatch, responses):
    """Fake httpx client. `responses` e' uma lista consumida por chamada."""
    import backend.services.searchbug as sb

    calls = []

    class _Client:
        async def post(self, url, data=None, **_kwargs):
            calls.append(dict(data or {}))
            item = responses[min(len(calls) - 1, len(responses) - 1)]
            if isinstance(item, Exception):
                raise item
            return item

        async def aclose(self):
            return None

    monkeypatch.setattr(sb.httpx, "AsyncClient", lambda *a, **k: _Client())
    return calls


def _rows():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM searchbug_calls")
        conn.commit()
    finally:
        conn.close()


async def _clean():
    """Flush pendente antes de limpar: evita herdar linhas de outro teste."""
    await searchbug_metrics.flush_once()
    _rows()


async def _last_row():
    await searchbug_metrics.flush_once()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM searchbug_calls ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def test_normalize_zip_pads_boston():
    assert normalize_zip("2114") == "02114"
    assert normalize_zip("02114") == "02114"
    assert normalize_zip("02114-1234") == "02114"
    assert normalize_zip(None) is None


def test_split_person_name_registry_order():
    assert split_person_name("PEACOCK TAWANNA", city="NYC") == ("TAWANNA", "PEACOCK")
    assert split_person_name("MARCHIO PAUL A", city="NYC") == ("PAUL", "MARCHIO A")
    # Chicago misto: sem inicial final mantem FIRST LAST.
    assert split_person_name("JENNIFER M BREWER", city="Chicago") == ("JENNIFER", "M BREWER")


@pytest.mark.asyncio
async def test_provider_payload_uses_five_digit_zip(monkeypatch):
    await _clean()
    calls = _patch(monkeypatch, [_Response({"Status": "OK", "Data": {"RECORD": [
        {"FNAME": "PAUL", "LNAME": "MARCHIO", "PHONE": "6175551234"}
    ]}})])
    svc = _service(monkeypatch)

    await svc._lookup_searchbug_nape(
        "431 E Third St", "Boston", "MA",
        owner_name="MARCHIO PAUL A", zip_code="2127",
    )

    assert calls[0]["ZIP"] == "02127", "ZIP de 4 digitos tem de ser padded"


@pytest.mark.asyncio
async def test_name_match_accepts_correct_person(monkeypatch):
    await _clean()
    _patch(monkeypatch, [_Response({"Status": "OK", "Data": {"RECORD": [
        {"FNAME": "JOHN", "LNAME": "SMITH", "PHONE": "2125551234"}
    ]}})])
    svc = _service(monkeypatch)

    result = await svc._lookup_searchbug_nape(
        "10 Main St", "New York", "NY", owner_name="John Smith",
        lead_id=42, owner_class="private", layer="L2",
    )

    assert result.success is True
    assert result.verified is True
    assert result.name_match == 1.0

    row = await _last_row()
    assert row["lead_id"] == 42
    assert row["owner_class"] == "private"
    assert row["layer"] == "L2"
    assert row["name_match"] == 1.0
    assert row["transport_error"] == 0
    assert row["billed"] == 1


@pytest.mark.asyncio
async def test_name_match_rejects_wrong_person(monkeypatch):
    await _clean()
    _patch(monkeypatch, [_Response({"Status": "OK", "Data": {"RECORD": [
        {"FNAME": "JAMES", "LNAME": "DOHERTY", "PHONE": "2125559999"}
    ]}})])
    svc = _service(monkeypatch)

    result = await svc._lookup_searchbug_nape(
        "10 Main St", "New York", "NY", owner_name="John Smith",
    )

    assert result.success is False
    assert result.error == "name_mismatch"
    assert result.verified is False
    assert result.name_match == 0.0

    row = await _last_row()
    assert row["outcome"] == "name_mismatch"
    assert row["billed"] == 1, "a chamada foi feita; o telefone e' que nao serve"


@pytest.mark.asyncio
async def test_empty_body_is_transport_error_and_not_billed(monkeypatch):
    await _clean()
    _patch(monkeypatch, [_Response(text="")])
    svc = _service(monkeypatch)

    result = await svc._lookup_searchbug_nape(
        "10 Main St", "New York", "NY", owner_name="John Smith",
    )

    assert result.success is False
    assert result.error.startswith("transport_error")
    row = await _last_row()
    assert row["outcome"] == "transport_error"
    assert row["billed"] == 0
    assert row["transport_error"] == 1


@pytest.mark.asyncio
async def test_zip_validation_error_is_not_billed(monkeypatch):
    await _clean()
    _patch(monkeypatch, [_Response({"Status": "Error", "ERROR": "Please enter 5-digit ZIP Code"})])
    svc = _service(monkeypatch)

    result = await svc._lookup_searchbug_nape(
        "10 Main St", "Boston", "MA", owner_name="John Smith", zip_code="2114",
    )

    assert result.success is False
    row = await _last_row()
    assert row["outcome"] == "invalid_request"
    assert row["billed"] == 0


@pytest.mark.asyncio
async def test_transport_retries_once(monkeypatch):
    await _clean()
    calls = _patch(monkeypatch, [_Response(text=""), _Response({"Status": "NORESULTS"})])
    svc = _service(monkeypatch)

    result = await svc.lookup_phone(
        "10 Main St", "New York", "NY", owner_name="John Smith", zip_code="10001",
    )

    assert len(calls) == 2, "1 retry em transport_error"
    assert result.success is False
    assert result.error == "No results"


@pytest.mark.asyncio
async def test_l3_off_by_default_is_guarded(monkeypatch):
    await _clean()
    calls = _patch(monkeypatch, [_Response({"Status": "NORESULTS"})])
    svc = _service(monkeypatch)
    monkeypatch.setattr("backend.services.searchbug.settings.PHONE_L3_UNNAMED_ENABLED", False, raising=False)

    result = await svc.lookup_phone("10 Main St", "New York", "NY", owner_name=None)

    assert result.error == "guard_skipped:owner_name_ausente"
    assert calls == [], "sem nome e sem flag nao se gasta dinheiro"
    row = await _last_row()
    assert row["outcome"] == "guard_skipped"
    assert row["billed"] == 0


@pytest.mark.asyncio
async def test_l3_on_returns_unverified(monkeypatch):
    await _clean()
    calls = _patch(monkeypatch, [_Response({"Status": "OK", "Data": {"RECORD": [
        {"FNAME": "MERRY", "LNAME": "MOORE", "PHONE": "3125551234"}
    ]}})])
    svc = _service(monkeypatch)
    monkeypatch.setattr("backend.services.searchbug.settings.PHONE_L3_UNNAMED_ENABLED", True, raising=False)

    result = await svc.lookup_phone("10 Main St", "Chicago", "IL", owner_name=None, zip_code="60601")

    assert len(calls) == 1
    assert result.success is True
    assert result.verified is False, "L3 sem nome nunca e' verificado"

    row = await _last_row()
    assert row["layer"] == "L3"
    assert row["owner_class"] == "unknown"
    assert row["name_match"] is None


@pytest.mark.asyncio
async def test_placeholder_is_guarded_without_call(monkeypatch):
    await _clean()
    calls = _patch(monkeypatch, [_Response({"Status": "NORESULTS"})])
    svc = _service(monkeypatch)

    for name in ("UNAVAILABLE OWNER", "TAXPAYER OF", "CHICAGO CITY OF", "* CITY OF"):
        result = await svc.lookup_phone("10 Main St", "Chicago", "IL", owner_name=name)
        assert result.error.startswith("guard_skipped:")

    assert calls == [], "placeholders nunca chegam ao provider"


def test_phone_verified_column_exists():
    conn = get_connection()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
    finally:
        conn.close()
    assert "phone_verified" in cols


def test_searchbug_calls_new_columns_exist():
    conn = get_connection()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(searchbug_calls)").fetchall()}
    finally:
        conn.close()
    assert {"lead_id", "owner_class", "layer", "name_match", "transport_error"} <= cols
