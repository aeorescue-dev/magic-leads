"""Reaper de mensagens presas em 'sending' — robustez sob concorrencia.

Cobre os casos que a auditoria levantou:

* linha LEGADA (anterior a existencia de `claimed_at`) nao pode ficar presa
  para sempre — o cutoff usa `COALESCE(claimed_at, queued_at, created_at)`;
* mensagem recente (inclusive legada) nao pode ser marcada como falhada;
* dois reapers em paralelo transicionam cada linha UMA vez (at-most-once),
  nunca duplicam o rowcount;
* `process_queue` dispara o reaper (o worker nao depende de cron externo);
* `_now_str`/`day_key` normalizam datetimes aware de outros fusos para UTC.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import outbound_engine as engine_module
from backend.services.db import db_service, get_connection
from backend.services.outbound_engine import OutboundEngine, _now_str, day_key

STALE_MINUTES = 15


def _svc():
    return db_service._service


def _cutoff(minutes: int = STALE_MINUTES) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _ts(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


@pytest.fixture()
def clean_messages():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM outbound_messages")
        conn.commit()
    finally:
        conn.close()
    yield
    conn = get_connection()
    try:
        conn.execute("DELETE FROM outbound_messages")
        conn.commit()
    finally:
        conn.close()


def _insert_sending(
    email: str,
    *,
    claimed_at: str | None,
    queued_at: str | None = None,
    created_at: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO outbound_messages (batch_id, contact_id, city, channel, "
            "to_email, subject, body_hash, status, claimed_at, queued_at, created_at) "
            "VALUES (NULL, NULL, 'BOSTON', 'email', ?, 's', 'h', 'sending', ?, ?, ?)",
            (email, claimed_at, queued_at, created_at),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


# ------------------------------------------------------------------ linhas legadas


def test_legacy_sending_without_claimed_at_is_reaped(clean_messages):
    """Linha anterior a `claimed_at`: usa `queued_at` como idade."""
    legacy_id = _insert_sending(
        "legacy-old@test.local", claimed_at=None, queued_at=_ts(120)
    )

    assert _svc().count_stale_sending_outbound_messages(_cutoff()) == 1
    assert _svc().fail_stale_sending_outbound_messages(_cutoff()) == 1

    row = _svc().get_outbound_message(legacy_id)
    assert row["status"] == "failed"
    assert "stale sending claim" in (row["error"] or "")


def test_legacy_sending_falls_back_to_created_at(clean_messages):
    """Sem `claimed_at` nem `queued_at` antigo, `created_at` ainda conta."""
    legacy_id = _insert_sending(
        "legacy-created@test.local",
        claimed_at=None,
        queued_at=None,
        created_at=_ts(180),
    )

    assert _svc().fail_stale_sending_outbound_messages(_cutoff()) == 1
    assert _svc().get_outbound_message(legacy_id)["status"] == "failed"


def test_recent_legacy_sending_is_not_reaped(clean_messages):
    """Sem `claimed_at` mas enfileirada agora: envio em curso, nao mexer."""
    recent_id = _insert_sending(
        "legacy-recent@test.local", claimed_at=None, queued_at=_ts(0)
    )

    assert _svc().fail_stale_sending_outbound_messages(_cutoff()) == 0
    assert _svc().get_outbound_message(recent_id)["status"] == "sending"


def test_claimed_at_wins_over_old_queued_at(clean_messages):
    """Uma mensagem reclamada ha pouco nao e' limpa so' porque `queued_at` e' velho."""
    recent_id = _insert_sending(
        "reclaimed@test.local", claimed_at=_ts(0), queued_at=_ts(600)
    )

    assert _svc().fail_stale_sending_outbound_messages(_cutoff()) == 0
    assert _svc().get_outbound_message(recent_id)["status"] == "sending"


# ------------------------------------------------------------------ concorrencia


def test_two_concurrent_reapers_transition_each_row_once(clean_messages):
    """Dois reapers em paralelo: rowcount total == linhas (sem dupla transicao)."""
    ids = [
        _insert_sending(f"race-{i}@test.local", claimed_at=_ts(120)) for i in range(5)
    ]
    cutoff = _cutoff()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_svc().fail_stale_sending_outbound_messages, [cutoff, cutoff]))

    assert sum(results) == len(ids), results
    for message_id in ids:
        assert _svc().get_outbound_message(message_id)["status"] == "failed"
    assert _svc().count_stale_sending_outbound_messages(cutoff) == 0


