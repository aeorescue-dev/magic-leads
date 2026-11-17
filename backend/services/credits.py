"""Motor comercial do Marco 1A: carteira de créditos, pacotes e reveal de sinal.

Regras:
- 1 crédito = $0,01. $1,50 = 150; $3,00 = 300.
- `credit_ledger` é a fonte de verdade; `credit_wallets` é cache.
- O telefone ($3) fica atrás de feature flag; a 1A só entrega sinal ($1,50).
- Exclusividade por ofício, 7 dias.
- Nada aqui chama Searchbug/Telnyx.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .db import DB_PATH

SIGNAL_PRICE_CENTS = 150
PHONE_PRICE_CENTS = 300
EXCLUSIVITY_DAYS = 7
TRUSTED_SIGNAL_SOURCES = {
    "seed_staging", "hpd_registration", "acris", "cook_assessor",
    "boston_assessing", "dcad", "manual_review",
}

PACKS: tuple[dict[str, Any], ...] = (
    {"code": "starter", "price_cents": 600, "credits_cents": 700, "bonus_cents": 100, "label": "Starter", "sort_order": 1},
    {"code": "basic", "price_cents": 900, "credits_cents": 1100, "bonus_cents": 200, "label": "Basic", "sort_order": 2},
    {"code": "pro", "price_cents": 1500, "credits_cents": 1900, "bonus_cents": 400, "label": "Pro", "sort_order": 3},
    {"code": "business", "price_cents": 4500, "credits_cents": 6000, "bonus_cents": 1500, "label": "Business", "sort_order": 4},
    {"code": "scale", "price_cents": 9000, "credits_cents": 12500, "bonus_cents": 3500, "label": "Scale", "sort_order": 5},
    {"code": "agency", "price_cents": 18000, "credits_cents": 26000, "bonus_cents": 8000, "label": "Agency", "sort_order": 6},
)

_INIT: dict[str, Optional[str]] = {"path": None}


class CreditsError(Exception):
    def __init__(self, code: str, status_code: int = 400, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.status_code = status_code
        self.detail = detail or code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init() -> None:
    if _INIT["path"] == DB_PATH:
        return
    conn = get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS credit_wallets (
              user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
              balance_cents INTEGER NOT NULL DEFAULT 0,
              reserved_cents INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS credit_packs (
              code TEXT PRIMARY KEY,
              price_cents INTEGER NOT NULL,
              credits_cents INTEGER NOT NULL,
              bonus_cents INTEGER NOT NULL DEFAULT 0,
              label TEXT NOT NULL,
              stripe_price_id TEXT,
              active INTEGER NOT NULL DEFAULT 1,
              sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS credit_purchases (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              pack_code TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              credits_cents INTEGER NOT NULL,
              stripe_session_id TEXT UNIQUE,
              stripe_payment_intent_id TEXT,
              status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              paid_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_credit_purchases_user
              ON credit_purchases (user_id, created_at);

            CREATE TABLE IF NOT EXISTS stripe_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id TEXT NOT NULL UNIQUE,
              event_type TEXT,
              user_id INTEGER,
              granted INTEGER NOT NULL DEFAULT 1,
              processed_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS credit_holds (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              amount_cents INTEGER NOT NULL,
              reference_type TEXT NOT NULL,
              reference_id TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              expires_at TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(user_id, reference_type, reference_id)
            );

            CREATE TABLE IF NOT EXISTS lead_exclusivity (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
              trade_code TEXT NOT NULL,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              reveal_id INTEGER,
              starts_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_lead_exclusivity_active
              ON lead_exclusivity (lead_id, trade_code) WHERE status='active';
            CREATE INDEX IF NOT EXISTS idx_lead_exclusivity_user
              ON lead_exclusivity (user_id, status, expires_at);
            """
        )
        _add_column(conn, "leads", "signal_ready", "INTEGER DEFAULT 0")
        _add_column(conn, "leads", "phone_eligible", "INTEGER DEFAULT 0")
        _add_column(conn, "leads", "phone_ready", "INTEGER DEFAULT 0")
        _add_column(conn, "leads", "parcel_id", "TEXT")
        _add_column(conn, "leads", "owner_source", "TEXT")
        _add_column(conn, "leads", "owner_kind", "TEXT")
        _add_column(conn, "leads", "principal_name", "TEXT")
        _add_column(conn, "lead_reveals", "reveal_type", "TEXT DEFAULT 'signal'")
        _add_column(conn, "lead_reveals", "trade_code", "TEXT")
        _add_column(conn, "lead_reveals", "credits_cents", "INTEGER DEFAULT 0")
        _add_column(conn, "lead_reveals", "exclusive_until", "TEXT")
        _add_column(conn, "lead_reveals", "payload_json", "TEXT")
        _add_column(conn, "lead_reveals", "searchbug_call_id", "INTEGER")
        _add_column(conn, "users", "account_status", "TEXT DEFAULT 'active'")
        _add_column(conn, "users", "email_verified_at", "TEXT")
        for pack in PACKS:
            conn.execute(
                "INSERT INTO credit_packs "
                "(code, price_cents, credits_cents, bonus_cents, label, stripe_price_id, active, sort_order) "
                "VALUES (?, ?, ?, ?, ?, '', 1, ?) "
                "ON CONFLICT(code) DO UPDATE SET "
                "price_cents=excluded.price_cents, credits_cents=excluded.credits_cents, "
                "bonus_cents=excluded.bonus_cents, label=excluded.label, sort_order=excluded.sort_order",
                (
                    pack["code"], pack["price_cents"], pack["credits_cents"],
                    pack["bonus_cents"], pack["label"], pack["sort_order"],
                ),
            )
        conn.commit()
        _INIT["path"] = DB_PATH
    finally:
        conn.close()


