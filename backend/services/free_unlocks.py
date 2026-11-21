"""Bonus de boas-vindas para contas gratuitas (flag `FREE_UNLOCKS_ENABLED`).

Pacote vitalicio por conta free: 2 telefones + 3 cartas/visitas. Nao renova.
Gate de antiabuso: email canonico (aliases/+tag), dominios descartaveis,
fingerprint de dispositivo+IP/UA, verificacao de email, Turnstile no registo e
circuit breaker financeiro (25 contas/dia, $75/mes em Searchbug).

Tudo atras da flag; com a flag desligada nenhuma funcao concede ou consome.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from ..config import settings
from . import billing_time
from .db import db_service, get_connection

logger = logging.getLogger(__name__)

PHONE = "phone"
LETTER = "letter"

DISPOSABLE_DOMAINS = {
    "10minutemail.com",
    "33mail.com",
    "discard.email",
    "dispostable.com",
    "emailondeck.com",
    "fakeinbox.com",
    "getnada.com",
    "guerrillamail.com",
    "guerrillamail.net",
    "inboxkitten.com",
    "luxusmail.org",
    "maildrop.cc",
    "mailinator.com",
    "mailnesia.com",
    "mintemail.com",
    "moakt.com",
    "mytemp.email",
    "sharklasers.com",
    "spamgourmet.com",
    "temp-mail.org",
    "tempmail.com",
    "tempr.email",
    "throwawaymail.com",
    "trashmail.com",
    "yopmail.com",
}

_INIT: dict = {"ready": False}


def enabled() -> bool:
    return bool(getattr(settings, "FREE_UNLOCKS_ENABLED", False))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return billing_time.local_date(datetime.now(timezone.utc))


def _month() -> str:
    return _today()[:7]


def canonical_email(email: str) -> str:
    raw = str(email or "").strip().lower()
    if "@" not in raw:
        return raw
    local, domain = raw.rsplit("@", 1)
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
    return f"{local}@{domain}"


def email_domain(email: str) -> str:
    return str(email or "").strip().lower().rsplit("@", 1)[-1]


def is_disposable(email: str) -> bool:
    domain = email_domain(email)
    if not domain:
        return False
    return any(domain == d or domain.endswith("." + d) for d in DISPOSABLE_DOMAINS)


def device_key(device_id: str, user_agent: str = "", ip: str = "") -> str:
    raw = f"{str(device_id or '').strip()}|{str(user_agent or '')}|{str(ip or '')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_turnstile(token: str, ip: str = "") -> bool:
    secret = str(getattr(settings, "TURNSTILE_SECRET_KEY", "") or "").strip()
    if not secret:
        # Sem chave configurada, o registo segue sem captcha (flag de teste).
        return True
    if not str(token or "").strip():
        return False
    try:
        resp = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": ip},
            timeout=10,
        )
        return bool(resp.json().get("success"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FREE-UNLOCKS] turnstile falhou: %s", exc)
        return False


def _verify_secret() -> str:
    return str(
        getattr(settings, "EMAIL_VERIFY_SECRET", "")
        or getattr(settings, "UNSUBSCRIBE_SECRET", "")
        or getattr(settings, "CRON_SECRET", "")
        or "magic-leads-verify"
    )


def email_token(user_id: int, email: str, ttl_seconds: int = 86400) -> str:
    payload = f"{int(user_id)}:{int(time.time()) + ttl_seconds}:{canonical_email(email)}"
    raw = urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    sig = hmac.new(_verify_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def read_email_token(token: str) -> dict:
    try:
        raw, sig = str(token or "").split(".", 1)
    except ValueError:
        return {"ok": False, "reason": "malformed"}
    expected = hmac.new(
        _verify_secret().encode(), raw.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return {"ok": False, "reason": "bad_signature"}
    try:
        payload = urlsafe_b64decode(raw.encode()).decode("utf-8")
        user_id, expires, email = payload.split(":", 2)
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "malformed"}
    if int(expires) < int(time.time()):
        return {"ok": False, "reason": "expired"}
    return {"ok": True, "user_id": int(user_id), "email": email}


def init() -> None:
    if _INIT["ready"]:
        return
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS free_unlock_grants (
              user_id INTEGER PRIMARY KEY,
              email_canonical TEXT NOT NULL,
              device_key TEXT,
              phone_total INTEGER NOT NULL DEFAULT 2,
              phone_used INTEGER NOT NULL DEFAULT 0,
              letter_total INTEGER NOT NULL DEFAULT 3,
              letter_used INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'active',
              paused_reason TEXT,
              granted_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS free_unlock_keys (
              key TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              user_id INTEGER NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS free_unlock_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              lead_id INTEGER,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              cost_cents INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_free_unlock_events_user
              ON free_unlock_events (user_id, kind, created_at DESC);
            CREATE TABLE IF NOT EXISTS free_unlock_daily (
              day TEXT PRIMARY KEY,
              grants INTEGER NOT NULL DEFAULT 0,
              phone_costs_cents INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS free_unlock_pending (
              user_id INTEGER PRIMARY KEY,
              email_canonical TEXT NOT NULL,
              device_key TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS free_unlock_circuit (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              reason TEXT NOT NULL,
              day TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        try:
            conn.execute("ALTER TABLE users ADD COLUMN email_verified_at TEXT")
        except Exception:  # noqa: BLE001 - coluna ja existe
            pass
        conn.commit()
    finally:
        conn.close()
    _INIT["ready"] = True


def _alert(code: str, message: str) -> None:
    try:
        service = getattr(db_service, "_service", db_service)
        service.record_system_alert("warning", code, message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FREE-UNLOCKS] alerta %s falhou: %s", code, exc)


def _daily_grants(conn) -> int:
    row = conn.execute(
        "SELECT grants FROM free_unlock_daily WHERE day=?", (_today(),)
    ).fetchone()
    return int(row["grants"] or 0) if row else 0


def _month_cost_cents(conn) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_cents),0) c FROM free_unlock_events "
        "WHERE substr(created_at,1,7)=? AND status='consumed'",
        (_month(),),
    ).fetchone()
    return int(row["c"] or 0)


def _paused(conn, reason: str) -> None:
    """Circuit breaker: bloqueia novas concessoes; nao toca nos bonus ja dados."""
    conn.execute(
        "INSERT INTO free_unlock_circuit (id, reason, day, created_at) "
        "VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "reason=excluded.reason, day=excluded.day, created_at=excluded.created_at",
        (reason, _today(), _now()),
    )
    conn.commit()
    _alert("FREE_UNLOCKS_PAUSED", f"Novos bónus grátis pausados: {reason}")


def _circuit_reason(conn) -> str | None:
    row = conn.execute(
        "SELECT reason, day FROM free_unlock_circuit WHERE id=1"
    ).fetchone()
    if not row:
        return None
    # O tecto diario expira no dia seguinte; o orcamento mensal nao.
    if row["reason"] == "daily_cap" and row["day"] != _today():
        conn.execute("DELETE FROM free_unlock_circuit WHERE id=1")
        conn.commit()
        return None
    if row["reason"] == "monthly_budget" and str(row["day"])[:7] != _month():
        conn.execute("DELETE FROM free_unlock_circuit WHERE id=1")
        conn.commit()
        return None
    return str(row["reason"])


def pause_all(reason: str = "manual") -> dict:
    init()
    conn = get_connection()
    try:
        _paused(conn, reason)
    finally:
        conn.close()
    return {"ok": True, "paused": reason}


def resume_all() -> dict:
    init()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM free_unlock_circuit WHERE id=1")
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


def pending_signup(user_id: int, email: str, device: str) -> None:
    init()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO free_unlock_pending (user_id, email_canonical, device_key, created_at) "
            "VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
            "email_canonical=excluded.email_canonical, device_key=excluded.device_key",
            (int(user_id), canonical_email(email), device, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def grant(user_id: int, email: str = "", device: str = "") -> dict:
    """Concede o pacote se elegivel. Idempotente. Nunca levanta excecao."""
    if not enabled():
        return {"ok": False, "reason": "disabled"}
    init()
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT * FROM free_unlock_grants WHERE user_id=?", (int(user_id),)
        ).fetchone()
        if existing:
            return {"ok": True, "granted": False, "reason": "already_granted"}

        paused = _circuit_reason(conn)
        if paused:
            return {"ok": False, "reason": paused}

        pending = conn.execute(
            "SELECT * FROM free_unlock_pending WHERE user_id=?", (int(user_id),)
        ).fetchone()
        canonical = canonical_email(email or (pending["email_canonical"] if pending else ""))
        device = device or (pending["device_key"] if pending else "")

        if _daily_grants(conn) >= int(getattr(settings, "FREE_UNLOCKS_DAILY_CAP", 25) or 25):
            _paused(conn, "daily_cap")
            return {"ok": False, "reason": "daily_cap"}

        budget_cents = int(
            float(getattr(settings, "FREE_UNLOCKS_MONTHLY_BUDGET_USD", 75) or 75) * 100
        )
        if _month_cost_cents(conn) >= budget_cents:
            _paused(conn, "monthly_budget")
            return {"ok": False, "reason": "monthly_budget"}

        keys = []
        if canonical:
            keys.append((f"email:{canonical}", "email"))
        if device:
            keys.append((f"device:{device}", "device"))
        for key, kind in keys:
            used = conn.execute(
                "SELECT user_id FROM free_unlock_keys WHERE key=?", (key,)
            ).fetchone()
            if used and int(used["user_id"]) != int(user_id):
                return {"ok": False, "reason": f"{kind}_already_used"}

        phone_total = int(getattr(settings, "FREE_UNLOCKS_PHONE_TOTAL", 2) or 2)
        letter_total = int(getattr(settings, "FREE_UNLOCKS_LETTER_TOTAL", 3) or 3)
        conn.execute(
            "INSERT INTO free_unlock_grants "
            "(user_id, email_canonical, device_key, phone_total, phone_used, "
            " letter_total, letter_used, status, granted_at) "
            "VALUES (?,?,?,?,0,?,0,'active',?)",
            (int(user_id), canonical, device, phone_total, letter_total, _now()),
        )
        for key, kind in keys:
            conn.execute(
                "INSERT OR IGNORE INTO free_unlock_keys (key, kind, user_id, created_at) "
                "VALUES (?,?,?,?)",
                (key, kind, int(user_id), _now()),
            )
        conn.execute(
            "INSERT INTO free_unlock_daily (day, grants) VALUES (?,1) "
            "ON CONFLICT(day) DO UPDATE SET grants=grants+1",
            (_today(),),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "granted": True,
        "phone_total": phone_total,
        "letter_total": letter_total,
    }


def canonical_in_use(email: str) -> bool:
    """True se ja existe conta com o mesmo email canonico (alias/+tag)."""
    init()
    canonical = canonical_email(email)
    if not canonical:
        return False
    conn = get_connection()
    try:
        rows = conn.execute("SELECT email FROM users").fetchall()
        return any(canonical_email(row["email"]) == canonical for row in rows)
    finally:
        conn.close()


def send_verify_email(email: str, token: str) -> dict:
    """Envia o link de verificacao via Resend. Fail-soft."""
    api_key = str(getattr(settings, "EMAIL_API_KEY", "") or "").strip()
    sender = str(getattr(settings, "EMAIL_FROM", "") or "").strip()
    if not api_key or not sender:
        return {"ok": False, "reason": "email_not_configured"}
    base = str(getattr(settings, "PUBLIC_API_URL", "") or "").rstrip("/")
    link = f"{base}/api/auth/verify-email?token={quote(token, safe='')}"
    html = (
        "<p>Confirm your email to unlock your Magic Leads welcome bonus:</p>"
        f'<p><a href="{link}">Verify email and unlock 2 phones + 3 letters</a></p>'
        "<p>If you did not create this account, ignore this email.</p>"
    )
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": sender,
                "to": [email],
                "subject": "Verify your email — Magic Leads",
                "html": html,
                "text": f"Verify your email: {link}",
            },
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FREE-UNLOCKS] email falhou: %s", exc)
        return {"ok": False, "reason": "network"}
    if resp.status_code >= 300:
        logger.warning("[FREE-UNLOCKS] Resend HTTP %s", resp.status_code)
        return {"ok": False, "reason": f"http_{resp.status_code}"}
    return {"ok": True}


def mark_email_verified(user_id: int) -> None:
    init()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET email_verified_at=? WHERE id=?", (_now(), int(user_id))
        )
        conn.commit()
    finally:
        conn.close()


def balance(user_id: int) -> dict:
    if not enabled():
        return {
            "enabled": False,
            "granted": False,
            "phone": {"total": 0, "used": 0, "remaining": 0},
            "letter": {"total": 0, "used": 0, "remaining": 0},
        }
    init()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM free_unlock_grants WHERE user_id=?", (int(user_id),)
        ).fetchone()
        if not row:
            return {
                "enabled": True,
                "granted": False,
                "status": None,
                "phone": {"total": 0, "used": 0, "remaining": 0},
                "letter": {"total": 0, "used": 0, "remaining": 0},
            }
        phone_total = int(row["phone_total"] or 0)
        phone_used = int(row["phone_used"] or 0)
        letter_total = int(row["letter_total"] or 0)
        letter_used = int(row["letter_used"] or 0)
        return {
            "enabled": True,
            "granted": True,
            "status": row["status"],
            "paused_reason": row["paused_reason"],
            "phone": {
                "total": phone_total,
                "used": phone_used,
                "remaining": max(0, phone_total - phone_used),
            },
            "letter": {
                "total": letter_total,
                "used": letter_used,
                "remaining": max(0, letter_total - letter_used),
            },
        }
    finally:
        conn.close()


def remaining(user_id: int, kind: str) -> int:
    data = balance(user_id)
    return int(data.get(kind, {}).get("remaining", 0))


def _consume(user_id: int, kind: str, lead_id=None) -> dict:
    init()
    column = "phone_used" if kind == PHONE else "letter_used"
    total_col = "phone_total" if kind == PHONE else "letter_total"
    conn = get_connection()
    try:
        cur = conn.execute(
            f"UPDATE free_unlock_grants SET {column}={column}+1 "
            f"WHERE user_id=? AND status='active' AND {column} < {total_col}",
            (int(user_id),),
        )
        if cur.rowcount == 0:
            conn.commit()
            return {"ok": False, "reason": "exhausted"}
        conn.execute(
            "INSERT INTO free_unlock_events "
            "(user_id, lead_id, kind, status, cost_cents, created_at) "
            "VALUES (?,?,?,'consumed',0,?)",
            (int(user_id), int(lead_id) if lead_id else None, kind, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "kind": kind, "lead_id": lead_id}


def consume_phone(user_id: int, lead_id=None) -> dict:
    if not enabled():
        return {"ok": False, "reason": "disabled"}
    return _consume(user_id, PHONE, lead_id)


def consume_letter(user_id: int, lead_id=None) -> dict:
    if not enabled():
        return {"ok": False, "reason": "disabled"}
    return _consume(user_id, LETTER, lead_id)


def _refund(user_id: int, kind: str, lead_id=None) -> dict:
    init()
    column = "phone_used" if kind == PHONE else "letter_used"
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE free_unlock_grants SET {column}=MAX(0,{column}-1) "
            "WHERE user_id=?",
            (int(user_id),),
        )
        conn.execute(
            "UPDATE free_unlock_events SET status='refunded' "
            "WHERE id = (SELECT id FROM free_unlock_events "
            "           WHERE user_id=? AND kind=? AND status='consumed' "
            "             AND (? IS NULL OR lead_id=?) "
            "           ORDER BY id DESC LIMIT 1)",
            (int(user_id), kind, lead_id, lead_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "refunded": kind}


def refund_phone(user_id: int, lead_id=None) -> dict:
    return _refund(user_id, PHONE, lead_id)


def refund_letter(user_id: int, lead_id=None) -> dict:
    return _refund(user_id, LETTER, lead_id)


def add_phone_cost(user_id: int, lead_id=None) -> dict:
    """Regista o custo Searchbug ($0,20) de um unlock gratuito de telefone."""
    init()
    cents = int(getattr(settings, "FREE_UNLOCKS_PHONE_COST_CENTS", 20) or 20)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE free_unlock_events SET cost_cents=? "
            "WHERE id = (SELECT id FROM free_unlock_events "
            "           WHERE user_id=? AND kind='phone' AND status='consumed' "
            "             AND (? IS NULL OR lead_id=?) "
            "           ORDER BY id DESC LIMIT 1)",
            (cents, int(user_id), lead_id, lead_id),
        )
        conn.execute(
            "INSERT INTO free_unlock_daily (day, phone_costs_cents) VALUES (?,?) "
            "ON CONFLICT(day) DO UPDATE SET phone_costs_cents=phone_costs_cents+?",
            (_today(), cents, cents),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "cost_cents": cents}


def status() -> dict:
    init()
    conn = get_connection()
    try:
        grants = conn.execute(
            "SELECT COUNT(*) c FROM free_unlock_grants"
        ).fetchone()["c"]
        today = _daily_grants(conn)
        cost = _month_cost_cents(conn)
    finally:
        conn.close()
    return {
        "enabled": enabled(),
        "grants_total": int(grants or 0),
        "grants_today": today,
        "daily_cap": int(getattr(settings, "FREE_UNLOCKS_DAILY_CAP", 25) or 25),
        "month_cost_cents": cost,
        "month_budget_cents": int(
            float(getattr(settings, "FREE_UNLOCKS_MONTHLY_BUDGET_USD", 75) or 75) * 100
        ),
    }
