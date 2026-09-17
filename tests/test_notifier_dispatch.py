"""Regressão do despacho de notificações e da regra canônica de acesso.

Contexto: o despacho de alertas quebrou silenciosamente porque um whitelist de
status obsoleto (`IN ('trial','active','subscribed')`) deixou de casar com o
vocabulário real do banco. Estes testes blindam:

1. Fonte única de verdade de acesso (is_access_active / normalize_status).
2. Elegibilidade do despacho (acesso vigente + interesse + cidade).
3. Fallback inteligente: usuário sem interesses = todas as categorias.
4. Dead Man's Switch: inserted > 0 e audience == 0 gera alerta crítico
   auditável; cap diário atingido (audience > 0) NÃO dispara.
"""

import asyncio
import uuid
from datetime import datetime, timedelta

from backend.services.access import (
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_TRIAL,
    is_access_active,
    normalize_status,
)
from backend.services.db import db_service, get_connection
from backend.services.notifier import fanout_new_lead_batch, guard_silent_fanout


def _run(coro):
    return asyncio.run(coro)


def _future(days: int = 5) -> str:
    return (datetime.utcnow() + timedelta(days=days)).isoformat()


def _past(days: int = 1) -> str:
    return (datetime.utcnow() - timedelta(days=days)).isoformat()


def _reset_tables() -> None:
    conn = get_connection()
    try:
        for table in ("notifications", "user_interests", "system_alerts", "leads", "users"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def _create_user(subscription_status, plan_until, interests=None,
                 cities_filter=None, email=None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, "
            "subscription_status, plan_until, cities_filter) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                email or f"u_{uuid.uuid4().hex[:10]}@test.com",
                "not-a-real-hash",
                "Test Co",
                "pro",
                subscription_status,
                plan_until,
                cities_filter,
            ),
        )
        uid = cur.lastrowid
        for cat in interests or []:
            conn.execute(
                "INSERT OR IGNORE INTO user_interests (user_id, category) VALUES (?, ?)",
                (uid, cat),
            )
        conn.commit()
        return uid
    finally:
        conn.close()


def _create_lead(city: str = "NYC", category: str = "Roof") -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, date_reported) VALUES (?, '311', ?, ?, 'NY', ?, ?)",
            (
                f"ext-{uuid.uuid4().hex[:10]}",
                f"{uuid.uuid4().hex[:6]} Test St",
                city,
                category,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1) Fonte única de verdade de acesso
# ---------------------------------------------------------------------------

def test_is_access_active_matrix():
    future, past = _future(), _past()
    # Concede acesso (status válido + prazo futuro)
    assert is_access_active("active", future) is True
    assert is_access_active("ACTIVE", future) is True
    assert is_access_active(" active ", future) is True
    assert is_access_active("trial", future) is True
    assert is_access_active("trialing", future) is True      # legado
    assert is_access_active("subscribed", future) is True    # legado
    # Nega acesso
    assert is_access_active("active", past) is False         # vencido
    assert is_access_active("trial", past) is False          # trial vencido
    assert is_access_active("active", None) is False         # sem prazo
    assert is_access_active("inactive", future) is False
    assert is_access_active("expired", future) is False
    assert is_access_active("", future) is False
    assert is_access_active("token_desconhecido", future) is False


def test_normalize_status_aliases():
    assert normalize_status("Trialing") == STATUS_TRIAL
    assert normalize_status("SUBSCRIBED") == STATUS_ACTIVE
    assert normalize_status("Active") == STATUS_ACTIVE
    assert normalize_status("inactive") == STATUS_EXPIRED
    assert normalize_status("pending_payment") == STATUS_EXPIRED
    assert normalize_status(None) == STATUS_EXPIRED
    assert normalize_status("") == STATUS_EXPIRED


def test_subscription_status_uses_canonical_access():
    _reset_tables()
    u_active = _create_user("active", _future(), email="s.active@test.com")
    u_expired = _create_user("active", _past(), email="s.expired@test.com")
    u_legacy = _create_user("trialing", _future(), email="s.legacy@test.com")
    u_inactive = _create_user("inactive", _future(), email="s.inactive@test.com")

    assert _run(db_service.get_user_subscription_status(u_active))["can_access"] is True
    assert _run(db_service.get_user_subscription_status(u_expired))["can_access"] is False
    assert _run(db_service.get_user_subscription_status(u_legacy))["can_access"] is True
    assert _run(db_service.get_user_subscription_status(u_inactive))["can_access"] is False


# ---------------------------------------------------------------------------
# 2) Elegibilidade do despacho
# ---------------------------------------------------------------------------

