"""Integridade da chamada Searchbug: SUBTYPE, auth nao faturada, outcomes."""
from __future__ import annotations

import json

import pytest

import backend.services.searchbug as sb
from backend.services.db import get_connection
from backend.services.metrics import searchbug_metrics
from backend.services.searchbug import PhoneLookupService, classify_searchbug_outcome


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
    monkeypatch.setattr(sb.settings, "SEARCHBUG_ACCOUNT_CODE", "test-code", raising=False)
    monkeypatch.setattr(sb.settings, "SEARCHBUG_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(sb.settings, "PHONE_TRANSPORT_RETRY_DELAY_S", 0.01, raising=False)
    svc = PhoneLookupService()
    svc._phone_cache.clear()
    svc._transport_failures = 0
    svc._circuit_open_until = 0.0
    return svc


def _patch(monkeypatch, responses):
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


async def _clean():
    await searchbug_metrics.flush_once()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM searchbug_calls")
        conn.commit()
    finally:
        conn.close()


async def _last_row():
    await searchbug_metrics.flush_once()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM searchbug_calls ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def test_auth_error_is_not_billed():
    assert classify_searchbug_outcome(
        False, "auth_error:ACCOUNT NUMBER, PASSWORD OR API KEY IS NOT VALID"
    ) == "auth_error"


@pytest.mark.asyncio
async def test_auth_error_never_marks_billed(monkeypatch):
    await _clean()
    _patch(
        monkeypatch,
        [
            _Response(
                {
                    "Status": "ERROR",
                    "ERROR": "ACCOUNT NUMBER, PASSWORD OR API KEY IS NOT VALID",
                }
            )
        ],
    )
    svc = _service(monkeypatch)
    result = await svc._lookup_searchbug_nape(
        "10 Main St", "New York", "NY", owner_name="John Smith"
    )
    assert result.success is False
    assert result.error.startswith("auth_error")

    row = await _last_row()
    assert row["outcome"] == "auth_error"
    assert row["billed"] == 0, "credencial invalida nao e' uma busca faturavel"
    assert row["cost_usd"] == 0


@pytest.mark.asyncio
async def test_subtype_p_is_sent(monkeypatch):
    await _clean()
    calls = _patch(
        monkeypatch,
        [
            _Response(
                {
                    "Status": "OK",
                    "Data": {"RECORD": [{"FNAME": "JOHN", "LNAME": "SMITH", "PHONE": "2125551234"}]},
                }
            )
        ],
    )
    monkeypatch.setattr(sb.settings, "SEARCHBUG_PHONE_ONLY", True, raising=False)
    svc = _service(monkeypatch)

    await svc._lookup_searchbug_nape(
        "10 Main St", "New York", "NY", owner_name="John Smith", trigger="user_click"
    )
    assert calls[0]["SUBTYPE"] == "p"

    row = await _last_row()
    assert row["trigger"] == "user_click"


@pytest.mark.asyncio
async def test_subtype_can_be_disabled(monkeypatch):
    await _clean()
    calls = _patch(monkeypatch, [_Response({"Status": "NORESULTS"})])
    monkeypatch.setattr(sb.settings, "SEARCHBUG_PHONE_ONLY", False, raising=False)
    svc = _service(monkeypatch)

    await svc._lookup_searchbug_nape(
        "10 Main St", "New York", "NY", owner_name="John Smith"
    )
    assert "SUBTYPE" not in calls[0]


def test_underscore_no_results_is_recognized():
    assert classify_searchbug_outcome(False, "no_results") == "no_results"
