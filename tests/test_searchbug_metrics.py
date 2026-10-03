"""Fase 2: telemetria de custo da Searchbug.

Invariantes fixados aqui:

  1. `billed=1` e exclusivamente o que chegou ao provider. Um
     `guard_skipped` ou um cache hit NUNCA sao cobrados, mesmo quando
     devolvem `success=True` (o cache hit).
  2. Uma chamada que sai com `no_results` FOI cobrada: e "cobranÃ§a
     fantasma" e tem de contar como tal, nÃ£o como erro interno.
  3. `record()` nunca levanta e nunca toca na BD. Uma BD bloqueada ou
     caÃ­da nÃ£o pode transformar uma consulta paga num 500 para o
     utilizador.
  4. O flush Ã© assÃ­ncrono e tolera falhas: um insert que falha devolve o
     lote ao buffer em vez de o descartar.
  5. Telemetria perdida Ã© visÃ­vel (`dropped`/`flush_errors`), para nÃ£o
     aparecer como "zero eventos" enganador no painel.
  6. A classificaÃ§Ã£o de outcome Ã© uma funÃ§Ã£o pura partilhada entre o
     serviÃ§o, o painel e os testes.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.services.db import get_connection
from backend.services.metrics import (
    _SEARCHBUG_COLUMNS,
    MetricsBuffer,
    searchbug_metrics,
)
from backend.services.searchbug import (
    PhoneLookupService,
    classify_searchbug_outcome,
)

# --------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def _clean_calls():
    """Zera a tabela de telemetria antes de cada teste."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM searchbug_calls")
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


# ------------------------------------------------------- 6. classificacao

@pytest.mark.parametrize(
    "success,error,expected",
    [
        (True, None, "success"),
        (True, "", "success"),
        (False, "No results", "no_results"),
        (False, "NORESULTS", "no_results"),
        (False, "No phone found in results", "no_results"),
        (False, "HTTP 503: upstream busy", "http_error"),
        (False, "ReadTimeout: timed out", "timeout"),
        (False, "connect timeout", "timeout"),
        (False, "Unexpected response format (no Data)", "bad_response"),
        (False, "Searchbug CO_CODE (account number) or API key not configured", "not_configured"),
        (False, "Invalid CO_CODE supplied", "not_configured"),
        (False, "weird unforeseen thing", "error"),
        (False, None, "error"),
        # "timeout" nÃ£o pode ser confundido com um erro de parsing qualquer
        (False, "All phone lookup providers failed", "error"),
    ],
)
def test_classify_outcome(success, error, expected):
    assert classify_searchbug_outcome(success, error) == expected


# ------------------------------------------------- 3. record() nunca falha

def test_record_never_raises_with_garbage():
    buf = MetricsBuffer("searchbug_calls", _SEARCHBUG_COLUMNS)
    # Tipos absurdos, chaves desconhecidas, latÃªncia como texto.
    buf.record(outcome="success", billed=True, latency_ms="abc", city=object())
    buf.record(chave_desconhecida="ignorado")
    buf.record(outcome=None)
    assert buf.stats()["buffered"] == 3


def test_record_drops_oldest_when_full():
    buf = MetricsBuffer("searchbug_calls", _SEARCHBUG_COLUMNS)
    from backend.services import metrics as metrics_module

    original_max = metrics_module._MAX_BUFFER
    metrics_module._MAX_BUFFER = 5
    try:
        for i in range(12):
            buf.record(outcome=f"o{i}")
        st = buf.stats()
        assert st["buffered"] == 5
        assert st["dropped"] == 7
    finally:
        metrics_module._MAX_BUFFER = original_max


# ------------------------------------------------- 4/5. flush tolerante

def test_flush_once_writes_rows():
    buf = MetricsBuffer("searchbug_calls", _SEARCHBUG_COLUMNS)
    buf.record(outcome="success", billed=True, latency_ms=120, city="New York")
    buf.record(outcome="no_results", billed=True, latency_ms=340, city="Miami")

    written = asyncio.run(buf.flush_once())
    assert written == 2
    assert buf.stats()["buffered"] == 0

    rows = _rows()
    assert len(rows) == 2
    assert rows[0]["outcome"] == "success"
    assert rows[0]["billed"] == 1
    assert rows[0]["latency_ms"] == 120
    assert rows[0]["city"] == "New York"


def test_flush_once_on_empty_buffer_is_noop():
    buf = MetricsBuffer("searchbug_calls", _SEARCHBUG_COLUMNS)
    assert asyncio.run(buf.flush_once()) == 0


