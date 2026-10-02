"""Contrato do payload enviado ao Searchbug (provider PAGO).

Porquê fixar o payload num teste: cada chamada ao Searchbug custa dinheiro, e um
payload com lixo nao é apenas feio -- degrada o match e queima credito. Estes
testes interceptam o `httpx.AsyncClient.post` e verificam o `form_data` real
que sairia para a rede, sem fazer chamada nenhuma.

Cada teste fixa uma correccao concreta:
1. Nome corporativo NAO e partido em FNAME/LNAME ("65 MS LLC" chegava como
   FNAME="65" / LNAME="MS LLC").
2. Nome de pessoa continua a ser partido, com sufixos no ultimo nome.
3. ADDRESS nao repete a cidade/estado/zip que ja vao em campos dedicados.
4. O ZIP entra na chave de cache: o mesmo address/city/state com ZIP diferente
   e outro imovel.
5. verify=True: a verificacao de TLS nao pode ser desligada.

Nenhum destes testes toca na rede.
"""
from __future__ import annotations

import httpx
import pytest

from backend.services import searchbug as sb
from backend.services.searchbug import (
    PhoneLookupResult,
    PhoneLookupService,
    is_corporate_name,
    normalize_provider_address,
    split_person_name,
)


class _CapturedPost:
    """Substitui httpx.AsyncClient e guarda o form_data enviado."""

    def __init__(self, calls: list[dict]):
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, **kwargs):
        self._calls.append({"url": url, "data": dict(data or {}), "kwargs": kwargs})
        return httpx.Response(
            200,
            json={"Status": "NORESULTS", "ERROR": "No results"},
            request=httpx.Request("POST", url),
        )


@pytest.fixture
def captured(monkeypatch):
    """Captura o payload e impede qualquer chamada real."""
    calls: list[dict] = []

    def _factory(*args, **kwargs):
        monkeypatch_client_kwargs.update(kwargs)
        return _CapturedPost(calls)

    monkeypatch_client_kwargs: dict = {}
    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    return calls, monkeypatch_client_kwargs


@pytest.fixture
def service(monkeypatch):
    """Servico com credenciais, pronto a construir payload."""
    monkeypatch.setattr(sb.settings, "SEARCHBUG_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(sb.settings, "SEARCHBUG_ACCOUNT_CODE", "test-code", raising=False)
    svc = PhoneLookupService()
    svc._phone_cache.clear()
    return svc


# ---------------------------------------------------------------------------
# 1) Nome corporativo nunca vira FNAME/LNAME
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "owner_name",
    [
        "65 MS LLC",
        "ACME INC",
        "PARK AVENUE REALTY LLC",
        "MSLLC",
        "ACMEINC",
        "BIG BEAR HOLDINGS",
        "SOHO PROPERTY GROUP",
    ],
)
async def test_corporate_name_is_never_split_into_fname_lname(
    captured, service, owner_name
):
    """O bug original: "65 MS LLC" -> FNAME="65", LNAME="MS LLC".

    Enviado ao provider, esse lixo piora o match de uma chamada PAGA. O
    owner_name completo nao e um campo do API, portanto nao se envia -- a
    consulta continua a funcionar pela morada, que e a chave real.
    """
    calls, _ = captured
    result = await service.lookup_phone(
        "101 WEST 104 STREET", "NEW YORK", "NY", owner_name=owner_name, zip_code="10011"
    )
    assert result.success is False

    assert len(calls) == 1, "esperava exatamente uma chamada paga"
    form = calls[0]["data"]
    assert "FNAME" not in form, f"nome corporativo partido em FNAME: {form.get('FNAME')!r}"
    assert "LNAME" not in form, f"nome corporativo partido em LNAME: {form.get('LNAME')!r}"
    # A morada continua a ser enviada: sem nome, o lookup funciona na mesma.
    assert form["ADDRESS"] == "101 WEST 104 STREET"
    assert form["CITY"] == "NEW YORK"
    assert form["STATE"] == "NY"
    assert form["ZIP"] == "10011"


# ---------------------------------------------------------------------------
# 2) Nome de pessoa continua a ser partido corretamente
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "owner_name,expected_fname,expected_lname",
    [
        ("MARIA SANTOS", "MARIA", "SANTOS"),
        ("JOHN", "JOHN", ""),
        ("JOHN SMITH JR", "JOHN", "SMITH JR"),
        ("MARIA DE OLIVEIRA", "MARIA", "DE OLIVEIRA"),
        ("PEDRO  MARTIN  ", "PEDRO", "MARTIN"),
    ],
)
async def test_person_name_is_still_split(
    captured, service, owner_name, expected_fname, expected_lname
):
    """A correccao do caso corporativo nao pode partir os nomes de pessoa."""
    calls, _ = captured
    await service.lookup_phone(
        "101 WEST 104 STREET", "NEW YORK", "NY", owner_name=owner_name, zip_code="10011"
    )

    form = calls[0]["data"]
    assert form.get("FNAME") == expected_fname, form
    if expected_lname:
        assert form.get("LNAME") == expected_lname, form
    else:
        assert "LNAME" not in form, form


