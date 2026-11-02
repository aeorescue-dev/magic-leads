"""Prospeção B2B por voz — Fase 1.

Owns `voice.db`: fontes, empresas (pessoas jurídicas), checks DNC, supressões
e tentativas de chamada. Não lê nem escreve dados de homeowners e não toca em
`leads.db`.

O gate `can_call()` é fail-closed: sem check DNC fresco, sem telefone válido,
fora de Massachusetts ou com supressão interna, a empresa não entra na fila.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from ..config import settings

VERSION = "2026-11-02.1"
PILOT_STATES = ("MA", "NY", "TX", "IL")
DEFAULT_STATE = "MA"
CITY_ALIASES = {
    "NYC": "New York",
    "NEW YORK": "New York",
    "BOSTON": "Boston",
    "CHICAGO": "Chicago",
    "DALLAS": "Dallas",
}
STATE_TIMEZONES = {
    "MA": "America/New_York",
    "NY": "America/New_York",
    "TX": "America/Chicago",
    "IL": "America/Chicago",
}
CALL_TZ = ZoneInfo("America/New_York")
CALL_START_HOUR = 8
CALL_END_HOUR = 21
DNC_MAX_AGE_DAYS = 31
MAX_ATTEMPTS_7D = 3

OUTCOMES = {
    "connected",
    "voicemail",
    "no_answer",
    "busy",
    "wrong_number",
    "not_interested",
    "callback",
    "meeting_booked",
    "do_not_call",
}
SUPPRESS_OUTCOMES = {"wrong_number", "not_interested", "do_not_call"}

REASON_LABELS = {
    "not_business": "Não é pessoa jurídica",
    "invalid_phone": "Telefone inválido",
    "state_not_enabled": "Estado fora do piloto",
    "status_blocked": "Contacto bloqueado",
    "suppressed": "Supressão interna",
    "dnc_not_checked": "DNC não verificado",
    "dnc_stale": "DNC expirado",
    "dnc_listed": "Listado no DNC",
    "attempt_cap": "Limite de tentativas",
    "outside_hours": "Fora do horário",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prospect_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'ma_hic_csv',
  name TEXT,
  source_url TEXT,
  captured_at TEXT,
  imported_at TEXT NOT NULL,
  row_count INTEGER DEFAULT 0,
  checksum TEXT,
  imported_by INTEGER,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS prospect_companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER REFERENCES prospect_sources(id) ON DELETE SET NULL,
  company_name TEXT NOT NULL,
  contact_name TEXT,
  phone TEXT NOT NULL UNIQUE,
  email TEXT,
  website TEXT,
  city TEXT,
  state TEXT NOT NULL DEFAULT 'MA',
  zip_code TEXT,
  license_number TEXT,
  license_status TEXT,
  trade TEXT,
  permit_count INTEGER DEFAULT 0,
  permit_value_usd REAL DEFAULT 0,
  years_active INTEGER,
  employee_estimate INTEGER,
  entity_type TEXT NOT NULL DEFAULT 'business',
  consent_basis TEXT NOT NULL DEFAULT 'b2b_legit_interest',
  status TEXT NOT NULL DEFAULT 'ready',
  score INTEGER NOT NULL DEFAULT 0,
  last_attempt_at TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prospect_status ON prospect_companies (status, state, score DESC);
CREATE INDEX IF NOT EXISTS idx_prospect_city ON prospect_companies (city);
CREATE INDEX IF NOT EXISTS idx_prospect_license ON prospect_companies (license_number);

CREATE TABLE IF NOT EXISTS dnc_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phone TEXT NOT NULL UNIQUE,
  listed INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'manual',
  provider TEXT,
  checked_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  raw_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_dnc_expires ON dnc_checks (expires_at);

CREATE TABLE IF NOT EXISTS voice_suppressions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  value TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'phone',
  reason TEXT DEFAULT 'manual',
  created_at TEXT NOT NULL,
  UNIQUE(value, channel)
);

CREATE TABLE IF NOT EXISTS call_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES prospect_companies(id) ON DELETE CASCADE,
  user_id INTEGER,
  started_at TEXT NOT NULL,
  outcome TEXT NOT NULL,
  notes TEXT,
  callback_at TEXT,
  duration_seconds INTEGER,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_call_attempts_company ON call_attempts (company_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_call_attempts_at ON call_attempts (started_at);

CREATE TABLE IF NOT EXISTS voice_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL DEFAULT 'telnyx',
  provider_call_id TEXT UNIQUE,
  company_id INTEGER REFERENCES prospect_companies(id) ON DELETE CASCADE,
  campaign_id TEXT,
  script_id TEXT,
  city TEXT,
  trade_code TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  intent TEXT,
  showcase_link_id INTEGER,
  checkout_session_id TEXT,
  cost_cents INTEGER DEFAULT 0,
  started_at TEXT,
  ended_at TEXT,
  answered_at TEXT,
  duration_seconds INTEGER DEFAULT 0,
  listen_seconds INTEGER DEFAULT 0,
  hangup_cause TEXT,
  showcase_clicked_at TEXT,
  revenue_cents INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_voice_calls_company ON voice_calls (company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_voice_calls_provider ON voice_calls (provider_call_id);

CREATE TABLE IF NOT EXISTS voice_campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  city TEXT,
  trade TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  max_calls INTEGER NOT NULL DEFAULT 25,
  quota_total INTEGER NOT NULL DEFAULT 0,
  batch_size INTEGER NOT NULL DEFAULT 25,
  include_fallback INTEGER NOT NULL DEFAULT 1,
  dry_run INTEGER NOT NULL DEFAULT 0,
  calls_started INTEGER NOT NULL DEFAULT 0,
  showcases_sent INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  next_batch_at TEXT,
  created_by INTEGER,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_voice_campaigns_status
  ON voice_campaigns (status, created_at DESC);

CREATE TABLE IF NOT EXISTS voice_campaign_skips (
  campaign_id INTEGER NOT NULL,
  company_id INTEGER NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(campaign_id, company_id)
);

CREATE TABLE IF NOT EXISTS voice_segments (
  city_slug TEXT NOT NULL,
  trade_slug TEXT NOT NULL,
  city TEXT NOT NULL,
  state TEXT NOT NULL,
  trade_code TEXT NOT NULL,
  trade_label TEXT,
  total INTEGER NOT NULL DEFAULT 0,
  callable INTEGER NOT NULL DEFAULT 0,
  blocked INTEGER NOT NULL DEFAULT 0,
  showcase_mode TEXT NOT NULL DEFAULT 'no_showcase',
  showcase_exact INTEGER NOT NULL DEFAULT 0,
  showcase_city_total INTEGER NOT NULL DEFAULT 0,
  page_path TEXT,
  built_at TEXT NOT NULL,
  PRIMARY KEY (city_slug, trade_slug)
);

CREATE INDEX IF NOT EXISTS idx_voice_segments_mode
  ON voice_segments (showcase_mode, callable DESC);

CREATE TABLE IF NOT EXISTS voice_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'http_csv',
  url TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  config_json TEXT,
  last_sync_at TEXT,
  last_status TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_ingest (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER,
  checksum TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  row_count INTEGER DEFAULT 0,
  imported INTEGER DEFAULT 0,
  updated INTEGER DEFAULT 0,
  skipped INTEGER DEFAULT 0,
  error TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_raw_ingest_source
  ON raw_ingest (source_id, started_at DESC);

CREATE TABLE IF NOT EXISTS voice_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""

_LOCK = threading.Lock()
_INIT: dict[str, Optional[str]] = {"path": None}


def db_path() -> str:
    override = (os.getenv("VOICE_DB_PATH") or "").strip()
    if override:
        return override
    data_dir = (os.getenv("DATA_DIR") or "/data").strip()
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.getcwd(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "voice.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Migra tabelas antigas sem destruir dados."""
    campaign_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(voice_campaigns)")
    }
    for name, ddl in (
        ("quota_total", "INTEGER NOT NULL DEFAULT 0"),
        ("batch_size", "INTEGER NOT NULL DEFAULT 25"),
        ("include_fallback", "INTEGER NOT NULL DEFAULT 1"),
        ("dry_run", "INTEGER NOT NULL DEFAULT 0"),
        ("next_batch_at", "TEXT"),
    ):
        if name not in campaign_cols:
            conn.execute(f"ALTER TABLE voice_campaigns ADD COLUMN {name} {ddl}")

    call_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(voice_calls)")
    }
    for name, ddl in (
        ("answered_at", "TEXT"),
        ("duration_seconds", "INTEGER DEFAULT 0"),
        ("listen_seconds", "INTEGER DEFAULT 0"),
        ("hangup_cause", "TEXT"),
        ("showcase_clicked_at", "TEXT"),
        ("revenue_cents", "INTEGER DEFAULT 0"),
    ):
        if name not in call_cols:
            conn.execute(f"ALTER TABLE voice_calls ADD COLUMN {name} {ddl}")