def test_flush_failure_returns_rows_to_buffer():
    """Uma BD em falha nÃ£o pode engolir telemetria em silÃªncio."""
    buf = MetricsBuffer("searchbug_calls", _SEARCHBUG_COLUMNS)
    buf.record(outcome="success", billed=True)

    def _boom(_rows):
        raise RuntimeError("database is locked")

    buf._insert = _boom  # injeta a falha de I/O

    assert asyncio.run(buf.flush_once()) == 0
    st = buf.stats()
    assert st["buffered"] == 1, "o lote tem de voltar ao buffer"
    assert st["flush_errors"] == 1
    assert st["flushed"] == 0


def test_error_field_is_truncated():
    """Mensagens de provider podem trazer payloads inteiros."""
    buf = MetricsBuffer("searchbug_calls", _SEARCHBUG_COLUMNS)
    buf.record(outcome="error", billed=True, error="X" * 5000)
    asyncio.run(buf.flush_once())
    row = _rows()[0]
    assert len(row["error"]) == 300


def test_ignored_columns_are_dropped():
    """SÃ³ as colunas conhecidas entram; nada de SQL injection via kwargs."""
    buf = MetricsBuffer("searchbug_calls", _SEARCHBUG_COLUMNS)
    buf.record(outcome="; DROP TABLE searchbug_calls; --", billed=True)
    asyncio.run(buf.flush_once())
    assert _rows()[0]["outcome"] == "; DROP TABLE searchbug_calls; --"
    # e a tabela continua lÃ¡
    conn = get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM searchbug_calls").fetchone()[0] == 1
    finally:
        conn.close()


# ---------------------------------- 1/2. instrumentaÃ§Ã£o do serviÃ§o real

class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    """Substitui httpx.AsyncClient para nÃ£o sair Ã  rede."""

    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        if self._raises is not None:
            raise self._raises
        return self._response


@pytest.fixture
def _configured(monkeypatch):
    monkeypatch.setattr(
        "backend.services.searchbug.settings.SEARCHBUG_ACCOUNT_CODE", "CO_TEST", raising=False
    )
    service = PhoneLookupService()
    service.searchbug_key = "KEY_TEST"
    return service


async def _patch_client(monkeypatch, response=None, raises=None):
    client = _FakeClient(response=response, raises=raises)

    def _factory(*args, **kwargs):
        return client

    monkeypatch.setattr("backend.services.searchbug.httpx.AsyncClient", _factory)
    return client



async def _flush() -> list[dict]:
    """Esvazia o buffer assincrono e devolve as linhas ja persistidas.

    Os testes validam a telemetria como o painel a ve: depois de um flush,
    nao de dentro do buffer em memoria.
    """
    await searchbug_metrics.flush_once()
    return _rows()

@pytest.mark.asyncio
async def test_successful_call_is_billed_and_recorded(monkeypatch, _configured):
    payload = {
        "Status": "OK",
        "Data": {"RECORD": [{"PHONES": {"PHONE": ["2125551234"]}}]},
    }
    await _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    result = await _configured._lookup_searchbug("10 Main St", "New York", "NY")

    assert result.success is True
    rows = await _flush()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "success"
    assert rows[0]["billed"] == 1, "chegou ao provider: custou dinheiro"
    assert rows[0]["http_status"] == 200
    assert rows[0]["city"] == "New York"
    assert rows[0]["latency_ms"] is not None


@pytest.mark.asyncio
async def test_no_results_is_a_ghost_charge(monkeypatch, _configured):
    """A metrica de dinheiro: consulta paga, sem telefone utilizavel."""
    payload = {"Status": "NORESULTS"}
    await _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    result = await _configured._lookup_searchbug("10 Main St", "Miami", "FL")

    assert result.success is False
    row = (await _flush())[0]
    assert row["outcome"] == "no_results"
    assert row["billed"] == 1
    assert row["http_status"] == 200


@pytest.mark.asyncio
async def test_no_phone_in_records_is_billed(monkeypatch, _configured):
    """Resposta OK mas sem telefone: tambem custou dinheiro."""
    payload = {"Status": "OK", "Data": {"RECORD": [{"PHONES": {"PHONE": []}}]}}
    await _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    result = await _configured._lookup_searchbug("10 Main St", "Miami", "FL")

    assert result.success is False
    row = (await _flush())[0]
    assert row["outcome"] == "no_results"
    assert row["billed"] == 1


@pytest.mark.asyncio
async def test_http_error_records_status(monkeypatch, _configured):
    await _patch_client(monkeypatch, response=_FakeResponse(503, None, text="upstream busy"))

    result = await _configured._lookup_searchbug("10 Main St", "Miami", "FL")

    assert result.success is False
    row = (await _flush())[0]
    assert row["outcome"] == "http_error"
    assert row["billed"] == 1
    assert row["http_status"] == 503


@pytest.mark.asyncio
async def test_bad_response_shape_is_separated(monkeypatch, _configured):
    await _patch_client(monkeypatch, response=_FakeResponse(200, {"Status": "OK"}))

    result = await _configured._lookup_searchbug("10 Main St", "Miami", "FL")

    assert result.success is False
    row = (await _flush())[0]
    assert row["outcome"] == "bad_response"
    assert row["billed"] == 1