# ---------------------------------------------------------------------------
# 3) ADDRESS nao repete cidade/estado/zip
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_address,city,state,expected",
    [
        # O caso real: os scrapers devolvem a cidade dentro do address.
        ("123 MAIN ST, BROOKLYN, NY", "BROOKLYN", "NY", "123 MAIN ST"),
        ("123 MAIN ST, BROOKLYN, NY 11201", "BROOKLYN", "NY", "123 MAIN ST"),
        # Ja limpo: nao se mexe.
        ("123 MAIN ST", "BROOKLYN", "NY", "123 MAIN ST"),
        # So o zip no fim.
        ("123 MAIN ST, 11201", "BROOKLYN", "NY", "123 MAIN ST"),
        # subunits / suites: preservados.
        ("123 MAIN ST APT 4B, BROOKLYN, NY", "BROOKLYN", "NY", "123 MAIN ST APT 4B"),
    ],
)
async def test_address_does_not_repeat_city_state_or_zip(
    captured, service, raw_address, city, state, expected
):
    calls, _ = captured
    await service.lookup_phone(
        raw_address, city, state, owner_name="MARIA SANTOS", zip_code="11201"
    )

    form = calls[0]["data"]
    assert form["ADDRESS"] == expected, form
    assert form["CITY"] == city
    assert form["STATE"] == state


def test_normalize_provider_address_never_mutates_a_legit_address():
    """Guarda contra mutilacao: so se corta o que duplica city/state/zip."""
    # "MANHATTAN" e uma palavra do nome da rua, nao a cidade: preserva.
    assert (
        normalize_provider_address("5 MANHATTAN AVE", "BROOKLYN", "NY")
        == "5 MANHATTAN AVE"
    )
    # Endereco sem cidade nao e tocado.
    assert normalize_provider_address("123 MAIN ST", "", "") == "123 MAIN ST"


# ---------------------------------------------------------------------------
# 4) ZIP na chave de cache
# ---------------------------------------------------------------------------
def test_cache_key_separates_different_zips(service):
    """Mesmo address/city/state com ZIP diferente = imoveis diferentes."""
    a = service._cache_key("101 WEST 104 ST", "NEW YORK", "NY", "10011", "MARIA SANTOS")
    b = service._cache_key("101 WEST 104 ST", "NEW YORK", "NY", "10012", "MARIA SANTOS")
    assert a != b, "ZIP ausente da cache key: um 'nao achou' contamina o outro"


@pytest.mark.asyncio
async def test_negative_cache_does_not_leak_across_zips(service):
    """O negativo de um ZIP nao pode fechar a consulta de outro imovel.

    Conta-se as chamadas ao PROVIDER, nao as HTTP: o provider e substituido
    aqui, por isso nao ha pedidos para capturar.

    Sequencia: 10011 (miss) -> 10012 (miss) -> 10011 (hit no negativo).
    Esperado: 2 chamadas pagas. Sem o ZIP na chave, a 2a herdava o negativo da
    1a e o cliente pagava um "nao achou" por um imovel que nunca foi consultado.
    """
    paid_calls = []

    async def _no_results(address, city, state, owner_name=None, zip_code=None):
        paid_calls.append(zip_code)
        return PhoneLookupResult(success=False, error="No results", provider="Searchbug")

    service._lookup_searchbug = _no_results
    service._phone_cache.clear()

    for zip_code in ("10011", "10012", "10011"):
        await service.lookup_phone(
            "101 WEST 104 ST",
            "NEW YORK",
            "NY",
            owner_name="MARIA SANTOS",
            zip_code=zip_code,
        )

    assert paid_calls == ["10011", "10012"], (
        f"o cache negativeu entre imoveis diferentes: chamadas pagas={paid_calls}"
    )


# ---------------------------------------------------------------------------
# 5) TLS verificado
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tls_verification_is_enabled(captured, service):
    """verify=False envia a credencial da conta sem proteccao no transporte."""
    calls, client_kwargs = captured
    await service.lookup_phone(
        "101 WEST 104 STREET", "NEW YORK", "NY", owner_name="MARIA SANTOS"
    )
    assert client_kwargs.get("verify") is True, (
        "verificacao de TLS desligada no cliente do provider"
    )


# ---------------------------------------------------------------------------
# 6) Predicados isolados
# ---------------------------------------------------------------------------
def test_is_corporate_name():
    assert is_corporate_name("65 MS LLC") is True
    assert is_corporate_name("ACME INC") is True
    assert is_corporate_name("PARKSLTD") is True
    assert is_corporate_name("MARIA SANTOS") is False
    assert is_corporate_name("JOHN SMITH JR") is False
    assert is_corporate_name(None) is False
    assert is_corporate_name("") is False


def test_split_person_name_never_loses_tokens():
    for name in ("MARIA SANTOS", "JOHN SMITH JR", "MARIA DE OLIVEIRA", "PEDRO MARTIN"):
        first, last = split_person_name(name)
        rebuilt = " ".join(t for t in (first, last) if t)
        assert rebuilt == " ".join(name.split()), (name, rebuilt)