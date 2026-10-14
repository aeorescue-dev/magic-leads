"""Fase 2: telemetria de custo da Searchbug.

Invariantes fixados aqui:

  1. `billed=1` e exclusivamente o que chegou ao provider. Um
     `guard_skipped` ou um cache hit NUNCA sao cobrados, mesmo quando
     devolvem `success=True` (o cache hit).
  2. Uma chamada que sai com `no_results` NAO FOI cobrada: segundo a
     documentacao Searchbug, `NORESULTS` nao e faturado. So chamadas que
     devolvem telefone (`success`) ou erros de rede/timeout sao cobradas.
  3. `record()` nunca levanta e nunca toca na BD. Uma BD bloqueada ou
     caida nao pode transformar uma consulta paga num 500 para o
     utilizador.
  4. O flush e assincrono e tolera falhas: um insert que falha devolve o
     lote ao buffer em vez de o descartar.
  5. Telemetria perdida e visivel (`dropped`/`flush_errors`), para nao
     aparecer como "zero eventos" enganador no painel.
  6. A classificacao de outcome e uma funcao pura partilhada entre o
     servico, o painel e os testes.
  7. Auditoria de custo: cada chamada `billed=1` gera UM evento
     `searchbug_cost` no `credit_ledger` (user_id=0, sistema), gravado na
     MESMA transacao do insert de telemetria — fatura nao pode existir sem
     o seu registo de custo, nem duplicar.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.services.db import _record_credit_event_connection, get_connection
from backend.services.metrics import (
    _SEARCHBUG_COLUMNS,
    MetricsBuffer,
    searchbug_metrics,
)
from backend.services.searchbug import (
    PhoneLookupService,
    classify_searchbug_outcome,
)

# --------------------------------------------------------------- _FakeResponse

class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self._text = text

    def json(self):
        return self._payload

    @property
    def text(self):
        return self._text


# --------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def _clean_calls():
    """Zera telemetria e auditoria de custo antes de cada teste."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM searchbug_calls")
        conn.execute("DELETE FROM credit_ledger")
        conn.commit()
    finally:
        conn.close()
    yield


