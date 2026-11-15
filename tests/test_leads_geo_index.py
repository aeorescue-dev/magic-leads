"""Índice de produção `idx_leads_geo`: idempotência e plano de execução."""

from __future__ import annotations

from backend.services.db import get_connection, init_db


def test_index_creation_is_idempotent_and_used_by_planner():
    init_db()
    init_db()  # segunda execução não pode falhar nem recriar

    conn = get_connection()
    try:
        index = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_leads_geo'"
        ).fetchone()
        assert index is not None
        assert "is_feed_ok" in index["sql"]
        assert "neighborhood" in index["sql"]
        # O agregado de frescos (<24 h) usa created_at; tem de estar no índice
        # para o plano continuar COVERING (SLO <50 ms pós-deploy).
        assert "created_at" in index["sql"]

        plan = [
            row["detail"]
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT COUNT(*) FROM leads l "
                "WHERE l.is_feed_ok=1 AND l.city=? COLLATE NOCASE "
                "AND l.date_reported >= date('now','-7 days') "
                "AND l.signal_type IS NOT NULL",
                ("Boston",),
            )
        ]
        fresh_plan = [
            row["detail"]
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT COUNT(*), SUM(CASE WHEN datetime(l.created_at) "
                ">= datetime('now','-24 hours') THEN 1 ELSE 0 END) "
                "FROM leads l "
                "WHERE l.is_feed_ok=1 AND l.city=? COLLATE NOCASE "
                "AND l.date_reported >= date('now','-7 days') "
                "AND l.signal_type IS NOT NULL",
                ("Boston",),
            )
        ]
    finally:
        conn.close()

    assert any("idx_leads_geo" in detail for detail in plan), plan
    assert any("COVERING INDEX idx_leads_geo" in detail for detail in fresh_plan), fresh_plan
