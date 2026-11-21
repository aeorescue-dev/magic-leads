"""Cache persistente e single-flight da fila de telefone."""
from __future__ import annotations

from types import SimpleNamespace

from backend.services import phone_cache, phone_jobs
from backend.services.db import get_connection


def _cleanup(lead_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM phone_lookups WHERE lead_id = ?", (lead_id,))
        conn.execute("DELETE FROM phone_jobs WHERE lead_id = ?", (lead_id,))
        conn.commit()
    finally:
        conn.close()


def test_cache_hit_and_owner_change_invalidates_key():
    lead_id = 99001
    _cleanup(lead_id)
    try:
        key_old = phone_cache.build_cache_key(lead_id, "OLD OWNER", "10 MAIN ST", "02127")
        key_new = phone_cache.build_cache_key(lead_id, "NEW OWNER", "10 MAIN ST", "02127")
        assert key_old != key_new, "mudanca de titular tem de mudar a chave"

        phone_cache.put(
            cache_key=key_old,
            lead_id=lead_id,
            owner_name="OLD OWNER",
            address="10 MAIN ST",
            zip_code="02127",
            state="MA",
            phone="+16175550111",
            verified=True,
            label="owner_verified",
            layer="L2",
            provider="Searchbug",
            result_code="success",
        )
        row = phone_cache.get(key_old)
        assert row is not None
        assert row["phone"] == "+16175550111"
        assert row["verified"] == 1
        assert phone_cache.get(key_new) is None
    finally:
        _cleanup(lead_id)


def test_negative_cache_is_kept_and_expires():
    lead_id = 99002
    _cleanup(lead_id)
    try:
        key = phone_cache.build_cache_key(lead_id, "JOHN SMITH", "10 MAIN ST", "02127")
        phone_cache.put(
            cache_key=key,
            lead_id=lead_id,
            owner_name="JOHN SMITH",
            address="10 MAIN ST",
            zip_code="02127",
            state="MA",
            phone=None,
            verified=False,
            label=None,
            layer="L2",
            provider="Searchbug",
            result_code="no_results",
        )
        row = phone_cache.get(key)
        assert row is not None and row["phone"] is None

        conn = get_connection()
        try:
            conn.execute(
                "UPDATE phone_lookups SET expires_at = datetime('now', '-1 second') "
                "WHERE cache_key = ?",
                (key,),
            )
            conn.commit()
        finally:
            conn.close()
        assert phone_cache.get(key) is None, "miss expirado nao pode ser servido"
    finally:
        _cleanup(lead_id)


def test_enqueue_is_single_flight():
    lead_id = 99003
    _cleanup(lead_id)
    try:
        decision = SimpleNamespace(lookup_address_kind="property")
        key = phone_cache.build_cache_key(lead_id, "JOHN SMITH", "10 MAIN ST", "02127")
        first = phone_jobs.enqueue(
            cache_key=key,
            lead_id=lead_id,
            user_id=None,
            idempotency_key="idem",
            trigger="user_click",
            decision=decision,
            quota_ref={"bucket": "base", "addon_id": None},
        )
        second = phone_jobs.enqueue(
            cache_key=key,
            lead_id=lead_id,
            user_id=None,
            idempotency_key="idem-2",
            trigger="user_click",
            decision=decision,
            quota_ref={"bucket": "base", "addon_id": None},
        )
        assert first["id"] == second["id"]

        conn = get_connection()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM phone_jobs WHERE lead_id = ?", (lead_id,)
            ).fetchone()["c"]
        finally:
            conn.close()
        assert count == 1, "dois cliques = um job"
    finally:
        _cleanup(lead_id)