def _ensure_wallet(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    conn.execute(
        "INSERT OR IGNORE INTO credit_wallets (user_id, balance_cents, reserved_cents) VALUES (?, 0, 0)",
        (int(user_id),),
    )
    row = conn.execute(
        "SELECT * FROM credit_wallets WHERE user_id=?", (int(user_id),)
    ).fetchone()
    if not row:
        raise CreditsError("wallet_not_found", 500)
    return row


def get_wallet(user_id: int) -> dict[str, Any]:
    init()
    conn = get_conn()
    try:
        row = _ensure_wallet(conn, user_id)
        conn.commit()
        balance = int(row["balance_cents"] or 0)
        reserved = int(row["reserved_cents"] or 0)
        return {
            "balance_cents": balance,
            "reserved_cents": reserved,
            "available_cents": max(0, balance - reserved),
            "balance_usd": round(balance / 100.0, 2),
        }
    finally:
        conn.close()


def list_packs() -> list[dict[str, Any]]:
    init()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT code, price_cents, credits_cents, bonus_cents, label, sort_order "
            "FROM credit_packs WHERE active=1 ORDER BY sort_order, price_cents"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pack(code: str) -> dict[str, Any]:
    init()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM credit_packs WHERE code=? AND active=1", (code,)
        ).fetchone()
        if not row:
            raise CreditsError("pack_not_found", 404)
        return dict(row)
    finally:
        conn.close()


def _ledger_insert(
    conn: sqlite3.Connection,
    user_id: int,
    event_type: str,
    amount_cents: int,
    balance_after: int,
    reference_type: str,
    reference_id: str,
    metadata: Optional[dict] = None,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO credit_ledger "
        "(user_id, event_type, amount, balance_after, reference_type, reference_id, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            int(user_id), event_type, int(amount_cents), int(balance_after),
            reference_type, str(reference_id), json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )


def create_purchase(user_id: int, pack_code: str, stripe_session_id: Optional[str] = None) -> dict[str, Any]:
    pack = get_pack(pack_code)
    init()
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO credit_purchases "
            "(user_id, pack_code, amount_cents, credits_cents, stripe_session_id, status) "
            "VALUES (?, ?, ?, ?, ?, 'pending')",
            (
                int(user_id), pack["code"], int(pack["price_cents"]),
                int(pack["credits_cents"]), stripe_session_id,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM credit_purchases WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_purchase(purchase_id: int, user_id: Optional[int] = None) -> dict[str, Any]:
    init()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM credit_purchases WHERE id=?", (int(purchase_id),)
        ).fetchone()
        if not row:
            raise CreditsError("purchase_not_found", 404)
        if user_id is not None and int(row["user_id"]) != int(user_id):
            raise CreditsError("purchase_not_owned", 403)
        return dict(row)
    finally:
        conn.close()


