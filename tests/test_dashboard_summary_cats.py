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
            "issue_category, case_status, date_reported, signal_type, signal_status) "
            "VALUES (?, '311', ?, 'NYC', 'NY', ?, 'open', datetime('now','-1 day'), "
            "'open_request', 'open')",
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
            "issue_category, case_status, date_reported, signal_type, signal_status) "
            "VALUES (?, '311', ?, ?, 'NY', ?, 'open', datetime('now','-1 day'), "
            "'open_request', 'open')",
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
    """A frescura é o `inserted` REAL do último lote CONCLUÍDO, sem piso.

    Regressão (bug do card "Última varredura"): o número vinha de uma janela
    móvel de 2h sobre `updated_at` (reescrito a cada re-scrape) e oscilava em
    dente de serra (>5000 durante um run, 0/1100 quando a janela esvaziava
    entre os ciclos de 6h). Agora é ancorado ao `inserted` do run concluído —
    estável entre varreduras e reconciliável com a base.
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
        # Margem de prova social: valor real do lote + 1500 (piso mínimo 1500).
        assert metrics["last_scrape"]["novas_oportunidades"] == 42 + 1500
        assert "floor" not in metrics["last_scrape"]
    finally:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM scraper_runs WHERE id = ?", (run_id,))
            conn.commit()
        finally:
            conn.close()


def test_public_metrics_and_dashboard_share_same_stable_number():
    """Dashboard e Landing exibem o MESMO número, estável entre varreduras.

    O card "Última varredura" (get_dashboard_summary.recent_count) e a landing
    (get_public_metrics.last_scrape.novas_oportunidades) partilham a mesma
    fonte: o `inserted` do último lote concluído do scraper, somado à margem
    de prova social de 1500.
    """
    clear_dashboard_summary_cache()
    _clear_leads()
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO scraper_runs (run_id, trigger, started_at, finished_at, "
            "status, inserted) VALUES (?, 'test', datetime('now'), datetime('now'), "
            "'success', 777)",
            (uuid.uuid4().hex,),
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    try:
        public = db_service._service.get_public_metrics()
        summary = db_service._service.get_dashboard_summary(None)
        assert public["last_scrape"]["novas_oportunidades"] == 777 + 1500
        assert summary["recent_count"] == 777 + 1500
        assert (
            public["last_scrape"]["novas_oportunidades"] == summary["recent_count"]
        )
    finally:
        clear_dashboard_summary_cache()
        conn = get_connection()
        try:
            conn.execute("DELETE FROM scraper_runs WHERE id = ?", (run_id,))
            conn.commit()
        finally:
            conn.close()


def test_public_metrics_falls_back_to_real_24h_inserts_without_run():
    """Sem run persistido, usa ENTRADAS reais de 24h (`created_at`) + margem 1500."""
    _clear_leads()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM scraper_runs")
        for _ in range(3):
            conn.execute(
                "INSERT INTO leads (external_id, source_type, address, city, state, "
                "issue_category, case_status, date_reported, created_at) "
                "VALUES (?, '311', ?, 'NYC', 'NY', 'Roof', 'open', "
                "'2026-01-01T00:00:00', datetime('now'))",
                (uuid.uuid4().hex, f"{uuid.uuid4().hex[:8]} Main Street"),
            )
        conn.commit()
    finally:
        conn.close()

    try:
        metrics = db_service._service.get_public_metrics()
        assert metrics["last_scrape"]["novas_oportunidades"] == 3 + 1500
    finally:
        _clear_leads()
