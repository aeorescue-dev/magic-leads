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
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, time, timedelta, timezone
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
CALL_START_HOUR = 9
CALL_END_HOUR = 20


def _call_window() -> tuple[int, int]:
    """Janela local configurável; fail-safe em 9-20."""
    try:
        start = int(getattr(settings, "VOICE_CALL_START_HOUR", 9))
        end = int(getattr(settings, "VOICE_CALL_END_HOUR", 20))
    except (TypeError, ValueError):
        return CALL_START_HOUR, CALL_END_HOUR
    start = max(0, min(23, start))
    end = max(1, min(24, end))
    if end <= start:
        return CALL_START_HOUR, CALL_END_HOUR
    return start, end
DNC_MAX_AGE_DAYS = 31
MAX_ATTEMPTS_7D = 3

# Cache materializado de segmentos. O stock de elegibilidade muda com a hora
# local, DNC, scoring e self-healing; 5 min é o compromisso entre frescura e
# custo (rebuild percorre os ~15,5k prospects).
VOICE_SEGMENTS_TTL_SECONDS = max(
    60, int(os.getenv("VOICE_SEGMENTS_TTL_SECONDS", "300") or 300)
)

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

-- Classificação multi-label: a mesma empresa pode servir vários trades sem
-- duplicar o contacto (o telefone continua único em prospect_companies).
CREATE TABLE IF NOT EXISTS company_trades (
  company_id INTEGER NOT NULL REFERENCES prospect_companies(id) ON DELETE CASCADE,
  trade_code TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT '',
  is_primary INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (company_id, trade_code)
);

CREATE INDEX IF NOT EXISTS idx_company_trades_trade
  ON company_trades (trade_code, confidence DESC);

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
  phone TEXT,
  city TEXT,
  trade_code TEXT,
  category_code TEXT,
  script_scope TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  intent TEXT,
  showcase_link_id INTEGER,
  checkout_session_id TEXT,
  assistant_id TEXT,
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

-- Reserva atomica de DID por dia operacional (America/New_York).
CREATE TABLE IF NOT EXISTS voice_did_usage (
  day TEXT NOT NULL,
  did TEXT NOT NULL,
  calls INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, did)
);

CREATE INDEX IF NOT EXISTS idx_voice_did_usage_day
  ON voice_did_usage (day, calls);

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
  budget_total_usd REAL NOT NULL DEFAULT 0,
  budget_daily_usd REAL NOT NULL DEFAULT 0,
  max_days INTEGER NOT NULL DEFAULT 0,
  start_hour_et INTEGER NOT NULL DEFAULT 9,
  call_interval_seconds INTEGER NOT NULL DEFAULT 30,
  batch_plan TEXT,
  trade_plan TEXT,
  plan_index INTEGER NOT NULL DEFAULT 0,
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
        ("budget_total_usd", "REAL NOT NULL DEFAULT 0"),
        ("budget_daily_usd", "REAL NOT NULL DEFAULT 0"),
        ("max_days", "INTEGER NOT NULL DEFAULT 0"),
        ("start_hour_et", "INTEGER NOT NULL DEFAULT 9"),
        ("call_interval_seconds", "INTEGER NOT NULL DEFAULT 30"),
        ("batch_plan", "TEXT"),
        ("trade_plan", "TEXT"),
        ("plan_index", "INTEGER NOT NULL DEFAULT 0"),
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
        ("assistant_id", "TEXT"),
        ("from_number", "TEXT"),
        ("phone", "TEXT"),
        ("fallback_audio_started_at", "TEXT"),
        ("amd_result", "TEXT"),
        ("category_code", "TEXT"),
        ("script_scope", "TEXT"),
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


def staging_mode() -> bool:
    return bool(getattr(settings, "VOICE_STAGING_MODE", False))


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


def is_valid_us_phone(raw: Any) -> bool:
    """Valida NANP/E.164 dos EUA: +1, area 2-9, exchange 2-9."""
    phone = normalize_phone(raw)
    return bool(phone and re.fullmatch(r"\+1[2-9]\d{2}[2-9]\d{6}", phone))


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


_PHONE_RE = re.compile(
    r"(?:\+?1[\s.\-()]*)?\(?\d{3}\)?[\s.\-]*\d{3}[\s.\-]*\d{4}"
)
_CLEAN_RE = re.compile(
    r"\b(clean|clear|not[_\s-]?listed|no|false|0|allow|ok|safe)\b", re.I
)


def _extract_dnc_entries(text: str) -> tuple[dict[str, bool], int]:
    """Aceita qualquer lista: CSV, TSV, uma coluna ou linhas soltas."""
    found: dict[str, bool] = {}
    skipped = 0
    for line in (text or "").lstrip("\ufeff").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        phones: list[str] = []
        for match in _PHONE_RE.finditer(line):
            phone = normalize_phone(match.group(0))
            if phone and phone.startswith("+1") and len(phone) == 12:
                phones.append(phone)
        if not phones:
            for token in re.split(r"[,;\t|]+", line):
                phone = normalize_phone(token)
                if phone and phone.startswith("+1") and len(phone) == 12:
                    phones.append(phone)
        if not phones:
            skipped += 1
            continue
        clean = bool(_CLEAN_RE.search(line))
        for phone in phones:
            # Se o mesmo número aparecer como listado e limpo, prevalece listado.
            found[phone] = found.get(phone, False) or (not clean)
    return found, skipped


def import_dnc_text(text: str, source: str = "raw") -> dict:
    """Importa DNC de qualquer formato, sem exigir cabeçalho ou colunas."""
    init()
    found, skipped = _extract_dnc_entries(text)
    if not found:
        raise ValueError(
            "nenhum telefone detetado; aceita CSV, TXT, uma coluna ou linhas soltas"
        )
    now = _utc_now()
    expires = now + timedelta(days=DNC_MAX_AGE_DAYS)
    listed_count = 0
    conn = get_conn()
    try:
        for phone, listed in found.items():
            conn.execute(
                """
                INSERT INTO dnc_checks
                  (phone, listed, source, provider, checked_at, expires_at, raw_status)
                VALUES (?, ?, ?, 'raw_import', ?, ?, ?)
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
                    source or "raw",
                    _iso(now),
                    _iso(expires),
                    "listed" if listed else "clear",
                ),
            )
            if listed:
                listed_count += 1
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "imported": len(found),
        "skipped": skipped,
        "listed": listed_count,
        "cleaned": len(found) - listed_count,
        "total": len(found) + skipped,
        "format": "raw",
    }


def import_dnc_csv(csv_text: str, source: str = "import") -> dict:
    """Compatibilidade: qualquer texto é aceite pelo parser universal."""
    return import_dnc_text(csv_text, source)


def scrub_prospects_with_dnc_text(text: str, source: str = "official") -> dict:
    """Aplica a lista DNC à base: listados bloqueiam, não listados ficam limpos.

    Assume que a lista é a registry oficial completa. Para listas parciais,
    usar apenas `import_dnc_text` (não scrub).
    """
    init()
    found, _ = _extract_dnc_entries(text)
    if not found:
        raise ValueError("nenhum telefone detetado na lista DNC")
    now = _utc_now()
    expires = now + timedelta(days=DNC_MAX_AGE_DAYS)
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT phone FROM prospect_companies WHERE COALESCE(TRIM(phone),'')<>''"
        ).fetchall()
        listed = cleared = 0
        for row in rows:
            phone = str(row["phone"])
            is_listed = bool(found.get(phone, False))
            conn.execute(
                """
                INSERT INTO dnc_checks
                  (phone, listed, source, provider, checked_at, expires_at, raw_status)
                VALUES (?, ?, 'dnc_scrub', 'file', ?, ?, ?)
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
                    1 if is_listed else 0,
                    _iso(now),
                    _iso(expires),
                    "listed" if is_listed else "scrub_clear",
                ),
            )
            if is_listed:
                listed += 1
            else:
                cleared += 1
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "prospects": len(rows),
        "listed": listed,
        "cleared": cleared,
        "dnc_numbers": len(found),
        "source": source,
    }


def staging_clear_dnc() -> dict:
    """Marca todos os telefones como DNC limpo em staging (auditável)."""
    if not staging_mode():
        raise ValueError("staging_mode_disabled")
    init()
    now = _utc_now()
    expires = now + timedelta(days=DNC_MAX_AGE_DAYS)
    conn = get_conn()
    try:
        phones = [
            str(row["phone"])
            for row in conn.execute(
                "SELECT phone FROM prospect_companies WHERE COALESCE(TRIM(phone),'')<>''"
            ).fetchall()
        ]
        for phone in phones:
            conn.execute(
                """
                INSERT INTO dnc_checks
                  (phone, listed, source, provider, checked_at, expires_at, raw_status)
                VALUES (?, 0, 'staging', 'staging', ?, ?, 'staging_clear')
                ON CONFLICT(phone) DO UPDATE SET
                  listed=0,
                  source='staging',
                  provider='staging',
                  checked_at=excluded.checked_at,
                  expires_at=excluded.expires_at,
                  raw_status='staging_clear'
                """,
                (phone, _iso(now), _iso(expires)),
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "cleared": len(phones), "mode": "staging"}


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


