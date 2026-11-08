"""Auto-Ramp e disjuntor das caixas (Fase 1).

Cobrem a escada, os gates (amostra/bounce/complaint/auth), o teto, a
idempotência diária e a pausa automática por bounce/consecutivos/auth.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import auto_ramp, inbox_sync, mailbox_guard
from backend.services.db import db_service, get_connection
from backend.services.outbound_engine import effective_mailbox_cap

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
DAY = 24 * 60 * 60


@pytest.fixture()
def clean_mailboxes():
    conn = get_connection()
    try:
        for table in (
            "mailbox_bounce_events",
            "mailbox_ramp_log",
            "sending_mailboxes",
            "outbound_messages",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM system_kv WHERE key=?", (auto_ramp.EVAL_KEY,))
        conn.commit()
    finally:
        conn.close()
    yield
    conn = get_connection()
    try:
        for table in (
            "mailbox_bounce_events",
            "mailbox_ramp_log",
            "sending_mailboxes",
            "outbound_messages",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def _mailbox(**overrides) -> dict:
    base = {
        "email": "ramp@example.com",
        "provider": "gmail",
        "transport": "gmail_api",
        "daily_cap": 10,
        "enabled": 1,
        "warmup_state": "warm",
        "auth_ref": json.dumps({"refresh_token": "x"}),
    }
    base.update(
        {
            k: v
            for k, v in overrides.items()
            if k in ("email", "provider", "transport", "daily_cap", "enabled",
                     "warmup_state", "auth_ref", "city")
        }
    )
    row = db_service._service.upsert_sending_mailbox(**base)
    assert row
    sets = ["warmup_started_at=?"]
    params: list = [(NOW - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")]
    for key in (
        "auto_ramp_enabled",
        "auto_ramp_cap",
        "auto_ramp_max",
        "auto_ramp_stage",
        "auto_ramp_last_step_at",
        "paused_at",
        "paused_reason",
    ):
        if key in overrides:
            sets.append(f"{key}=?")
            params.append(overrides[key])
    params.append(row["id"])
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE sending_mailboxes SET {', '.join(sets)} WHERE id=?", params
        )
        conn.commit()
        refreshed = conn.execute(
            "SELECT * FROM sending_mailboxes WHERE id=?", (row["id"],)
        ).fetchone()
        return dict(refreshed)
    finally:
        conn.close()


def _metrics(sent=250, bounces=0, complaints=0, auth=None) -> dict:
    return {
        "days": 30,
        "sent": sent,
        "bounces": bounces,
        "complaints": complaints,
        "bounce_rate": (bounces / sent) if sent else 0.0,
        "complaint_rate": (complaints / sent) if sent else 0.0,
        "last_auth_error_at": auth,
    }


# ------------------------------------------------------------------ escada


def test_next_stage_cap_respeita_teto():
    assert auto_ramp.next_stage_cap(1, 75) == 2
    assert auto_ramp.next_stage_cap(20, 75) == 25
    assert auto_ramp.next_stage_cap(25, 75) == 35
    assert auto_ramp.next_stage_cap(50, 75) == 75
    assert auto_ramp.next_stage_cap(75, 75) is None
    assert auto_ramp.next_stage_cap(20, 12) is None


def test_curva_acelerada_chega_a_75_em_cerca_de_cinco_semanas():
    """2-3 dias por degrau no warm-up; ~32-35 dias ate 75/dia."""
    total = 0
    cap = 1
    caminho = []
    while True:
        nxt = auto_ramp.next_stage_cap(cap, 75)
        if nxt is None:
            break
        dias = auto_ramp.step_interval_days(cap)
        caminho.append((cap, dias))
        total += dias
        cap = nxt
    assert cap == 75
    assert total <= 40, f"curva demasiado lenta: {total} dias ({caminho})"
    assert auto_ramp.step_interval_days(1) == 2
    assert auto_ramp.step_interval_days(20) == 3
    assert auto_ramp.step_interval_days(75) == 7


def test_evaluate_hold_por_intervalo():
    mailbox = {
        "enabled": 1,
        "auto_ramp_enabled": 1,
        "auto_ramp_cap": 25,
        "auto_ramp_max": 75,
        "auto_ramp_last_step_at": (NOW - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
    }
    assert auto_ramp.evaluate_mailbox(mailbox, _metrics(), NOW)["reason"] == "interval"


def test_evaluate_hold_por_amostra_no_patamar_25():
    mailbox = {
        "enabled": 1,
        "auto_ramp_enabled": 1,
        "auto_ramp_cap": 25,
        "auto_ramp_max": 75,
        "auto_ramp_last_step_at": (NOW - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"),
    }
    assert auto_ramp.evaluate_mailbox(mailbox, _metrics(sent=199), NOW)["reason"] == "sample"
    decision = auto_ramp.evaluate_mailbox(mailbox, _metrics(sent=200), NOW)
    assert decision["action"] == "step"
    assert decision["to_cap"] == 35


def test_evaluate_hold_bounce_complaint_auth():
    base = {
        "enabled": 1,
        "auto_ramp_enabled": 1,
        "auto_ramp_cap": 35,
        "auto_ramp_max": 75,
        "auto_ramp_last_step_at": (NOW - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"),
    }
    assert auto_ramp.evaluate_mailbox(base, _metrics(bounces=3), NOW)["reason"] == "bounce"
    assert auto_ramp.evaluate_mailbox(base, _metrics(complaints=1), NOW)["reason"] == "complaint"
    assert (
        auto_ramp.evaluate_mailbox(
            base, _metrics(auth=(NOW - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")), NOW
        )["reason"]
        == "auth"
    )


def test_evaluate_warmup_sobe_com_amostra_pequena():
    mailbox = {
        "enabled": 1,
        "auto_ramp_enabled": 1,
        "auto_ramp_cap": 1,
        "auto_ramp_max": 75,
        "auto_ramp_last_step_at": (NOW - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"),
    }
    assert auto_ramp.evaluate_mailbox(mailbox, _metrics(sent=7), NOW)["action"] == "step"
    assert auto_ramp.evaluate_mailbox(mailbox, _metrics(sent=3), NOW)["reason"] == "sample"


def test_evaluate_teto_maximo():
    mailbox = {
        "enabled": 1,
        "auto_ramp_enabled": 1,
        "auto_ramp_cap": 75,
        "auto_ramp_max": 75,
        "auto_ramp_last_step_at": (NOW - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S"),
    }
    assert auto_ramp.evaluate_mailbox(mailbox, _metrics(sent=2000), NOW)["reason"] == "max"


# --------------------------------------------------------------- integracao


@pytest.mark.asyncio
async def test_evaluate_auto_ramp_aplica_e_audita(clean_mailboxes, monkeypatch):
    mailbox = _mailbox(auto_ramp_enabled=1, auto_ramp_cap=25, auto_ramp_max=75)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE sending_mailboxes SET auto_ramp_last_step_at=? WHERE id=?",
            ((NOW - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"), mailbox["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    async def fake_metrics(mailbox_id, days=30):
        return _metrics(sent=250)

    monkeypatch.setattr(
        auto_ramp.db_service, "mailbox_metrics", fake_metrics, raising=False
    )
    result = await auto_ramp.evaluate_auto_ramp(now=NOW, force=True)
    assert result["steps"] == 1

    row = db_service._service.list_sending_mailboxes()[0]
    assert row["auto_ramp_cap"] == 35
    assert row["auto_ramp_stage"] == 1
    log = db_service._service.mailbox_ramp_log(mailbox["id"])
    assert log and log[0]["to_cap"] == 35


@pytest.mark.asyncio
async def test_evaluate_auto_ramp_uma_vez_por_dia(clean_mailboxes, monkeypatch):
    _mailbox(auto_ramp_enabled=1, auto_ramp_cap=25, auto_ramp_max=75)

    async def fake_metrics(mailbox_id, days=30):
        return _metrics(sent=250)

    monkeypatch.setattr(
        auto_ramp.db_service, "mailbox_metrics", fake_metrics, raising=False
    )
    assert (await auto_ramp.evaluate_auto_ramp(now=NOW))["status"] == "ok"
    second = await auto_ramp.evaluate_auto_ramp(now=NOW)
    assert second["status"] == "skipped"


# ------------------------------------------------------------- effective cap


def test_effective_cap_auto_ramp():
    config = {"per_mailbox_daily_cap": "25", "warmup_enabled": "1"}
    mb = {"auto_ramp_enabled": 1, "auto_ramp_cap": 35, "auto_ramp_max": 75}
    assert effective_mailbox_cap(mb, config, NOW) == 25  # teto global manda
    config2 = {"per_mailbox_daily_cap": "100", "warmup_enabled": "1"}
    assert effective_mailbox_cap(mb, config2, NOW) == 35
    mb2 = {"auto_ramp_enabled": 1, "auto_ramp_cap": 80, "auto_ramp_max": 75}
    assert effective_mailbox_cap(mb2, config2, NOW) == 75


# ------------------------------------------------------------------ disjuntor


def test_looks_like_auth_error():
    assert mailbox_guard.looks_like_auth_error("invalid_grant", None)
    assert mailbox_guard.looks_like_auth_error("gmail auth failed: invalid_grant", 400)
    assert mailbox_guard.looks_like_auth_error("HTTP 403", 403)
    assert not mailbox_guard.looks_like_auth_error("HTTP 500", 500)


@pytest.mark.asyncio
async def test_bounce_rate_pausa_caixa(clean_mailboxes, monkeypatch):
    mailbox = _mailbox()
    conn = get_connection()
    try:
        for idx in range(3):
            conn.execute(
                "INSERT OR IGNORE INTO mailbox_bounce_events (mailbox_id, email, kind) "
                "VALUES (?, ?, 'bounce')",
                (mailbox["id"], f"x{idx}@example.com"),
            )
        conn.commit()
    finally:
        conn.close()

    async def fake_metrics(mailbox_id, days=30):
        return _metrics(sent=100, bounces=3)

    monkeypatch.setattr(
        mailbox_guard.db_service, "mailbox_metrics", fake_metrics, raising=False
    )
    result = await mailbox_guard.check_mailboxes(NOW)
    assert result["paused"] == 1
    row = db_service._service.list_sending_mailboxes()[0]
    assert row["enabled"] == 0
    assert row["paused_reason"] == "bounce_rate"


@pytest.mark.asyncio
async def test_dois_bounces_consecutivos_pausam(clean_mailboxes, monkeypatch):
    mailbox = _mailbox()
    conn = get_connection()
    try:
        for idx in range(2):
            conn.execute(
                "INSERT OR IGNORE INTO mailbox_bounce_events (mailbox_id, email, kind) "
                "VALUES (?, ?, 'bounce')",
                (mailbox["id"], f"y{idx}@example.com"),
            )
        conn.commit()
    finally:
        conn.close()

    async def fake_metrics(mailbox_id, days=30):
        return _metrics(sent=3, bounces=2)

    monkeypatch.setattr(
        mailbox_guard.db_service, "mailbox_metrics", fake_metrics, raising=False
    )
    await mailbox_guard.check_mailboxes(NOW)
    row = db_service._service.list_sending_mailboxes()[0]
    assert row["enabled"] == 0
    assert row["paused_reason"] == "consecutive_bounces"


@pytest.mark.asyncio
async def test_bounce_duplicado_do_mesmo_email_nao_pausa(clean_mailboxes, monkeypatch):
    """O mesmo DSN re-lido não pode valer por dois bounces consecutivos."""
    mailbox = _mailbox()
    conn = get_connection()
    try:
        for _ in range(2):
            conn.execute(
                "INSERT OR IGNORE INTO mailbox_bounce_events (mailbox_id, email, kind) "
                "VALUES (?, 'dup@example.com', 'bounce')",
                (mailbox["id"],),
            )
        conn.commit()
    finally:
        conn.close()

    async def fake_metrics(mailbox_id, days=30):
        return _metrics(sent=3, bounces=2)

    monkeypatch.setattr(
        mailbox_guard.db_service, "mailbox_metrics", fake_metrics, raising=False
    )
    await mailbox_guard.check_mailboxes(NOW)
    row = db_service._service.list_sending_mailboxes()[0]
    assert row["enabled"] == 1
    assert row["paused_reason"] is None


def test_suppress_e_idempotente_para_o_mesmo_bounce(clean_mailboxes):
    mailbox = _mailbox()
    inbox_sync._suppress("dup@example.com", "bounce", mailbox["id"])
    inbox_sync._suppress("dup@example.com", "bounce", mailbox["id"])

    conn = get_connection()
    try:
        events = conn.execute(
            "SELECT COUNT(*) FROM mailbox_bounce_events WHERE lower(email)='dup@example.com'"
        ).fetchone()[0]
        suppressions = conn.execute(
            "SELECT COUNT(*) FROM suppressions WHERE lower(value)='dup@example.com'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert events == 1
    assert suppressions == 1


@pytest.mark.asyncio
async def test_auth_error_pausa_e_marca(clean_mailboxes):
    mailbox = _mailbox()
    await mailbox_guard.handle_auth_error(mailbox, "HTTP 401 invalid_grant")
    row = db_service._service.list_sending_mailboxes()[0]
    assert row["enabled"] == 0
    assert row["paused_reason"] == "auth_failure"
    assert row["last_auth_error_at"]


# ------------------------------------------- auditoria preditiva (2026-11-01)
#
# O Auto-Ramp e' avaliado 1x/dia no primeiro tick apos a meia-noite de Nova
# Iorque. Estes testes simulam o calendario real (03/11 e 05/11), o jitter de
# ate 60 s entre dois degraus e as fronteiras exatas do disjuntor.


def _ramp_box(cap: int, last: datetime, max_cap: int = 75) -> dict:
    return {
        "enabled": 1,
        "auto_ramp_enabled": 1,
        "auto_ramp_cap": cap,
        "auto_ramp_max": max_cap,
        "auto_ramp_last_step_at": last.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _at(day: int, hour: int, minute: int, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


def test_rampa_03_11_e_05_11_resistem_ao_jitter_do_tick():
    """2 -> 3 em 03/11 e 3 -> 5 em 05/11 mesmo com 20 s de jitter."""
    last = datetime(2026, 11, 1, 0, 43, 47, tzinfo=timezone.utc)
    box = _ramp_box(2, last)

    # 02/11 00:01 ET: so' 1 dia e 4 h desde o passo -> segura.
    assert auto_ramp.evaluate_mailbox(box, _metrics(sent=12), _at(2, 5, 1))["reason"] == "interval"

    # 03/11 00:00:10 ET: primeiro tick do dia -> sobe para 3.
    step = auto_ramp.evaluate_mailbox(box, _metrics(sent=12), _at(3, 5, 0))
    assert step["action"] == "step"
    assert (step["from_cap"], step["to_cap"]) == (2, 3)

    # O passo real ficou gravado 20 s DEPOIS da avaliacao (jitter do tick).
    box3 = _ramp_box(3, datetime(2026, 11, 3, 5, 0, 30))
    # 04/11: um dia antes -> nunca sobe (nem com a folga de 1 h).
    assert auto_ramp.evaluate_mailbox(box3, _metrics(sent=20), _at(4, 5, 0))["reason"] == "interval"
    # 05/11 00:00:10 ET: 20 s "cedo" face ao passo, mas dentro da folga -> sobe.
    step2 = auto_ramp.evaluate_mailbox(box3, _metrics(sent=20), _at(5, 5, 0))
    assert step2["action"] == "step"
    assert (step2["from_cap"], step2["to_cap"]) == (3, 5)


def test_rampa_nunca_salta_degraus_mesmo_com_folga_maxima():
    box = _ramp_box(2, datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc))
    decision = auto_ramp.evaluate_mailbox(box, _metrics(sent=2000), _at(3, 12, 0))
    assert decision["action"] == "step"
    assert decision["to_cap"] == 3, "a escada so' avanca um degrau por avaliacao"


def test_rampa_segura_com_erro_de_auth_dentro_de_30_dias_e_liberta_depois():
    last = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    box = _ramp_box(25, last)
    now = _at(3, 12, 0)
    dentro = _metrics(sent=250, auth=(now - timedelta(days=29)).strftime("%Y-%m-%d %H:%M:%S"))
    assert auto_ramp.evaluate_mailbox(box, dentro, now)["reason"] == "auth"
    fora = _metrics(sent=250, auth=(now - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S"))
    assert auto_ramp.evaluate_mailbox(box, fora, now)["action"] == "step"


def test_caixa_pausada_pelo_disjuntor_nao_e_retomada_pelo_auto_ramp():
    box = _ramp_box(5, datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc))
    box["paused_at"] = "2026-11-01 12:00:00"
    box["paused_reason"] = "bounce_rate"
    assert auto_ramp.evaluate_mailbox(box, _metrics(sent=500), _at(3, 12, 0)) == {
        "action": "hold",
        "reason": "paused",
    }


@pytest.mark.asyncio
async def test_complaint_acima_de_0_1_por_cento_pausa(clean_mailboxes, monkeypatch):
    mailbox = _mailbox()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO mailbox_bounce_events (mailbox_id, email, kind) "
            "VALUES (?, 'x@example.com', 'complaint')",
            (mailbox["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    async def fake_metrics(mailbox_id, days=30):
        return _metrics(sent=20, complaints=1)

    monkeypatch.setattr(
        mailbox_guard.db_service, "mailbox_metrics", fake_metrics, raising=False
    )
    result = await mailbox_guard.check_mailboxes(NOW)
    assert result["paused"] == 1
    row = db_service._service.list_sending_mailboxes()[0]
    assert row["enabled"] == 0
    assert row["paused_reason"] == "complaint_rate"


@pytest.mark.asyncio
async def test_limites_exatos_do_disjuntor_nao_pausam(clean_mailboxes, monkeypatch):
    """bounce == 2% e complaint == 0.1% ficam no limite, sem pausa (regra e' >)."""
    mailbox = _mailbox()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO mailbox_bounce_events (mailbox_id, email, kind) "
            "VALUES (?, 'x@example.com', 'bounce')",
            (mailbox["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    state = {"metrics": _metrics(sent=50, bounces=1)}
    async def fake_metrics(mailbox_id, days=30):
        return state["metrics"]

    monkeypatch.setattr(
        mailbox_guard.db_service, "mailbox_metrics", fake_metrics, raising=False
    )

    # 1 bounce em 50 envios = 2,0% (nao e' > 2%).
    result = await mailbox_guard.check_mailboxes(NOW)
    assert result["paused"] == 0
    row = db_service._service.list_sending_mailboxes()[0]
    assert row["enabled"] == 1

    # 1 complaint em 1.000 envios = 0,1% (nao e' > 0,1%).
    state["metrics"] = _metrics(sent=1000, complaints=1)
    result = await mailbox_guard.check_mailboxes(NOW)
    assert result["paused"] == 0
    row = db_service._service.list_sending_mailboxes()[0]
    assert row["enabled"] == 1
