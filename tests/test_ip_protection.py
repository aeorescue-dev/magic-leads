"""Regressão de proteção de propriedade intelectual (IP) na API.

Fechado por auditoria de go-live. Cada teste abaixo travava uma fuga real
encontrada em produção:

1. `/api/scraper/discover` era PUBLICO e devolvia 847 datasets (dominio + id +
   nome) — o mapa completo de que fontes o scraper cobre, ou seja, o segredo
   de negocio. Frontend nao consome a rota; agora e admin-only.
2. `/openapi.json`, `/docs` e `/redoc` eram publicos e documentavam as 89
   rotas da API (incluindo 22 de admin/cron/scraper) num unico GET.
3. O texto das excecoes (`detail=f"Erro: {e!s}"`) aparecia nas respostas 500
   de rotas publicas/usuario — fuga de detalhes internos (schema, caminhos).
4. `/api/push/test-endpoint` era um resto de debug sem utilizadores.

Se algum destes testes voltar a falhar, uma fuga de IP reabriu-se.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture
def client(monkeypatch):
    from backend import config
    from backend import main as main_mod

    # NOTA: LEADS_DB_PATH é definido pelo conftest ANTES do import do backend;
    # setenv aqui não teria efeito (settings já cacheado).
    monkeypatch.setattr(config.settings, "ADMIN_SECRET", "segredo-de-teste", raising=False)
    monkeypatch.setattr(main_mod.settings, "ADMIN_SECRET", "segredo-de-teste", raising=False)
    monkeypatch.setattr(main_mod.settings, "DEBUG", False, raising=False)
    return TestClient(main_mod.app, raise_server_exceptions=False)


def _no_admin(client, url, method="get", **kw):
    r = getattr(client, method)(url, **kw)
    assert r.status_code in (401, 403), (
        f"{method.upper()} {url} devolveu {r.status_code} sem credenciais de admin — fuga reaberta"
    )
    return r


def test_discover_e_admin_only(client):
    """O catalogo de 847 datasets nao pode ser publico."""
    r = _no_admin(client, "/api/scraper/discover")
    body = r.text.lower()
    for marker in ("socrata", "dataset", "domain", "cookcounty", "cityofchicago"):
        assert marker not in body, f"resposta sem auth ainda expoe {marker!r}"


def test_openapi_e_docs_desativados_em_producao():
    """/openapi.json, /docs e /redoc nao existem quando DEBUG=False.

    A app constrói o FastAPI no import, por isso avaliamos num subprocesso com
    DEBUG=False (como no Railway) em vez de monkeypatchar a instância viva.
    """
    import os
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    code = (
        "from backend import main;"
        "print(main.app.openapi_url, main.app.docs_url, main.app.redoc_url)"
    )
    env = {**os.environ, "DEBUG": "False", "PYTHONPATH": str(repo)}
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120,
        cwd=str(repo), env=env,
    )
    assert out.returncode == 0, out.stderr[-500:]
    # O logger do app escreve no stdout; procuramos a linha do print no fim.
    last_line = out.stdout.strip().splitlines()[-1].strip()
    assert last_line == "None None None", (
        f"em producao (DEBUG=False) os endpoints de docs continuam ligados: {last_line!r}"
    )


def test_push_test_endpoint_removido(client):
    """Resto de debug removido — nao pode reaparecer."""
    r = client.get("/api/push/test-endpoint")
    assert r.status_code == 404, f"/api/push/test-endpoint voltou com HTTP {r.status_code}"


def test_admin_routes_falham_fechado(client):
    """As rotas admin continuam 401 sem o X-Admin-Secret."""
    for url in ("/api/admin/overview", "/api/admin/sources", "/api/admin/reveals"):
        _no_admin(client, url)


def test_rotas_publicas_nao_devolvem_texto_de_excecao(client):
    """Uma rota publica que estoura nao pode devolver a mensagem da excecao."""
    # lead inexistente (404) e o caminho feliz; o objetivo aqui e garantir que
    # o handler generico existe — se algum handler voltar a interpolar `e`,
    # o import abaixo rebenta a colecao.
    import inspect

    import backend.main as m

    src = inspect.getsource(m)
    assert 'detail=f"Erro: {e' not in src, "handler volta a interpolar excecao no detail"
    assert 'detail=f"Erro ao processar reserva: {e}"' not in src
    r = client.get("/api/leads/999999999")
    assert r.status_code in (200, 404)
    assert "Traceback" not in r.text
    assert "sqlite3" not in r.text
