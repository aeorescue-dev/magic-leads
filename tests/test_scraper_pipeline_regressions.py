"""Regressao para os 3 pontos cegos do pipeline de garimpagem.

1. Chicago: a entrada pedia "service_request_number", coluna que NAO existe no
   dataset v6vf-nfxy. O portal devolvia 400, _fetch_soql devolvia [], e a cidade
   ficava verde no city_health com 0 leads durante semanas.
2. /api/leads/today: o filtro "Obrigacao legal" envia "dob_violation,hpd_violation"
   e o backend comparava a string inteira com "=", devolvendo sempre 0 sem erro.
3. city_health: falhas de fetch tem de marcar a cidade como falha, nunca como
   sucesso (verde falso).
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import httpx as _httpx_mod
import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import app
from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.scrapers.socrata_311 import SocrataFetchError, socrata_scraper
from backend.services.db import db_service

_EXT = {"n": 0}


def _insert(source_type: str, city: str, status: str = "Open") -> int:
    _EXT["n"] += 1
    payload = EnrichedLead(
        external_id=f"pytest-pipeline-{_EXT['n']}",
        source_type=SourceType(source_type),
        address=f"{_EXT['n']} REGRESSION AVENUE",
        city=city,
        state="IL",
        zip_code="60601",
        lat=None,
        lng=None,
        county="COOK",
        issue_category=IssueCategory.ROOF,
        issue_description="Chicago building roof leak",
        urgency_level=UrgencyLevel.HIGH,
        owner_name=None,
        owner_phone=None,
        owner_email=None,
        date_reported=datetime.now(),
        image_url=None,
        source_url=None,
    )
    row = db_service._service.insert_lead_new(payload)
    assert row is not None
    return row["id"]


# ---------------------------------------------------------------- 1. Chicago
def test_chicago_entry_uses_existing_column():
    """A entrada de Chicago tem de pedir sr_number (a coluna que existe).

    Regressao do 400 "No such column: service_request_number", que zerava a
    cidade inteira. Se alguém voltar a pedir service_request_number, este teste
    falha antes do deploy.
    """
    fields = _chicago_entry_fields()
    assert fields, "entrada de Chicago nao encontrada no _scrape_worker"
    assert "sr_number" in fields, (
        f"Chicago devia pedir sr_number; pede {fields}"
    )
    assert "service_request_number" not in fields, (
        "service_request_number nao existe no dataset v6vf-nfxy — "
        "o portal devolve 400 e a cidade fica com 0 leads"
    )


def test_guess_columns_recognises_sr_number():
    cols = socrata_scraper._guess_columns([
        "sr_number", "created_date", "sr_type", "street_address",
        "zip_code", "latitude", "longitude", "status",
    ])
    assert cols["_has_date"] is True
    assert cols["_has_desc"] is True
    assert cols["ext"] == "sr_number"


def _chicago_entry_fields() -> list[str]:
    """Le a lista de campos de Chicago diretamente da fonte do _scrape_worker.

    Usamos ast em vez de regex para nao partir a linha: a entrada e um dict
    dentro de um lista literal e a linha tem comentarios a seguir.
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(main_module._scrape_worker))
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Dict):
            continue
        pairs = dict(zip(
            [k.value for k in node.keys if isinstance(k, ast.Constant)],
            node.values,
        ))
        domain = pairs.get("domain")
        fields = pairs.get("fields")
        if (
            isinstance(domain, ast.Constant)
            and domain.value == "data.cityofchicago.org"
            and isinstance(fields, ast.List)
        ):
            return [el.value for el in fields.elts if isinstance(el, ast.Constant)]
    return []


# ------------------------------------------------------------------ 2. type
def test_type_filter_accepts_comma_separated_values():
    """'dob_violation,hpd_violation' tem de devolver a UNIAO das duas.

    Antes comparava a string inteira com "=" e devolvia 0 resultados com
    HTTP 200 — a aba Oportunidades ficava vazia sem qualquer erro.
    """
    dob_id = _insert("dob_violation", "CHICAGO")
    hpd_id = _insert("hpd_violation", "CHICAGO")
    other_id = _insert("permit", "CHICAGO")

    with TestClient(app) as client:
        r = client.get("/api/leads/today?type=dob_violation,hpd_violation&include_incomplete=true")
        assert r.status_code == 200
        body = r.json()
        ids = {str(lead["id"]) for lead in body["leads"]}

    assert str(dob_id) in ids, "lead dob_violation ausente do filtro agrupado"
    assert str(hpd_id) in ids, "lead hpd_violation ausente do filtro agrupado"
    assert str(other_id) not in ids, "lead permit nao deveria entrar no filtro"

    # A uniao tem de bater as partes. Este e o assert que apanha a regressao do
    # "=": com igualdade sobre a string inteira, o grouped devolvia 0 e o
    # teste passava por acidente se so verificassemos o status 200.
    with TestClient(app) as client:
        part_dob = client.get("/api/leads/today?type=dob_violation&include_incomplete=true").json()["total"]
        part_hpd = client.get("/api/leads/today?type=hpd_violation&include_incomplete=true").json()["total"]
        grouped = body["total"]

    assert grouped >= part_dob, (
        f"filtro agrupado ({grouped}) perdeu leads que o filtro isolado devolve "
        f"(dob={part_dob})"
    )
    assert grouped >= part_hpd, (
        f"filtro agrupado ({grouped}) perdeu leads que o filtro isolado devolve "
        f"(hpd={part_hpd})"
    )


