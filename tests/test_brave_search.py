"""Provider Brave: candidatos, verificacao, cache e orcamento diario."""
from __future__ import annotations

from backend.services import brave_search as brave
from backend.services.db import get_connection


def _page(html: str, status: int = 200) -> dict:
    return {"status": status, "url": "", "html": html.encode("utf-8")}


def test_candidate_domains_ignora_diretorios():
    results = [
        {"url": "https://www.yelp.com/biz/foo"},
        {"url": "https://www.kelso-burnett.com/about"},
        {"url": "https://kelso-burnett.com/"},
        {"url": "https://www.thumbtack.com/ny/foo"},
        {"url": "https://www.linkedin.com/company/foo"},
    ]
    assert brave.candidate_domains(results) == ["kelso-burnett.com"]


def test_verify_candidate_aceita_site_da_empresa():
    def fetch(url, timeout=6.0):
        return _page(
            "<html><title>Kelso-Burnett Co. | Electrical Contractor</title>"
            "<body>Kelso-Burnett Co. Chicago electrical contractor</body></html>"
        )

    found = brave.verify_candidate("KELSO-BURNETT CO.", "CHICAGO", "kelso-burnett.com", fetch)
    assert found and found["domain"] == "kelso-burnett.com"
    assert found["source"] == "brave"


def test_verify_candidate_rejeita_diretorio_e_nome_generico():
    def fetch(url, timeout=6.0):
        return _page(
            "<html><title>Contracting NYC - Find local contractors</title>"
            "<body>Directory of contractors in New York City</body></html>"
        )

    assert brave.verify_candidate("OZ CONTRACTING", "NYC", "contractingnyc.com", fetch) is None


def test_orcamento_diario_respeita_limite(monkeypatch):
    monkeypatch.setattr(brave, "daily_limit", lambda: 2)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM system_kv WHERE key LIKE 'brave_queries:%'")
        conn.commit()
    finally:
        conn.close()
    assert brave.consume_budget() is True
    assert brave.consume_budget() is True
    assert brave.consume_budget() is False
    assert brave.budget_left() == 0


def test_cache_negativo_evita_nova_query(monkeypatch):
    city = "TESTBRAVE"
    brave.cache_set("No Site Corp", city, None, 0.0)
    assert brave.cache_get("No Site Corp", city) == {
        "domain": None, "confidence": 0.0, "source": "brave_none", "snippet": "",
    }

    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        return True

    monkeypatch.setattr(brave, "consume_budget", boom)
    monkeypatch.setattr(brave, "api_key", lambda: "fake")
    import asyncio

    assert asyncio.run(brave.find_domain("No Site Corp", city)) is None
    assert calls["n"] == 0


def test_bloqueio_do_dia_para_o_orcamento(monkeypatch):
    from backend.services.db import get_connection

    monkeypatch.setattr(brave, "daily_limit", lambda: 5)
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM system_kv WHERE key LIKE 'brave_queries:%' "
            "OR key LIKE 'brave_blocked:%'"
        )
        conn.commit()
    finally:
        conn.close()
    brave.block_for_today(429)
    assert brave.consume_budget() is False
    assert brave.budget_left() == 5  # contador nao foi gasto


def test_cache_expira(monkeypatch):
    city = "TESTBRAVE2"
    brave.cache_set("Old Corp", city, "oldcorp.com", 0.7)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE domain_search_cache SET checked_at=? WHERE city=?",
            ("2020-01-01 00:00:00", city),
        )
        conn.commit()
    finally:
        conn.close()
    assert brave.cache_get("Old Corp", city) is None