def test_second_reaper_is_a_noop(clean_messages):
    message_id = _insert_sending("idempotent@test.local", claimed_at=_ts(120))

    assert _svc().fail_stale_sending_outbound_messages(_cutoff()) == 1
    assert _svc().fail_stale_sending_outbound_messages(_cutoff()) == 0
    assert _svc().get_outbound_message(message_id)["status"] == "failed"


# ------------------------------------------------------------------ integracao


@pytest.fixture()
def sending_enabled():
    """Liga o envio e neutraliza as quiet hours, restaurando no fim."""
    svc = _svc()
    previous = svc.get_outbound_config()
    svc.set_outbound_config("send_enabled", "1")
    svc.set_outbound_config("quiet_hours_start", "00:00")
    svc.set_outbound_config("quiet_hours_end", "00:00")
    try:
        yield
    finally:
        for key in ("send_enabled", "quiet_hours_start", "quiet_hours_end"):
            svc.set_outbound_config(key, previous.get(key) or "")


@pytest.mark.asyncio
async def test_process_queue_runs_the_reaper(clean_messages, sending_enabled):
    """O worker limpa sozinho: nao depende de cron externo para o reaper."""
    message_id = _insert_sending("worker-reaps@test.local", claimed_at=_ts(120))

    result = await OutboundEngine().process_queue(limit=1)

    assert result["status"] != "disabled"
    assert _svc().get_outbound_message(message_id)["status"] == "failed"


@pytest.mark.asyncio
async def test_process_queue_reaps_legacy_row(clean_messages, sending_enabled):
    message_id = _insert_sending(
        "worker-legacy@test.local", claimed_at=None, queued_at=_ts(120)
    )

    await OutboundEngine().process_queue(limit=1)

    assert _svc().get_outbound_message(message_id)["status"] == "failed"


@pytest.mark.asyncio
async def test_process_queue_reaps_during_quiet_hours(clean_messages, sending_enabled):
    """Quiet hours suspendem ENVIOS, nao a limpeza de claims mortos.

    Sem isto, um deploy entre 22:00 e 07:00 UTC deixava a mensagem presa em
    'sending' ate' a janela reabrir (9h), aparecendo no painel como em curso.
    """
    _svc().set_outbound_config("quiet_hours_start", "11:00")
    _svc().set_outbound_config("quiet_hours_end", "13:00")
    message_id = _insert_sending(
        "quiet-reaps@test.local", claimed_at="2025-12-31 00:00:00"
    )

    result = await OutboundEngine().process_queue(
        limit=1, now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    )

    assert result == {"status": "quiet_hours", "sent": 0}
    assert _svc().get_outbound_message(message_id)["status"] == "failed"


@pytest.mark.asyncio
async def test_reap_stale_sending_returns_zero_when_disabled(monkeypatch, clean_messages):
    monkeypatch.setattr(
        engine_module.settings, "OUTBOUND_STALE_SENDING_MINUTES", 0, raising=False
    )
    message_id = _insert_sending("disabled@test.local", claimed_at=_ts(600))

    assert await OutboundEngine().reap_stale_sending() == 0
    assert _svc().get_outbound_message(message_id)["status"] == "sending"


# ------------------------------------------------------------------ fuso horario


def test_now_str_normalizes_aware_datetimes_to_utc():
    tz_plus3 = timezone(timedelta(hours=3))
    assert _now_str(datetime(2026, 1, 1, 3, 0, tzinfo=tz_plus3)) == "2026-01-01 00:00:00"
    assert day_key(datetime(2026, 1, 1, 3, 0, tzinfo=tz_plus3)) == "2026-01-01"


def test_now_str_keeps_naive_datetimes_as_utc():
    assert _now_str(datetime(2026, 1, 1, 0, 0)) == "2026-01-01 00:00:00"


def test_cutoff_with_non_utc_aware_now_does_not_reap_in_flight(clean_messages):
    """`now` num fuso adiantado nao pode gerar um cutoff no futuro.

    Antes, formatar um datetime aware sem converter deslocava o cutoff em
    +3h e o reaper matava envios recem-reclamados.
    """
    tz_plus3 = timezone(timedelta(hours=3))
    in_flight = _insert_sending("just-claimed@test.local", claimed_at=_ts(1))
    old = _insert_sending("really-old@test.local", claimed_at=_ts(120))

    now = datetime.now(tz_plus3)
    cutoff = engine_module._now_str(now - timedelta(minutes=STALE_MINUTES))

    assert _svc().fail_stale_sending_outbound_messages(cutoff) == 1
    assert _svc().get_outbound_message(in_flight)["status"] == "sending"
    assert _svc().get_outbound_message(old)["status"] == "failed"