def init() -> None:
    path = db_path()
    if _INIT["path"] == path:
        return
    with _LOCK:
        if _INIT["path"] == path:
            return
        conn = get_conn()
        try:
            conn.executescript(_SCHEMA)
            _ensure_columns(conn)
            conn.execute(
                "INSERT INTO voice_meta (key, value) VALUES ('version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (VERSION,),
            )
            conn.commit()
        finally:
            conn.close()
        _INIT["path"] = path


def _utc_now() -> datetime:
    # Permite congelar o relógio em testes/QA (ex.: VOICE_NOW_ISO).
    override = (os.getenv("VOICE_NOW_ISO") or "").strip()
    if override:
        parsed = parse_dt(override)
        if parsed is not None:
            return parsed
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _utc_now()).isoformat()


def parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize_phone(raw: Any) -> Optional[str]:
    text = re.split(r"(?:ext\.?|extension|x)\s*\d+", str(raw or ""), flags=re.I)[0]
    digits = re.sub(r"\D", "", text)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if 8 <= len(digits) <= 15:
        return "+" + digits
    return None


def _norm_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _pick(row: dict, aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = row.get(alias)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _parse_bool(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "sim", "listed", "s"}


def _score(
    permit_count: int, license_status: str, years_active: int, employees: int
) -> int:
    score = 20
    score += min(40, max(0, permit_count) * 4)
    if "active" in (license_status or "").lower():
        score += 15
    if years_active >= 5:
        score += 10
    if employees >= 5:
        score += 10
    return max(0, min(100, score))


def _rows_from_csv(csv_text: str) -> list[dict]:
    text = (csv_text or "").lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    for raw in reader:
        rows.append({_norm_header(key): value for key, value in raw.items()})
    return rows


def import_licenses_csv(
    csv_text: str,
    source_name: str = "MA HIC / licenças",
    source_url: str = "",
    imported_by: int = 0,
) -> dict:
    """Importa licenças/permits de MA. Dedupe por telefone E.164."""
    init()
    rows = _rows_from_csv(csv_text)
    if not rows:
        raise ValueError("CSV vazio ou sem cabeçalho")

    now = _iso()
    checksum = hashlib.sha256((csv_text or "").encode()).hexdigest()[:32]
    imported = updated = skipped = 0
    errors: list[dict] = []

    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO prospect_sources "
            "(kind, name, source_url, captured_at, imported_at, row_count, "
            "checksum, imported_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ma_hic_csv",
                source_name,
                source_url,
                now,
                now,
                len(rows),
                checksum,
                int(imported_by or 0),
            ),
        )
        source_id = int(cur.lastrowid)

        for index, row in enumerate(rows, start=2):
            company = _pick(
                row,
                (
                    "company_name",
                    "company",
                    "business_name",
                    "business",
                    "dba",
                    "contractor",
                    "name",
                ),
            )
            phone = normalize_phone(
                _pick(
                    row,
                    (
                        "phone",
                        "phone_number",
                        "telephone",
                        "tel",
                        "mobile",
                        "business_phone",
                    ),
                )
            )
            if not company or not phone:
                skipped += 1
                if len(errors) < 5:
                    errors.append(
                        {
                            "row": index,
                            "reason": "company_name/phone em falta",
                        }
                    )
                continue

            state = (_pick(row, ("state", "st")) or DEFAULT_STATE).upper()
            state = {
                "MASSACHUSETTS": "MA",
                "NEW YORK": "NY",
                "TEXAS": "TX",
                "ILLINOIS": "IL",
            }.get(state, state)
            raw_city = _pick(row, ("city", "city_town", "town", "municipality"))
            city_label = CITY_ALIASES.get(
                raw_city.strip().upper(), raw_city.strip().title()
            )
            license_status = _pick(row, ("license_status", "status", "license_state"))
            permit_count = _to_int(
                _pick(row, ("permit_count", "permits", "permit_total", "projects", "jobs"))
            )
            years_active = _to_int(
                _pick(row, ("years_active", "years", "company_age"))
            )
            employees = _to_int(
                _pick(row, ("employee_estimate", "employees", "headcount", "size"))
            )
            score = _score(permit_count, license_status, years_active, employees)
            entity_type = (
                _pick(row, ("entity_type", "entity_kind")) or "business"
            ).lower()
            if entity_type in {"llc", "inc", "corp", "corporation", "company", "b2b"}:
                entity_type = "business"

            existing = conn.execute(
                "SELECT id FROM prospect_companies WHERE phone=?", (phone,)
            ).fetchone()
            conn.execute(
                """
                INSERT INTO prospect_companies (
                  source_id, company_name, contact_name, phone, email, website,
                  city, state, zip_code, license_number, license_status, trade,
                  permit_count, permit_value_usd, years_active, employee_estimate,
                  entity_type, consent_basis, status, score, notes,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET
                  source_id=excluded.source_id,
                  company_name=excluded.company_name,
                  contact_name=COALESCE(NULLIF(excluded.contact_name, ''), prospect_companies.contact_name),
                  email=COALESCE(NULLIF(excluded.email, ''), prospect_companies.email),
                  website=COALESCE(NULLIF(excluded.website, ''), prospect_companies.website),
                  city=COALESCE(NULLIF(excluded.city, ''), prospect_companies.city),
                  state=excluded.state,
                  zip_code=COALESCE(NULLIF(excluded.zip_code, ''), prospect_companies.zip_code),
                  license_number=COALESCE(NULLIF(excluded.license_number, ''), prospect_companies.license_number),
                  license_status=COALESCE(NULLIF(excluded.license_status, ''), prospect_companies.license_status),
                  trade=COALESCE(NULLIF(excluded.trade, ''), prospect_companies.trade),
                  permit_count=MAX(prospect_companies.permit_count, excluded.permit_count),
                  permit_value_usd=MAX(prospect_companies.permit_value_usd, excluded.permit_value_usd),
                  years_active=MAX(COALESCE(prospect_companies.years_active, 0), COALESCE(excluded.years_active, 0)),
                  employee_estimate=MAX(COALESCE(prospect_companies.employee_estimate, 0), COALESCE(excluded.employee_estimate, 0)),
                  entity_type=excluded.entity_type,
                  consent_basis=excluded.consent_basis,
                  score=MAX(prospect_companies.score, excluded.score),
                  status=CASE
                    WHEN prospect_companies.status IN ('do_not_call', 'invalid')
                    THEN prospect_companies.status
                    ELSE 'ready'
                  END,
                  updated_at=excluded.updated_at
                """,
                (
                    source_id,
                    company,
                    _pick(row, ("contact_name", "contact", "owner", "owner_name", "manager")),
                    phone,
                    _pick(row, ("email", "email_address")),
                    _pick(row, ("website", "url", "site")),
                    city_label,
                    state,
                    _pick(row, ("zip_code", "zip", "postal_code")),
                    _pick(row, ("license_number", "license", "license_no", "license_id", "hic", "registration_number")),
                    license_status,
                    _pick(row, ("trade", "category", "service", "specialty")),
                    permit_count,
                    _to_float(_pick(row, ("permit_value_usd", "permit_value", "value", "obra_value"))),
                    years_active,
                    employees,
                    entity_type,
                    _pick(row, ("consent_basis",)) or "b2b_legit_interest",
                    score,
                    _pick(row, ("notes", "note", "comments")),
                    now,
                    now,
                ),
            )
            if existing:
                updated += 1
            else:
                imported += 1

        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "source_id": source_id,
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "total": len(rows),
        "errors": errors,
    }


