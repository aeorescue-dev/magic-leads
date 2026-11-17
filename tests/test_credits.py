"""Marco 1A: carteira de créditos, idempotência e reveal de sinal."""
from __future__ import annotations

import sqlite3
import uuid

import pytest

from backend.services import credits
from backend.services.db import DB_PATH, db_service  # noqa: F401
from backend.services.security import hash_password


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _user(email: str) -> int:
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, company_name, plan, subscription_status) "
            "VALUES (?, ?, 'QA Co', 'free', 'expired')",
            (email, hash_password("test-pass-123")),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _lead(external_id: str, *, mailing: str = "1 Mail St, New York, NY 10001", trade: str = "Plumbing") -> int:
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, zip_code, "
            "issue_category, issue_description, owner_name, mailing_address, date_reported, "
            "is_qualified, is_junk, case_status, signal_type, signal_status, signal_ready, "
            "phone_ready, owner_source, owner_kind, parcel_id, lead_status) "
            "VALUES (?, 'credits_seed', '123 Test Street', 'NYC', 'NY', '10001', ?, "
            "'Test signal', 'Alice Owner', ?, date('now'), 1, 0, 'open', "
            "'open_request', 'open', 1, 0, 'seed_staging', 'person', ?, 'available')",
            (external_id, trade, mailing, f"BBL-{external_id}"),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _cleanup(emails: list[str], external_ids: list[str]) -> None:
    conn = _conn()
    try:
        for email in emails:
            conn.execute("DELETE FROM users WHERE email=?", (email,))
        for ext in external_ids:
            conn.execute("DELETE FROM leads WHERE external_id=?", (ext,))
        conn.commit()
    finally:
        conn.close()


def _credit(user_id: int, pack: str = "starter") -> None:
    purchase = credits.create_purchase(user_id, pack)
    session_id = f"test:{purchase['id']}"
    credits.attach_session(purchase["id"], session_id)
    credits.mark_purchase_paid(session_id, event_id=f"evt:{purchase['id']}")


def test_pack_purchase_is_idempotent():
    suffix = uuid.uuid4().hex[:8]
    email = f"credits-buy-{suffix}@magic.test"
    uid = _user(email)
    try:
        purchase = credits.create_purchase(uid, "starter")
        session_id = f"test:{purchase['id']}"
        credits.attach_session(purchase["id"], session_id)
        first = credits.mark_purchase_paid(session_id, event_id=f"evt:{purchase['id']}")
        second = credits.mark_purchase_paid(session_id, event_id=f"evt:{purchase['id']}")
        wallet = credits.get_wallet(uid)
        assert first["duplicate"] is False
        assert second["duplicate"] is True
        assert wallet["balance_cents"] == 700
        entries = [e for e in credits.list_ledger(uid) if e["event_type"] == "pack_purchase"]
        assert len(entries) == 1
        assert entries[0]["amount"] == 700
        assert entries[0]["balance_after"] == 700
    finally:
        _cleanup([email], [])


def test_signal_reveal_charges_once_and_locks_trade():
    suffix = uuid.uuid4().hex[:8]
    email1 = f"credits-a-{suffix}@magic.test"
    email2 = f"credits-b-{suffix}@magic.test"
    ext = f"test-lead-{suffix}"
    uid1 = _user(email1)
    uid2 = _user(email2)
    lead_id = _lead(ext)
    try:
        _credit(uid1)
        first = credits.reveal_signal(uid1, lead_id, "Plumbing", f"idem-{suffix}-1")
        assert first["duplicate"] is False
        assert first["wallet"]["balance_cents"] == 550
        assert first["payload"]["mailing_address"].startswith("1 Mail St")
        assert first["payload"]["address"] == "123 Test Street"

        duplicate = credits.reveal_signal(uid1, lead_id, "Plumbing", f"idem-{suffix}-1")
        assert duplicate["duplicate"] is True
        assert duplicate["wallet"]["balance_cents"] == 550

        other_trade = credits.reveal_signal(uid1, lead_id, "Electrical", f"idem-{suffix}-2")
        assert other_trade["duplicate"] is False
        assert other_trade["wallet"]["balance_cents"] == 400

        with pytest.raises(credits.CreditsError) as exc:
            credits.reveal_signal(uid2, lead_id, "Plumbing", f"idem-{suffix}-3")
        assert exc.value.code == "exclusive_by_other"
        assert exc.value.status_code == 409
    finally:
        _cleanup([email1, email2], [ext])