def clear_suppression(value: str, channel: str = "phone") -> int:
    """Remove uma supressão (usado pelo test-call antes de cada ensaio)."""
    init()
    normalized = normalize_phone(value) or str(value or "").strip()
    if not normalized:
        return 0
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM voice_suppressions WHERE value=? AND channel=?",
            (normalized, channel),
        )
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()


def _company_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _state_tz(state: str) -> ZoneInfo:
    return ZoneInfo(STATE_TIMEZONES.get((state or "").upper(), "America/New_York"))


def _eligibility(
    company: dict,
    conn: sqlite3.Connection,
    now: datetime,
    allow_international: bool = False,
) -> dict:
    reasons: list[str] = []
    checks: dict[str, bool] = {}

    phone = str(company.get("phone") or "")
    checks["phone_valid"] = bool(re.match(r"^\+1\d{10}$", phone)) or (
        allow_international and bool(re.match(r"^\+\d{8,15}$", phone))
    )
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
    staging = staging_mode()
    if dnc is None:
        if staging:
            checks["dnc_checked"] = True
            checks["dnc_fresh"] = True
            checks["dnc_clear"] = True
            checks["dnc_staging_bypass"] = True
        else:
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
            if staging:
                checks["dnc_fresh"] = True
                checks["dnc_staging_bypass"] = True
            else:
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
    start_hour, end_hour = _call_window()
    checks["within_hours"] = start_hour <= local.hour < end_hour
    if not checks["within_hours"]:
        reasons.append("outside_hours")

    return {
        "allowed": not reasons,
        "reasons": reasons,
        "reason_labels": [REASON_LABELS.get(code, code) for code in reasons],
        "checks": checks,
        "local_time": local.strftime("%Y-%m-%d %H:%M %Z"),
    }


def can_call(
    company: dict, now: Optional[datetime] = None, allow_international: bool = False
) -> dict:
    """Fail-closed. Recebe a empresa (dict) e devolve allowed + reasons."""
    init()
    reference = now or _utc_now()
    conn = get_conn()
    try:
        return _eligibility(
            company, conn, reference, allow_international=allow_international
        )
    finally:
        conn.close()