def check_dnc(
    phone: str,
    listed: bool,
    source: str = "manual",
    provider: str = "manual",
    raw_status: str = "",
) -> dict:
    init()
    normalized = normalize_phone(phone)
    if not normalized:
        raise ValueError("telefone inválido")
    now = _utc_now()
    expires = now + timedelta(days=DNC_MAX_AGE_DAYS)
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO dnc_checks
              (phone, listed, source, provider, checked_at, expires_at, raw_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
              listed=excluded.listed,
              source=excluded.source,
              provider=excluded.provider,
              checked_at=excluded.checked_at,
              expires_at=excluded.expires_at,
              raw_status=excluded.raw_status
            """,
            (
                normalized,
                1 if listed else 0,
                source,
                provider,
                _iso(now),
                _iso(expires),
                raw_status or ("listed" if listed else "clear"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "phone": normalized,
        "listed": bool(listed),
        "checked_at": _iso(now),
        "expires_at": _iso(expires),
    }


def import_dnc_csv(csv_text: str, source: str = "import") -> dict:
    """Importa uma lista DNC (phone, listed[, source])."""
    init()
    rows = _rows_from_csv(csv_text)
    if not rows:
        raise ValueError("CSV vazio ou sem cabeçalho")
    imported = skipped = listed_count = 0
    now = _utc_now()
    expires = now + timedelta(days=DNC_MAX_AGE_DAYS)
    conn = get_conn()
    try:
        for row in rows:
            phone = normalize_phone(_pick(row, ("phone", "phone_number", "telephone", "number")))
            if not phone:
                skipped += 1
                continue
            raw_listed = _pick(row, ("listed", "dnc", "is_listed", "status"))
            listed = _parse_bool(raw_listed)
            conn.execute(
                """
                INSERT INTO dnc_checks
                  (phone, listed, source, provider, checked_at, expires_at, raw_status)
                VALUES (?, ?, ?, 'csv', ?, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET
                  listed=excluded.listed,
                  source=excluded.source,
                  provider=excluded.provider,
                  checked_at=excluded.checked_at,
                  expires_at=excluded.expires_at,
                  raw_status=excluded.raw_status
                """,
                (
                    phone,
                    1 if listed else 0,
                    _pick(row, ("source", "list_source")) or source,
                    _iso(now),
                    _iso(expires),
                    raw_listed or ("listed" if listed else "clear"),
                ),
            )
            imported += 1
            if listed:
                listed_count += 1
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "listed": listed_count,
        "total": len(rows),
    }


def suppress(phone: str, reason: str = "manual") -> dict:
    init()
    normalized = normalize_phone(phone)
    if not normalized:
        raise ValueError("telefone inválido")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO voice_suppressions (value, channel, reason, created_at) "
            "VALUES (?, 'phone', ?, ?) "
            "ON CONFLICT(value, channel) DO UPDATE SET reason=excluded.reason",
            (normalized, reason, _iso()),
        )
        conn.execute(
            "UPDATE prospect_companies SET status='do_not_call', updated_at=? "
            "WHERE phone=? AND status<>'do_not_call'",
            (_iso(), normalized),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "phone": normalized, "reason": reason}


def _company_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _state_tz(state: str) -> ZoneInfo:
    return ZoneInfo(STATE_TIMEZONES.get((state or "").upper(), "America/New_York"))


def _eligibility(
    company: dict, conn: sqlite3.Connection, now: datetime
) -> dict:
    reasons: list[str] = []
    checks: dict[str, bool] = {}

    phone = str(company.get("phone") or "")
    checks["phone_valid"] = bool(re.match(r"^\+1\d{10}$", phone))
    if not checks["phone_valid"]:
        reasons.append("invalid_phone")

    checks["business"] = (company.get("entity_type") or "business") == "business"
    if not checks["business"]:
        reasons.append("not_business")

    checks["state_enabled"] = (company.get("state") or "").upper() in PILOT_STATES
    if not checks["state_enabled"]:
        reasons.append("state_not_enabled")

    checks["status_ready"] = company.get("status") not in (
        "do_not_call",
        "invalid",
        "meeting",
    )
    if not checks["status_ready"]:
        reasons.append("status_blocked")

    suppressed = conn.execute(
        "SELECT 1 FROM voice_suppressions WHERE value=? AND channel='phone'",
        (phone,),
    ).fetchone()
    checks["not_suppressed"] = suppressed is None
    if suppressed:
        reasons.append("suppressed")

    dnc = conn.execute(
        "SELECT listed, expires_at, source FROM dnc_checks WHERE phone=?", (phone,)
    ).fetchone()
    if dnc is None:
        checks["dnc_checked"] = False
        checks["dnc_fresh"] = False
        checks["dnc_clear"] = False
        reasons.append("dnc_not_checked")
    else:
        expires = parse_dt(dnc["expires_at"])
        checks["dnc_checked"] = True
        checks["dnc_fresh"] = bool(expires and expires > now)
        checks["dnc_clear"] = int(dnc["listed"] or 0) == 0
        if not checks["dnc_fresh"]:
            reasons.append("dnc_stale")
        if not checks["dnc_clear"]:
            reasons.append("dnc_listed")

    since = (now - timedelta(days=7)).isoformat()
    attempts = int(
        conn.execute(
            "SELECT COUNT(*) FROM call_attempts "
            "WHERE company_id=? AND started_at>=?",
            (company.get("id"), since),
        ).fetchone()[0]
        or 0
    )
    checks["attempts_ok"] = attempts < MAX_ATTEMPTS_7D
    if not checks["attempts_ok"]:
        reasons.append("attempt_cap")

    local = now.astimezone(_state_tz(company.get("state") or ""))
    checks["within_hours"] = CALL_START_HOUR <= local.hour < CALL_END_HOUR
    if not checks["within_hours"]:
        reasons.append("outside_hours")

    return {
        "allowed": not reasons,
        "reasons": reasons,
        "reason_labels": [REASON_LABELS.get(code, code) for code in reasons],
        "checks": checks,
        "local_time": local.strftime("%Y-%m-%d %H:%M %Z"),
    }


def can_call(company: dict, now: Optional[datetime] = None) -> dict:
    """Fail-closed. Recebe a empresa (dict) e devolve allowed + reasons."""
    init()
    reference = now or _utc_now()
    conn = get_conn()
    try:
        return _eligibility(company, conn, reference)
    finally:
        conn.close()


def queue(
    limit: int = 50,
    include_blocked: bool = False,
    city: str = "",
    trade: str = "",
    state: str = "",
) -> dict:
    init()
    now = _utc_now()
    where: list[str] = []
    params: list[Any] = []
    if city.strip():
        where.append("UPPER(TRIM(city))=UPPER(?)")
        params.append(city.strip())
    if state.strip():
        where.append("UPPER(TRIM(state))=UPPER(?)")
        params.append(state.strip())
    if trade.strip():
        where.append("LOWER(TRIM(COALESCE(trade,''))) = LOWER(?)")
        params.append(trade.strip())
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = get_conn()
    try:
        rows = conn.execute(
            f"SELECT * FROM prospect_companies{clause} "
            "ORDER BY score DESC, permit_count DESC, id ASC LIMIT ?",
            (*params, max(1, min(1000, int(limit)))),
        ).fetchall()
        items = []
        callable_count = 0
        for row in rows:
            company = _company_dict(row)
            eligibility = _eligibility(company, conn, now)
            if eligibility["allowed"]:
                callable_count += 1
            if include_blocked or eligibility["allowed"]:
                items.append({**company, "eligibility": eligibility})
        total = int(
            conn.execute(
                f"SELECT COUNT(*) FROM prospect_companies{clause}", tuple(params)
            ).fetchone()[0]
            or 0
        )
        return {
            "items": items,
            "generated_at": _iso(now),
            "limit": limit,
            "total": total,
            "callable": callable_count,
            "include_blocked": include_blocked,
            "filters": {
                "city": city,
                "trade": trade,
                "state": state,
            },
        }
    finally:
        conn.close()


def stats() -> dict:
    init()
    now = _utc_now()
    conn = get_conn()
    try:
        total = int(
            conn.execute("SELECT COUNT(*) FROM prospect_companies").fetchone()[0] or 0
        )
        callable_count = 0
        by_city: dict[str, dict] = {}
        by_trade: dict[str, dict] = {}
        for row in conn.execute("SELECT * FROM prospect_companies").fetchall():
            company = _company_dict(row)
            allowed = _eligibility(company, conn, now)["allowed"]
            if allowed:
                callable_count += 1
            city = (company.get("city") or "—").strip() or "—"
            trade = (company.get("trade") or "—").strip() or "—"
            for bucket, key in ((by_city, city), (by_trade, trade)):
                entry = bucket.setdefault(
                    key, {"name": key, "total": 0, "callable": 0, "blocked": 0}
                )
                entry["total"] += 1
                if allowed:
                    entry["callable"] += 1
                else:
                    entry["blocked"] += 1
        today = now.date().isoformat()
        attempts_today = int(
            conn.execute(
                "SELECT COUNT(*) FROM call_attempts WHERE substr(started_at, 1, 10)=?",
                (today,),
            ).fetchone()[0]
            or 0
        )
        meetings = int(
            conn.execute(
                "SELECT COUNT(*) FROM prospect_companies WHERE status='meeting'"
            ).fetchone()[0]
            or 0
        )
        dnc_listed = int(
            conn.execute("SELECT COUNT(*) FROM dnc_checks WHERE listed=1").fetchone()[0]
            or 0
        )
        suppressed = int(
            conn.execute(
                "SELECT COUNT(*) FROM voice_suppressions WHERE channel='phone'"
            ).fetchone()[0]
            or 0
        )
        checked = int(
            conn.execute("SELECT COUNT(*) FROM dnc_checks").fetchone()[0] or 0
        )
        campaigns = [
            dict(r)
            for r in conn.execute(
                "SELECT campaign_id, COUNT(*) calls, "
                "SUM(CASE WHEN showcase_link_id IS NOT NULL THEN 1 ELSE 0 END) showcases, "
                "SUM(CASE WHEN intent='showcase' THEN 1 ELSE 0 END) intents "
                "FROM voice_calls WHERE COALESCE(campaign_id,'')<>'' "
                "GROUP BY campaign_id ORDER BY calls DESC LIMIT 20"
            ).fetchall()
        ]
        return {
            "total": total,
            "callable": callable_count,
            "blocked": max(0, total - callable_count),
            "attempts_today": attempts_today,
            "meetings": meetings,
            "dnc_listed": dnc_listed,
            "dnc_checked": checked,
            "suppressed": suppressed,
            "generated_at": _iso(now),
            "pilot_state": ", ".join(PILOT_STATES),
            "pilot_states": list(PILOT_STATES),
            "calling_window": f"{CALL_START_HOUR:02d}:00–{CALL_END_HOUR:02d}:00 local (ET/CT)",
            "dnc_max_age_days": DNC_MAX_AGE_DAYS,
            "max_attempts_7d": MAX_ATTEMPTS_7D,
            "by_city": sorted(by_city.values(), key=lambda x: x["total"], reverse=True),
            "by_trade": sorted(by_trade.values(), key=lambda x: x["total"], reverse=True),
            "campaigns": campaigns,
        }
    finally:
        conn.close()


def segments(city: str = "", trade: str = "", state: str = "") -> list[dict]:
    """Agrupa empresas por cidade + nicho e qualifica a vitrine disponível."""
    from . import showcase

    init()
    now = _utc_now()
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM prospect_companies").fetchall()
        groups: dict[tuple[str, str, str], dict] = {}
        for row in rows:
            company = _company_dict(row)
            company_city = (company.get("city") or "—").strip() or "—"
            company_state = (company.get("state") or "").strip().upper()
            company_trade = (company.get("trade") or "—").strip() or "—"
            if city.strip() and company_city.lower() != city.strip().lower():
                continue
            if state.strip() and company_state != state.strip().upper():
                continue
            if trade.strip() and company_trade.lower() != trade.strip().lower():
                continue
            key = (company_city, company_state, company_trade)
            group = groups.setdefault(
                key,
                {
                    "city": company_city,
                    "state": company_state,
                    "trade": company_trade,
                    "total": 0,
                    "callable": 0,
                    "blocked": 0,
                },
            )
            allowed = _eligibility(company, conn, now)["allowed"]
            group["total"] += 1
            if allowed:
                group["callable"] += 1
            else:
                group["blocked"] += 1
    finally:
        conn.close()

    for group in groups.values():
        trade_code = showcase.normalize_trade(group["trade"])
        available = showcase.available(
            group["city"], trade_code or group["trade"]
        )
        if available["available"]:
            mode = "dedicated"
        elif available["city_total"] >= available["min_items"]:
            mode = "city_fallback"
        else:
            mode = "no_showcase"
        group["showcase_mode"] = mode
        group["showcase_exact"] = available["exact_count"]
        group["showcase_city_total"] = available["city_total"]
        group["page_path"] = available["page_path"]
    return sorted(
        groups.values(),
        key=lambda item: (item["callable"], item["total"]),
        reverse=True,
    )


def create_campaign(
    name: str,
    city: str = "",
    trade: str = "",
    max_calls: int = 25,
    created_by: int = 0,
    quota_total: Optional[int] = None,
    batch_size: Optional[int] = None,
    include_fallback: bool = True,
    dry_run: bool = False,
) -> dict:
    init()
    now = _iso()
    quota = max(1, min(10000, int(quota_total if quota_total is not None else max_calls)))
    batch = max(1, min(quota, int(batch_size or quota)))
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO voice_campaigns "
            "(name, city, trade, status, max_calls, quota_total, batch_size, "
            "include_fallback, dry_run, created_by, created_at, started_at) "
            "VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                city,
                trade,
                quota,
                quota,
                batch,
                1 if include_fallback else 0,
                1 if dry_run else 0,
                int(created_by or 0),
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM voice_campaigns WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_campaign(campaign_id: int) -> Optional[dict]:
    init()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM voice_campaigns WHERE id=?", (int(campaign_id),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_campaigns(limit: int = 20) -> list[dict]:
    init()
    conn = get_conn()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM voice_campaigns ORDER BY id DESC LIMIT ?",
                (max(1, min(100, int(limit))),),
            ).fetchall()
        ]
    finally:
        conn.close()


def update_campaign(campaign_id: int, **fields: Any) -> Optional[dict]:
    init()
    allowed = {
        "status",
        "error",
        "finished_at",
        "max_calls",
        "quota_total",
        "batch_size",
        "include_fallback",
        "dry_run",
        "next_batch_at",
        "name",
        "city",
        "trade",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return get_campaign(campaign_id)
    conn = get_conn()
    try:
        sets = ", ".join(f"{key}=?" for key in updates)
        conn.execute(
            f"UPDATE voice_campaigns SET {sets} WHERE id=?",
            (*updates.values(), int(campaign_id)),
        )
        conn.commit()
    finally:
        conn.close()
    return get_campaign(campaign_id)


def bump_campaign(
    campaign_id: int,
    calls_started: int = 0,
    showcases_sent: int = 0,
    skipped: int = 0,
) -> None:
    init()
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE voice_campaigns SET "
            "calls_started=calls_started+?, "
            "showcases_sent=showcases_sent+?, "
            "skipped=skipped+? WHERE id=?",
            (
                int(calls_started),
                int(showcases_sent),
                int(skipped),
                int(campaign_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def stop_campaign(campaign_id: int) -> Optional[dict]:
    return update_campaign(
        campaign_id, status="stopped", finished_at=_iso()
    )


def mark_interrupted_campaigns(self_reason: str = "campanha interrompida (processo reiniciado)") -> int:
    init()
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE voice_campaigns SET status='error', error=?, finished_at=? "
            "WHERE status='running'",
            (self_reason, _iso()),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def skip_campaign_company(campaign_id: int, company_id: int, reason: str = "") -> None:
    init()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO voice_campaign_skips "
            "(campaign_id, company_id, reason, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, company_id) DO UPDATE SET reason=excluded.reason",
            (int(campaign_id), int(company_id), reason[:300], _iso()),
        )
        conn.commit()
    finally:
        conn.close()


def campaign_candidates(
    campaign_id: int,
    city: str = "",
    trade: str = "",
    limit: int = 50,
    include_fallback: bool = True,
) -> list[dict]:
    init()
    where = ["status NOT IN ('do_not_call', 'invalid', 'meeting')"]
    params: list[Any] = []
    if city.strip():
        where.append("UPPER(TRIM(city))=UPPER(?)")
        params.append(city.strip())
    if trade.strip():
        where.append("LOWER(TRIM(COALESCE(trade,'')))=LOWER(?)")
        params.append(trade.strip())
    where.append(
        "id NOT IN (SELECT company_id FROM voice_calls WHERE campaign_id=?)"
    )
    params.append(str(int(campaign_id)))
    where.append(
        "id NOT IN (SELECT company_id FROM voice_campaign_skips WHERE campaign_id=?)"
    )
    params.append(int(campaign_id))
    conn = get_conn()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM prospect_companies WHERE {' AND '.join(where)} "
                "ORDER BY score DESC, permit_count DESC, id ASC LIMIT ?",
                (*params, max(1, min(1000, int(limit)))),
            ).fetchall()
        ]
        if not include_fallback and rows:
            from . import showcase

            dedicated = {
                (row["city_slug"], row["trade_slug"])
                for row in conn.execute(
                    "SELECT city_slug, trade_slug FROM voice_segments "
                    "WHERE showcase_mode='dedicated'"
                ).fetchall()
            }
            filtered = []
            for row in rows:
                city_slug = showcase.normalize_city_slug(row.get("city"))
                trade_code = showcase.normalize_trade(row.get("trade")) or row.get(
                    "trade"
                )
                trade_slug = showcase.slugify(trade_code)
                if (city_slug, trade_slug) in dedicated:
                    filtered.append(row)
            rows = filtered
        return rows
    finally:
        conn.close()


def rebuild_segments() -> int:
    """Materializa voice_segments a partir do estoque e da vitrine disponível."""
    from . import showcase

    items = segments()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM voice_segments")
        for item in items:
            trade_code = showcase.normalize_trade(item["trade"]) or item["trade"]
            city_slug = showcase.normalize_city_slug(item["city"])
            trade_slug = showcase.slugify(trade_code)
            conn.execute(
                """
                INSERT INTO voice_segments
                  (city_slug, trade_slug, city, state, trade_code, trade_label,
                   total, callable, blocked, showcase_mode, showcase_exact,
                   showcase_city_total, page_path, built_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(city_slug, trade_slug) DO UPDATE SET
                  city=excluded.city,
                  state=excluded.state,
                  trade_code=excluded.trade_code,
                  trade_label=excluded.trade_label,
                  total=excluded.total,
                  callable=excluded.callable,
                  blocked=excluded.blocked,
                  showcase_mode=excluded.showcase_mode,
                  showcase_exact=excluded.showcase_exact,
                  showcase_city_total=excluded.showcase_city_total,
                  page_path=excluded.page_path,
                  built_at=excluded.built_at
                """,
                (
                    city_slug,
                    trade_slug,
                    item["city"],
                    item["state"],
                    trade_code,
                    showcase.trade_label(trade_code),
                    item["total"],
                    item["callable"],
                    item["blocked"],
                    item["showcase_mode"],
                    item["showcase_exact"],
                    item["showcase_city_total"],
                    item["page_path"],
                    _iso(),
                ),
            )
        conn.commit()
        return len(items)
    finally:
        conn.close()


def cached_segments(
    city: str = "", trade: str = "", state: str = ""
) -> list[dict]:
    """Lê voice_segments; reconstrói se ainda não existir."""
    init()
    conn = get_conn()
    try:
        count = int(
            conn.execute("SELECT COUNT(*) FROM voice_segments").fetchone()[0] or 0
        )
    finally:
        conn.close()
    if count == 0:
        rebuild_segments()
    where = []
    params: list[Any] = []
    if city.strip():
        where.append("UPPER(city)=UPPER(?)")
        params.append(city.strip())
    if state.strip():
        where.append("UPPER(state)=UPPER(?)")
        params.append(state.strip())
    if trade.strip():
        where.append(
            "(LOWER(trade_code)=LOWER(?) OR LOWER(trade_label)=LOWER(?))"
        )
        params.extend([trade.strip(), trade.strip()])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = get_conn()
    try:
        rows = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM voice_segments{clause} "
                "ORDER BY callable DESC, total DESC",
                tuple(params),
            ).fetchall()
        ]
    finally:
        conn.close()
    for row in rows:
        row["trade"] = row.get("trade_label") or row.get("trade_code")
    return rows


def create_source(
    name: str,
    kind: str,
    url: str = "",
    enabled: bool = True,
    config: Optional[dict] = None,
) -> dict:
    import json

    init()
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO voice_sources "
            "(name, kind, url, enabled, config_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                name,
                kind,
                url,
                1 if enabled else 0,
                json.dumps(config or {}, ensure_ascii=False),
                _iso(),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM voice_sources WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_sources() -> list[dict]:
    init()
    conn = get_conn()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM voice_sources ORDER BY id DESC"
            ).fetchall()
        ]
    finally:
        conn.close()


def get_source(source_id: int) -> Optional[dict]:
    init()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM voice_sources WHERE id=?", (int(source_id),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _source_url_allowed(url: str) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    allowed = {
        item.strip().lower()
        for item in str(settings.VOICE_SOURCE_ALLOWED_HOSTS or "").split(",")
        if item.strip()
    }
    return parsed.scheme == "https" and bool(host) and host in allowed


def sync_source(source_id: int) -> dict:
    """Sincroniza uma fonte http_csv: fetch -> import -> rebuild -> segmentos."""
    from . import showcase

    init()
    source = get_source(source_id)
    if not source:
        raise ValueError("fonte não encontrada")
    started = _iso()
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO raw_ingest (source_id, status, started_at) "
            "VALUES (?, 'running', ?)",
            (int(source_id), started),
        )
        ingest_id = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()

    try:
        kind = source.get("kind")
        if kind == "http_csv":
            url = str(source.get("url") or "")
            if not _source_url_allowed(url):
                raise ValueError("host não autorizado em VOICE_SOURCE_ALLOWED_HOSTS")
            response = httpx.get(url, timeout=30, follow_redirects=True)
            response.raise_for_status()
            text = response.text
            checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
            imported = import_licenses_csv(
                text,
                source_name=str(source.get("name") or "source"),
                source_url=url,
                imported_by=0,
            )
        elif kind == "contractor_entities":
            imported = bridge_contractor_entities()
            checksum = ""
        else:
            raise ValueError(f"kind não suportado: {kind}")
        built = showcase.build_pages()
        rebuilt = rebuild_segments()
        finished = _iso()
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE raw_ingest SET checksum=?, status='success', row_count=?, "
                "imported=?, updated=?, skipped=?, finished_at=? WHERE id=?",
                (
                    checksum,
                    imported["total"],
                    imported["imported"],
                    imported["updated"],
                    imported["skipped"],
                    finished,
                    ingest_id,
                ),
            )
            conn.execute(
                "UPDATE voice_sources SET last_sync_at=?, last_status='success', "
                "last_error=NULL WHERE id=?",
                (finished, int(source_id)),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "ok": True,
            "source_id": int(source_id),
            "ingest_id": ingest_id,
            "import": imported,
            "showcase": built,
            "segments": rebuilt,
        }
    except Exception as exc:  # noqa: BLE001
        message = str(exc)[:300]
        finished = _iso()
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE raw_ingest SET status='error', error=?, finished_at=? "
                "WHERE id=?",
                (message, finished, ingest_id),
            )
            conn.execute(
                "UPDATE voice_sources SET last_sync_at=?, last_status='error', "
                "last_error=? WHERE id=?",
                (finished, message, int(source_id)),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "ok": False,
            "source_id": int(source_id),
            "ingest_id": ingest_id,
            "error": message,
        }


def sync_enabled_sources() -> dict:
    results = []
    for source in list_sources():
        if int(source.get("enabled") or 0) != 1:
            continue
        results.append(sync_source(int(source["id"])))
    return {"ok": all(item.get("ok") for item in results), "results": results}


def _rate(numerator: int, denominator: int) -> float:
    return round((numerator * 100.0 / denominator), 1) if denominator else 0.0


def metrics(days: int = 30, city: str = "", trade: str = "") -> dict:
    """Métricas de funil por período, cidade e nicho (instrumentação Fase 2)."""
    init()
    from . import showcase

    days = max(1, min(365, int(days)))
    since = (_utc_now() - timedelta(days=days)).isoformat()
    city_filter = city.strip()
    trade_code = showcase.normalize_trade(trade) if trade.strip() else ""
    where = ["datetime(COALESCE(v.created_at, v.started_at)) >= datetime(?)"]
    params: list[Any] = [since]
    if city_filter:
        where.append("UPPER(TRIM(COALESCE(v.city, c.city)))=UPPER(?)")
        params.append(city_filter)
    if trade_code:
        where.append("LOWER(COALESCE(v.trade_code, c.trade))=LOWER(?)")
        params.append(trade_code)
    clause = " WHERE " + " AND ".join(where)
    conn = get_conn()
    try:
        row = conn.execute(
            f"""
            SELECT
              COUNT(*) dialed,
              SUM(CASE WHEN v.answered_at IS NOT NULL THEN 1 ELSE 0 END) answered,
              SUM(CASE WHEN v.answered_at IS NULL THEN 1 ELSE 0 END) unanswered,
              AVG(CASE WHEN v.answered_at IS NOT NULL
                       THEN v.listen_seconds END) avg_listen,
              SUM(CASE WHEN v.answered_at IS NOT NULL AND v.listen_seconds >= 30
                       THEN 1 ELSE 0 END) engaged,
              SUM(CASE WHEN v.answered_at IS NOT NULL AND v.listen_seconds >= 15
                       THEN 1 ELSE 0 END) ge15,
              SUM(CASE WHEN v.answered_at IS NOT NULL AND v.listen_seconds >= 30
                       THEN 1 ELSE 0 END) ge30,
              SUM(CASE WHEN v.answered_at IS NOT NULL AND v.listen_seconds >= 60
                       THEN 1 ELSE 0 END) ge60,
              SUM(CASE WHEN v.answered_at IS NOT NULL AND v.listen_seconds >= 90
                       THEN 1 ELSE 0 END) ge90,
              SUM(CASE WHEN v.showcase_clicked_at IS NOT NULL THEN 1 ELSE 0 END) clicks,
              SUM(CASE WHEN v.checkout_session_id IS NOT NULL THEN 1 ELSE 0 END) checkouts,
              COALESCE(SUM(v.revenue_cents),0) revenue_cents,
              COALESCE(SUM(v.cost_cents),0) cost_cents
            FROM voice_calls v
            LEFT JOIN prospect_companies c ON c.id = v.company_id
            {clause}
            """,
            tuple(params),
        ).fetchone()
        summary = dict(row) if row else {}
        for key in ("answered", "unanswered", "engaged", "clicks", "checkouts"):
            summary[key] = int(summary.get(key) or 0)
        dialed = int(summary.get("dialed") or 0)
        answered = int(summary.get("answered") or 0)
        engaged = int(summary.get("engaged") or 0)
        clicks = int(summary.get("clicks") or 0)
        checkouts = int(summary.get("checkouts") or 0)
        revenue = int(summary.get("revenue_cents") or 0)
        cost = int(summary.get("cost_cents") or 0)
        summary.update(
            {
                "answer_rate": _rate(answered, dialed),
                "drop_rate": _rate(dialed - answered, dialed),
                "engagement_rate": _rate(engaged, answered),
                "showcase_ctr": _rate(clicks, answered),
                "checkout_rate": _rate(checkouts, clicks),
                "avg_listen_seconds": round(float(summary.get("avg_listen") or 0), 1),
                "revenue_usd": round(revenue / 100.0, 2),
                "cost_usd": round(cost / 100.0, 2),
                "net_usd": round((revenue - cost) / 100.0, 2),
            }
        )
        retention = [
            {
                "seconds": seconds,
                "count": int(summary.get(key) or 0),
                "pct_of_answered": _rate(int(summary.get(key) or 0), answered),
            }
            for seconds, key in ((15, "ge15"), (30, "ge30"), (60, "ge60"), (90, "ge90"))
        ]

        groups = [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT
                  COALESCE(v.city, c.city, '—') city,
                  COALESCE(v.trade_code, c.trade, '—') trade,
                  COUNT(*) dialed,
                  SUM(CASE WHEN v.answered_at IS NOT NULL THEN 1 ELSE 0 END) answered,
                  SUM(CASE WHEN v.answered_at IS NOT NULL AND v.listen_seconds >= 30
                           THEN 1 ELSE 0 END) engaged,
                  AVG(CASE WHEN v.answered_at IS NOT NULL
                           THEN v.listen_seconds END) avg_listen,
                  SUM(CASE WHEN v.showcase_clicked_at IS NOT NULL THEN 1 ELSE 0 END) clicks,
                  SUM(CASE WHEN v.checkout_session_id IS NOT NULL THEN 1 ELSE 0 END) checkouts,
                  COALESCE(SUM(v.revenue_cents),0) revenue_cents,
                  COALESCE(SUM(v.cost_cents),0) cost_cents
                FROM voice_calls v
                LEFT JOIN prospect_companies c ON c.id = v.company_id
                {clause}
                GROUP BY 1, 2
                ORDER BY revenue_cents DESC, dialed DESC
                """,
                tuple(params),
            ).fetchall()
        ]
        for group in groups:
            gd = int(group.get("dialed") or 0)
            ga = int(group.get("answered") or 0)
            gc = int(group.get("clicks") or 0)
            gco = int(group.get("checkouts") or 0)
            grev = int(group.get("revenue_cents") or 0)
            gcost = int(group.get("cost_cents") or 0)
            group.update(
                {
                    "answer_rate": _rate(ga, gd),
                    "engagement_rate": _rate(
                        int(group.get("engaged") or 0), ga
                    ),
                    "showcase_ctr": _rate(gc, ga),
                    "checkout_rate": _rate(gco, gc),
                    "avg_listen_seconds": round(
                        float(group.get("avg_listen") or 0), 1
                    ),
                    "revenue_usd": round(grev / 100.0, 2),
                    "cost_usd": round(gcost / 100.0, 2),
                    "net_usd": round((grev - gcost) / 100.0, 2),
                }
            )
        return {
            "days": days,
            "generated_at": _iso(),
            "summary": summary,
            "retention": retention,
            "funnel": {
                "dialed": dialed,
                "answered": answered,
                "engaged": engaged,
                "clicks": clicks,
                "checkouts": checkouts,
                "revenue_usd": round(revenue / 100.0, 2),
            },
            "by_city_trade": groups,
        }
    finally:
        conn.close()


def paused_campaigns_due(now: Optional[datetime] = None) -> list[int]:
    init()
    reference = (now or _utc_now()).isoformat()
    conn = get_conn()
    try:
        return [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM voice_campaigns WHERE status='paused' "
                "AND next_batch_at IS NOT NULL "
                "AND datetime(next_batch_at) <= datetime(?)",
                (reference,),
            ).fetchall()
        ]
    finally:
        conn.close()


