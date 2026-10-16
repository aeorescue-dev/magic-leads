"""Regressão: o resumo do dashboard honra o filtro de categorias.

Bug de produção: `get_dashboard_summary` recebia as chaves canónicas
("Roof", "Structure", ...) mas o `cat_map` interno só conhecia as legadas PT
("telhado", "estrutura", ...). O resultado era `db_cats=[]` e o filtro de
categoria era descartado em silêncio — o "No seu interesse" contava TODOS os
leads, ignorando as categorias escolhidas.
"""

import uuid

import pytest

from backend.services.db import (
    clear_dashboard_summary_cache,
    db_service,
    get_connection,
    normalize_trade_categories,
)


@pytest.fixture(autouse=True)
def _isolate_leads():
    """Limpa `leads` e o cache do resumo antes e depois de cada teste.

    As linhas inseridas aqui são visíveis para outros ficheiros (ex.:
    test_imports::test_leads_endpoint lista /api/leads) e este ficheiro corre
    antes, pelo que sem isolamento poluiriam esses testes. O cache in-process
    do resumo (TTL curto) também tem de ser invalidado entre testes, senão um
    resultado de um teste serviria o seguinte.
    """
    clear_dashboard_summary_cache()
    _clear_leads()
    yield
    _clear_leads()
    clear_dashboard_summary_cache()



# ---------------------------------------------------------------------------
# normalize_trade_categories (função pura)
# ---------------------------------------------------------------------------

def test_normalize_keeps_canonical_keys():
    assert normalize_trade_categories(["Roof", "Paint"]) == ["Roof", "Paint"]


def test_normalize_maps_legacy_pt_keys():
    assert normalize_trade_categories(["telhado", "obras"]) == ["Roof", "Permit_Rejected"]


def test_normalize_dedupes_and_preserves_order():
    assert normalize_trade_categories(["Paint", "Roof", "Paint"]) == ["Paint", "Roof"]
    # canónica + legada da mesma categoria não duplica
    assert normalize_trade_categories(["Roof", "telhado"]) == ["Roof"]


def test_normalize_ignores_unknown_and_empty():
    assert normalize_trade_categories(["Banana", "", None, "Roof"]) == ["Roof"]
    assert normalize_trade_categories(None) == []


# ---------------------------------------------------------------------------
# get_dashboard_summary (end-to-end com SQLite)
# ---------------------------------------------------------------------------

def _clear_leads() -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads")
        conn.commit()
    finally:
        conn.close()


def _qualified_lead(category: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, case_status, date_reported) "
            "VALUES (?, '311', ?, 'NYC', 'NY', ?, 'open', '2026-01-01T00:00:00')",
            (uuid.uuid4().hex, f"{uuid.uuid4().hex[:8]} Main Street", category),
        )
        conn.commit()
    finally:
        conn.close()


def _qualified_lead_in(city: str, category: str = "Roof") -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, case_status, date_reported) "
            "VALUES (?, '311', ?, ?, 'NY', ?, 'open', '2026-01-01T00:00:00')",
            (uuid.uuid4().hex, f"{uuid.uuid4().hex[:8]} Main Street", city, category),
        )
        conn.commit()
    finally:
        conn.close()


def test_dashboard_summary_filters_by_canonical_category():
    _clear_leads()
    for _ in range(3):
        _qualified_lead("Roof")
    for _ in range(2):
        _qualified_lead("Paint")

    assert db_service._service.get_dashboard_summary(["Roof"])["total_interested"] == 3
    assert db_service._service.get_dashboard_summary(["Paint"])["total_interested"] == 2
    assert db_service._service.get_dashboard_summary(["Roof", "Paint"])["total_interested"] == 5


def test_dashboard_summary_filters_by_legacy_category():
    _clear_leads()
    for _ in range(3):
        _qualified_lead("Roof")

    assert db_service._service.get_dashboard_summary(["telhado"])["total_interested"] == 3


def test_dashboard_summary_without_interests_counts_all():
    _clear_leads()
    for _ in range(3):
        _qualified_lead("Roof")
    for _ in range(2):
        _qualified_lead("Paint")

    assert db_service._service.get_dashboard_summary(None)["total_interested"] == 5


def test_dashboard_summary_by_category_only_has_filtered_cats():
    _clear_leads()
    _qualified_lead("Roof")
    _qualified_lead("Paint")

    summary = db_service._service.get_dashboard_summary(["Roof"])
    assert set(summary["by_category"].keys()) == {"Roof"}


def test_dashboard_summary_by_city_sums_to_total_interested():
    """Invariante da barra de cidades: soma(by_city) == total_interested.

    O totalizador do painel e a barra de cidades consomem a mesma base
    (`base_where`), pelo que uma cidade isolada nunca pode exceder o total.
    """
    _clear_leads()
    for _ in range(4):
        _qualified_lead_in("NYC")
    for _ in range(3):
        _qualified_lead_in("Chicago")

    summary = db_service._service.get_dashboard_summary(None)
    assert summary["total_interested"] == 7
    assert sum(summary["by_city"].values()) == summary["total_interested"]
    assert summary["by_city"] == {"NYC": 4, "Chicago": 3}


def test_public_metrics_novas_oportunidades_is_real_inserted():
    """A frescura é o `inserted` REAL do último run, não um piso estimado.

    Regressão: `novas_oportunidades = max(captured_24h, média(inserted))`
    inflava o número (piso mínimo 500) e não correspondia a nenhuma query.
    """
    _clear_leads()
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO scraper_runs (run_id, trigger, started_at, finished_at, "
            "status, inserted) VALUES (?, 'test', datetime('now'), datetime('now'), "
            "'success', 42)",
            (uuid.uuid4().hex,),
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    try:
        metrics = db_service._service.get_public_metrics()
        assert metrics["last_scrape"]["inserted"] == 42
        assert metrics["last_scrape"]["novas_oportunidades"] == 42
        assert "floor" not in metrics["last_scrape"]
    finally:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM scraper_runs WHERE id = ?", (run_id,))
            conn.commit()
        finally:
            conn.close()
