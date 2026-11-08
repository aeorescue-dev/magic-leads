"""System Health (Fase 27): scores, camadas e snapshots.

Os testes puros fixam as regras de negócio do painel: um score só desce por
sinais documentados, e o status global é o pior dos sete.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import system_health as sh
from backend.services.db import get_connection

NOW = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)  # 11:00 em Nova Iorque


def _iso(dt):
    return dt.isoformat()


def _city(name, age_h, **extra):
    return {
        "city": name,
        "total": 100,
        "facts_24h": 10,
        "created_24h": 5,
        "last_fact": _iso(NOW - timedelta(hours=age_h)),
        "owners": 80,
        "emails": 20,
        **extra,
    }


def _run(started_h_ago=1, inserted=10, status="success"):
    return {
        "run_id": "r1",
        "status": status,
        "inserted": inserted,
        "started_at": _iso(NOW - timedelta(hours=started_h_ago)),
        "finished_at": _iso(NOW - timedelta(hours=started_h_ago, minutes=-20)),
    }


# ------------------------------------------------------------------ status
@pytest.mark.parametrize(
    "score, status",
    [(100, "ok"), (90, "ok"), (89, "warn"), (60, "warn"), (59, "fail"), (0, "fail")],
)
def test_score_to_status(score, status):
    assert sh.score_to_status(score) == status


# ------------------------------------------------------------------ ingest
def test_ingest_all_fresh_scores_100():
    layer = sh.score_ingest(
        [_city("NYC", 2), _city("CHICAGO", 5)], [_run()], NOW
    )
    assert layer["score"] == 100
    assert layer["status"] == "ok"
    assert "2/2" in layer["headline"]


def test_ingest_city_25h_is_warn():
    layer = sh.score_ingest([_city("NYC", 25)], [_run()], NOW)
    assert layer["score"] == 75
    assert layer["status"] == "warn"


def test_ingest_city_25h_is_fresh_com_limite_36h():
    layer = sh.score_ingest(
        [_city("NYC", 25)], [_run()], NOW, stale_hours=36
    )
    assert layer["score"] == 100
    assert layer["status"] == "ok"
    assert layer["metrics"][0]["threshold"] == "36h"


def test_ingest_city_40h_is_warn_com_limite_36h():
    layer = sh.score_ingest(
        [_city("NYC", 40)], [_run()], NOW, stale_hours=36
    )
    assert layer["score"] == 75
    assert layer["status"] == "warn"


def test_ingest_city_40h_is_fail():
    layer = sh.score_ingest([_city("NYC", 40)], [_run()], NOW)
    assert layer["score"] == 50
    assert layer["status"] == "fail"


def test_ingest_boston_weekend_uses_business_age():
    # NOW e' segunda 11:00 ET; 40h brutas caiem no fim de semana.
    layer = sh.score_ingest([_city("BOSTON", 40)], [_run()], NOW)
    assert layer["score"] == 100
    assert layer["status"] == "ok"
    assert layer["reasons"] == []


def test_ingest_missing_city_date_is_fail():
    layer = sh.score_ingest(
        [{"city": "BOSTON", "last_fact": None, "total": 0}], [_run()], NOW
    )
    assert layer["score"] == 50
    assert "sem data" in " ".join(layer["reasons"])


def test_ingest_zero_insert_streak_penalises():
    runs = [_run(inserted=0), _run(started_h_ago=7, inserted=0)]
    layer = sh.score_ingest([_city("NYC", 2)], runs, NOW)
    assert layer["score"] == 70
    assert "sem inserir" in " ".join(layer["reasons"])


def test_ingest_no_runs_penalises():
    layer = sh.score_ingest([_city("NYC", 2)], [], NOW)
    assert layer["score"] == 50
    assert layer["status"] == "fail"


def test_ingest_overdue_run_penalises():
    layer = sh.score_ingest(
        [_city("NYC", 2)], [_run(started_h_ago=12)], NOW, interval_hours=6
    )
    assert layer["score"] == 70


# ------------------------------------------------------------- enrichment
def test_enrichment_healthy_is_100():
    layer = sh.score_enrichment(
        [{"city": "NYC", "enabled": 1, "jobs_today": 100, "domain_jobs_today": 10}],
        {"NYC": {"new": 10, "ready": 5, "quarantined": 1}},
        {"pending": 0, "oldest_age_h": None},
        [{"city": "NYC", "last_run_at": _iso(NOW - timedelta(hours=1))}],
        {"configured": True, "blocked": False, "domain_limit": 62},
        NOW,
    )
    assert layer["score"] == 100
    assert layer["status"] == "ok"


def test_enrichment_brave_blocked_and_no_ready():
    layer = sh.score_enrichment(
        [{"city": "NYC", "enabled": 1, "jobs_today": 10, "domain_jobs_today": 5}],
        {"NYC": {"new": 900, "ready": 0, "quarantined": 10}},
        {"pending": 0, "oldest_age_h": None},
        [],
        {"configured": True, "blocked": True, "domain_limit": 62},
        NOW,
    )
    assert layer["score"] == 50  # -25 Brave -25 zero ready
    assert layer["status"] == "fail"


def test_enrichment_queue_and_backfill_penalties():
    layer = sh.score_enrichment(
        [{"city": "NYC", "enabled": 1, "jobs_today": 10, "domain_jobs_today": 5}],
        {"NYC": {"new": 10, "ready": 5, "quarantined": 1}},
        {"pending": 3, "oldest_age_h": 30},
        [{"city": "NYC", "last_run_at": _iso(NOW - timedelta(hours=10))}],
        {"configured": False, "blocked": False, "domain_limit": 0},
        NOW,
    )
    assert layer["score"] == 75  # -15 fila 30h, -10 backfill parado


# ---------------------------------------------------------------- outreach
def _out(**extra):
    base = {
        "send_enabled": True,
        "queued": 0,
        "sent_today": 4,
        "mailbox_cap_total": 8,
        "mailboxes": [],
        "queue_blocker": None,
        "queue_oldest_age_hours": None,
    }
    base.update(extra)
    return base


def _metrics(sent=100, bounced=1, complaints=0):
    return {
        "totals": {
            "sent": sent,
            "bounced": bounced,
            "complaints": complaints,
            "bounce_rate": bounced / sent if sent else 0,
        },
        "mailboxes": [
            {
                "sent": sent,
                "bounced": bounced,
                "complaints": complaints,
                "bounce_rate": bounced / sent if sent else 0,
            }
        ],
    }


def test_outreach_healthy_is_100():
    assert sh.score_outreach(_out(), _metrics(), NOW)["score"] == 100


def test_outreach_paused_mailbox_penalises():
    layer = sh.score_outreach(
        _out(mailboxes=[{"email": "a@x.com", "paused_reason": "bounce"}]),
        _metrics(),
        NOW,
    )
    assert layer["score"] == 70
    assert "pausada" in " ".join(layer["reasons"])


def test_outreach_engine_off_with_queue():
    layer = sh.score_outreach(_out(send_enabled=False, queued=4), _metrics(), NOW)
    assert layer["score"] == 70


def test_outreach_bounce_and_complaint_are_fail():
    layer = sh.score_outreach(_out(), _metrics(sent=100, bounced=3, complaints=1), NOW)
    assert layer["score"] == 10  # -40 bounce -50 complaint
    assert layer["status"] == "fail"


def test_outreach_bounce_below_sample_is_warn_not_penalised():
    """1 bounce em 10 envios é visível, mas não é amostra para falhar."""
    layer = sh.score_outreach(_out(), _metrics(sent=10, bounced=1), NOW)
    assert layer["score"] == 100
    assert layer["status"] == "ok"
    metric = next(m for m in layer["metrics"] if m["key"] == "bounce_rate")
    assert metric["status"] == "warn"
    assert "amostra 10/20" in metric["threshold"]


def test_outreach_bounce_with_sample_penalises():
    layer = sh.score_outreach(_out(), _metrics(sent=20, bounced=1), NOW)
    assert layer["score"] == 60  # 1/20 = 5%
    assert layer["status"] == "warn"
    assert "amostra ≥20" in " ".join(layer["reasons"])


def test_outreach_cap_blocker_is_expected_not_penalised():
    layer = sh.score_outreach(
        _out(
            queued=2,
            queue_oldest_age_hours=6,
            queue_blocker={"reason": "mailbox_cap", "detail": "8/8"},
        ),
        _metrics(),
        NOW,
    )
    assert layer["score"] == 100


def test_outreach_queue_stuck_for_other_reason_penalises():
    layer = sh.score_outreach(
        _out(
            queued=2,
            queue_oldest_age_hours=6,
            queue_blocker={"reason": "city_send_disabled"},
        ),
        _metrics(),
        NOW,
    )
    assert layer["score"] == 80


# -------------------------------------------------------------------- push
def _push(**extra):
    base = {
        "deliveries": 20,
        "accepted": 20,
        "expired": 0,
        "rejected_dead": 0,
        "not_configured": 0,
        "clicks": 2,
        "active_subs": 10,
        "notifications_24h": 5,
    }
    base.update(extra)
    return base


def test_push_healthy_is_100():
    assert sh.score_push(_push())["score"] == 100


def test_push_not_configured_is_fail():
    layer = sh.score_push(_push(not_configured=2))
    assert layer["score"] == 40
    assert layer["status"] == "fail"


def test_push_dead_subscriptions_penalise():
    layer = sh.score_push(_push(expired=5, rejected_dead=2))
    assert layer["score"] == 70


def test_push_no_deliveries_with_subs_penalises():
    layer = sh.score_push(_push(deliveries=0, accepted=0))
    assert layer["score"] == 75


def test_push_no_deliveries_without_eligible_notifications_is_ok():
    layer = sh.score_push(
        _push(deliveries=0, accepted=0, notifications_24h=0)
    )
    assert layer["score"] == 100
    assert "sem alertas elegíveis" in layer["headline"]


# ------------------------------------------------------------------ quotas
def test_quotas_healthy_is_100():
    layer = sh.score_quotas(
        {"configured": True, "used": 10, "limit": 250, "blocked": False},
        {"cost_24h": 1, "cost_1h": 0.1, "calls_15m": 1, "transport_15m": 0,
         "calls_24h": 10, "billed": 5, "ghost": 0},
    )
    assert layer["score"] == 100


def test_quotas_brave_blocked_penalises():
    layer = sh.score_quotas(
        {"configured": True, "used": 250, "limit": 250, "blocked": True},
        {"cost_24h": 0, "cost_1h": 0, "calls_15m": 0, "transport_15m": 0,
         "calls_24h": 0, "billed": 0, "ghost": 0},
    )
    assert layer["score"] == 60
    assert layer["status"] == "warn"


def test_quotas_searchbug_transport_fail():
    layer = sh.score_quotas(
        {"configured": False, "used": 0, "limit": 0, "blocked": False},
        {"cost_24h": 1, "cost_1h": 0.1, "calls_15m": 5, "transport_15m": 4,
         "calls_24h": 10, "billed": 5, "ghost": 0},
    )
    assert layer["score"] == 60


# ------------------------------------------------------------------- infra
def test_infra_healthy_is_100():
    checks = [
        {"check_name": "worker", "status": "ok"},
        {"check_name": "backup", "status": "ok"},
        {"check_name": "gmail_tokens", "status": "ok"},
        {"check_name": "vps_worker", "status": "ok"},
    ]
    layer = sh.score_infra(checks, 50.0, 1.0, 2.0, NOW)
    assert layer["score"] == 100


def test_infra_worker_and_gmail_fail():
    checks = [
        {"check_name": "worker", "status": "fail"},
        {"check_name": "gmail_tokens", "status": "fail"},
    ]
    layer = sh.score_infra(checks, 50.0, 20.0, 2.0, NOW)
    assert layer["score"] == 20  # -40 worker -40 gmail
    assert layer["status"] == "fail"


def test_infra_backup_and_disk_warn():
    layer = sh.score_infra([], 85.0, 1.0, 40.0, NOW)
    assert layer["score"] == 70  # -15 backup -15 disco


# ------------------------------------------------------------------ alerts
def test_alerts_empty_is_100():
    assert sh.score_alerts([], NOW)["score"] == 100


def test_alerts_critical_and_old():
    alerts = [
        {"level": "critical", "created_at": _iso(NOW - timedelta(hours=30))},
        {"level": "warning", "created_at": _iso(NOW - timedelta(hours=2))},
    ]
    layer = sh.score_alerts(alerts, NOW)
    assert layer["score"] == 58  # -30 critical -2 warning -10 alerta >24h
    assert layer["status"] == "fail"


def test_alerts_only_historical_critical_is_warn_not_fail():
    alerts = [
        {"level": "critical", "created_at": _iso(NOW - timedelta(days=8))}
        for _ in range(4)
    ]
    layer = sh.score_alerts(alerts, NOW)
    assert layer["score"] == 80  # -5 cada histórico
    assert layer["status"] == "warn"
    assert "histórico" in " ".join(layer["reasons"])


def test_admin_access_alerts_are_informational_and_do_not_penalise():
    alerts = [
        {
            "level": "warn",
            "code": "ADMIN_ACCESS_GRANT",
            "message": "Concessão manual de 365 dias",
            "created_at": _iso(NOW - timedelta(hours=33)),
        }
    ]
    layer = sh.score_alerts(alerts, NOW)
    assert layer["score"] == 100
    assert layer["status"] == "ok"
    assert layer["reasons"] == []
    assert layer["headline"] == "1 aberto(s) (1 informativo(s))"
    assert layer["detail"]["items"][0]["informational"] is True
    metrics = {m["key"]: m for m in layer["metrics"]}
    assert metrics["informational"]["value"] == 1
    assert metrics["open"]["status"] == "ok"
    assert metrics["oldest_h"]["value"] is None  # só conta alertas operacionais


def test_admin_access_does_not_hide_operational_warning():
    alerts = [
        {
            "level": "warn",
            "code": "ADMIN_ACCESS_GRANT",
            "created_at": _iso(NOW - timedelta(hours=40)),
        },
        {
            "level": "warning",
            "code": "SCRAPER_CITY_STALE:BOSTON",
            "created_at": _iso(NOW - timedelta(hours=30)),
        },
    ]
    layer = sh.score_alerts(alerts, NOW)
    assert layer["score"] == 88  # -2 warning -10 alerta vivo >24h
    assert "atenção" in " ".join(layer["reasons"])
    metrics = {m["key"]: m for m in layer["metrics"]}
    assert metrics["oldest_h"]["value"] == 30.0


# ----------------------------------------------------------------- overall
def test_overall_weighted_and_worst_status():
    layers = {
        key: {"score": 100, "status": "ok", "reasons": []} for key in sh.LAYER_ORDER
    }
    layers["ingest"] = {"score": 50, "status": "fail", "reasons": ["Boston seco"]}
    overall = sh.build_overall(layers)
    # 20% * 50 + 80% * 100 = 90
    assert overall["score"] == 90
    assert overall["status"] == "fail"
    assert "Boston seco" in overall["reasons"]


# --------------------------------------------------------------- snapshots
@pytest.fixture()
def clean_snapshots():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM system_health_snapshots")
        conn.commit()
    finally:
        conn.close()
    yield
    conn = get_connection()
    try:
        conn.execute("DELETE FROM system_health_snapshots")
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_snapshot_insert_list_and_prune(clean_snapshots):
    from backend.services.db import db_service

    old = (NOW - timedelta(days=35)).isoformat()
    fresh = NOW.isoformat()
    await db_service.insert_system_health_snapshot(old, "warn", 80, "{}")
    await db_service.insert_system_health_snapshot(fresh, "ok", 100, "{}")

    rows = await db_service.list_system_health_snapshots(24 * 60)
    assert len(rows) == 2

    removed = await db_service.prune_system_health_snapshots(30)
    assert removed == 1
    rows = await db_service.list_system_health_snapshots(24 * 60)
    assert len(rows) == 1
    assert rows[0]["overall_score"] == 100


@pytest.mark.asyncio
async def test_build_snapshot_has_all_layers(clean_snapshots):
    snap = await sh.build_snapshot(24, include_history=False)
    assert snap["overall"]["score"] == int(snap["overall"]["score"])
    assert 0 <= snap["overall"]["score"] <= 100
    assert set(snap["layers"]) == set(sh.LAYER_ORDER)
    for layer in snap["layers"].values():
        assert 0 <= layer["score"] <= 100
        assert layer["status"] in ("ok", "warn", "fail")
        assert isinstance(layer["metrics"], list)


@pytest.mark.asyncio
async def test_capture_snapshot_persists_compact_payload(clean_snapshots):
    compact = await sh.capture_snapshot()
    assert "overall" in compact
    rows = await sh.db_service.list_system_health_snapshots(1)
    assert rows, "snapshot não gravado"
    assert rows[-1]["overall_status"] in ("ok", "warn", "fail")