def test_signal_requires_credits_and_mailing():
    suffix = uuid.uuid4().hex[:8]
    email = f"credits-c-{suffix}@magic.test"
    ext = f"test-lead-{suffix}"
    uid = _user(email)
    lead_id = _lead(ext, mailing="")
    try:
        with pytest.raises(credits.CreditsError) as exc:
            credits.reveal_signal(uid, lead_id, "Plumbing", f"idem-{suffix}-1")
        assert exc.value.code == "signal_not_ready"
        assert exc.value.status_code == 422
        assert credits.get_wallet(uid)["balance_cents"] == 0
    finally:
        _cleanup([email], [ext])


def test_phone_reveal_is_disabled_in_1a():
    with pytest.raises(credits.CreditsError) as exc:
        credits.reveal_phone(1, 1, "Plumbing", "idem")
    assert exc.value.code == "phone_reveal_disabled"
    assert exc.value.status_code == 503


def test_readiness_flags_materialize_and_filter():
    """Carta = owner + mailing + sinal; telefone = verificado + número."""
    suffix = uuid.uuid4().hex[:8]
    email = f"credits-r-{suffix}@magic.test"
    ext = f"test-readiness-{suffix}"
    uid = _user(email)
    conn = _conn()
    lead_id = 0
    try:
        cur = conn.execute(
            "INSERT INTO leads (external_id, source_type, address, city, state, zip_code, "
            "issue_category, issue_description, owner_name, mailing_address, date_reported, "
            "is_qualified, is_junk, case_status, signal_type, signal_status, owner_source, "
            "owner_kind, lead_status) "
            "VALUES (?, 'credits_seed', '999 Readiness Lane', 'NYC', 'NY', '10001', "
            "'Plumbing', 'Readiness signal', 'Alice Owner', '1 Mail St, New York, NY 10001', "
            "date('now'), 1, 0, 'open', 'open_request', 'open', 'seed_staging', "
            "'person', 'available')",
            (ext,),
        )
        lead_id = int(cur.lastrowid)
        conn.commit()
        row = conn.execute(
            "SELECT signal_ready, phone_ready FROM leads WHERE id=?", (lead_id,)
        ).fetchone()
        assert int(row["signal_ready"]) == 1
        assert int(row["phone_ready"]) == 0

        conn.execute(
            "UPDATE leads SET owner_phone=?, phone_verified=1 WHERE id=?",
            ("+1 212 555 0100", lead_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT signal_ready, phone_ready FROM leads WHERE id=?", (lead_id,)
        ).fetchone()
        assert int(row["signal_ready"]) == 1
        assert int(row["phone_ready"]) == 1
    finally:
        conn.close()

    try:
        letter, _ = db_service._service.get_leads_feed(
            city="NYC", search="999 Readiness", readiness="letter"
        )
        assert any(int(row["id"]) == lead_id for row in letter)
        phone, _ = db_service._service.get_leads_feed(
            city="NYC", search="999 Readiness", readiness="phone"
        )
        assert any(int(row["id"]) == lead_id for row in phone)
        counts = db_service._service.count_leads_by_readiness(
            city="NYC", search="999 Readiness"
        )
        assert counts == {"all": 1, "letter": 1, "phone": 1}

        credit_rows = credits.list_leads(uid, city="NYC", limit=100, readiness="letter")
        assert any(row["id"] == lead_id for row in credit_rows)
        assert credits.readiness_counts(city="NYC")["letter"] >= 1
    finally:
        _cleanup([email], [ext])