@pytest.mark.asyncio
async def test_timeout_is_distinguished_from_generic_error(monkeypatch, _configured):
    await _patch_client(monkeypatch, raises=TimeoutError("Read timed out"))

    result = await _configured._lookup_searchbug("10 Main St", "Miami", "FL")

    assert result.success is False
    row = (await _flush())[0]
    assert row["outcome"] == "timeout"
    assert row["billed"] == 1


@pytest.mark.asyncio
async def test_missing_credentials_are_not_billed(monkeypatch):
    """Sem CO_CODE/PASS nao ha rede: custo zero."""
    monkeypatch.setattr(
        "backend.services.searchbug.settings.SEARCHBUG_ACCOUNT_CODE", None, raising=False
    )
    service = PhoneLookupService()
    service.searchbug_key = None

    result = await service._lookup_searchbug("10 Main St", "Miami", "FL")

    assert result.success is False
    row = (await _flush())[0]
    assert row["outcome"] == "not_configured"
    assert row["billed"] == 0, "sem credenciais nao ha chamada paga"

@pytest.mark.asyncio
async def test_guard_skipped_is_not_billed(monkeypatch, _configured):
    """Address incompleta: o provider nunca e consultado."""
    await _patch_client(monkeypatch, response=_FakeResponse(500))

    result = await _configured.lookup_phone("", "Miami", "FL", owner_name="John Smith")

    assert result.success is False
    assert result.error == "guard_skipped:address_incompleta"
    row = (await _flush())[0]
    assert row["outcome"] == "guard_skipped"
    assert row["billed"] == 0


@pytest.mark.asyncio
async def test_cache_hit_is_success_but_not_billed(monkeypatch, _configured):
    """Cache hit devolve success=True e mesmo assim custo zero."""
    payload = {
        "Status": "OK",
        "Data": {"RECORD": [{"PHONES": {"PHONE": ["2125551234"]}}]},
    }
    await _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    first = await _configured.lookup_phone(
        "10 Main St", "New York", "NY", owner_name="John Smith", zip_code="10001"
    )
    assert first.success is True

    second = await _configured.lookup_phone(
        "10 Main St", "New York", "NY", owner_name="John Smith", zip_code="10001"
    )
    assert second.success is True
    assert second.provider == "cache"

    rows = await _flush()
    hits = [r for r in rows if r["outcome"] == "cache_hit"]
    assert len(hits) == 1
    assert hits[0]["billed"] == 0, "o cache nunca custa dinheiro"
    # O success do cache nao pode ser contado como uma consulta cobrada.
    assert sum(1 for r in rows if r["billed"] == 1) == 1


@pytest.mark.asyncio
async def test_cache_negative_is_not_billed(monkeypatch, _configured):
    """'Sem resultado' dentro do TTL nao volta a pagar."""
    await _patch_client(monkeypatch, response=_FakeResponse(200, {"Status": "NORESULTS"}))

    first = await _configured.lookup_phone(
        "10 Main St", "Miami", "FL", owner_name="John Smith", zip_code="33101"
    )
    assert first.success is False

    second = await _configured.lookup_phone(
        "10 Main St", "Miami", "FL", owner_name="John Smith", zip_code="33101"
    )
    assert second.success is False
    assert second.error == "cache_sem_resultado"

    rows = await _flush()
    negatives = [r for r in rows if r["outcome"] == "cache_negative"]
    assert len(negatives) == 1
    assert negatives[0]["billed"] == 0
    # Duas chamadas logadas, mas so uma foi ao provider.
    assert sum(1 for r in rows if r["billed"] == 1) == 1


@pytest.mark.asyncio
async def test_metrics_failure_does_not_break_lookup(monkeypatch, _configured):
    """O contrato mais importante: telemetria rota nao pode falhar o pedido."""
    payload = {
        "Status": "OK",
        "Data": {"RECORD": [{"PHONES": {"PHONE": ["2125551234"]}}]},
    }
    await _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    def _boom(**kwargs):
        raise RuntimeError("metrics backend em chamas")

    monkeypatch.setattr("backend.services.searchbug.searchbug_metrics.record", _boom)

    result = await _configured._lookup_searchbug("10 Main St", "New York", "NY")
    assert result.success is True, "a falha de telemetria e engolida"


@pytest.mark.asyncio
async def test_one_event_per_provider_call(monkeypatch, _configured):
    """Nao pode haver contagem dupla: 1 chamada = 1 linha."""
    payload = {
        "Status": "OK",
        "Data": {"RECORD": [{"PHONES": {"PHONE": ["2125551234"]}}]},
    }
    await _patch_client(monkeypatch, response=_FakeResponse(200, payload))

    await _configured._lookup_searchbug("10 Main St", "New York", "NY")

    rows = await _flush()
    assert len(rows) == 1