def queue(
    limit: int = 50,
    include_blocked: bool = False,
    city: str = "",
    trade: str = "",
    state: str = "",
    offset: int = 0,
    score_min: Optional[int] = None,
    score_max: Optional[int] = None,
    status: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict:
    init()
    now = _utc_now()
    offset = max(0, int(offset))
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
    if score_min is not None:
        where.append("score >= ?")
        params.append(int(score_min))
    if score_max is not None:
        where.append("score <= ?")
        params.append(int(score_max))
    if status.strip():
        where.append("status = ?")
        params.append(status.strip())
    if date_from.strip():
        where.append("date(created_at) >= date(?)")
        params.append(date_from.strip())
    if date_to.strip():
        where.append("date(created_at) <= date(?)")
        params.append(date_to.strip())
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = get_conn()
    try:
        rows = conn.execute(
            f"SELECT * FROM prospect_companies{clause} "
            "ORDER BY score DESC, permit_count DESC, id ASC LIMIT ? OFFSET ?",
            (*params, max(1, min(1000, int(limit))), offset),
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
            "offset": offset,
            "total": total,
            "callable": callable_count,
            "include_blocked": include_blocked,
            "filters": {
                "city": city,
                "trade": trade,
                "state": state,
                "score_min": score_min,
                "score_max": score_max,
                "status": status,
                "date_from": date_from,
                "date_to": date_to,
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
        # O dialer grava em `voice_calls`; `call_attempts` só recebe registos
        # manuais. A KPI "Tentativas hoje" tem de refletir as chamadas reais.
        attempts_today = int(
            conn.execute(
                "SELECT COUNT(*) FROM voice_calls "
                "WHERE date(COALESCE(created_at, started_at))=? "
                "AND COALESCE(campaign_id,'') <> 'test_call' "
                "AND COALESCE(status,'') <> 'dry_run'",
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
        usage = voice_daily_usage()
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
            "staging_mode": staging_mode(),
            "daily_budget_usd": (
                round(usage["budget_cents"] / 100.0, 2)
                if usage["budget_cents"]
                else 0.0
            ),
            "daily_spent_usd": round(
                usage["estimated_total_cents"] / 100.0, 2
            ),
            "daily_calls": usage["calls"],
            "max_calls_per_day": usage["max_calls_per_day"],
            "daily_budget_remaining_usd": (
                round(usage["budget_remaining_cents"] / 100.0, 2)
                if usage["budget_remaining_cents"] is not None
                else None
            ),
            "calling_window": (
                f"{_call_window()[0]:02d}:00–{_call_window()[1]:02d}:00 "
                "local (ET/CT)"
            ),
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

    voice_min = max(
        1,
        int(getattr(settings, "VOICE_MIN_SHOWCASE_ITEMS", 5) or 5),
    )
    for group in groups.values():
        trade_code = showcase.normalize_trade(group["trade"])
        available = showcase.available(
            group["city"],
            trade_code or group["trade"],
            min_items=voice_min,
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
    budget_total_usd: Optional[float] = None,
    budget_daily_usd: Optional[float] = None,
    max_days: Optional[int] = None,
    start_hour_et: Optional[int] = None,
    call_interval_seconds: Optional[int] = None,
    batch_plan: Optional[list[int]] = None,
    trade_plan: Optional[list[dict]] = None,
) -> dict:
    init()
    now = _iso()
    quota = max(1, min(10000, int(quota_total if quota_total is not None else max_calls)))
    batch = max(1, min(quota, int(batch_size or quota)))
    total_budget = max(
        0.0,
        float(
            budget_total_usd
            if budget_total_usd is not None
            else getattr(settings, "VOICE_CAMPAIGN_TOTAL_BUDGET_USD", 100.0)
        ),
    )
    daily_budget = max(
        0.0,
        float(
            budget_daily_usd
            if budget_daily_usd is not None
            else getattr(settings, "VOICE_CAMPAIGN_DAILY_BUDGET_USD", 5.0)
        ),
    )
    days = max(
        0,
        int(
            max_days
            if max_days is not None
            else getattr(settings, "VOICE_CAMPAIGN_MAX_DAYS", 30)
        ),
    )
    start_hour = max(
        0,
        min(
            23,
            int(
                start_hour_et
                if start_hour_et is not None
                else getattr(settings, "VOICE_CALL_START_HOUR", 9)
            ),
        ),
    )
    interval = max(
        0,
        int(
            call_interval_seconds
            if call_interval_seconds is not None
            else getattr(settings, "VOICE_AUTOSCHED_DELAY_SECONDS", 30)
        ),
    )
    plan_json = ""
    if batch_plan:
        try:
            values = [
                max(1, min(quota, int(value)))
                for value in batch_plan
                if int(value) > 0
            ]
            if values:
                plan_json = json.dumps(values)
        except (TypeError, ValueError):
            plan_json = ""
    trade_plan_json = ""
    if isinstance(trade_plan, dict):
        trade_plan = [trade_plan]
    if trade_plan:
        from . import showcase, voice_taxonomy

        rows: list[dict] = []
        for item in trade_plan:
            item = item or {}
            category = str(item.get("category") or "").strip()
            code = showcase.normalize_trade(item.get("trade"))
            if not code and category:
                code = voice_taxonomy.category_trade(category)
            try:
                amount = int(item.get("quota") or 0)
            except (TypeError, ValueError):
                amount = 0
            if code and amount > 0:
                row = {"trade": code, "quota": amount}
                if category:
                    row["category"] = category
                rows.append(row)
        if rows:
            total_plan = sum(row["quota"] for row in rows)
            if total_plan != quota:
                raise ValueError(
                    f"trade_plan soma {total_plan}, quota_total é {quota}"
                )
            # Limite duro do GC quando os scopes não-exact estão ligados. O
            # bundle/city só existem para o GC; nunca podem ser a maioria da
            # campanha. 10% por defeito.
            scopes = {
                part.strip().lower()
                for part in str(
                    getattr(settings, "VOICE_GUARD_SCOPES", "exact") or "exact"
                ).split(",")
                if part.strip()
            }
            if scopes - {"exact"}:
                gc_quota = sum(
                    row["quota"]
                    for row in rows
                    if row["trade"] == "general_contractor"
                )
                if gc_quota:
                    try:
                        pct = max(
                            1,
                            min(
                                100,
                                int(
                                    getattr(
                                        settings,
                                        "VOICE_CITY_SCOPE_MAX_PCT",
                                        10,
                                    )
                                    or 10
                                ),
                            ),
                        )
                    except (TypeError, ValueError):
                        pct = 10
                    cap = max(1, (quota * pct + 99) // 100)
                    if gc_quota > cap:
                        raise ValueError(
                            "trade_plan: general_contractor "
                            f"{gc_quota} excede o limite de {pct}% "
                            f"({cap} de {quota})"
                        )
            trade_plan_json = json.dumps(rows)
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO voice_campaigns "
            "(name, city, trade, status, max_calls, quota_total, batch_size, "
            "include_fallback, dry_run, budget_total_usd, budget_daily_usd, "
            "max_days, start_hour_et, call_interval_seconds, batch_plan, "
            "trade_plan, plan_index, created_by, created_at, started_at) "
            "VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (
                name,
                city,
                trade,
                quota,
                quota,
                batch,
                1 if include_fallback else 0,
                1 if dry_run else 0,
                round(total_budget, 2),
                round(daily_budget, 2),
                days,
                start_hour,
                interval,
                plan_json,
                trade_plan_json,
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
        "budget_total_usd",
        "budget_daily_usd",
        "max_days",
        "start_hour_et",
        "call_interval_seconds",
        "batch_plan",
        "trade_plan",
        "plan_index",
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


def campaign_trade_counts(campaign_id: int) -> dict[str, int]:
    """Chamadas já criadas por trade nesta campanha (para o trade_plan)."""
    init()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT LOWER(TRIM(COALESCE(trade_code,''))) AS trade, "
            "COUNT(*) AS n FROM voice_calls WHERE campaign_id=? "
            "AND status <> 'dry_run' GROUP BY 1",
            (str(int(campaign_id)),),
        ).fetchall()
        return {str(r["trade"] or ""): int(r["n"] or 0) for r in rows}
    finally:
        conn.close()


def _verified_trade_clause() -> str:
    """Cláusula única de verificação de nicho.

    Só aceita `company_trades` com confiança >=0.80, nunca
    `primary_unconfirmed`, e exige licença/registo OU fonte forte
    (`license`/`niche_key`/`site_text`). O `trade` primário de
    `prospect_companies` deixou de ser suficiente.
    """
    return (
        "EXISTS (SELECT 1 FROM company_trades ct "
        "WHERE ct.company_id=prospect_companies.id "
        "AND LOWER(ct.trade_code)=LOWER(?) "
        "AND ct.confidence>=0.80 "
        "AND COALESCE(ct.source,'')<>'primary_unconfirmed' "
        "AND (COALESCE(TRIM(prospect_companies.license_number),'')<>'' "
        "     OR ct.source IN ('license','niche_key','site_text')))"
    )


def verified_candidate_count(city: str, trade: str) -> int:
    """Contactos 100% validados para cidade+trade (sem depender da hora)."""
    init()
    from . import showcase

    code = showcase.normalize_trade(trade) or str(trade or "").strip()
    if not code:
        return 0
    where = [
        "status NOT IN ('do_not_call', 'invalid', 'meeting')",
        "LENGTH(phone)=12 AND phone LIKE '+1%'",
        "UPPER(TRIM(city))=UPPER(?)",
        _verified_trade_clause(),
    ]
    conn = get_conn()
    try:
        return int(
            conn.execute(
                "SELECT COUNT(1) FROM prospect_companies WHERE "
                + " AND ".join(where),
                (str(city or "").strip(), code),
            ).fetchone()[0]
            or 0
        )
    finally:
        conn.close()


def validate_campaign_niche(campaign_id: int) -> dict:
    """Gate duro: cada quota do trade_plan tem de ter contactos verificados."""
    campaign = get_campaign(int(campaign_id))
    if not campaign:
        raise ValueError(f"campaign_not_found: {campaign_id}")
    city = str(campaign.get("city") or "").strip()
    raw = campaign.get("trade_plan")
    try:
        plan = json.loads(raw) if raw else []
    except (TypeError, ValueError, json.JSONDecodeError):
        plan = []
    if not plan:
        plan = [
            {
                "trade": str(campaign.get("trade") or "").strip(),
                "quota": int(campaign.get("quota_total") or 0),
            }
        ]
    deficits: list[str] = []
    checked: list[dict] = []
    for item in plan:
        trade = str(item.get("trade") or "").strip()
        quota = max(0, int(item.get("quota") or 0))
        if not trade or quota <= 0:
            continue
        available = verified_candidate_count(city, trade)
        checked.append({"trade": trade, "quota": quota, "verified": available})
        if available < quota:
            deficits.append(f"{trade}: quota {quota} > verificados {available}")
    if deficits:
        raise ValueError("niche_gate: " + "; ".join(deficits))
    return {"ok": True, "campaign_id": int(campaign_id), "city": city, "trades": checked}


def audit_campaign_candidates(
    campaign_id: int,
    at: Optional[datetime] = None,
    sample_limit: int = 5,
) -> dict:
    """Auditoria pré-call: quota vs verificados vs permitidos no horário."""
    campaign = get_campaign(int(campaign_id))
    if not campaign:
        raise ValueError(f"campaign_not_found: {campaign_id}")
    city = str(campaign.get("city") or "").strip()
    raw = campaign.get("trade_plan")
    try:
        plan = json.loads(raw) if raw else []
    except (TypeError, ValueError, json.JSONDecodeError):
        plan = []
    if not plan:
        plan = [
            {
                "trade": str(campaign.get("trade") or "").strip(),
                "quota": int(campaign.get("quota_total") or 0),
            }
        ]
    limit = max(1, min(20, int(sample_limit or 5)))
    trades: list[dict] = []
    total_quota = 0
    total_verified = 0
    total_candidates = 0
    total_allowed = 0
    gc_in_plan = 0
    all_green = True
    for item in plan:
        trade = str(item.get("trade") or "").strip()
        quota = max(0, int(item.get("quota") or 0))
        if not trade or quota <= 0:
            continue
        if trade == "general_contractor":
            gc_in_plan += quota
        verified = verified_candidate_count(city, trade)
        rows = campaign_candidates(
            int(campaign_id), city, trade, limit=quota, include_fallback=True
        )
        allowed = 0
        samples: list[dict] = []
        for row in rows:
            if can_call(row, now=at).get("allowed"):
                allowed += 1
            if len(samples) < limit:
                phone = str(row.get("phone") or "")
                masked = (
                    phone[:2] + "*" * max(0, len(phone) - 6) + phone[-4:]
                    if len(phone) >= 6
                    else phone
                )
                samples.append(
                    {
                        "company": row.get("company_name"),
                        "phone": masked,
                        "trade": trade,
                        "license": row.get("license_number"),
                    }
                )
        green = verified >= quota and allowed >= quota
        all_green = all_green and green
        total_quota += quota
        total_verified += verified
        total_candidates += len(rows)
        total_allowed += allowed
        trades.append(
            {
                "trade": trade,
                "quota": quota,
                "verified": verified,
                "candidates": len(rows),
                "allowed_at": allowed,
                "green": green,
                "sample": samples,
            }
        )
    return {
        "campaign_id": int(campaign_id),
        "city": city,
        "status": campaign.get("status"),
        "next_batch_at": campaign.get("next_batch_at"),
        "quota_total": int(campaign.get("quota_total") or 0),
        "at": at.isoformat() if at else None,
        "total_quota": total_quota,
        "total_verified": total_verified,
        "total_candidates": total_candidates,
        "total_allowed": total_allowed,
        "gc_in_plan": gc_in_plan,
        "gc_verified_city": verified_candidate_count(city, "general_contractor"),
        "all_green": bool(all_green and gc_in_plan == 0 and total_allowed >= total_quota),
        "trades": trades,
    }


def campaign_candidates(
    campaign_id: int,
    city: str = "",
    trade: str = "",
    limit: int = 50,
    include_fallback: bool = True,
) -> list[dict]:
    init()
    where = [
        "status NOT IN ('do_not_call', 'invalid', 'meeting')",
        "LENGTH(phone)=12 AND phone LIKE '+1%'",
    ]
    params: list[Any] = []
    if city.strip():
        where.append("UPPER(TRIM(city))=UPPER(?)")
        params.append(city.strip())
    if trade.strip():
        # Multi-label: o campo primário continua a valer, mas uma empresa
        # reclassificada (ex.: GC que também é plumbing) entra pelo sinal com
        # confiança >=0.80. O EXISTS evita duplicar a empresa no lote.
        where.append(_verified_trade_clause())
        params.append(trade.strip())
    where.append(
        "id NOT IN (SELECT company_id FROM voice_calls WHERE campaign_id=?)"
    )
    params.append(str(int(campaign_id)))
    where.append(
        "id NOT IN (SELECT company_id FROM voice_campaign_skips WHERE campaign_id=?)"
    )
    params.append(int(campaign_id))
    # Exclusao global: nenhuma campanha repete um contacto chamado nos
    # ultimos 7 dias. A exclusao por campanha acima nao chega quando duas
    # campanhas correm em paralelo no mesmo segmento.
    since = (_utc_now() - timedelta(days=7)).isoformat()
    where.append(
        "id NOT IN (SELECT company_id FROM voice_calls "
        "WHERE COALESCE(provider,'')='telnyx' "
        "AND COALESCE(campaign_id,'') <> 'test_call' "
        "AND status <> 'dry_run' "
        "AND datetime(COALESCE(created_at, started_at)) >= datetime(?))"
    )
    params.append(since)
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
                # A empresa pode ter sido chamada por um trade secundário
                # (multi-label). O segmento tem de ser o trade da campanha,
                # não o campo primário antigo.
                trade_code = (
                    showcase.normalize_trade(trade)
                    or showcase.normalize_trade(row.get("trade"))
                    or row.get("trade")
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


def _segments_built_at() -> datetime | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(built_at) AS built_at FROM voice_segments"
        ).fetchone()
    finally:
        conn.close()
    text = str((row["built_at"] if row else "") or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _inside_calling_window() -> bool:
    try:
        start, end = _call_window()
        local = datetime.now(timezone.utc).astimezone(_state_tz("NY"))
        return start <= local.hour < end
    except Exception:  # noqa: BLE001 - nunca bloquear a leitura por horário
        return False


def _has_callable_inventory() -> bool:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM prospect_companies "
            "WHERE status NOT IN ('do_not_call','invalid','meeting') "
            "AND LENGTH(phone)=12 AND phone LIKE '+1%' LIMIT 1"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def ensure_segments_fresh() -> bool:
    """Reconstrói `voice_segments` se estiver vazio, velho ou zerado na janela.

    Fora da janela de chamadas um `callable=0` é legítimo; não se reconstrói em
    loop. Dentro da janela, se o stock diz 0 mas há telefones elegíveis por
    estado, força rebuild imediato.
    """
    init()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(1) AS n, MAX(built_at) AS built_at, "
            "COALESCE(SUM(callable),0) AS callable FROM voice_segments"
        ).fetchone()
    finally:
        conn.close()
    count = int((row["n"] if row else 0) or 0)
    callable_count = int((row["callable"] if row else 0) or 0)
    built_at = _segments_built_at()
    stale = count == 0 or built_at is None
    if not stale and built_at is not None:
        age = (datetime.now(timezone.utc) - built_at).total_seconds()
        stale = age > VOICE_SEGMENTS_TTL_SECONDS
    if (
        not stale
        and callable_count == 0
        and _inside_calling_window()
        and _has_callable_inventory()
    ):
        stale = True
    if stale:
        rebuild_segments()
        return True
    return False


def cached_segments(
    city: str = "", trade: str = "", state: str = ""
) -> list[dict]:
    """Lê voice_segments com TTL/gatilho de frescura."""
    init()
    ensure_segments_fresh()
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
        classified = sync_company_trades()
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
            "company_trades": classified,
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
    where = [
        "datetime(COALESCE(v.created_at, v.started_at)) >= datetime(?)",
        "COALESCE(v.campaign_id, '') <> 'test_call'",
    ]
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
              SUM(CASE WHEN v.intent='showcase' THEN 1 ELSE 0 END) accepts,
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
        for key in (
            "answered",
            "unanswered",
            "engaged",
            "accepts",
            "clicks",
            "checkouts",
        ):
            summary[key] = int(summary.get(key) or 0)
        dialed = int(summary.get("dialed") or 0)
        answered = int(summary.get("answered") or 0)
        engaged = int(summary.get("engaged") or 0)
        accepts = int(summary.get("accepts") or 0)
        clicks = int(summary.get("clicks") or 0)
        checkouts = int(summary.get("checkouts") or 0)
        revenue = int(summary.get("revenue_cents") or 0)
        cost = int(summary.get("cost_cents") or 0)
        summary.update(
            {
                "answer_rate": _rate(answered, dialed),
                "drop_rate": _rate(dialed - answered, dialed),
                "engagement_rate": _rate(engaged, answered),
                "accept_rate": _rate(accepts, answered),
                "showcase_ctr": _rate(clicks, answered),
                "checkout_rate": _rate(checkouts, clicks),
                "subscription_rate": _rate(checkouts, accepts),
                "avg_listen_seconds": round(float(summary.get("avg_listen") or 0), 1),
                "revenue_usd": round(revenue / 100.0, 2),
                "revenue_per_accept_usd": (
                    round((revenue / 100.0) / accepts, 2) if accepts else 0.0
                ),
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

        rows = [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT
                  COALESCE(c.state, '—') state,
                  COALESCE(v.city, c.city, '—') city,
                  COALESCE(v.trade_code, c.trade, '—') trade,
                  COUNT(*) dialed,
                  SUM(CASE WHEN v.answered_at IS NOT NULL THEN 1 ELSE 0 END) answered,
                  SUM(CASE WHEN v.answered_at IS NOT NULL AND v.listen_seconds >= 30
                           THEN 1 ELSE 0 END) engaged,
                  SUM(CASE WHEN v.intent='showcase' THEN 1 ELSE 0 END) accepts,
                  AVG(CASE WHEN v.answered_at IS NOT NULL
                           THEN v.listen_seconds END) avg_listen,
                  SUM(CASE WHEN v.showcase_clicked_at IS NOT NULL THEN 1 ELSE 0 END) clicks,
                  SUM(CASE WHEN v.checkout_session_id IS NOT NULL THEN 1 ELSE 0 END) checkouts,
                  COALESCE(SUM(v.revenue_cents),0) revenue_cents,
                  COALESCE(SUM(v.cost_cents),0) cost_cents
                FROM voice_calls v
                LEFT JOIN prospect_companies c ON c.id = v.company_id
                {clause}
                GROUP BY 1, 2, 3
                """,
                tuple(params),
            ).fetchall()
        ]

        def _empty_group(extra: dict) -> dict:
            return {
                "city": "",
                "trade": "",
                "state": "",
                **extra,
                "dialed": 0,
                "answered": 0,
                "engaged": 0,
                "accepts": 0,
                "clicks": 0,
                "checkouts": 0,
                "avg_listen_total": 0.0,
                "avg_listen_count": 0,
                "revenue_cents": 0,
                "cost_cents": 0,
            }

        def _add(bucket: dict, row: dict) -> None:
            answered_row = int(row.get("answered") or 0)
            bucket["dialed"] += int(row.get("dialed") or 0)
            bucket["answered"] += answered_row
            bucket["engaged"] += int(row.get("engaged") or 0)
            bucket["accepts"] += int(row.get("accepts") or 0)
            bucket["clicks"] += int(row.get("clicks") or 0)
            bucket["checkouts"] += int(row.get("checkouts") or 0)
            bucket["revenue_cents"] += int(row.get("revenue_cents") or 0)
            bucket["cost_cents"] += int(row.get("cost_cents") or 0)
            listen = row.get("avg_listen")
            if listen is not None and answered_row:
                bucket["avg_listen_total"] += float(listen) * answered_row
                bucket["avg_listen_count"] += answered_row

        def _finalize(bucket: dict) -> dict:
            gd = int(bucket["dialed"])
            ga = int(bucket["answered"])
            ge = int(bucket["engaged"])
            gac = int(bucket["accepts"])
            gc = int(bucket["clicks"])
            gco = int(bucket["checkouts"])
            grev = int(bucket["revenue_cents"])
            gcost = int(bucket["cost_cents"])
            listen_count = int(bucket["avg_listen_count"])
            avg_listen = (
                bucket["avg_listen_total"] / listen_count if listen_count else 0.0
            )
            return {
                **{
                    key: value
                    for key, value in bucket.items()
                    if key
                    not in (
                        "avg_listen_total",
                        "avg_listen_count",
                        "revenue_cents",
                        "cost_cents",
                    )
                },
                "answer_rate": _rate(ga, gd),
                "accept_rate": _rate(gac, ga),
                "engagement_rate": _rate(ge, ga),
                "showcase_ctr": _rate(gc, ga),
                "checkout_rate": _rate(gco, gc),
                "subscription_rate": _rate(gco, gac),
                "avg_listen_seconds": round(avg_listen, 1),
                "revenue_usd": round(grev / 100.0, 2),
                "cost_usd": round(gcost / 100.0, 2),
                "net_usd": round((grev - gcost) / 100.0, 2),
                "revenue_per_accept_usd": (
                    round((grev / 100.0) / gac, 2) if gac else 0.0
                ),
            }

        by_state: dict[str, dict] = {}
        by_city: dict[tuple[str, str], dict] = {}
        by_trade: dict[str, dict] = {}
        by_city_trade: dict[tuple[str, str, str], dict] = {}
        for row in rows:
            state = str(row.get("state") or "—")
            city_name = str(row.get("city") or "—")
            trade_name = str(row.get("trade") or "—")
            for store, key, extra in (
                (by_state, state, {"state": state}),
                (by_city, (city_name, state), {"city": city_name, "state": state}),
                (by_trade, trade_name, {"trade": trade_name}),
                (
                    by_city_trade,
                    (city_name, trade_name, state),
                    {"city": city_name, "trade": trade_name, "state": state},
                ),
            ):
                if key not in store:
                    store[key] = _empty_group(extra)
                _add(store[key], row)

        def _sorted_groups(store: dict) -> list[dict]:
            groups = [_finalize(bucket) for bucket in store.values()]
            groups.sort(
                key=lambda g: (
                    -float(g["revenue_usd"]),
                    -float(g["accept_rate"]),
                    -int(g["dialed"]),
                )
            )
            return groups

        return {
            "days": days,
            "generated_at": _iso(),
            "summary": summary,
            "retention": retention,
            "funnel": {
                "dialed": dialed,
                "answered": answered,
                "engaged": engaged,
                "accepts": accepts,
                "clicks": clicks,
                "checkouts": checkouts,
                "revenue_usd": round(revenue / 100.0, 2),
            },
            "by_state": _sorted_groups(by_state),
            "by_city": _sorted_groups(by_city),
            "by_trade": _sorted_groups(by_trade),
            "by_city_trade": _sorted_groups(by_city_trade),
        }
    finally:
        conn.close()


def _parse_dt(value: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def live_dashboard(
    campaign_id: Optional[int] = None, recent_limit: int = 15
) -> dict:
    """Snapshot vivo de uma campanha para o Admin (polling de 30 s)."""
    init()
    now = datetime.now(timezone.utc)
    limit = max(1, min(50, int(recent_limit or 15)))
    conn = get_conn()
    try:
        if campaign_id is None:
            # Preferencia: campanha a correr -> campanha com chamadas nas
            # ultimas 24h -> proxima agendada -> ultimo id. Evita ficar
            # presa na campanha de maior id (ex.: uma rampa futura).
            row = conn.execute(
                "SELECT id FROM voice_campaigns WHERE status='running' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT campaign_id AS id, MAX(created_at) AS last_at "
                    "FROM voice_calls "
                    "WHERE COALESCE(campaign_id,'') NOT IN ('', 'test_call') "
                    "AND datetime(created_at) >= datetime('now','-24 hours') "
                    "GROUP BY campaign_id "
                    "ORDER BY last_at DESC LIMIT 1"
                ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT id FROM voice_campaigns WHERE status='paused' "
                    "AND next_batch_at IS NOT NULL "
                    "AND datetime(next_batch_at) >= datetime('now') "
                    "ORDER BY datetime(next_batch_at) ASC, id ASC LIMIT 1"
                ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT id FROM voice_campaigns ORDER BY id DESC LIMIT 1"
                ).fetchone()
            campaign_id = int(row["id"]) if row and row["id"] is not None else None
        campaign = get_campaign(int(campaign_id)) if campaign_id else None
        if not campaign:
            return {
                "generated_at": _iso(now),
                "campaign": None,
                "summary": {},
                "thermometer": {
                    "red": 0,
                    "yellow": 0,
                    "green": 0,
                    "total": 0,
                    "red_pct": 0,
                    "yellow_pct": 0,
                    "green_pct": 0,
                    "basis": "answered_non_voicemail",
                    "thresholds": {"red": 15, "green": 40},
                },
                "day_cycle": {},
                "active_calls": [],
                "recent_calls": [],
            }
        cid = str(int(campaign_id))
        active_rows = conn.execute(
            "SELECT v.id, v.company_id, c.company_name, c.phone, v.city, "
            "v.trade_code, v.status, v.started_at, v.answered_at, v.amd_result "
            "FROM voice_calls v LEFT JOIN prospect_companies c ON c.id=v.company_id "
            "WHERE v.campaign_id=? AND v.status IN "
            "('queued','dialing','assistant_pending','assistant_starting','in_call') "
            "ORDER BY v.id ASC",
            (cid,),
        ).fetchall()
        active = []
        for row in active_rows:
            started = _parse_dt(row["started_at"])
            answered = _parse_dt(row["answered_at"])
            active.append(
                {
                    "id": int(row["id"]),
                    "company_id": row["company_id"],
                    "company": row["company_name"] or "",
                    "phone": row["phone"] or "",
                    "city": row["city"] or "",
                    "trade": row["trade_code"] or "",
                    "status": row["status"],
                    "amd_result": row["amd_result"] or "",
                    "elapsed_seconds": (
                        max(0, int((now - started).total_seconds())) if started else 0
                    ),
                    "listen_seconds": (
                        max(0, int((now - answered).total_seconds()))
                        if answered
                        else 0
                    ),
                    "started_at": row["started_at"],
                    "answered_at": row["answered_at"],
                }
            )

        summary_row = conn.execute(
            "SELECT COUNT(*) dialed, "
            "SUM(CASE WHEN answered_at IS NOT NULL THEN 1 ELSE 0 END) answered, "
            "SUM(CASE WHEN answered_at IS NULL THEN 1 ELSE 0 END) unanswered, "
            "SUM(CASE WHEN amd_result='human' THEN 1 ELSE 0 END) human, "
            "SUM(CASE WHEN amd_result='machine' THEN 1 ELSE 0 END) voicemail, "
            "SUM(CASE WHEN amd_result='not_sure' THEN 1 ELSE 0 END) not_sure, "
            "SUM(CASE WHEN intent='opt_out' THEN 1 ELSE 0 END) optouts, "
            "SUM(CASE WHEN answered_at IS NULL OR amd_result='machine' THEN 1 ELSE 0 END) disconnected, "
            "SUM(CASE WHEN hangup_cause IN ('static_tts_failed','render_failed',"
            "'assistant_start_failed','missing_assistant') THEN 1 ELSE 0 END) failed, "
            "AVG(CASE WHEN answered_at IS NOT NULL THEN listen_seconds END) avg_listen, "
            "COALESCE(SUM(cost_cents),0) cost_cents "
            "FROM voice_calls WHERE campaign_id=? AND status<>'dry_run'",
            (cid,),
        ).fetchone()
        summary = dict(summary_row) if summary_row else {}
        for key in (
            "dialed",
            "answered",
            "unanswered",
            "human",
            "voicemail",
            "not_sure",
            "optouts",
            "disconnected",
            "failed",
        ):
            summary[key] = int(summary.get(key) or 0)
        summary["real_attended"] = summary["human"] + summary["not_sure"]
        summary["avg_listen_seconds"] = round(float(summary.get("avg_listen") or 0), 1)
        summary["answer_rate"] = _rate(summary["answered"], summary["dialed"])
        summary["human_rate"] = _rate(summary["human"], summary["dialed"])
        summary["voicemail_rate"] = _rate(summary["voicemail"], summary["dialed"])
        summary["optout_rate"] = _rate(summary["optouts"], summary["dialed"])
        summary["cost_usd"] = round(int(summary.get("cost_cents") or 0) / 100.0, 2)

        thermo_rows = conn.execute(
            "SELECT listen_seconds FROM voice_calls WHERE campaign_id=? "
            "AND status<>'dry_run' AND answered_at IS NOT NULL "
            "AND COALESCE(amd_result,'')<>'machine'",
            (cid,),
        ).fetchall()
        red = yellow = green = 0
        for row in thermo_rows:
            seconds = int(row["listen_seconds"] or 0)
            if seconds < 15:
                red += 1
            elif seconds < 40:
                yellow += 1
            else:
                green += 1
        thermo_total = red + yellow + green
        thermometer = {
            "red": red,
            "yellow": yellow,
            "green": green,
            "total": thermo_total,
            "red_pct": _rate(red, thermo_total),
            "yellow_pct": _rate(yellow, thermo_total),
            "green_pct": _rate(green, thermo_total),
            "basis": "answered_non_voicemail",
            "thresholds": {"red": 15, "green": 40},
        }

        start_hour = int(campaign.get("start_hour_et") or 9)
        interval = max(1, int(campaign.get("call_interval_seconds") or 75))
        pause_every = max(0, int(getattr(settings, "VOICE_PAUSE_EVERY_CALLS", 25) or 0))
        pause_seconds = max(0, int(getattr(settings, "VOICE_PAUSE_SECONDS", 600) or 0))
        quota = int(campaign.get("quota_total") or 0)
        done = int(campaign.get("calls_started") or 0)
        remaining = max(0, quota - done)
        et_tz = ZoneInfo("America/New_York")
        finished = _parse_dt(campaign.get("finished_at"))
        today = now.astimezone(et_tz).date()
        scheduled_start = datetime.combine(
            today, time(hour=start_hour), tzinfo=et_tz
        )

        def simulate(base: datetime, first_done: int, count: int, step: int) -> datetime:
            cursor = base
            call_no = first_done
            for idx in range(count):
                cursor += timedelta(seconds=step)
                call_no += 1
                if pause_every and call_no % pause_every == 0 and idx < count - 1:
                    cursor += timedelta(seconds=pause_seconds)
            return cursor

        if campaign.get("status") == "completed" and finished:
            finish_at = finished
            earliest = latest = finished
        else:
            next_batch = _parse_dt(campaign.get("next_batch_at"))
            if campaign.get("status") == "running":
                base = now
            elif next_batch and next_batch > now:
                # Campanha agendada: o ciclo do dia começa no next_batch,
                # não nas 09:00 de hoje (que já passaram).
                base = next_batch.astimezone(et_tz)
            else:
                base = scheduled_start
            finish_at = simulate(base, done, remaining, interval)
            earliest = simulate(base, done, remaining, max(1, int(interval * 0.8)))
            latest = simulate(base, done, remaining, max(1, int(interval * 1.2)))
        day_cycle = {
            "city": campaign.get("city") or "",
            "planned_calls": quota,
            "calls_done": done,
            "calls_remaining": remaining,
            "start_hour_et": start_hour,
            "started_at": campaign.get("started_at"),
            "finished_at": campaign.get("finished_at"),
            "call_interval_seconds": interval,
            "pause_every": pause_every,
            "pause_seconds": pause_seconds,
            "estimated_finish_at": _iso(finish_at),
            "estimated_finish_earliest": _iso(earliest),
            "estimated_finish_latest": _iso(latest),
        }

        recent_rows = conn.execute(
            "SELECT v.id, v.company_id, c.company_name, v.city, v.trade_code, "
            "v.status, v.intent, v.amd_result, v.duration_seconds, "
            "v.listen_seconds, v.hangup_cause, v.created_at, v.answered_at "
            "FROM voice_calls v LEFT JOIN prospect_companies c ON c.id=v.company_id "
            "WHERE v.campaign_id=? AND v.status<>'dry_run' "
            "ORDER BY v.id DESC LIMIT ?",
            (cid, limit),
        ).fetchall()
        recent = [dict(row) for row in recent_rows]
        return {
            "generated_at": _iso(now),
            "campaign": {
                "id": int(campaign["id"]),
                "name": campaign.get("name"),
                "status": campaign.get("status"),
                "city": campaign.get("city"),
                "quota_total": campaign.get("quota_total"),
                "calls_started": campaign.get("calls_started"),
                "next_batch_at": campaign.get("next_batch_at"),
                "error": campaign.get("error"),
                "include_fallback": campaign.get("include_fallback"),
                "start_hour_et": start_hour,
                "call_interval_seconds": interval,
            },
            "summary": summary,
            "thermometer": thermometer,
            "day_cycle": day_cycle,
            "active_calls": active,
            "recent_calls": recent,
        }
    finally:
        conn.close()


def voice_liquidity(city: str = "", trade: str = "") -> dict:
    """Stock chamável por cidade/trade, com separação exact vs fallback.

    Usa `voice_segments` como stock materializado e desconta as empresas
    chamadas nos últimos 7 dias. `built_at` é exposto para o Admin mostrar a
    idade do stock. A frescura é garantida por TTL/gatilho antes da leitura.
    """
    init()
    ensure_segments_fresh()
    from . import showcase

    city_filter = str(city or "").strip()
    trade_filter = showcase.normalize_trade(trade) if trade.strip() else ""
    selected = ("New York", "Dallas", "Chicago", "Boston")
    conn = get_conn()
    try:
        where = ["city IN (?, ?, ?, ?)"]
        params: list[Any] = list(selected)
        if city_filter:
            where.append("UPPER(TRIM(city))=UPPER(?)")
            params.append(city_filter)
        if trade_filter:
            where.append("LOWER(trade_code)=LOWER(?)")
            params.append(trade_filter)
        rows = conn.execute(
            "SELECT city,state,city_slug,trade_code,total,callable,"
            "showcase_mode,showcase_exact,built_at FROM voice_segments "
            f"WHERE {' AND '.join(where)} ORDER BY city, trade_code",
            tuple(params),
        ).fetchall()
        used_rows = conn.execute(
            "SELECT COALESCE(city,'') city, COALESCE(trade_code,'') trade, "
            "COUNT(DISTINCT company_id) used "
            "FROM voice_calls WHERE COALESCE(campaign_id,'')<>'test_call' "
            "AND status<>'dry_run' "
            "AND datetime(COALESCE(created_at,started_at))>=datetime('now','-7 days') "
            "GROUP BY 1,2"
        ).fetchall()
        used = {
            (str(r["city"]).strip().lower(), str(r["trade"]).strip().lower()): int(
                r["used"] or 0
            )
            for r in used_rows
        }
        now = datetime.now(timezone.utc)
        out = []
        for row in rows:
            exact = (
                str(row["showcase_mode"]) == "dedicated"
                and int(row["showcase_exact"] or 0) >= 5
            )
            callable_n = int(row["callable"] or 0)
            used_n = used.get(
                (str(row["city"]).strip().lower(), str(row["trade_code"]).lower()),
                0,
            )
            available = max(0, callable_n - used_n)
            built = _parse_dt(row["built_at"])
            out.append(
                {
                    "city": row["city"],
                    "state": row["state"],
                    "trade": row["trade_code"],
                    "total": int(row["total"] or 0),
                    "callable": callable_n,
                    "used_7d": used_n,
                    "available": available,
                    "exact": exact,
                    "scope": "exact" if exact else "city_fallback",
                    "showcase_items": int(row["showcase_exact"] or 0),
                    "built_at": row["built_at"],
                    "age_hours": (
                        round((now - built).total_seconds() / 3600.0, 1)
                        if built
                        else None
                    ),
                }
            )
        return {
            "generated_at": _iso(now),
            "cities": list(selected),
            "rows": out,
            "exact_available": sum(
                r["available"] for r in out if r["exact"]
            ),
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
    from . import showcase, voice_taxonomy

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
        ("general contractor", "general_contractor"),
        ("general contractors", "general_contractor"),
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
        if voice_taxonomy.token_matches(lowered, token):
            return code
    # Sem sinal explícito, NÃO inventar general_contractor. A empresa fica
    # unclassified e só entra em campanha se `company_trades` a promover com
    # confiança >=0.80 e licença/fonte verificada.
    return ""


def sync_company_trades(limit: int = 0, min_confidence: float = 0.0) -> dict:
    """Materializa a classificação multi-label em `company_trades`.

    Idempotente: substitui apenas as linhas da empresa. Nunca apaga a empresa
    nem o telefone. Empresas `general_contractor` sem sinal forte ficam com
    confiança baixa (0.40) e não entram em campanha; é o report honesto do
    que ainda não sabemos classificar.
    """
    from . import showcase, voice_taxonomy

    init()
    capped = max(0, int(limit or 0))
    sql = (
        "SELECT id, company_name, trade FROM prospect_companies "
        "ORDER BY id ASC"
    )
    params: tuple = ()
    if capped:
        sql += " LIMIT ?"
        params = (capped,)
    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        inserted = 0
        multi = 0
        unclassified = 0
        for row in rows:
            company_id = int(row["id"])
            primary_raw = str(row["trade"] or "").strip()
            primary = showcase.normalize_trade(primary_raw) or primary_raw
            signals = voice_taxonomy.classify_company(
                row["company_name"],
                primary_trade=primary,
            )
            by_trade = voice_taxonomy.merge_signals(signals)

            if primary and primary in voice_taxonomy.TRADE_TO_CATEGORIES:
                if primary in ("general_contractor", "remodeling"):
                    if primary == "remodeling":
                        by_trade.setdefault(
                            primary,
                            voice_taxonomy.TradeSignal(
                                primary, 0.85, "primary_trade", primary
                            ),
                        )
                    elif primary not in by_trade:
                        by_trade[primary] = voice_taxonomy.TradeSignal(
                            primary, 0.40, "primary_unconfirmed", primary
                        )
                else:
                    current = by_trade.get(primary)
                    if current is None or current.confidence < 0.90:
                        by_trade[primary] = voice_taxonomy.TradeSignal(
                            primary, 0.90, "primary_trade", primary
                        )
            elif primary:
                by_trade.setdefault(
                    primary,
                    voice_taxonomy.TradeSignal(
                        primary, 0.90, "primary_trade", primary
                    ),
                )

            if not by_trade:
                unclassified += 1
                continue
            if len([s for s in by_trade.values() if s.confidence >= 0.80]) > 1:
                multi += 1

            conn.execute(
                "DELETE FROM company_trades WHERE company_id=?",
                (company_id,),
            )
            for trade, signal in by_trade.items():
                if signal.confidence < float(min_confidence or 0):
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO company_trades "
                    "(company_id, trade_code, confidence, source, is_primary, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        company_id,
                        trade,
                        round(float(signal.confidence), 3),
                        signal.source,
                        1 if trade == primary else 0,
                        _iso(),
                    ),
                )
                inserted += 1
        conn.commit()
        return {
            "companies": len(rows),
            "signals": inserted,
            "multi_trade": multi,
            "unclassified": unclassified,
        }
    finally:
        conn.close()


def company_trades_for(company_id: int, min_confidence: float = 0.0) -> list[dict]:
    init()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT trade_code, confidence, source, is_primary, updated_at "
            "FROM company_trades WHERE company_id=? AND confidence>=? "
            "ORDER BY confidence DESC, trade_code ASC",
            (int(company_id), float(min_confidence or 0)),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def company_trade_stats(
    city: str = "",
    state: str = "",
    min_confidence: float = 0.80,
) -> list[dict]:
    """Contagem distinta de empresas por trade classificada (para o planeador)."""
    init()
    where = ["ct.confidence>=?"]
    params: list[Any] = [float(min_confidence or 0)]
    if city.strip():
        where.append("UPPER(TRIM(c.city))=UPPER(?)")
        params.append(city.strip())
    if state.strip():
        where.append("UPPER(TRIM(c.state))=UPPER(?)")
        params.append(state.strip())
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT ct.trade_code AS trade, COUNT(DISTINCT ct.company_id) AS n "
            "FROM company_trades ct "
            "JOIN prospect_companies c ON c.id=ct.company_id "
            f"WHERE {' AND '.join(where)} "
            "GROUP BY ct.trade_code ORDER BY n DESC",
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def bridge_contractor_entities(limit: int = 20000) -> dict:
    """Converte contractor_entities (licenças já ingeridas) em prospect_companies."""
    import csv as _csv

    from . import voice_taxonomy
    from .db import get_connection as get_leads_connection
    from .showcase import CITY_CANON

    leads = get_leads_connection()
    try:
        rows = leads.execute(
            "SELECT legal_name, city, state, phone, email, license, niche_key, "
            "site_snippet, status, quarantine_reason FROM contractor_entities "
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
        signals = voice_taxonomy.classify_company(
            name,
            niche_key=str(row["niche_key"] or ""),
            site_text=str(row["site_snippet"] or ""),
        )
        strong = [s for s in signals if s.confidence >= 0.80]
        if strong:
            trade = strong[0].trade
            note = f"contractor_entities:classified:{strong[0].source}"
        else:
            trade = _infer_trade(name, str(row["niche_key"] or ""))
            note = "contractor_entities:unclassified"
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
                note,
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


def _valid_did(value: object) -> str:
    did = str(value or "").strip()
    return did if len(did) == 12 and did.startswith("+1") else ""


def _did_warmup_caps() -> list[int]:
    raw = str(getattr(settings, "VOICE_DID_WARMUP_CAPS", "") or "")
    caps: list[int] = []
    for part in raw.split(","):
        try:
            value = int(part.strip())
        except (TypeError, ValueError):
            continue
        if value > 0:
            caps.append(value)
    return caps


def reserve_did(
    pool: list[str], day: Optional[str] = None, cap: Optional[int] = None
) -> str:
    """Reserva atomicamente o DID menos usado do pool para o dia.

    Devolve "" quando todos os DIDs do pool atingiram o cap. A reserva e'
    gravada em `voice_did_usage` antes da chamada, para que dois processos
    concorrentes nunca ultrapassem o cap diario.
    """
    init()
    dids: list[str] = []
    for value in pool or []:
        did = _valid_did(value)
        if did and did not in dids:
            dids.append(did)
    if not dids:
        return ""
    from . import timeutil

    day_key = str(day or timeutil.day_key())
    cap_value = int(
        cap
        if cap is not None
        else (getattr(settings, "VOICE_DID_DAILY_CAP", 50) or 50)
    )
    if cap_value <= 0:
        return ""
    warmup_caps = _did_warmup_caps()
    try:
        today = datetime.strptime(day_key, "%Y-%m-%d").date()
    except ValueError:
        today = datetime.now(timezone.utc).date()
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in dids)
        rows = conn.execute(
            "SELECT did, MIN(day) AS first_day, "
            "SUM(CASE WHEN day=? THEN calls ELSE 0 END) AS today_calls "
            f"FROM voice_did_usage WHERE did IN ({placeholders}) "
            "GROUP BY did",
            (day_key, *dids),
        ).fetchall()
        used: dict[str, int] = {}
        first_days: dict[str, str] = {}
        for row in rows:
            did = str(row["did"])
            used[did] = int(row["today_calls"] or 0)
            first_days[did] = str(row["first_day"] or day_key)

        def effective_cap(did: str) -> int:
            first = first_days.get(did) or day_key
            try:
                age = max(
                    0,
                    (today - datetime.strptime(first, "%Y-%m-%d").date()).days,
                )
            except ValueError:
                age = 0
            if warmup_caps and age < len(warmup_caps):
                return min(cap_value, warmup_caps[age])
            return cap_value

        candidates = [
            d for d in dids if used.get(d, 0) < effective_cap(d)
        ]
        if not candidates:
            conn.rollback()
            return ""
        chosen = min(candidates, key=lambda d: (used.get(d, 0), dids.index(d)))
        conn.execute(
            "INSERT INTO voice_did_usage (day, did, calls) VALUES (?, ?, 1) "
            "ON CONFLICT(day, did) DO UPDATE SET "
            "calls=voice_did_usage.calls+1",
            (day_key, chosen),
        )
        conn.commit()
        return chosen
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_did(did: str, day: Optional[str] = None) -> None:
    """Devolve uma reserva que nao chegou a originar chamada."""
    init()
    valid = _valid_did(did)
    if not valid:
        return
    from . import timeutil

    day_key = str(day or timeutil.day_key())
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE voice_did_usage SET calls=MAX(0, calls-1) "
            "WHERE day=? AND did=?",
            (day_key, valid),
        )
        conn.commit()
    finally:
        conn.close()


def did_capacity_status(
    pool: list[str], day: Optional[str] = None, cap: Optional[int] = None
) -> dict:
    """Uso do pool por DID no dia (preflight do auto-dialer)."""
    init()
    dids = []
    for value in pool or []:
        did = _valid_did(value)
        if did and did not in dids:
            dids.append(did)
    from . import timeutil

    day_key = str(day or timeutil.day_key())
    cap_value = int(
        cap
        if cap is not None
        else (getattr(settings, "VOICE_DID_DAILY_CAP", 50) or 50)
    )
    warmup_caps = _did_warmup_caps()
    try:
        today = datetime.strptime(day_key, "%Y-%m-%d").date()
    except ValueError:
        today = datetime.now(timezone.utc).date()
    used: dict[str, int] = {}
    first_days: dict[str, str] = {}
    conn = get_conn()
    try:
        if dids:
            placeholders = ",".join("?" for _ in dids)
            rows = conn.execute(
                "SELECT did, MIN(day) AS first_day, "
                "SUM(CASE WHEN day=? THEN calls ELSE 0 END) AS today_calls "
                f"FROM voice_did_usage WHERE did IN ({placeholders}) "
                "GROUP BY did",
                (day_key, *dids),
            ).fetchall()
            for row in rows:
                did = str(row["did"])
                used[did] = int(row["today_calls"] or 0)
                first_days[did] = str(row["first_day"] or day_key)
    finally:
        conn.close()

    def effective_cap(did: str) -> tuple[int, int]:
        first = first_days.get(did) or day_key
        try:
            age = max(
                0,
                (today - datetime.strptime(first, "%Y-%m-%d").date()).days,
            )
        except ValueError:
            age = 0
        if warmup_caps and age < len(warmup_caps):
            return min(cap_value, warmup_caps[age]), age
        return cap_value, age

    items = []
    for did in dids:
        effective, age = effective_cap(did)
        items.append(
            {
                "did": did,
                "calls": used.get(did, 0),
                "cap": effective,
                "base_cap": cap_value,
                "age_days": age,
            }
        )
    return {
        "day": day_key,
        "cap": cap_value,
        "warmup_caps": warmup_caps,
        "dids": items,
        "total_calls": sum(item["calls"] for item in items),
        "capacity": sum(item["cap"] for item in items),
    }


def create_voice_call(
    company: dict,
    provider: str = "telnyx",
    campaign_id: str = "",
    script_id: str = "",
    city: Optional[str] = None,
    trade_code: Optional[str] = None,
    assistant_id: Optional[str] = None,
    category_code: Optional[str] = None,
    script_scope: Optional[str] = None,
    from_number: Optional[str] = None,
) -> dict:
    init()
    now = _iso()
    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO voice_calls
              (provider, company_id, campaign_id, script_id, phone, city,
               trade_code, category_code, script_scope, assistant_id,
               from_number, status, started_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                provider,
                int(company["id"]) if company.get("id") else None,
                campaign_id,
                script_id,
                normalize_phone(company.get("phone")),
                city or company.get("city"),
                trade_code or company.get("trade"),
                category_code or "",
                script_scope or "",
                assistant_id or "",
                str(from_number or "").strip(),
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


def claim_assistant_start(voice_call_id: int) -> bool:
    """Reclama o arranque do assistant uma unica vez (AMD vs timer)."""
    init()
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE voice_calls SET status='assistant_starting' "
            "WHERE id=? AND status='assistant_pending'",
            (int(voice_call_id),),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def claim_fallback_playback(voice_call_id: int) -> bool:
    """Reclama o playback do MP3 uma unica vez (conversation.ended vs timer)."""
    init()
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE voice_calls SET fallback_audio_started_at=?, "
            "status='fallback_playing' "
            "WHERE id=? AND fallback_audio_started_at IS NULL",
            (
                datetime.now(timezone.utc).isoformat(),
                int(voice_call_id),
            ),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def voice_daily_usage() -> dict:
    """Uso de voz do dia (America/New_York), sem test_call/dry_run."""
    from ..config import settings
    from .timeutil import day_key, day_start_utc

    day = day_key(_utc_now())
    since = day_start_utc(day)
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT status, cost_cents FROM voice_calls "
            "WHERE datetime(created_at) >= datetime(?) "
            "AND COALESCE(provider,'')='telnyx' "
            "AND COALESCE(campaign_id,'') <> 'test_call' "
            "AND status <> 'dry_run'",
            (since,),
        ).fetchall()
    finally:
        conn.close()
    calls = len(rows)
    spent_cents = sum(int(row["cost_cents"] or 0) for row in rows)
    active = sum(
        1
        for row in rows
        if str(row["status"] or "") not in ("ended", "failed")
    )
    estimate = max(
        0, int(getattr(settings, "VOICE_ESTIMATED_CALL_COST_CENTS", 25) or 0)
    )
    reserved_cents = active * estimate
    estimated_total = spent_cents + reserved_cents
    budget_cents = max(
        0, int(round(float(getattr(settings, "VOICE_MAX_DAILY_BUDGET_USD", 5.0) or 0) * 100))
    )
    max_calls = max(
        0, int(getattr(settings, "VOICE_MAX_CALLS_PER_DAY", 100) or 0)
    )
    return {
        "day": day,
        "calls": calls,
        "spent_cents": spent_cents,
        "active_calls": active,
        "reserved_cents": reserved_cents,
        "estimated_total_cents": estimated_total,
        "budget_cents": budget_cents,
        "budget_remaining_cents": (
            max(0, budget_cents - estimated_total) if budget_cents > 0 else None
        ),
        "max_calls_per_day": max_calls,
        "calls_remaining": (
            max(0, max_calls - calls) if max_calls > 0 else None
        ),
    }


def campaign_budget_status(campaign_id: int) -> dict:
    """Tetos de campanha: total, diario e dias. Inclui reserva de ativas."""
    from ..config import settings
    from .timeutil import day_key, day_start_utc

    campaign = get_campaign(int(campaign_id))
    if not campaign:
        return {"ok": False, "reason": "campaign_not_found"}
    now = _utc_now()
    started = parse_dt(
        campaign.get("started_at") or campaign.get("created_at")
    ) or now
    days_elapsed = max(1, (now - started).days + 1)
    max_days = max(0, int(campaign.get("max_days") or 0))
    day = day_key(now)
    since = day_start_utc(day)
    estimate = max(
        0, int(getattr(settings, "VOICE_ESTIMATED_CALL_COST_CENTS", 25) or 0)
    )
    conn = get_conn()
    try:
        all_rows = conn.execute(
            "SELECT status, cost_cents FROM voice_calls "
            "WHERE campaign_id=? AND COALESCE(provider,'')='telnyx' "
            "AND status <> 'dry_run'",
            (str(int(campaign_id)),),
        ).fetchall()
        today_rows = conn.execute(
            "SELECT status, cost_cents FROM voice_calls "
            "WHERE campaign_id=? AND COALESCE(provider,'')='telnyx' "
            "AND status <> 'dry_run' AND datetime(created_at) >= datetime(?)",
            (str(int(campaign_id)), since),
        ).fetchall()
    finally:
        conn.close()

    def _totals(rows) -> tuple[int, int, int, int]:
        spent = sum(int(row["cost_cents"] or 0) for row in rows)
        active = sum(
            1
            for row in rows
            if str(row["status"] or "") not in ("ended", "failed")
        )
        reserved = active * estimate
        return spent, active, reserved, spent + reserved

    total_spent, total_active, total_reserved, total_estimated = _totals(all_rows)
    daily_spent, daily_active, daily_reserved, daily_estimated = _totals(today_rows)
    total_budget_cents = max(
        0, int(round(float(campaign.get("budget_total_usd") or 0) * 100))
    )
    daily_budget_cents = max(
        0, int(round(float(campaign.get("budget_daily_usd") or 0) * 100))
    )

    blocked_reason = ""
    blocked_detail = ""
    if max_days > 0 and days_elapsed > max_days:
        blocked_reason = "days_limit_reached"
        blocked_detail = f"Campanha no dia {days_elapsed}; limite {max_days}."
    elif (
        total_budget_cents > 0
        and total_estimated + estimate > total_budget_cents
    ):
        blocked_reason = "total_budget_reached"
        blocked_detail = (
            f"Orçamento total: ${total_estimated / 100:.2f} usados/reservados "
            f"de ${total_budget_cents / 100:.2f}."
        )
    elif (
        daily_budget_cents > 0
        and daily_estimated + estimate > daily_budget_cents
    ):
        blocked_reason = "daily_budget_reached"
        blocked_detail = (
            f"Orçamento diário: ${daily_estimated / 100:.2f} usados/reservados "
            f"de ${daily_budget_cents / 100:.2f}."
        )

    return {
        "ok": True,
        "campaign_id": int(campaign_id),
        "day": day,
        "days_elapsed": days_elapsed,
        "max_days": max_days,
        "days_remaining": (
            max(0, max_days - days_elapsed + 1) if max_days > 0 else None
        ),
        "total_budget_cents": total_budget_cents,
        "total_spent_cents": total_spent,
        "total_active_calls": total_active,
        "total_reserved_cents": total_reserved,
        "total_estimated_cents": total_estimated,
        "total_remaining_cents": (
            max(0, total_budget_cents - total_estimated)
            if total_budget_cents > 0
            else None
        ),
        "daily_budget_cents": daily_budget_cents,
        "daily_spent_cents": daily_spent,
        "daily_active_calls": daily_active,
        "daily_reserved_cents": daily_reserved,
        "daily_estimated_cents": daily_estimated,
        "daily_remaining_cents": (
            max(0, daily_budget_cents - daily_estimated)
            if daily_budget_cents > 0
            else None
        ),
        "blocked_reason": blocked_reason,
        "blocked_detail": blocked_detail,
    }


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
        "assistant_id",
        "fallback_audio_started_at",
        "amd_result",
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


def delete_voice_call(voice_call_id: int) -> bool:
    """Remove uma chamada que falhou antes de sair para a Telnyx.

    Erros http_402/403/429/5xx/network_error nao chegaram a ser discados;
    se ficassem em `voice_calls`, a empresa era excluida dos candidatos e a
    tentativa contava para o teto diario.
    """
    init()
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM voice_calls WHERE id=? "
            "AND COALESCE(provider_call_id,'')='' "
            "AND status IN ('failed','queued')",
            (int(voice_call_id),),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_voice_call_by_provider_id(provider_call_id: str) -> Optional[dict]:
    """Encontra a chamada pelo call_control_id da Telnyx (usado pelas tools)."""
    value = str(provider_call_id or "").strip()
    if not value:
        return None
    init()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM voice_calls WHERE provider_call_id=? "
            "ORDER BY id DESC LIMIT 1",
            (value,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_company_email(company_id: int, email: str) -> bool:
    """Guarda o email ditado na chamada, para reutilizar no envio da vitrine."""
    value = str(email or "").strip().lower()
    if not value or "@" not in value or not company_id:
        return False
    init()
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE prospect_companies SET email=?, updated_at=? WHERE id=?",
            (value, _iso(), int(company_id)),
        )
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def mark_company_do_not_call(company_id: int, reason: str = "caller_opt_out") -> bool:
    if not company_id:
        return False
    init()
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE prospect_companies SET status='do_not_call', notes=?, "
            "updated_at=? WHERE id=?",
            (str(reason)[:200], _iso(), int(company_id)),
        )
        conn.commit()
        return bool(cur.rowcount)
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
