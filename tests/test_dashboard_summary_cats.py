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
    db_service,
    get_connection,
    normalize_trade_categories,
)


@pytest.fixture(autouse=True)
def _isolate_leads():
    """Limpa `leads` antes e depois de cada teste.

    As linhas inseridas aqui são visíveis para outros ficheiros (ex.:
    test_imports::test_leads_endpoint lista /api/leads) e este ficheiro corre
    antes, pelo que sem isolamento poluiriam esses testes.
    """
    _clear_leads()
    yield
    _clear_leads()



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