def test_dispatch_eligibility_ignores_lapsed_and_stale_statuses():
    _reset_tables()
    future, past = _future(), _past()

    roof_active = _create_user("active", future, ["Roof"], email="roof.active@test.com")
    paint_trial = _create_user("trial", future, ["Paint"], email="paint.trial@test.com")
    roof_expired = _create_user("active", past, ["Roof"], email="roof.expired@test.com")
    roof_inactive = _create_user("inactive", future, ["Roof"], email="roof.inactive@test.com")
    roof_legacy = _create_user("trialing", future, ["Roof"], email="roof.legacy@test.com")

    roof_ids = {u["id"] for u in _run(db_service.get_users_interested_in("Roof"))}
    paint_ids = {u["id"] for u in _run(db_service.get_users_interested_in("Paint"))}

    assert roof_active in roof_ids
    assert roof_legacy in roof_ids          # 'trialing' normalizado -> trial
    assert roof_expired not in roof_ids     # plan_until vencido
    assert roof_inactive not in roof_ids    # status não concede acesso
    assert roof_active not in paint_ids     # isolamento de categoria
    assert paint_trial in paint_ids


# ---------------------------------------------------------------------------
# 3) Fallback inteligente: sem interesses = todas as categorias
# ---------------------------------------------------------------------------

def test_dispatch_fallback_when_user_has_no_interests():
    _reset_tables()
    future = _future()
    all_cats = _create_user("active", future, [], email="all.cats@test.com")
    some_cat = _create_user("active", future, ["Roof"], email="some.cat@test.com")

    roof_ids = {u["id"] for u in _run(db_service.get_users_interested_in("Roof"))}
    gas_ids = {u["id"] for u in _run(db_service.get_users_interested_in("Gas"))}

    assert all_cats in roof_ids and all_cats in gas_ids   # fallback universal
    assert some_cat in roof_ids                            # interesse explícito
    assert some_cat not in gas_ids                         # mas só no dele


def test_dispatch_city_filter():
    _reset_tables()
    future = _future()
    guy_nyc = _create_user("active", future, ["Roof"], cities_filter='["NYC"]',
                           email="nyc@test.com")
    guy_any = _create_user("active", future, ["Roof"], cities_filter=None,
                           email="any@test.com")

    nyc_ids = {u["id"] for u in _run(db_service.get_users_interested_in("Roof", "NYC"))}
    dallas_ids = {u["id"] for u in _run(db_service.get_users_interested_in("Roof", "Dallas"))}

    assert guy_nyc in nyc_ids
    assert guy_nyc not in dallas_ids       # filtro de cidade respeitado
    assert guy_any in nyc_ids and guy_any in dallas_ids  # sem filtro = todas


# ---------------------------------------------------------------------------
# 4) Fan-out end-to-end + Dead Man's Switch
# ---------------------------------------------------------------------------

def test_fanout_creates_notification_and_dedups():
    _reset_tables()
    uid = _create_user("active", _future(), ["Roof"], email="fanout@test.com")
    lid = _create_lead("NYC", "Roof")
    lead = {
        "id": lid,
        "issue_category": "Roof",
        "address": "1 Main St",
        "city": "NYC",
        "date_reported": datetime.utcnow().isoformat(),
    }

    first = _run(fanout_new_lead_batch("Roof", [lead]))
    assert first.created == 1
    assert first.audience == 1

    second = _run(fanout_new_lead_batch("Roof", [lead]))
    assert second.created == 0          # dedup: já notificado
    assert second.audience == 1         # elegível ainda é detectado

    conn = get_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM notifications "
            "WHERE user_id = ? AND lead_id = ? AND type = 'new_lead'",
            (uid, lid),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert count == 1


def test_dead_mans_switch_records_critical_alert():
    _reset_tables()

    # Fluxo saudável (notificou) -> sem alerta
    assert _run(guard_silent_fanout(
        inserted=5, notified=3, audience=10, context={"run_id": "ok"},
    )) is True
    # Fluxo saudável (cap diário atingido: há elegíveis, mas notified == 0)
    # -> NÃO é bloqueio. Regressão do falso positivo NOTIFIER_SILENT_FAILURE.
    assert _run(guard_silent_fanout(
        inserted=1471, notified=0, audience=8, context={"run_id": "capped"},
    )) is True
    conn = get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM system_alerts").fetchone()["c"] == 0
    finally:
        conn.close()

    # Bloqueio silencioso (nenhum destinatário elegível) -> alerta crítico
    assert _run(guard_silent_fanout(
        inserted=5, notified=0, audience=0, context={"run_id": "blocked"},
    )) is False

    alerts = _run(db_service.get_recent_system_alerts(5))
    assert any(a["code"] == "NOTIFIER_SILENT_FAILURE" for a in alerts)
    assert alerts[0]["level"] == "critical"
    assert "blocked" in (alerts[0]["context"] or "")


def test_acknowledge_system_alert_marks_and_misses():
    _reset_tables()

    created = _run(db_service.record_system_alert(
        level="critical",
        code="NOTIFIER_SILENT_FAILURE",
        message="alerta de teste",
        context={"run_id": "ack"},
    ))
    assert created is not None
    assert created["acknowledged"] == 0

    acked = _run(db_service.acknowledge_system_alert(created["id"]))
    assert acked is not None
    assert acked["acknowledged"] == 1

    # Persistiu no banco.
    alerts = _run(db_service.get_recent_system_alerts(5))
    assert alerts[0]["acknowledged"] == 1

    # ID inexistente -> None (rota responde 404).
    assert _run(db_service.acknowledge_system_alert(999999)) is None
