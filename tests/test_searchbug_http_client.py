"""Client HTTP partilhado do phone lookup (Searchbug).

Porquê fixar isto em testes: o Searchbug e a etapa PAGA e cada chamada pagava
DNS + TCP + TLS (3 RTT) porque se criava um `httpx.AsyncClient` novo por
request. Com keep-alive nao se paga esse handshake de cada vez.

Invariantes fixados aqui:

  1. O mesmo `AsyncClient` (e o mesmo keep-alive) e reutilizado entre
     chamadas: criar um client por request e o bug que custou a latencia.
  2. O timeout e configuravel e o default e 10s, nao 20s.
  3. `verify=True` nunca e desligado (a credencial da conta trafega em claro).
  4. `follow_redirects=True` e `limits` de pooling sao definidos na construcao,
     nao por request.
  5. `aclose()` fecha o client e deixa o servico utilizavel outra vez.

Nenhum destes testes toca na rede: o `httpx.AsyncClient` e interceptado.
"""
from __future__ import annotations

import httpx
import pytest

from backend.services import searchbug as sb
from backend.services.searchbug import PhoneLookupService


class _FakeClient:
    """Doubles de `httpx.AsyncClient`: regista construcoes e posts."""

    instances: list["_FakeClient"] = []
    posts: list[dict] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        _FakeClient.instances.append(self)

    async def post(self, url, data=None, **kwargs):
        _FakeClient.posts.append({"url": url, "data": dict(data or {}), "kwargs": kwargs})
        return httpx.Response(
            200,
            json={"Status": "NORESULTS", "ERROR": "No results"},
            request=httpx.Request("POST", url),
        )

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fakes():
    _FakeClient.instances.clear()
    _FakeClient.posts.clear()
    yield
    _FakeClient.instances.clear()
    _FakeClient.posts.clear()


@pytest.fixture(autouse=True)
def _isolate_telemetry(monkeypatch):
    """Impede que estes testes alimentem o buffer global de telemetria.

    `searchbug_metrics` e um singleton de processo partilhado. Sem isto, os
    eventos dos `lookup_phone` daqui ficam pendurados no buffer e sao descarregados
    para `data/leads.db` durante um teste posterior de telemetria, que conta as
    linhas e falha. Estes testes sokiemcovers o client HTTP.
    """
    monkeypatch.setattr(sb.searchbug_metrics, "record", lambda *a, **k: None)
    yield


@pytest.fixture
def patched_client(monkeypatch):
    monkeypatch.setattr(sb.httpx, "AsyncClient", _FakeClient)
    return _FakeClient


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(sb.settings, "SEARCHBUG_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(sb.settings, "SEARCHBUG_ACCOUNT_CODE", "test-code", raising=False)
    svc = PhoneLookupService()
    svc._phone_cache.clear()
    svc._client = None
    return svc


# ---------------------------------------------------------------------------
# 1) Reutilizacao: um unico client para varias chamadas
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_client_is_reused_across_calls(patched_client, service):
    """Duas chamadas -> um unico client. Um client por request = bug original."""
    await service._get_client()
    await service._get_client()
    await service._get_client()

    assert len(patched_client.instances) == 1, (
        f"esperava 1 client partilhado, criaram {len(patched_client.instances)}"
    )


@pytest.mark.asyncio
async def test_concurrent_get_client_creates_only_one(patched_client, service):
    """Corridas no arranque nao podem criar clients duplicados (o lock protege)."""
    import asyncio

    clients = await asyncio.gather(*(service._get_client() for _ in range(8)))

    assert len(patched_client.instances) == 1
    assert all(c is clients[0] for c in clients)


@pytest.mark.asyncio
async def test_repeated_lookups_do_not_rebuild_client(patched_client, service):
    """Duas lookups reais passam pelo mesmo client e o payload continua inteiro."""
    await service.lookup_phone("10 MAIN ST", "NEW YORK", "NY", owner_name="JOHN DOE")
    await service.lookup_phone(
        "22 BROAD ST", "NEW YORK", "NY", owner_name="JANE ROE", zip_code="10004"
    )

    assert len(patched_client.instances) == 1
    assert len(patched_client.posts) == 2
    assert patched_client.posts[1]["data"]["ADDRESS"] == "22 BROAD ST"


# ---------------------------------------------------------------------------
# 2) Timeout: default 10s, configuravel
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_default_timeout_is_ten_seconds(patched_client, service):
    await service._get_client()

    timeout = service.timeout
    assert timeout.read == 10.0, f"timeout de leitura deve ser 10s, veio {timeout.read}"
    assert timeout.connect == 5.0, f"timeout de ligacao deve ser 5s, veio {timeout.connect}"


def test_timeout_comes_from_settings(monkeypatch):
    """Operador pode ajustar o timeout sem tocar em codigo."""
    monkeypatch.setattr(sb.settings, "SEARCHBUG_TIMEOUT_SECONDS", 7.5, raising=False)
    monkeypatch.setattr(sb.settings, "SEARCHBUG_CONNECT_TIMEOUT_SECONDS", 3.0, raising=False)
    monkeypatch.setattr(sb.settings, "SEARCHBUG_API_KEY", "k", raising=False)

    svc = PhoneLookupService()
    assert svc.timeout.read == 7.5
    assert svc.timeout.connect == 3.0


# ---------------------------------------------------------------------------
# 3/4) Seguranca e pooling definidos na construcao, nao por request
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_verify_true_and_pooling_are_set_at_construction(patched_client, service):
    """TLS nunca desligado; pooling e redirects sao do client, nao de cada post."""
    await service._get_client()

    kwargs = patched_client.instances[0].kwargs
    assert kwargs.get("verify") is True, "verify=False exporia a credencial da conta"
    assert kwargs.get("follow_redirects") is True
    assert isinstance(kwargs.get("limits"), httpx.Limits)
    assert kwargs["limits"].max_connections == 10
    assert kwargs["limits"].max_keepalive_connections == 5


@pytest.mark.asyncio
async def test_post_does_not_override_timeout_per_request(patched_client, service):
    """O timeout vem do client. Passar timeout=20 por request anulava a config."""
    await service.lookup_phone("10 MAIN ST", "NEW YORK", "NY", owner_name="JOHN DOE")

    assert patched_client.posts, "esperava pelo menos uma chamada"
    for call in patched_client.posts:
        assert "timeout" not in call["kwargs"], (
            "timeout por request sobrepoe-se a config do client"
        )
        assert call["kwargs"].get("follow_redirects") is None


# ---------------------------------------------------------------------------
# 5) Shutdown limpo
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_aclose_closes_client_and_allows_reuse(patched_client, service):
    first = await service._get_client()

    await service.aclose()

    assert first.closed is True
    assert service._client is None

    second = await service._get_client()
    assert second is not first
    assert len(patched_client.instances) == 2


@pytest.mark.asyncio
async def test_aclose_is_safe_without_client(service):
    """Sem client criado, o shutdown nao pode explodir."""
    await service.aclose()
    assert service._client is None