def ensure_builtin_source(name: str, kind: str) -> dict:
    for source in list_sources():
        if (source.get("kind") or "") == kind:
            return source
    return create_source(name, kind, "", True)


def _infer_trade(name: str, niche_key: str = "") -> str:
    from . import showcase

    raw = (niche_key or "").strip().lower()
    mapping = {
        "general_contractors": "general_contractor",
        "restoration": "remediation",
    }
    if raw:
        code = mapping.get(raw, raw)
        if showcase.normalize_trade(code):
            return code
    lowered = (name or "").lower()
    keywords = (
        ("elevator", "elevator"),
        ("sign", "signage"),
        ("electric", "electrical"),
        ("air condition", "hvac"),
        ("heating", "hvac"),
        ("hvac", "hvac"),
        ("roof", "roofing"),
        ("plumb", "plumbing"),
        ("paint", "painting"),
        ("landscap", "landscaping"),
        ("lawn", "landscaping"),
        ("pest", "pest_control"),
        ("debris", "debris_removal"),
        ("clean", "cleaning"),
        ("window", "windows"),
        ("door", "windows"),
        ("restor", "remediation"),
        ("remodel", "remodeling"),
        ("construction", "remodeling"),
        ("builder", "remodeling"),
        ("builders", "remodeling"),
    )
    for token, code in keywords:
        if token in lowered:
            return code
    return "general_contractor"