def _rows() -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT * FROM searchbug_calls ORDER BY id"
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _ledger() -> list[dict]:
    """Eventos de auditoria de custo ('searchbug_cost') no credit_ledger."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """SELECT id, user_id, event_type, amount, balance_after,
                      reference_id, reference_type, metadata
               FROM credit_ledger WHERE event_type = 'searchbug_cost'
               ORDER BY id"""
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


async def _flush():
    """Forca flush da telemetria e devolve o numero de linhas escritas."""
    return await searchbug_metrics.flush_once()


async def _rows_after_flush():
    """Flush and return the rows from the database."""
    await _flush()
    return _rows()


def _patch_client(monkeypatch, response: _FakeResponse | None = None, raises: Exception | None = None):
    import backend.services.searchbug as sb

    def _factory(*args, **kwargs):
        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, data=None, **_kwargs):
                if raises:
                    raise raises
                return response

        return _Client()

    monkeypatch.setattr(sb.httpx, "AsyncClient", _factory)


def _configured_service(monkeypatch):
    """Servico com credenciais de teste configuradas."""
    import backend.services.searchbug as sb
    monkeypatch.setattr(sb.settings, "SEARCHBUG_ACCOUNT_CODE", "test-code", raising=False)
    monkeypatch.setattr(sb.settings, "SEARCHBUG_API_KEY", "test-key", raising=False)
    service = PhoneLookupService()
    service._phone_cache.clear()
    return service


# --------------------------------------------------------------- 1. outcome + billed

@pytest.mark.asyncio
async def test_successful_call_is_billed_and_recorded(monkeypatch):
    payload = {
        "Status": "OK",
        "Data": {"RECORD": [{"PHONE": "2125551234"}]},
    }
    _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    service = _configured_service(monkeypatch)
    result = await service._lookup_searchbug_nape("10 Main St", "New York", "NY", owner_name="John Smith")

    assert result.success is True
    rows = await _rows_after_flush()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "success"
    assert rows[0]["billed"] == 1
    assert rows[0]["http_status"] == 200


@pytest.mark.asyncio
async def test_no_results_is_NOT_billed(monkeypatch):
    """NORESULTS nao e faturado segundo documentacao Searchbug."""
    _patch_client(monkeypatch, response=_FakeResponse(200, {"Status": "NORESULTS"}))

    service = _configured_service(monkeypatch)
    result = await service._lookup_searchbug_nape("10 Main St", "Miami", "FL", owner_name="John Smith")

    assert result.success is False
    row = (await _rows_after_flush())[0]
    assert row["outcome"] == "no_results"
    assert row["billed"] == 0  # no_results nao e cobrado


@pytest.mark.asyncio
async def test_no_phone_in_records_is_NOT_billed(monkeypatch):
    """OK mas sem telefone nos registros = no_results nao cobrado."""
    payload = {"Status": "OK", "Data": {"RECORD": [{}]}}  # sem PHONE
    _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    service = _configured_service(monkeypatch)
    result = await service._lookup_searchbug_nape("10 Main St", "Miami", "FL", owner_name="John Smith")

    assert result.success is False
    row = (await _rows_after_flush())[0]
    assert row["outcome"] == "no_results"
    assert row["billed"] == 0


@pytest.mark.asyncio
async def test_http_error_records_status(monkeypatch):
    _patch_client(monkeypatch, response=_FakeResponse(503, None, text="upstream busy"))

    service = _configured_service(monkeypatch)
    result = await service._lookup_searchbug_nape("10 Main St", "Miami", "FL", owner_name="John Smith")

    assert result.success is False
    row = (await _rows_after_flush())[0]
    assert row["outcome"] == "http_error"
    assert row["billed"] == 1
    assert row["http_status"] == 503


@pytest.mark.asyncio
async def test_no_phone_in_records_is_NOT_billed(monkeypatch):
    """OK mas sem telefone nos registros = no_results nao cobrado."""
    payload = {"Status": "OK", "Data": {"RECORD": [{}]}}  # sem PHONE
    _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    service = _configured_service(monkeypatch)
    result = await service._lookup_searchbug_nape("10 Main St", "Miami", "FL", owner_name="John Smith")

    assert result.success is False
    row = (await _rows_after_flush())[0]
    assert row["outcome"] == "no_results"
    assert row["billed"] == 0


@pytest.mark.asyncio
async def test_timeout_is_billed(monkeypatch):
    _patch_client(monkeypatch, raises=TimeoutError("Read timed out"))

    service = _configured_service(monkeypatch)
    result = await service._lookup_searchbug_nape("10 Main St", "Miami", "FL", owner_name="John Smith")

    assert result.success is False
    row = (await _rows_after_flush())[0]
    assert row["outcome"] == "timeout"
    assert row["billed"] == 1


@pytest.mark.asyncio
async def test_missing_credentials_are_not_billed(monkeypatch):
    """Sem CO_CODE/PASS nao ha rede: custo zero."""
    import backend.services.searchbug as sb
    monkeypatch.setattr(sb.settings, "SEARCHBUG_ACCOUNT_CODE", None, raising=False)
    service = PhoneLookupService()
    service.searchbug_key = None

    result = await service._lookup_searchbug_nape("10 Main St", "Miami", "FL", owner_name="John Smith")

    assert result.success is False
    row = (await _rows_after_flush())[0]
    assert row["outcome"] == "not_configured"
    assert row["billed"] == 0


@pytest.mark.asyncio
async def test_guard_skipped_is_not_billed(monkeypatch):
    """Address incompleta: o provider nunca e consultado."""
    _patch_client(monkeypatch, response=_FakeResponse(500))

    service = _configured_service(monkeypatch)
    result = await service.lookup_phone("", "Miami", "FL", owner_name="John Smith")

    assert result.success is False
    assert result.error == "guard_skipped:address_incompleta"
    row = (await _rows_after_flush())[0]
    assert row["outcome"] == "guard_skipped"
    assert row["billed"] == 0


# --------------------------------------------------------------- 2. cache

@pytest.mark.asyncio
async def test_cache_hit_is_success_but_not_billed(monkeypatch):
    """Cache hit devolve success=True e mesmo assim custo zero."""
    payload = {
        "Status": "OK",
        "Data": {"RECORD": [{"PHONE": "2125551234"}]},
    }
    _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    service = _configured_service(monkeypatch)
    first = await service.lookup_phone(
        "10 Main St", "New York", "NY", owner_name="John Smith", zip_code="10001"
    )
    assert first.success is True

    second = await service.lookup_phone(
        "10 Main St", "New York", "NY", owner_name="John Smith", zip_code="10001"
    )
    assert second.success is True
    assert second.provider == "cache"

    rows = await _rows_after_flush()
    hits = [r for r in rows if r["outcome"] == "cache_hit"]
    assert len(hits) == 1
    assert hits[0]["billed"] == 0
    assert sum(1 for r in rows if r["billed"] == 1) == 1


@pytest.mark.asyncio
async def test_cache_negative_is_not_billed(monkeypatch):
    """'Sem resultado' dentro do TTL nao volta a pagar."""
    _patch_client(monkeypatch, response=_FakeResponse(200, {"Status": "NORESULTS"}))

    service = _configured_service(monkeypatch)
    first = await service.lookup_phone(
        "10 Main St", "Miami", "FL", owner_name="John Smith", zip_code="33101"
    )
    assert first.success is False

    second = await service.lookup_phone(
        "10 Main St", "Miami", "FL", owner_name="John Smith", zip_code="33101"
    )
    assert second.success is False
    assert second.error == "cache_sem_resultado"

    rows = await _rows_after_flush()
    negatives = [r for r in rows if r["outcome"] == "cache_negative"]
    assert len(negatives) == 1
    assert negatives[0]["billed"] == 0
    # Duas chamadas logadas, mas so uma foi ao provider (e nao cobrou por no_results).
    assert sum(1 for r in rows if r["billed"] == 1) == 0


# --------------------------------------------------------------- 3. resiliencia

@pytest.mark.asyncio
async def test_metrics_failure_does_not_break_lookup(monkeypatch):
    """O contrato mais importante: telemetria rota nao pode falhar o pedido."""
    payload = {
        "Status": "OK",
        "Data": {"RECORD": [{"PHONE": "2125551234"}]},
    }
    _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    def _boom(**kwargs):
        raise RuntimeError("metrics backend em chamas")

    monkeypatch.setattr("backend.services.searchbug.searchbug_metrics.record", _boom)

    service = _configured_service(monkeypatch)
    result = await service._lookup_searchbug_nape("10 Main St", "New York", "NY", owner_name="John Smith")
    assert result.success is True, "a falha de telemetria e engolida"


@pytest.mark.asyncio
async def test_one_event_per_provider_call(monkeypatch):
    """Nao pode haver contagem dupla: 1 chamada = 1 linha."""
    payload = {
        "Status": "OK",
        "Data": {"RECORD": [{"PHONE": "2125551234"}]},
    }
    _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    service = _configured_service(monkeypatch)
    await service._lookup_searchbug_nape("10 Main St", "New York", "NY", owner_name="John Smith")

    rows = await _rows_after_flush()
    assert len(rows) == 1


# --------------------------------------- 7. auditoria de custo no ledger


@pytest.mark.asyncio
async def test_billed_call_records_system_cost_event(monkeypatch):
    """Chamada que chegou ao provider = evento de custo, user 0 (sistema)."""
    payload = {
        "Status": "OK",
        "Data": {"RECORD": [{"PHONE": "2125551234"}]},
    }
    _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    service = _configured_service(monkeypatch)
    result = await service._lookup_searchbug_nape("10 Main St", "New York", "NY", owner_name="John Smith")

    assert result.success is True
    rows = await _rows_after_flush()

    ledger = _ledger()
    assert len(ledger) == 1
    ev = ledger[0]
    assert ev["user_id"] == 0, "custo e do sistema (user_id=0), como no backfill"
    assert ev["event_type"] == "searchbug_cost"
    assert ev["amount"] == 0, "auditoria de custo nunca altera saldo de creditos"
    assert ev["balance_after"] == 0
    assert ev["reference_type"] == "searchbug_call"
    assert ev["reference_id"] == rows[0]["id"], "referencia ao call que o originou"

    import json
    meta = json.loads(ev["metadata"])
    assert meta["billed"] == 1
    assert meta["outcome"] == "success"
    assert meta["city"] == "New York"
    assert meta["latency_ms"] is not None


@pytest.mark.asyncio
async def test_not_billed_call_records_no_cost_event(monkeypatch):
    """guard_skipped/not_configured = custo zero = nenhum evento de custo."""
    import backend.services.searchbug as sb
    monkeypatch.setattr(sb.settings, "SEARCHBUG_ACCOUNT_CODE", None, raising=False)
    service = PhoneLookupService()
    service.searchbug_key = None

    result = await service.lookup_phone("", "Miami", "FL", owner_name="John Smith")

    assert result.success is False
    await _flush()
    assert _ledger() == [], "sem chamada paga nao ha auditoria de custo"


@pytest.mark.asyncio
async def test_cache_hit_records_no_cost_event(monkeypatch):
    """Cache hit nao custa: nem telemetria billed nem evento de custo."""
    payload = {
        "Status": "OK",
        "Data": {"RECORD": [{"PHONE": "2125551234"}]},
    }
    _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    service = _configured_service(monkeypatch)
    await service.lookup_phone(
        "10 Main St", "New York", "NY", owner_name="John Smith", zip_code="10001"
    )
    await service.lookup_phone(
        "10 Main St", "New York", "NY", owner_name="John Smith", zip_code="10001"
    )

    await _flush()
    assert len(_ledger()) == 1, "so a chamada original (billed) gera custo"


def test_audit_failure_rolls_back_telemetry_and_buffer():
    """Auditoria rota nao pode deixar telemetria sem o seu custo.

    O evento de custo corre na MESMA transacao: se falhar, a linha de
    telemetria tambem e desfeita e o lote volta ao buffer (visivel, nao
    engolido), tal como uma falha de insert normal.
    """
    def _boom(*_args, **_kwargs):
        raise RuntimeError("credit_ledger indisponivel")

    buf = MetricsBuffer("searchbug_calls", _SEARCHBUG_COLUMNS, audit_hook=_boom)
    buf.record(outcome="success", billed=True, latency_ms=120, city="New York")

    assert asyncio.run(buf.flush_once()) == 0
    st = buf.stats()
    assert st["buffered"] == 1, "lote volta ao buffer"
    assert st["flush_errors"] == 1
    assert st["flushed"] == 0


# --------------------------------------------------------------- classify_searchbug_outcome

def test_classify_no_results():
    assert classify_searchbug_outcome(False, "No results") == "no_results"
    assert classify_searchbug_outcome(False, "No phone found") == "no_results"
    assert classify_searchbug_outcome(False, "noresults") == "no_results"

def test_classify_timeout():
    assert classify_searchbug_outcome(False, "Read timeout") == "timeout"
    assert classify_searchbug_outcome(False, "HTTP 408: Request Timeout") == "timeout"

def test_classify_http_error():
    assert classify_searchbug_outcome(False, "HTTP 503: Service Unavailable") == "http_error"

def test_classify_not_configured():
    assert classify_searchbug_outcome(False, "not configured") == "not_configured"
    assert classify_searchbug_outcome(False, "CO_CODE missing") == "not_configured"

def test_classify_bad_response():
    assert classify_searchbug_outcome(False, "Unexpected response format") == "bad_response"
    assert classify_searchbug_outcome(False, "no data") == "bad_response"

def test_classify_success():
    assert classify_searchbug_outcome(True, None) == "success"

def test_classify_generic_error():
    assert classify_searchbug_outcome(False, "some random error") == "error"