def attach_session(purchase_id: int, session_id: str) -> dict[str, Any]:
    init()
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE credit_purchases SET stripe_session_id=? WHERE id=?",
            (session_id, int(purchase_id)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM credit_purchases WHERE id=?", (int(purchase_id),)
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def mark_purchase_paid(
    session_id: str,
    *,
    event_id: Optional[str] = None,
    payment_intent_id: Optional[str] = None,
    stripe_event_type: str = "checkout.session.completed",
) -> dict[str, Any]:
    init()
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if event_id:
            existing = conn.execute(
                "SELECT event_id FROM stripe_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if existing:
                conn.rollback()
                purchase = conn.execute(
                    "SELECT * FROM credit_purchases WHERE stripe_session_id=?", (session_id,)
                ).fetchone()
                return {"duplicate": True, "purchase": dict(purchase) if purchase else None}
            conn.execute(
                "INSERT INTO stripe_events (event_id, event_type) VALUES (?, ?)",
                (event_id, stripe_event_type),
            )
        purchase = conn.execute(
            "SELECT * FROM credit_purchases WHERE stripe_session_id=?", (session_id,)
        ).fetchone()
        if not purchase:
            conn.rollback()
            raise CreditsError("purchase_not_found", 404)
        if purchase["status"] == "paid":
            conn.rollback()
            return {"duplicate": True, "purchase": dict(purchase)}
        wallet = _ensure_wallet(conn, int(purchase["user_id"]))
        new_balance = int(wallet["balance_cents"] or 0) + int(purchase["credits_cents"] or 0)
        conn.execute(
            "UPDATE credit_purchases SET status='paid', paid_at=?, stripe_payment_intent_id=COALESCE(?, stripe_payment_intent_id) "
            "WHERE id=?",
            (_iso(), payment_intent_id, purchase["id"]),
        )
        conn.execute(
            "UPDATE credit_wallets SET balance_cents=?, updated_at=? WHERE user_id=?",
            (new_balance, _iso(), int(purchase["user_id"])),
        )
        _ledger_insert(
            conn, int(purchase["user_id"]), "pack_purchase",
            int(purchase["credits_cents"]), new_balance,
            "credit_purchase", str(purchase["id"]),
            {"pack_code": purchase["pack_code"], "amount_cents": purchase["amount_cents"]},
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM credit_purchases WHERE id=?", (purchase["id"],)
        ).fetchone()
        return {"duplicate": False, "purchase": dict(row), "wallet": get_wallet(int(purchase["user_id"]))}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mock_purchase(user_id: int, pack_code: str, idempotency_key: str) -> dict[str, Any]:
    session_id = f"mock:{idempotency_key}"
    init()
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT * FROM credit_purchases WHERE stripe_session_id=?", (session_id,)
        ).fetchone()
        if existing:
            return {"duplicate": True, "purchase": dict(existing), "wallet": get_wallet(user_id)}
    finally:
        conn.close()
    purchase = create_purchase(user_id, pack_code, stripe_session_id=session_id)
    result = mark_purchase_paid(
        session_id, event_id=f"evt_mock:{idempotency_key}", payment_intent_id=f"pi_mock:{idempotency_key}",
        stripe_event_type="mock.checkout.completed",
    )
    result["purchase"] = result.get("purchase") or purchase
    return result


def refund_purchase(session_id: str, event_id: Optional[str] = None) -> dict[str, Any]:
    init()
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        purchase = conn.execute(
            "SELECT * FROM credit_purchases WHERE stripe_session_id=?", (session_id,)
        ).fetchone()
        if not purchase:
            conn.rollback()
            raise CreditsError("purchase_not_found", 404)
        if purchase["status"] == "refunded":
            conn.rollback()
            return {"duplicate": True, "purchase": dict(purchase)}
        if event_id:
            existing = conn.execute("SELECT event_id FROM stripe_events WHERE event_id=?", (event_id,)).fetchone()
            if not existing:
                conn.execute("INSERT INTO stripe_events (event_id, event_type) VALUES (?, 'charge.refunded')", (event_id,))
        wallet = _ensure_wallet(conn, int(purchase["user_id"]))
        new_balance = int(wallet["balance_cents"] or 0) - int(purchase["credits_cents"] or 0)
        conn.execute("UPDATE credit_purchases SET status='refunded' WHERE id=?", (purchase["id"],))
        conn.execute(
            "UPDATE credit_wallets SET balance_cents=?, updated_at=? WHERE user_id=?",
            (new_balance, _iso(), int(purchase["user_id"])),
        )
        _ledger_insert(
            conn, int(purchase["user_id"]), "purchase_refund",
            -int(purchase["credits_cents"]), new_balance,
            "credit_purchase_refund", str(purchase["id"]),
            {"pack_code": purchase["pack_code"]},
        )
        conn.commit()
        return {"duplicate": False, "purchase": dict(purchase)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _lead_row(conn: sqlite3.Connection, lead_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM leads WHERE id=?", (int(lead_id),)).fetchone()
    if not row:
        raise CreditsError("lead_not_found", 404)
    return row


def _mask_owner(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return "Proprietário não identificado"
    tokens = text.split()
    if len(tokens) == 1:
        return tokens[0][0] + "***"
    return f"{tokens[0][0]}*** {tokens[-1][0]}***"


def _mask_address(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return "Endereço não disponível"
    parts = text.split(",")
    first = parts[0].strip()
    tokens = first.split()
    if len(tokens) > 1:
        return "*** " + " ".join(tokens[1:])
    return "***"


def _lead_payload(lead: sqlite3.Row, trade_code: str, exclusive_until: Optional[str] = None) -> dict[str, Any]:
    return {
        "lead_id": int(lead["id"]),
        "type": "signal",
        "trade_code": trade_code,
        "address": lead["address"],
        "city": lead["city"],
        "state": lead["state"],
        "zip_code": lead["zip_code"],
        "owner_name": lead["owner_name"],
        "mailing_address": lead["mailing_address"],
        "phone": None,
        "exclusive_until": exclusive_until,
        "price_cents": SIGNAL_PRICE_CENTS,
    }


def active_exclusivity(conn: sqlite3.Connection, lead_id: int, trade_code: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM lead_exclusivity WHERE lead_id=? AND trade_code=? AND status='active' "
        "AND datetime(expires_at) > datetime('now') ORDER BY id DESC LIMIT 1",
        (int(lead_id), trade_code),
    ).fetchone()


def _readiness_base(trade_code: Optional[str] = None, city: Optional[str] = None) -> tuple[list[str], list[Any]]:
    """Base comum das três abas do painel de créditos.

    `is_feed_ok=1` alinha com o feed oficial; `signal_type` e `lead_status`
    evitam lixo e convertidos. A prontidão é aplicada por `list_leads`.
    """
    where = [
        "l.is_feed_ok = 1",
        "l.signal_type IS NOT NULL",
        "l.lead_status != 'converted'",
    ]
    params: list[Any] = []
    if trade_code:
        where.append("l.issue_category = ?")
        params.append(trade_code)
    if city:
        where.append("UPPER(l.city) = UPPER(?)")
        params.append(city)
    return where, params


def list_leads(
    user_id: int,
    trade_code: Optional[str] = None,
    city: Optional[str] = None,
    limit: int = 60,
    readiness: str = "letter",
) -> list[dict[str, Any]]:
    init()
    conn = get_conn()
    try:
        where, params = _readiness_base(trade_code, city)
        readiness = str(readiness or "letter").strip().lower()
        if readiness == "letter":
            where.append("l.signal_ready = 1")
        elif readiness == "phone":
            where.append("(l.phone_eligible = 1 OR l.phone_ready = 1)")
        rows = conn.execute(
            "SELECT l.* FROM leads l WHERE " + " AND ".join(where) +
            " ORDER BY l.date_reported DESC, l.id DESC LIMIT ?",
            (*params, max(1, min(int(limit), 100))),
        ).fetchall()
        out = []
        for row in rows:
            trade = str(row["issue_category"] or "")
            excl = active_exclusivity(conn, int(row["id"]), trade)
            out.append({
                "id": int(row["id"]),
                "city": row["city"],
                "trade_code": trade,
                "zone": row["neighborhood"] or row["zip_code"] or "",
                "date_reported": row["date_reported"],
                "title": row["case_title"] or row["issue_description"] or row["descriptor"] or "Oportunidade ativa",
                "address_masked": _mask_address(row["address"]),
                "owner_masked": _mask_owner(row["owner_name"]),
                "mailing_ready": bool((row["mailing_address"] or "").strip()),
                "signal_ready": bool(int(row["signal_ready"] or 0)),
                "phone_eligible": bool(int(row["phone_eligible"] or 0)),
                "phone_ready": bool(int(row["phone_ready"] or 0)),
                "signal_price_cents": SIGNAL_PRICE_CENTS,
                "phone_price_cents": PHONE_PRICE_CENTS,
                "exclusive": bool(excl),
                "exclusive_mine": bool(excl and int(excl["user_id"]) == int(user_id)),
                "exclusive_until": excl["expires_at"] if excl else None,
            })
        return out
    finally:
        conn.close()


def readiness_counts(trade_code: Optional[str] = None, city: Optional[str] = None) -> dict[str, int]:
    """Counts das três abas no mesmo filtro de cidade/ofício."""
    init()
    conn = get_conn()
    try:
        where, params = _readiness_base(trade_code, city)
        row = conn.execute(
            "SELECT COUNT(*) AS all_count, "
            "COALESCE(SUM(CASE WHEN l.signal_ready = 1 THEN 1 ELSE 0 END), 0) AS letter_count, "
            "COALESCE(SUM(CASE WHEN l.phone_eligible = 1 OR l.phone_ready = 1 THEN 1 ELSE 0 END), 0) AS phone_count "
            "FROM leads l WHERE " + " AND ".join(where),
            params,
        ).fetchone()
        return {
            "all": int(row["all_count"] or 0),
            "letter": int(row["letter_count"] or 0),
            "phone": int(row["phone_count"] or 0),
        }
    finally:
        conn.close()


def preview(user_id: int, lead_id: int, trade_code: Optional[str] = None) -> dict[str, Any]:
    init()
    conn = get_conn()
    try:
        lead = _lead_row(conn, lead_id)
        trade = trade_code or str(lead["issue_category"] or "")
        excl = active_exclusivity(conn, int(lead_id), trade)
        mine = bool(excl and int(excl["user_id"]) == int(user_id))
        if mine:
            reveal = conn.execute(
                "SELECT * FROM lead_reveals WHERE lead_id=? AND user_id=? AND trade_code=? "
                "ORDER BY id DESC LIMIT 1",
                (int(lead_id), int(user_id), trade),
            ).fetchone()
            payload = json.loads(reveal["payload_json"]) if reveal and reveal["payload_json"] else None
            return {"masked": False, "already_revealed": True, "reveal": payload, "exclusive_until": excl["expires_at"] if excl else None}
        return {
            "masked": True,
            "already_revealed": False,
            "lead": {
                "id": int(lead["id"]),
                "city": lead["city"],
                "trade_code": trade,
                "zone": lead["neighborhood"] or lead["zip_code"] or "",
                "date_reported": lead["date_reported"],
                "title": lead["case_title"] or lead["issue_description"] or lead["descriptor"] or "Oportunidade ativa",
                "address_masked": _mask_address(lead["address"]),
                "owner_masked": _mask_owner(lead["owner_name"]),
                "mailing_ready": bool((lead["mailing_address"] or "").strip()),
                "signal_ready": bool(int(lead["signal_ready"] or 0)),
                "phone_ready": bool(int(lead["phone_ready"] or 0)),
                "signal_price_cents": SIGNAL_PRICE_CENTS,
                "phone_price_cents": PHONE_PRICE_CENTS,
                "exclusive": bool(excl),
                "exclusive_mine": mine,
                "exclusive_until": excl["expires_at"] if excl else None,
            },
            "blocked_reason": "exclusive_by_other" if excl and not mine else None,
        }
    finally:
        conn.close()


def _spend_locked(conn: sqlite3.Connection, user_id: int, amount: int, event_type: str, reference_type: str, reference_id: str, metadata: dict) -> int:
    wallet = _ensure_wallet(conn, user_id)
    balance = int(wallet["balance_cents"] or 0)
    reserved = int(wallet["reserved_cents"] or 0)
    if balance - reserved < amount:
        raise CreditsError("insufficient_credits", 402, f"Saldo insuficiente: precisa de {amount} créditos.")
    new_balance = balance - amount
    conn.execute(
        "UPDATE credit_wallets SET balance_cents=?, updated_at=? WHERE user_id=?",
        (new_balance, _iso(), int(user_id)),
    )
    _ledger_insert(conn, user_id, event_type, -amount, new_balance, reference_type, reference_id, metadata)
    return new_balance


def reveal_signal(user_id: int, lead_id: int, trade_code: Optional[str], idempotency_key: str) -> dict[str, Any]:
    init()
    if not idempotency_key:
        raise CreditsError("idempotency_key_required", 422)
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT * FROM lead_reveals WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if existing:
            payload = json.loads(existing["payload_json"]) if existing["payload_json"] else None
            return {"duplicate": True, "reveal_id": int(existing["id"]), "payload": payload, "wallet": get_wallet(user_id)}
        lead = _lead_row(conn, lead_id)
        trade = (trade_code or str(lead["issue_category"] or "")).strip()
        if not trade:
            raise CreditsError("trade_required", 422)
        if not int(lead["signal_ready"] or 0):
            raise CreditsError("signal_not_ready", 422, "Este lead ainda não tem sinal verificado para carta.")
        if not (lead["owner_name"] or "").strip():
            raise CreditsError("owner_missing", 422, "Proprietário oficial em falta.")
        if not (lead["address"] or "").strip():
            raise CreditsError("address_missing", 422, "Endereço da obra em falta.")
        source = str(lead["owner_source"] or "").strip()
        if source and source not in TRUSTED_SIGNAL_SOURCES:
            raise CreditsError("owner_untrusted", 422, "Proprietário sem fonte oficial validada.")
        if not (lead["mailing_address"] or "").strip():
            raise CreditsError("mailing_missing", 422, "Mailing address em falta; não é possível vender carta.")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE lead_exclusivity SET status='expired' "
            "WHERE status='active' AND datetime(expires_at) <= datetime('now')"
        )
        excl = active_exclusivity(conn, int(lead_id), trade)
        if excl and int(excl["user_id"]) != int(user_id):
            conn.rollback()
            raise CreditsError("exclusive_by_other", 409, "Lead exclusivo para outro empreiteiro neste ofício.")
        if excl and int(excl["user_id"]) == int(user_id):
            reveal = conn.execute(
                "SELECT * FROM lead_reveals WHERE lead_id=? AND user_id=? AND trade_code=? ORDER BY id DESC LIMIT 1",
                (int(lead_id), int(user_id), trade),
            ).fetchone()
            conn.rollback()
            return {
                "duplicate": True,
                "reveal_id": int(reveal["id"]) if reveal else None,
                "payload": json.loads(reveal["payload_json"]) if reveal and reveal["payload_json"] else None,
                "wallet": get_wallet(user_id),
            }
        exclusive_until = _iso(_now() + timedelta(days=EXCLUSIVITY_DAYS))
        payload = _lead_payload(lead, trade, exclusive_until)
        cur = conn.execute(
            "INSERT INTO lead_reveals "
            "(lead_id, user_id, revealed_date, idempotency_key, reveal_type, trade_code, "
            "credits_cents, exclusive_until, payload_json) "
            "VALUES (?, ?, date('now'), ?, 'signal', ?, ?, ?, ?)",
            (
                int(lead_id), int(user_id), idempotency_key, trade,
                SIGNAL_PRICE_CENTS, exclusive_until,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        reveal_id = int(cur.lastrowid)
        # O ledger referencia o reveal real (idempotência por user/referência).
        new_balance = _spend_locked(
            conn, user_id, SIGNAL_PRICE_CENTS, "reveal_signal", "reveal_signal", str(reveal_id),
            {"lead_id": int(lead_id), "trade_code": trade},
        )
        conn.execute(
            "INSERT INTO lead_exclusivity "
            "(lead_id, trade_code, user_id, reveal_id, starts_at, expires_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active')",
            (int(lead_id), trade, int(user_id), reveal_id, _iso(), exclusive_until),
        )
        conn.execute(
            "INSERT INTO lead_events (lead_id, event_type, user_id, detail) VALUES (?, 'revealed', ?, ?)",
            (int(lead_id), int(user_id), f"signal:{trade}:{SIGNAL_PRICE_CENTS}c"),
        )
        conn.commit()
        return {"duplicate": False, "reveal_id": reveal_id, "payload": payload, "wallet": get_wallet(user_id), "balance_after_cents": new_balance}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def phone_quote(user_id: int, lead_id: int, trade_code: Optional[str] = None) -> dict[str, Any]:
    """Elegibilidade e saldo para o reveal de telefone on-demand."""
    init()
    conn = get_conn()
    try:
        lead = _lead_row(conn, lead_id)
        wallet = _ensure_wallet(conn, int(user_id))
        prior = conn.execute(
            "SELECT * FROM lead_reveals WHERE lead_id=? AND user_id=? "
            "AND reveal_type='phone' ORDER BY id DESC LIMIT 1",
            (int(lead_id), int(user_id)),
        ).fetchone()
        prior_payload = (
            json.loads(prior["payload_json"])
            if prior and prior["payload_json"]
            else None
        )
        return {
            "lead_id": int(lead_id),
            "trade_code": (trade_code or str(lead["issue_category"] or "")).strip(),
            "eligible": bool(
                int(lead["phone_eligible"] or 0) or int(lead["phone_ready"] or 0)
            ),
            "phone_ready": bool(int(lead["phone_ready"] or 0)),
            "owner_phone": str(lead["owner_phone"] or "") if prior else "",
            "already_revealed": bool(prior),
            "payload": prior_payload,
            "price_cents": PHONE_PRICE_CENTS,
            "balance_cents": int(wallet["balance_cents"] or 0) - int(wallet["reserved_cents"] or 0),
            "lead": dict(lead),
        }
    finally:
        conn.close()


def complete_phone_reveal(
    user_id: int,
    lead_id: int,
    trade_code: Optional[str],
    idempotency_key: str,
    phone: str,
    searchbug_call_id: Optional[int] = None,
) -> dict[str, Any]:
    """Cobra 300 créditos e regista o telefone revelado (idempotente)."""
    init()
    if not idempotency_key:
        raise CreditsError("idempotency_key_required", 422)
    if not str(phone or "").strip():
        raise CreditsError("phone_missing", 422)
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT * FROM lead_reveals WHERE idempotency_key=?", (idempotency_key,)
        ).fetchone()
        if existing:
            payload = json.loads(existing["payload_json"]) if existing["payload_json"] else None
            return {
                "success": True,
                "duplicate": True,
                "reveal_id": int(existing["id"]),
                "payload": payload,
                "wallet": get_wallet(user_id),
            }
        prior = conn.execute(
            "SELECT * FROM lead_reveals WHERE lead_id=? AND user_id=? "
            "AND reveal_type='phone' ORDER BY id DESC LIMIT 1",
            (int(lead_id), int(user_id)),
        ).fetchone()
        if prior:
            payload = json.loads(prior["payload_json"]) if prior["payload_json"] else None
            return {
                "success": True,
                "duplicate": True,
                "reveal_id": int(prior["id"]),
                "payload": payload,
                "wallet": get_wallet(user_id),
            }
        lead = _lead_row(conn, lead_id)
        trade = (trade_code or str(lead["issue_category"] or "")).strip()
        payload = {
            "lead_id": int(lead_id),
            "type": "phone",
            "trade_code": trade,
            "phone": str(phone).strip(),
            "owner_name": lead["owner_name"],
            "address": lead["address"],
            "city": lead["city"],
            "state": lead["state"],
            "zip_code": lead["zip_code"],
            "price_cents": PHONE_PRICE_CENTS,
        }
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO lead_reveals "
            "(lead_id, user_id, revealed_date, idempotency_key, reveal_type, trade_code, "
            "credits_cents, payload_json, searchbug_call_id) "
            "VALUES (?, ?, date('now'), ?, 'phone', ?, ?, ?, ?)",
            (
                int(lead_id), int(user_id), idempotency_key, trade,
                PHONE_PRICE_CENTS, json.dumps(payload, ensure_ascii=False),
                searchbug_call_id,
            ),
        )
        reveal_id = int(cur.lastrowid)
        new_balance = _spend_locked(
            conn, user_id, PHONE_PRICE_CENTS, "reveal_phone", "reveal_phone",
            str(reveal_id), {"lead_id": int(lead_id), "trade_code": trade},
        )
        conn.execute(
            "INSERT INTO lead_events (lead_id, event_type, user_id, detail) "
            "VALUES (?, 'phone_revealed', ?, ?)",
            (int(lead_id), int(user_id), f"phone:{PHONE_PRICE_CENTS}c"),
        )
        conn.commit()
        return {
            "success": True,
            "duplicate": False,
            "reveal_id": reveal_id,
            "payload": payload,
            "wallet": get_wallet(user_id),
            "balance_after_cents": new_balance,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reveal_phone(*args, **kwargs) -> dict[str, Any]:
    """Compatibilidade: o endpoint novo faz a consulta on-demand e chama
    `complete_phone_reveal`; este atalho mantém o contrato antigo fechado."""
    raise CreditsError("phone_reveal_disabled", 503, "Consulta de telefone indisponível.")


def list_ledger(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    init()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, created_at, event_type, amount, balance_after, reference_type, reference_id, metadata "
            "FROM credit_ledger WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (int(user_id), max(1, min(int(limit), 100))),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