def bridge_contractor_entities(limit: int = 20000) -> dict:
    """Converte contractor_entities (licenças já ingeridas) em prospect_companies."""
    import csv as _csv

    from .db import get_connection as get_leads_connection
    from .showcase import CITY_CANON

    leads = get_leads_connection()
    try:
        rows = leads.execute(
            "SELECT legal_name, city, state, phone, email, license, niche_key, "
            "status, quarantine_reason FROM contractor_entities "
            "WHERE COALESCE(TRIM(phone),'')<>'' AND state IN ('MA','NY','TX','IL') "
            "AND COALESCE(quarantine_reason,'')='' "
            "ORDER BY id DESC LIMIT ?",
            (max(1, min(50000, int(limit))),),
        ).fetchall()
    finally:
        leads.close()

    output = io.StringIO()
    writer = _csv.writer(output)
    writer.writerow(
        [
            "company_name",
            "phone",
            "email",
            "city",
            "state",
            "license_number",
            "license_status",
            "trade",
            "notes",
        ]
    )
    used = 0
    for row in rows:
        phone = normalize_phone(row["phone"])
        name = str(row["legal_name"] or "").strip()
        city_raw = str(row["city"] or "").strip()
        if not phone or not name or not city_raw:
            continue
        city = CITY_CANON.get(city_raw.upper(), city_raw.title())
        trade = _infer_trade(name, str(row["niche_key"] or ""))
        writer.writerow(
            [
                name,
                phone,
                str(row["email"] or "").strip(),
                city,
                str(row["state"] or "").strip().upper(),
                str(row["license"] or "").strip(),
                "active",
                trade,
                "contractor_entities",
            ]
        )
        used += 1
    if used == 0:
        return {
            "ok": True,
            "total": 0,
            "imported": 0,
            "updated": 0,
            "skipped": 0,
            "source_id": None,
        }
    result = import_licenses_csv(
        output.getvalue(),
        source_name="Contractor entities (licenças)",
        source_url="",
        imported_by=0,
    )
    result["ok"] = True
    return result