def test_type_filter_single_value_still_works():
    _insert("hpd_violation", "CHICAGO")
    with TestClient(app) as client:
        r = client.get("/api/leads/today?type=hpd_violation&include_incomplete=true")
        assert r.status_code == 200
        assert r.json()["total"] >= 1


def test_type_filter_rejects_unknown_values_without_500():
    with TestClient(app) as client:
        r = client.get("/api/leads/today?type=,,%20,&include_incomplete=true")
        assert r.status_code == 200
        assert r.json()["total"] >= 0


# ------------------------------------------------- 3. fetch error / city_health
def test_fetch_from_dataset_raises_on_missing_columns():
    """Colunas nao reconhecidas = falha de schema, nao 'zero leads'.

    Antes devolvia [] e a cidade era marcada como sucesso.
    """

    async def _go():
        with pytest.raises(SocrataFetchError):
            await socrata_scraper.fetch_from_dataset(
                "data.cityofchicago.org", "v6vf-nfxy", "Chicago", "IL",
                field_names=["campo_que_nao_existe", "outro_que_nao_existe"],
            )

    asyncio.run(_go())


def test_fetch_soql_raises_instead_of_returning_empty(monkeypatch):
    """Um 400 do portal tem de propagar, nunca virar lista vazia."""

    class _Resp:
        status_code = 400

        def raise_for_status(self):
            raise _httpx_mod.HTTPStatusError("400 Bad Request", request=None, response=None)

        def json(self):
            return {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(_httpx_mod, "AsyncClient", _Client)
    monkeypatch.setattr(socrata_scraper, "MAX_RETRIES", 0)

    async def _go():
        with pytest.raises(SocrataFetchError):
            await socrata_scraper._fetch_soql(
                domain="data.cityofchicago.org", dataset="v6vf-nfxy",
                select="sr_number", where=None,
            )

    asyncio.run(_go())


def test_city_health_marks_failure_when_all_sources_fail(monkeypatch):
    """Cidade com 0 fontes respondidas tem de ser registada como FALHA."""
    called = {"failure": [], "success": []}

    async def _fail(city, error=None):
        called["failure"].append(city)
        return {"failure_count": 1, "circuit_open_until": None}

    async def _ok(city):
        called["success"].append(city)

    async def _reset(city):
        return None

    async def _health():
        return {}

    async def _noop(*a, **k):
        return None

    async def _boom(*a, **k):
        raise SocrataFetchError("fonte morta")

    async def _no_insert(*a, **k):
        return None

    def _boom_client(*a, **k):
        raise SocrataFetchError("rede bloqueada no teste")

    # Patch no wrapper async (db_service.*), nao em _service.*: o wrapper usa
    # anyio.to_thread.run_sync e devolveria uma coroutine nunca esperada.
    monkeypatch.setattr(db_service, "record_city_failure", _fail)
    monkeypatch.setattr(db_service, "record_city_success", _ok)
    monkeypatch.setattr(db_service, "reset_anomaly_counter", _reset)
    monkeypatch.setattr(db_service, "get_all_city_health", _health)
    monkeypatch.setattr(main_module.db_service, "insert_lead_new", _no_insert)
    monkeypatch.setattr(main_module, "_dlq_reprocess", _noop)
    # Boston usa httpx directamente (CKAN) — cortar tambem, senao o teste
    # busca dados reais e o all_raw nao fica vazio.
    monkeypatch.setattr(_httpx_mod, "AsyncClient", _boom_client)
    # Corta TODAS as saidas de rede: Socrata (DOB violations/permits + generico),
    # Boston CKAN e o webhook. Sem isto o teste ia buscar dados reais ao portal.
    monkeypatch.setattr(socrata_scraper, "fetch_from_dataset", _boom)
    monkeypatch.setattr(type(socrata_scraper), "_fetch_soql", _boom)
    monkeypatch.setattr(main_module, "_send_scraper_webhook", _noop)
    # _scrape_worker lê a fila de runs; corre o corpo com um estado mínimo.
    main_module._scrape_runs["pytest-health-failure"] = {
        "run_id": "pytest-health-failure", "running": True,
        "started_at": datetime.now().isoformat(),
        "inserted": 0, "total_raw": 0, "status": "running",
        "error": None, "trigger": "manual",
    }
    monkeypatch.setattr(main_module.db_service, "record_scrape_run", _noop)

    asyncio.run(main_module._scrape_worker("pytest-health-failure"))

    assert "Chicago" in called["failure"], (
        f"Chicago devia estar em failure, obtive success={called['success']} "
        f"failure={called['failure']}"
    )
    assert "Chicago" not in called["success"]
