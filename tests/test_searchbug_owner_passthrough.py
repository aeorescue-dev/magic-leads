"""Regressao: o dispatcher do PhoneLookupService tem de preservar owner_name/zip_code.

Contexto
--------
`PhoneLookupService.lookup_phone` (backend/services/searchbug.py:107) recebe
`owner_name` e `zip_code`, mas a cadeia de providers chamava:

    result = await func(address, city, state)      # <- descartava os dois

O `_lookup_searchbug` (linha 139) aceita e usa esses parametros para montar
FNAME/LNAME/ZIP no pedido pago. Descartados no dispatcher, toda a consulta
paga era cega, apenas por endereco.

Impacto observado em producao (deploy 0f287...): 19 respostas "No results"
para 2 sucessos no mesmo intervalo, com credenciais válidas.

Regra arquitectural que este teste protege: o Searchbug é a ETAPA FINAL e
ISOLADA de telefone, e tem de usar o nome e o endereço já garimpados.
Nao pode ser uma consulta cega por endereco.
"""

import pytest

from backend.services.searchbug import PhoneLookupService, PhoneLookupResult


def _ok_result():
    return PhoneLookupResult(success=True, phone="(718) 555-0142", provider="Searchbug")


@pytest.mark.asyncio
async def test_lookup_phone_forwards_owner_name_and_zip(monkeypatch):
    """owner_name e zip_code chegam ao provider sem alteracao."""
    captured = {}

    async def _fake_provider(address, city, state, owner_name=None, zip_code=None):
        captured.update(
            address=address,
            city=city,
            state=state,
            owner_name=owner_name,
            zip_code=zip_code,
        )
        return _ok_result()

    service = PhoneLookupService()
    monkeypatch.setattr(service, "_lookup_searchbug", _fake_provider, raising=False)

    result = await service.lookup_phone(
        "2800 MICHIGAN AVE",
        "CHICAGO",
        "IL",
        owner_name="MARIA SANTOS",
        zip_code="60611",
    )

    assert result.phone == "(718) 555-0142"
    assert captured["owner_name"] == "MARIA SANTOS", (
        "owner_name foi descartado pelo dispatcher: o Searchbug passou a ser "
        "uma consulta cega por endereco."
    )
    assert captured["zip_code"] == "60611", "zip_code foi descartado pelo dispatcher."


@pytest.mark.asyncio
async def test_lookup_phone_forwards_owner_name_positionally_safe(monkeypatch):
    """A mesma garantia quando o owner_name contem nomes compostos."""
    captured = {}

    async def _fake_provider(address, city, state, owner_name=None, zip_code=None):
        captured.update(owner_name=owner_name, zip_code=zip_code)
        return _ok_result()

    service = PhoneLookupService()
    monkeypatch.setattr(service, "_lookup_searchbug", _fake_provider, raising=False)

    await service.lookup_phone(
        "101 WEST 104 STREET",
        "NEW YORK",
        "NY",
        owner_name="  JOEL DE LA CRUZ  ",
        zip_code="10025",
    )

    assert captured["owner_name"] == "  JOEL DE LA CRUZ  "
    assert captured["zip_code"] == "10025"


@pytest.mark.asyncio
async def test_provider_name_must_be_forwarded_as_keyword(monkeypatch):
    """Guarda estrutural: nenhum provider da cadeia pode ser chamado sem os args.

    Impede a reintroducao do bug poroutedra via assinatura posicional.
    """
    captured = {}

    async def _strict_provider(address, city, state, owner_name=None, zip_code=None):
        captured["chamada"] = True
        return _ok_result()

    service = PhoneLookupService()
    monkeypatch.setattr(service, "_lookup_searchbug", _strict_provider, raising=False)

    await service.lookup_phone("9630 63 DRIVE", "MIAMI", "FL", owner_name=None, zip_code=None)

    assert captured.get("chamada") is True


@pytest.mark.asyncio
async def test_searchbug_builds_fname_lname_zip_from_owner(monkeypatch):
    """O pedido pago ao Searchbug inclui FNAME/LNAME/ZIP."""
    captured = {}

    class _FakeResponse:
        status_code = 200
        text = '{"results": []}'
        headers = {"content-type": "application/json"}

        def json(self):
            return {"results": []}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None, **kwargs):
            captured.update(data=dict(data or {}))
            return _FakeResponse()

    import backend.services.searchbug as sb

    monkeypatch.setattr(sb.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(sb.settings, "SEARCHBUG_ACCOUNT_CODE", "123456", raising=False)

    service = PhoneLookupService()
    service.searchbug_key = "fake-key"

    await service._lookup_searchbug(
        "101 WEST 104 STREET",
        "NEW YORK",
        "NY",
        owner_name="MARIA SANTOS",
        zip_code="10025",
    )

    data = captured.get("data", {})
    assert data.get("FNAME") == "MARIA", f"FNAME ausente: {data}"
    assert data.get("LNAME") == "SANTOS", f"LNAME ausente: {data}"
    assert data.get("ZIP") == "10025", f"ZIP ausente: {data}"
    assert data.get("CO_CODE") == "123456"
    assert data.get("TYPE") == "api_contact"