def get_company(company_id: int) -> Optional[dict]:
    init()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM prospect_companies WHERE id=?", (int(company_id),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_voice_call(
    company: dict,
    provider: str = "telnyx",
    campaign_id: str = "",
    script_id: str = "",
    city: Optional[str] = None,
    trade_code: Optional[str] = None,
) -> dict:
    init()
    now = _iso()
    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO voice_calls
              (provider, company_id, campaign_id, script_id, city, trade_code,
               status, started_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                provider,
                int(company["id"]),
                campaign_id,
                script_id,
                city or company.get("city"),
                trade_code or company.get("trade"),
                now,
                now,
            ),
        )
        conn.commit()
        call_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM voice_calls WHERE id=?", (call_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_voice_call(voice_call_id: int, **fields: Any) -> Optional[dict]:
    init()
    allowed = {
        "provider_call_id",
        "status",
        "intent",
        "showcase_link_id",
        "checkout_session_id",
        "cost_cents",
        "started_at",
        "ended_at",
        "answered_at",
        "duration_seconds",
        "listen_seconds",
        "hangup_cause",
        "showcase_clicked_at",
        "revenue_cents",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return get_voice_call(voice_call_id)
    conn = get_conn()
    try:
        sets = ", ".join(f"{key}=?" for key in updates)
        conn.execute(
            f"UPDATE voice_calls SET {sets} WHERE id=?",
            (*updates.values(), int(voice_call_id)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM voice_calls WHERE id=?", (int(voice_call_id),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_voice_call(voice_call_id: int) -> Optional[dict]:
    init()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM voice_calls WHERE id=?", (int(voice_call_id),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def log_attempt(
    company_id: int,
    user_id: int,
    outcome: str,
    notes: str = "",
    callback_at: Optional[str] = None,
) -> dict:
    init()
    if outcome not in OUTCOMES:
        raise ValueError("outcome inválido")
    now = _utc_now()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM prospect_companies WHERE id=?", (int(company_id),)
        ).fetchone()
        if row is None:
            raise ValueError("empresa não encontrada")
        company = _company_dict(row)
        eligibility = _eligibility(company, conn, now)
        if not eligibility["allowed"] and outcome not in SUPPRESS_OUTCOMES:
            raise ValueError(
                "contacto bloqueado: " + ", ".join(eligibility["reason_labels"])
            )
        conn.execute(
            "INSERT INTO call_attempts "
            "(company_id, user_id, started_at, outcome, notes, callback_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(company_id),
                int(user_id or 0),
                _iso(now),
                outcome,
                notes,
                callback_at,
                _iso(now),
            ),
        )
        status = "called"
        if outcome in SUPPRESS_OUTCOMES:
            status = "do_not_call"
            conn.execute(
                "INSERT INTO voice_suppressions (value, channel, reason, created_at) "
                "VALUES (?, 'phone', ?, ?) "
                "ON CONFLICT(value, channel) DO UPDATE SET reason=excluded.reason",
                (company["phone"], outcome, _iso(now)),
            )
        elif outcome == "meeting_booked":
            status = "meeting"
        elif outcome == "callback":
            status = "callback"
        conn.execute(
            "UPDATE prospect_companies SET status=?, last_attempt_at=?, updated_at=? "
            "WHERE id=?",
            (status, _iso(now), _iso(now), int(company_id)),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM prospect_companies WHERE id=?", (int(company_id),)
        ).fetchone()
        eligibility = _eligibility(_company_dict(updated), conn, now)
        return {
            "ok": True,
            "company_id": int(company_id),
            "outcome": outcome,
            "status": status,
            "eligibility": eligibility,
        }
    finally:
        conn.close()
