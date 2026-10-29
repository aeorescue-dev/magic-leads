"""C2: custo real por chamada, agregacao e alertas de anomalia."""
from __future__ import annotations

import asyncio
import json

import pytest

from backend.services.control_tower import _check_searchbug_cost
from backend.services.db import _migrate_schema, db_service, get_connection
from backend.services.metrics import searchbug_metrics
from backend.services.searchbug import PhoneLookupService


class _Response:
    def __init__(self, payload=None, text=None, status_code=200):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _clean():
    try:
        asyncio.run(searchbug_metrics.flush_once())
    except RuntimeError:
        pass
    conn = get_connection()
    try:
        conn.execute("DELETE FROM searchbug_calls")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _clean_calls():
    _clean()
    yield
    _clean()


def _insert(outcome: str, billed: int = 0, cost: float = 0.0, city: str = "NYC",
            name_match=None, transport: int = 0, age_minutes: int = 0) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO searchbug_calls
               (outcome, billed, cost_usd, city, name_match, transport_error, called_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now', ?))""",
            (outcome, billed, cost, city, name_match, transport, f"-{int(age_minutes)} minutes"),
        )
        conn.commit()
    finally:
        conn.close()


def _service(monkeypatch):
    import backend.services.searchbug as sb
    monkeypatch.setattr(sb.settings, "SEARCHBUG_ACCOUNT_CODE", "test-code", raising=False)
    monkeypatch.setattr(sb.settings, "SEARCHBUG_API_KEY", "test-key", raising=False)
    return PhoneLookupService()


def _patch(monkeypatch, response):
    import backend.services.searchbug as sb

    class _Client:
        async def post(self, url, data=None, **_kwargs):
            return response

        async def aclose(self):
            return None

    monkeypatch.setattr(sb.httpx, "AsyncClient", lambda *a, **k: _Client())


@pytest.mark.asyncio
async def test_billed_success_records_cost(monkeypatch):
    _patch(monkeypatch, _Response({"Status": "OK", "Data": {"RECORD": [
        {"FNAME": "JOHN", "LNAME": "SMITH", "PHONE": "2125551234"}
    ]}}))
    svc = _service(monkeypatch)

    result = await svc._lookup_searchbug_nape(
        "10 Main St", "New York", "NY", owner_name="John Smith",
    )
    assert result.success is True
    await searchbug_metrics.flush_once()

    conn = get_connection()
    try:
        row = conn.execute("SELECT billed, cost_usd FROM searchbug_calls").fetchone()
    finally:
        conn.close()
    assert row["billed"] == 1
    assert row["cost_usd"] == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_no_results_cost_is_zero(monkeypatch):
    _patch(monkeypatch, _Response({"Status": "NORESULTS"}))
    svc = _service(monkeypatch)

    await svc._lookup_searchbug_nape("10 Main St", "Miami", "FL", owner_name="John Smith")
    await searchbug_metrics.flush_once()

    conn = get_connection()
    try:
        row = conn.execute("SELECT billed, cost_usd FROM searchbug_calls").fetchone()
    finally:
        conn.close()
    assert row["billed"] == 0
    assert row["cost_usd"] == 0


@pytest.mark.asyncio
async def test_transport_error_cost_is_zero(monkeypatch):
    _patch(monkeypatch, _Response(text=""))
    svc = _service(monkeypatch)

    await svc._lookup_searchbug_nape("10 Main St", "Miami", "FL", owner_name="John Smith")
    await searchbug_metrics.flush_once()

    conn = get_connection()
    try:
        row = conn.execute("SELECT billed, cost_usd, transport_error FROM searchbug_calls").fetchone()
    finally:
        conn.close()
    assert row["billed"] == 0
    assert row["cost_usd"] == 0
    assert row["transport_error"] == 1


def test_admin_metrics_aggregate_cost():
    _insert("success", billed=1, cost=0.20)
    _insert("no_results", billed=0, cost=0.0)
    _insert("transport_error", billed=0, cost=0.0, transport=1)

    data = db_service._service.admin_get_searchbug_metrics(days=7)

    assert data["totals"]["calls"] == 3
    assert data["totals"]["billed_calls"] == 1
    assert data["totals"]["successes"] == 1
    assert data["totals"]["cost_usd"] == pytest.approx(0.20)
    assert data["totals"]["transport_errors"] == 1
    assert data["cost_per_success"] == pytest.approx(0.20)
    assert data["today"]["cost_usd"] == pytest.approx(0.20)
    assert data["by_city"][0]["cost_usd"] == pytest.approx(0.20)


def test_cost_anomaly_transport_failure():
    for _ in range(5):
        _insert("transport_error", billed=0, cost=0.0, transport=1)

    check = _check_searchbug_cost()

    assert check["status"] == "fail"
    assert "transport_error" in check["detail"]


def test_cost_anomaly_ghost_charges():
    # 2h atras: isola a anomalia de ghost charges do pico de custo da ultima hora.
    for _ in range(10):
        _insert("no_results", billed=1, cost=0.20, age_minutes=120)

    check = _check_searchbug_cost()

    assert check["status"] == "warn"
    assert "sem telefone" in check["detail"]


def test_cost_anomaly_ok_when_clean():
    check = _check_searchbug_cost()
    assert check["status"] == "ok"


def test_migration_backfills_historical_cost():
    _insert("success", billed=1, cost=0.0)

    conn = get_connection()
    try:
        _migrate_schema(conn)
        conn.commit()
        row = conn.execute("SELECT cost_usd FROM searchbug_calls").fetchone()
    finally:
        conn.close()

    assert row["cost_usd"] == pytest.approx(0.20)
