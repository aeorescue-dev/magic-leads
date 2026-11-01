"""Fase 22 — qualificação materializada, paridade e caches.

Guardas:
  * `is_qualified`/`is_feed_ok` dão EXATAMENTE o mesmo conjunto que os WHERE
    dinâmicos (`_qualified_where`/`_feed_where`) — comparação nos dois sentidos;
  * a escrita (insert/update) recalcula as colunas;
  * o feed usa a coluna materializada e o total bate com o predicado legado;
  * `get_stats`/`get_public_metrics` usam cache de 60 s invalidável;
  * `/daily-stats` não corre sweeps de escrita.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services import db as dbmod
from backend.services.db import db_service, get_connection

CITY = "QUALITYCITY"


def _insert_lead(
    conn,
    external_id: str,
    address: str,
    category: str = "Roof",
    description: str = "roof leak",
    signal_type: str | None = "open_request",
    signal_status: str | None = "open",
    case_status: str | None = "open",
    source_type: str = "service_311",
    lead_status: str = "available",
    date_reported: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO leads (external_id, source_type, address, city, state, "
        "issue_category, issue_description, urgency_level, date_reported, "
        "signal_type, signal_status, case_status, lead_status) "
        "VALUES (?, ?, ?, ?, 'NY', ?, ?, 'medium', ?, ?, ?, ?, ?)",
        (
            external_id,
            source_type,
            address,
            CITY,
            category,
            description,
            date_reported or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            signal_type,
            signal_status,
            case_status,
            lead_status,
        ),
    )
    return int(cur.lastrowid)


@pytest.fixture()
def quality_city():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE city=?", (CITY,))
        conn.commit()
    finally:
        conn.close()
    yield
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE city=?", (CITY,))
        conn.commit()
    finally:
        conn.close()


def _legacy_ids(conn, predicate: str) -> set[int]:
    return {
        int(r["id"])
        for r in conn.execute(
            f"SELECT id FROM leads WHERE city=? AND ({predicate})", (CITY,)
        ).fetchall()
    }


def _materialized_ids(conn, column: str) -> set[int]:
    return {
        int(r["id"])
        for r in conn.execute(
            f"SELECT id FROM leads WHERE city=? AND {column}=1", (CITY,)
        ).fetchall()
    }


def test_paridade_exata_qualified_e_feed(quality_city):
    conn = get_connection()
    try:
        ids = {}
        ids["limpo"] = _insert_lead(conn, "q-clean", "123 MAIN STREET")
        ids["junk"] = _insert_lead(
            conn, "q-junk", "124 MAIN STREET",
            description="abandoned vehicle blocking the driveway",
        )
        ids["morada_curta"] = _insert_lead(conn, "q-short", "x")
        ids["categoria_fora"] = _insert_lead(
            conn, "q-cat", "125 MAIN STREET", category="Other"
        )
        ids["fechado"] = _insert_lead(
            conn, "q-closed", "126 MAIN STREET",
            signal_status="closed", case_status="closed",
        )
        ids["legado_sem_signal"] = _insert_lead(
            conn, "q-legacy", "127 MAIN STREET",
            signal_type=None, signal_status=None, case_status="open",
        )
        ids["legado_encerrado"] = _insert_lead(
            conn, "q-legacy-closed", "128 MAIN STREET",
            signal_type=None, signal_status=None, case_status="closed",
        )
        conn.commit()

        # Simula linhas antigas (antes da Fase 22): os triggers já calcularam
        # nas inserts, por isso forçamos NULL para testar o backfill.
        conn.execute(
            "UPDATE leads SET is_junk=NULL, is_feed_ok=NULL, is_qualified=NULL "
            "WHERE city=?",
            (CITY,),
        )
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) c FROM leads WHERE city=? AND is_qualified IS NULL",
            (CITY,),
        ).fetchone()["c"] == len(ids)

        dbmod.refresh_lead_quality(conn, "city = ?", (CITY,))
        conn.commit()

        legacy_qualified = _legacy_ids(conn, dbmod._qualified_where())
        legacy_feed = _legacy_ids(conn, dbmod._feed_where())
        assert _materialized_ids(conn, "is_qualified") == legacy_qualified
        assert _materialized_ids(conn, "is_feed_ok") == legacy_feed

        # Casos concretos (documentam a regra).
        assert ids["limpo"] in legacy_qualified
        assert ids["junk"] not in legacy_qualified
        assert ids["morada_curta"] not in legacy_qualified
        assert ids["categoria_fora"] not in legacy_qualified
        assert ids["fechado"] not in legacy_qualified
        assert ids["fechado"] in legacy_feed, "feed não olha ao gatilho"
        assert ids["legado_sem_signal"] in legacy_qualified
        assert ids["legado_encerrado"] not in legacy_qualified
    finally:
        conn.close()


def test_escrita_recalcula_as_colunas(quality_city):
    from backend.models.schemas import (
        EnrichedLead,
        IssueCategory,
        SourceType,
        UrgencyLevel,
    )

    svc = db_service._service
    lead = EnrichedLead(
        external_id="q-write-1",
        source_type=SourceType.SERVICE_311,
        address="200 WRITE AVENUE",
        city=CITY,
        state="NY",
        zip_code="10001",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="roof leak after storm",
        urgency_level=UrgencyLevel.MEDIUM,
        case_status="open",
        owner_name="ACME",
        owner_phone="3475550000",
        owner_email="acme@example.com",
        date_reported=datetime(2026, 1, 15, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    assert svc.insert_lead_new(lead) is not None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM leads WHERE external_id=?", ("q-write-1",)
        ).fetchone()
        legacy = conn.execute(
            f"SELECT ({dbmod._qualified_where()}) AS q, "
            f"({dbmod._feed_where()}) AS f FROM leads WHERE external_id=?",
            ("q-write-1",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["is_junk"] == 0
    assert row["is_feed_ok"] == int(bool(legacy["f"]))
    assert row["is_qualified"] == int(bool(legacy["q"]))
    assert row["is_qualified"] == 1

    # Fechar o sinal tira a qualificação, mas o feed continua elegível (o feed
    # exclui `closed` à parte).
    svc.update_lead_freshness(int(row["id"]), "closed", "closed")
    conn = get_connection()
    try:
        after = conn.execute("SELECT * FROM leads WHERE id=?", (row["id"],)).fetchone()
    finally:
        conn.close()
    assert after["is_qualified"] == 0
    assert after["is_feed_ok"] == 1


def test_feed_total_bate_com_predicado_legado(quality_city):
    svc = db_service._service
    conn = get_connection()
    try:
        for i in range(3):
            _insert_lead(conn, f"q-feed-{i}", f"30{i} FEED STREET")
        _insert_lead(conn, "q-feed-junk", "305 FEED STREET",
                     description="abandoned vehicle")
        conn.commit()
        dbmod.refresh_lead_quality(conn, "city = ?", (CITY,))
        conn.commit()
        legacy = conn.execute(
            f"SELECT COUNT(*) c FROM leads l WHERE l.city=? AND ({dbmod._feed_where('l')}) "
            "AND l.signal_type IS NOT NULL AND l.lead_status != 'converted' "
            "AND (l.lead_status='available')",
            (CITY,),
        ).fetchone()["c"]
    finally:
        conn.close()

    leads, total = svc.get_leads_feed(
        city=CITY, days=7, user_id=None, limit=60, offset=0
    )
    assert total == legacy == 3
    assert len(leads) == 3
    assert all(lead["signal_type"] is not None for lead in leads)


def test_stats_e_public_metrics_usam_cache(monkeypatch):
    dbmod.clear_global_metrics_cache()
    svc = db_service._service
    first = svc.get_stats()
    second = svc.get_stats()
    assert first is second, "segunda chamada tem de vir do cache"
    pub1 = svc.get_public_metrics()
    pub2 = svc.get_public_metrics()
    assert pub1 is pub2
    assert dbmod._GLOBAL_METRICS_CACHE
    dbmod.clear_global_metrics_cache()
    assert dbmod._GLOBAL_METRICS_CACHE == {}


@pytest.mark.asyncio
async def test_daily_stats_nao_corre_sweeps(monkeypatch):
    from backend.main import user_daily_stats

    async def boom(*_a, **_k):
        raise AssertionError("sweep de escrita não pode correr no /daily-stats")

    monkeypatch.setattr(db_service, "expire_holds", boom, raising=False)
    monkeypatch.setattr(db_service, "check_reveal_watchdogs", boom, raising=False)

    async def fake_used(user_id):
        return {"used": 2, "limit": 10, "remaining": 8, "user_id": user_id}

    monkeypatch.setattr(db_service, "get_daily_leads_used", fake_used, raising=False)
    out = await user_daily_stats(999, {"id": 999})
    assert out == {"used": 2, "limit": 10, "remaining": 8, "user_id": 999}
