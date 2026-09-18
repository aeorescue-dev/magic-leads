import os
import smtplib
import socket
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional

import anyio
import httpx

from ..config import settings
from ..models.schemas import EnrichedLead
from ..utils.logger import logger
from .access import (
    STATUS_ACTIVE,
    STATUS_TRIAL,
    is_access_active,
    normalize_status,
    parse_dt,
)
from .phone_lookup import PhoneResult, phone_lookup_service


def _not_junk_where(alias: str = "") -> str:
    """Filtro de não-serviço: mantém apenas ruído urbano que NÃO corresponde aos 16 ofícios
    da plataforma (estacionamento, tráfego/sinalização, veículos abandonados, TPW)."""
    prefix = f"{alias}." if alias else ""
    junk_terms = [
        "parking enforcement", "traffic signal", "general traffic", "signal",
        "sign repair", "missing sign", "bike rack", "boston bikes",
        "abandoned vehicle", "abandoned bicycle", "abandoned bike", "illegal auto",
        "dead animal", "hydrant", "towing", "tpw", "transportation",
        "debug test", "test issue", "contractors complaint", "fair housing",
        "needle", "work w/out permit", "working beyond hours",
    ]
    conditions = []
    for term in junk_terms:
        conditions.append(f"LOWER(COALESCE({prefix}issue_category, '')) NOT LIKE '%{term}%'")
        conditions.append(f"LOWER(COALESCE({prefix}issue_description, '')) NOT LIKE '%{term}%'")
        conditions.append(f"LOWER(COALESCE({prefix}descriptor, '')) NOT LIKE '%{term}%'")
    return " AND ".join(conditions)


# As 16 categorias de ofícios da plataforma (modelo de negócio).
_TRADE_CATEGORIES = (
    "Roof", "Structure", "Plumbing", "Grass", "Paint", "Permit_Rejected",
    "Heating", "Electrical", "Elevator", "Gas", "Rodent", "Mold", "Lead",
    "Unsanitary", "Door_Window", "Debris",
)

# Status considerados "chamado aberto / em andamento" (gatilho preditivo).
_OPEN_STATUSES = (
    "open", "new", "in progress", "in_progress", "assigned", "active",
    "approved", "issued", "pending", "acknowledged", "referred", "scheduled",
    "investigation", "awaiting", "awaiting assignment",
)


def _address_where(alias: str = "") -> str:
    """Endereço real presente (exclui só coordenadas/curtos)."""
    prefix = f"{alias}." if alias else ""
    return f"TRIM({prefix}address) IS NOT NULL AND LENGTH(TRIM({prefix}address)) > 8"


def _category_where(alias: str = "") -> str:
    """Lead mapeado para um dos 16 ofícios."""
    prefix = f"{alias}." if alias else ""
    values = ", ".join(f"'{c}'" for c in _TRADE_CATEGORIES)
    return f"{prefix}issue_category IN ({values})"


def _trigger_where(alias: str = "") -> str:
    """Gatilho preditivo: obrigação legal (violação/multa/permisção) OU chamado 311
    aberto/em andamento (intenção direta de resolução)."""
    prefix = f"{alias}." if alias else ""
    statuses = ", ".join(f"'{s}'" for s in _OPEN_STATUSES)
    return (
        f"(LOWER({prefix}case_status) IN ({statuses}) "
        f"OR {prefix}source_type IN ('permit', 'dob_violation', 'tax_delinquency'))"
    )


def _qualified_where(alias: str = "") -> str:
    """Lead qualificado: [Endereço + Categoria dos 16 Ofícios + Gatilho Preditivo],
    sem exigir department/descriptor/neighborhood."""
    parts = [
        _address_where(alias),
        _category_where(alias),
        _trigger_where(alias),
        _not_junk_where(alias),
    ]
    return " AND ".join(parts)

# Banco de dados SQLite: em produção DEVE apontar para volume persistente (Railway).
# Prioridade: LEADS_DB_PATH > DATA_DIR/leads.db > data/leads.db (repo, dev local).
# O Dockerfile define DATA_DIR=/data (volume persistente); sem volume montado os dados
# são perdidos a cada redeploy. Em produção multi-tenant, migrar para Postgres/Supabase.
_REPO_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "leads.db"
)
_DATA_DIR = os.environ.get("DATA_DIR")
if os.environ.get("LEADS_DB_PATH"):
    DB_PATH = os.environ["LEADS_DB_PATH"]
elif _DATA_DIR:
    DB_PATH = os.path.join(_DATA_DIR, "leads.db")
else:
    DB_PATH = _REPO_DB_PATH
logger.info(f"SQLite DB_PATH resolvido para: {DB_PATH}")

DEFAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  company_name TEXT NOT NULL,
  plan TEXT DEFAULT 'free',
  subscription_status TEXT DEFAULT 'expired',
  trial_started_at TEXT,
  trial_ends_at TEXT,
  is_trial_active INTEGER DEFAULT 1,
  subscription_ends_at TEXT,
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  plan_until TEXT,
  score INTEGER DEFAULT 0,
  leads_taken INTEGER DEFAULT 0,
  conversions INTEGER DEFAULT 0,
  cities_filter TEXT DEFAULT NULL,
  push_enabled INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  used INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_password_reset_token ON password_reset_tokens (token_hash);
CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens (user_id);

CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  external_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  address TEXT NOT NULL,
  city TEXT NOT NULL,
  state TEXT NOT NULL,
  zip_code TEXT,
  lat REAL,
  lng REAL,
  county TEXT,
  issue_category TEXT NOT NULL,
  issue_description TEXT,
  urgency_level TEXT DEFAULT 'medium',
  owner_name TEXT,
  owner_phone TEXT,
  owner_email TEXT,
  owner_status TEXT DEFAULT 'unknown',
  mailing_address TEXT,
  date_reported TEXT NOT NULL,
  date_first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
  image_url TEXT,
  source_url TEXT,
  is_validated INTEGER DEFAULT 0,
  validation_error TEXT,
  address_unit TEXT,
  address_type TEXT,
  address_street TEXT,
  address_city TEXT,
  address_state TEXT,
  address_zip TEXT,
  case_title TEXT,
  subject TEXT,
  reason TEXT,
  type TEXT,
  queue TEXT,
  department TEXT,
  closure_reason TEXT,
  case_status TEXT,
  on_time TEXT,
  sla_target_dt TEXT,
  closed_dt TEXT,
  submitted_photo TEXT,
  closed_photo TEXT,
  source TEXT,
  neighborhood TEXT,
  ward TEXT,
  precinct TEXT,
  descriptor TEXT,
  resolution_description TEXT,
  resolution_action_updated_date TEXT,
  status TEXT DEFAULT 'new',
  favorited INTEGER DEFAULT 0,
  lead_status TEXT DEFAULT 'available',
  reserved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  reserved_until TEXT,
  contact_count INTEGER DEFAULT 0,
  converted_by INTEGER,
  converted_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(external_id, source_type),
  UNIQUE(address, city)
);

CREATE TABLE IF NOT EXISTS lead_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  note TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lead_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  detail TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
  read INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_interests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category TEXT NOT NULL,
  UNIQUE(user_id, category)
);

CREATE TABLE IF NOT EXISTS user_favorites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, lead_id)
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint TEXT NOT NULL UNIQUE,
  p256dh TEXT NOT NULL,
  auth TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, endpoint)
);

CREATE TABLE IF NOT EXISTS user_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,
  device_info TEXT,
  ip_address TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_active_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(token_hash)
);

CREATE TABLE IF NOT EXISTS lead_holds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  held_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TEXT NOT NULL,
  release_reason TEXT,
  release_note TEXT,
  released_at TEXT,
  status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS contractor_release_tracking (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contractor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  release_count INTEGER DEFAULT 1,
  release_reasons TEXT,
  last_released_at TEXT DEFAULT CURRENT_TIMESTAMP,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(contractor_id, lead_id)
);

CREATE TABLE IF NOT EXISTS contractor_penalties (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contractor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  penalty_type TEXT,
  reason TEXT,
  penalty_level TEXT DEFAULT 'warning',
  penalty_expires_at TEXT,
  is_active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_daily_stats (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  leads_used INTEGER DEFAULT 0,
  leads_limit INTEGER DEFAULT 10,
  reset_at TEXT,
  PRIMARY KEY (user_id, date)
);

CREATE TABLE IF NOT EXISTS lead_reveals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  revealed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revealed_date TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  contact_flagged INTEGER DEFAULT 0,
  notified_30 INTEGER DEFAULT 0,
  notified_45 INTEGER DEFAULT 0,
  returned_to_pool INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contractor_metrics (
  contractor_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  releases_this_month INTEGER DEFAULT 0,
  suspicious_releases INTEGER DEFAULT 0,
  penalty_level INTEGER DEFAULT 0,
  penalty_until TEXT,
  last_penalty_reason TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lead_case_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  external_id TEXT,
  case_title TEXT,
  descriptor TEXT,
  subject TEXT,
  reason TEXT,
  case_status TEXT,
  department TEXT,
  opened_at TEXT,
  closed_at TEXT,
  resolution_description TEXT,
  closure_reason TEXT,
  source TEXT,
  source_url TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(lead_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_case_history_lead ON lead_case_history (lead_id);

CREATE INDEX IF NOT EXISTS idx_leads_city_reported ON leads (city, date_reported);
CREATE INDEX IF NOT EXISTS idx_leads_city_type_reported ON leads (city, source_type, date_reported DESC);
CREATE INDEX IF NOT EXISTS idx_leads_date_reported ON leads (date_reported);
CREATE INDEX IF NOT EXISTS idx_leads_lead_status ON leads (lead_status);
CREATE INDEX IF NOT EXISTS idx_leads_source ON leads (source_type);
CREATE INDEX IF NOT EXISTS idx_leads_category ON leads (issue_category);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads (owner_phone);
CREATE INDEX IF NOT EXISTS idx_users_plan_until ON users (plan_until);
CREATE INDEX IF NOT EXISTS idx_notes_lead ON lead_notes (lead_id);
CREATE INDEX IF NOT EXISTS idx_events_lead ON lead_events (lead_id);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications (created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications (read);
CREATE INDEX IF NOT EXISTS idx_interest_user ON user_interests (user_id);

CREATE TABLE IF NOT EXISTS scraper_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  trigger TEXT DEFAULT 'manual',
  started_at TEXT,
  finished_at TEXT,
  status TEXT DEFAULT 'running',
  inserted INTEGER DEFAULT 0,
  total_raw INTEGER DEFAULT 0,
  cities_covered INTEGER DEFAULT 0,
  error TEXT,
  note TEXT,
  UNIQUE(run_id)
);

CREATE TABLE IF NOT EXISTS city_health (
  city TEXT PRIMARY KEY,
  failure_count INTEGER DEFAULT 0,
  circuit_open_until TEXT,
  last_success_at TEXT,
  anomaly_counter INTEGER DEFAULT 0,
  last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stripe_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  event_type TEXT,
  user_id INTEGER,
  processed_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de auditoria de anomalias de fluxo (Dead Man's Switch).
CREATE TABLE IF NOT EXISTS system_alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level TEXT DEFAULT 'warning',
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  context TEXT,
  acknowledged INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_system_alerts_created ON system_alerts (created_at);
CREATE INDEX IF NOT EXISTS idx_system_alerts_code ON system_alerts (code);
"""


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        # Evita "database is locked" sob concorrência (scraper + API + webhook).
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except sqlite3.OperationalError:
        pass  # fs read-only (serverless) — segue com leitura
    return conn


def _seed_from_bundle(conn: sqlite3.Connection, force: bool = False) -> bool:
    """Se o banco está vazio/inexistente e existe seed versionado, restaura-o.
    Com force=1 (env LEADS_RESET_ON_BOOT) sobrescreve sempre, uma vez.
    Retorna True se restaurou (o chamador deve reabrir a conexão)."""
    if not force:
        try:
            count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        except sqlite3.OperationalError:
            count = 0
        if count > 0:
            return False
    seed = os.environ.get("LEADS_SEED_FILE", "")
    if not seed or not os.path.exists(seed):
        return False
    logger.info(f"Banco vazio — restaurando seed de {seed}")
    conn.close()
    data = open(seed, "rb").read()
    if seed.endswith(".gz"):
        import gzip
        data = gzip.decompress(data)
    with open(DB_PATH, "wb") as f:
        f.write(data)
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except OSError:
            pass
    if force:
        os.environ.pop("LEADS_RESET_ON_BOOT", None)
    return True


def _ensure_demo_user() -> None:
    """Garante que o usuário demo existe e tem a senha do ambiente (DEMO_PASSWORD).
    Idempotente; só atualiza o hash quando ele não confere."""
    import os
    demo_email = os.environ.get("DEMO_EMAIL", "demo@magicleads.app").lower()
    demo_password = os.environ.get("DEMO_PASSWORD", "")
    if not demo_password:
        return
    try:
        from .security import hash_password, verify_password
    except Exception:
        return
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (demo_email,)
        ).fetchone()
        if row:
            if row["password_hash"] and verify_password(demo_password, row["password_hash"]):
                return
            pwd_hash = hash_password(demo_password)
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_hash, row["id"]))
            logger.info(f"Senha do usuário demo {demo_email} atualizada")
        else:
            pwd_hash = hash_password(demo_password)
            conn.execute(
                "INSERT INTO users (email, password_hash, company_name, plan, subscription_status, plan_until) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (demo_email, pwd_hash, "Contratante Demo", "free", "expired", None),
            )
            logger.info(f"Usuário demo {demo_email} criado")
        conn.commit()
    except Exception as e:
        logger.warning(f"Erro ao garantir usuário demo: {e}")
    finally:
        conn.close()


def init_db() -> None:
    """Cria o schema se não existir (tolerante a fs read-only em produção)."""
    force_reset = os.environ.get("LEADS_RESET_ON_BOOT") == "1"
    for _ in range(2):
        try:
            conn = get_connection()
            try:
                if _seed_from_bundle(conn, force=force_reset and _ == 0):
                    conn = get_connection()
                conn.executescript(DEFAULT_SCHEMA)
                _migrate_schema(conn)
                conn.commit()
            finally:
                conn.close()
            _ensure_demo_user()
            logger.info(f"Banco SQLite pronto em {DB_PATH}")
            return
        except sqlite3.OperationalError:
            logger.warning("Filesystem read-only — usando banco versionado (leitura apenas).")
            return


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Adiciona colunas novas que não existiam em bancos antigos (idempotente)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
    if "status" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN status TEXT DEFAULT 'new'")
    if "favorited" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN favorited INTEGER DEFAULT 0")
    if "lead_status" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN lead_status TEXT DEFAULT 'available'")
    if "reserved_by" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN reserved_by INTEGER")
    if "reserved_until" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN reserved_until TEXT")
    if "contact_count" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN contact_count INTEGER DEFAULT 0")
    if "converted_by" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN converted_by INTEGER")
    if "converted_at" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN converted_at TEXT")
    if "mailing_address" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN mailing_address TEXT")
    extra_cols = {
        "address_unit": "TEXT",
        "address_type": "TEXT",
        "address_street": "TEXT",
        "address_city": "TEXT",
        "address_state": "TEXT",
        "address_zip": "TEXT",
        "case_title": "TEXT",
        "subject": "TEXT",
        "reason": "TEXT",
        "type": "TEXT",
        "queue": "TEXT",
        "department": "TEXT",
        "closure_reason": "TEXT",
        "case_status": "TEXT",
        "on_time": "TEXT",
        "sla_target_dt": "TEXT",
        "closed_dt": "TEXT",
        "submitted_photo": "TEXT",
        "closed_photo": "TEXT",
        "source": "TEXT",
        "neighborhood": "TEXT",
        "ward": "TEXT",
        "precinct": "TEXT",
        "descriptor": "TEXT",
        "resolution_description": "TEXT",
        "resolution_action_updated_date": "TEXT",
    }
    for name, ctype in extra_cols.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {name} {ctype}")

    deduped_keys = {
        "idx_leads_address_city": "(address, city)",
        "idx_leads_ext_src": "(external_id, source_type)",
    }
    for idx_name, idx_cols in deduped_keys.items():
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (idx_name,)
        ).fetchone()
        if not exists:
            group_cols = idx_cols.strip("()")
            conn.execute(
                f"DELETE FROM leads WHERE id NOT IN (SELECT MIN(id) FROM leads GROUP BY {group_cols})"
            )
            try:
                conn.execute(f"CREATE UNIQUE INDEX {idx_name} ON leads {idx_cols}")
            except sqlite3.OperationalError:
                pass

    user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if user_cols and "score" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN score INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE users ADD COLUMN leads_taken INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE users ADD COLUMN conversions INTEGER DEFAULT 0")
    if user_cols and "cities_filter" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN cities_filter TEXT DEFAULT NULL")
    if user_cols and "push_enabled" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN push_enabled INTEGER DEFAULT 0")

    event_cols = {r["name"] for r in conn.execute("PRAGMA table_info(lead_events)").fetchall()}
    if event_cols:
        if "user_id" not in event_cols:
            conn.execute("ALTER TABLE lead_events ADD COLUMN user_id INTEGER")
        if "detail" not in event_cols:
            conn.execute("ALTER TABLE lead_events ADD COLUMN detail TEXT")

    notif_cols = {r["name"] for r in conn.execute("PRAGMA table_info(notifications)").fetchall()}
    if notif_cols and "user_id" not in notif_cols:
        conn.execute("ALTER TABLE notifications ADD COLUMN user_id INTEGER")
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id, read)",
    ):
        try:
            conn.execute(index_sql)
        except sqlite3.OperationalError:
            pass

    notes_cols = {r["name"] for r in conn.execute("PRAGMA table_info(lead_notes)").fetchall()}
    if notes_cols and "user_id" not in notes_cols:
        conn.execute("ALTER TABLE lead_notes ADD COLUMN user_id INTEGER")


class _SmtpConnect(smtplib.SMTP):
    """Conexão SMTP forçando IPv4 (containers Docker/Railway costumam não ter
    egresso IPv6 e falham com 'Network is unreachable'/ENETUNREACH quando o
    getaddrinfo devolve endereço IPv6 primeiro).

    Se `context` for passado, o socket já nasce com TLS (equivale a SMTP_SSL,
    porta 465). Sem context, é uma conexão plana para STARTTLS (porta 587).
    """

    def __init__(self, host="", port=0, local_hostname=None, timeout=None,
                 context=None, source_address=None):
        self._tls_context = context
        super().__init__(
            host=host, port=port, local_hostname=local_hostname,
            timeout=timeout, source_address=source_address,
        )

    def _get_socket(self, host, port, timeout):
        last_err = None
        for _, socktype, proto, _, sockaddr in socket.getaddrinfo(
            host, port, socket.AF_INET, socket.SOCK_STREAM
        ):
            try:
                sock = socket.socket(socket.AF_INET, socktype, proto)
                sock.settimeout(timeout)
                sock.connect(sockaddr)
                if self._tls_context is not None:
                    sock = self._tls_context.wrap_socket(sock, server_hostname=self._host)
                return sock
            except OSError as err:
                last_err = err
        raise last_err


class DatabaseService:
    """Interface type-safe sobre o SQLite (espelha o antigo SupabaseService)."""

    def __init__(self):
        init_db()

    def insert_lead(self, lead: EnrichedLead) -> bool:
        """Insere lead no banco; ignora se (external_id, source_type) já existe."""
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO leads (
                  external_id, source_type, address, city, state, zip_code,
                  lat, lng, county, issue_category, issue_description, urgency_level,
                  owner_name, owner_phone, owner_email, owner_status, mailing_address,
                  date_reported, image_url, source_url, is_validated, created_at,
                  address_unit, address_type, address_street, address_city, address_state, address_zip,
                  case_title, subject, reason, type, queue, department,
                  closure_reason, case_status, on_time, sla_target_dt, closed_dt,
                  submitted_photo, closed_photo, source, neighborhood, ward, precinct,
                  descriptor, resolution_description, resolution_action_updated_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(address, city) DO UPDATE SET
                  external_id=excluded.external_id,
                  source_type=excluded.source_type,
                  state=excluded.state,
                  zip_code=excluded.zip_code,
                  lat=excluded.lat,
                  lng=excluded.lng,
                  county=excluded.county,
                  issue_category=excluded.issue_category,
                  issue_description=excluded.issue_description,
                  urgency_level=excluded.urgency_level,
                  owner_name=CASE WHEN excluded.owner_name IS NOT NULL AND excluded.owner_name != '' THEN excluded.owner_name ELSE leads.owner_name END,
                  owner_phone=CASE WHEN excluded.owner_phone IS NOT NULL AND excluded.owner_phone != '' THEN excluded.owner_phone ELSE leads.owner_phone END,
                  owner_email=CASE WHEN excluded.owner_email IS NOT NULL AND excluded.owner_email != '' THEN excluded.owner_email ELSE leads.owner_email END,
                  owner_status=CASE WHEN excluded.owner_status IS NOT NULL AND excluded.owner_status != '' THEN excluded.owner_status ELSE leads.owner_status END,
                  mailing_address=CASE WHEN excluded.mailing_address IS NOT NULL AND excluded.mailing_address != '' THEN excluded.mailing_address ELSE leads.mailing_address END,
                  date_reported=excluded.date_reported,
                  image_url=excluded.image_url,
                  source_url=excluded.source_url,
                  is_validated=excluded.is_validated,
                  updated_at=datetime('now'),
                  address_unit=excluded.address_unit,
                  address_type=excluded.address_type,
                  address_street=excluded.address_street,
                  address_city=excluded.address_city,
                  address_state=excluded.address_state,
                  address_zip=excluded.address_zip,
                  case_title=excluded.case_title,
                  subject=excluded.subject,
                  reason=excluded.reason,
                  type=excluded.type,
                  queue=excluded.queue,
                  department=excluded.department,
                  closure_reason=excluded.closure_reason,
                  case_status=excluded.case_status,
                  on_time=excluded.on_time,
                  sla_target_dt=excluded.sla_target_dt,
                  closed_dt=excluded.closed_dt,
                  submitted_photo=excluded.submitted_photo,
                  closed_photo=excluded.closed_photo,
                  source=excluded.source,
                  neighborhood=excluded.neighborhood,
                  ward=excluded.ward,
                  precinct=excluded.precinct,
                  descriptor=excluded.descriptor,
                  resolution_description=excluded.resolution_description,
                  resolution_action_updated_date=excluded.resolution_action_updated_date
                """,
                (
                    lead.external_id, lead.source_type.value, lead.address, lead.city,
                    lead.state, lead.zip_code, lead.lat, lead.lng, lead.county,
                    lead.issue_category.value, lead.issue_description, lead.urgency_level.value,
                    lead.owner_name, lead.owner_phone, lead.owner_email, lead.owner_status,
                    getattr(lead, "mailing_address", None),
                    lead.date_reported.isoformat(), lead.image_url, lead.source_url,
                    1 if getattr(lead, "is_validated", False) else 0, datetime.now().isoformat(),
                    lead.address_unit, lead.address_type, lead.address_street, lead.address_city, lead.address_state, lead.address_zip,
                    lead.case_title, lead.subject, lead.reason, lead.type, lead.queue, lead.department,
                    lead.closure_reason, lead.case_status, lead.on_time, lead.sla_target_dt, lead.closed_dt,
                    lead.submitted_photo, lead.closed_photo, lead.source, lead.neighborhood, lead.ward, lead.precinct,
                    lead.descriptor, lead.resolution_description, lead.resolution_action_updated_date,
                ),
            )
            conn.commit()
            logger.info(f"Lead inserido/atualizado: {lead.external_id}")
            return True
        except Exception as e:
            logger.error(f"Erro ao inserir lead: {e}")
            return False
        finally:
            conn.close()

    def insert_lead_new(self, lead: EnrichedLead) -> Optional[dict]:
        """Insere lead somente se ainda não existir (por external_id+source_type).

        Retorna um dict com {id, issue_category, address, city} se o lead era
        NOVO (para o fan-out de notificações por interesse), ou None se já
        existia (apenas atualizado — não gera alerta de 'novo lead').
        """
        conn = get_connection()
        try:
            # Use external_id + source_type for deduplication (matches UNIQUE constraint)
            exist = conn.execute(
                "SELECT id FROM leads WHERE external_id = ? AND source_type = ?",
                (lead.external_id, lead.source_type.value if hasattr(lead.source_type, 'value') else str(lead.source_type)),
            ).fetchone()
            if exist:
                # Lead exists, update it with new data
                self.insert_lead(lead)
                conn.close()
                return None
            self.insert_lead(lead)
            conn2 = get_connection()
            try:
                row = conn2.execute(
                    "SELECT id, issue_category, address, city FROM leads WHERE external_id = ? AND source_type = ?",
                    (lead.external_id, lead.source_type.value if hasattr(lead.source_type, 'value') else str(lead.source_type)),
                ).fetchone()
                return dict(row) if row else None
            finally:
                conn2.close()
        except Exception as e:
            logger.error(f"Erro ao inserir lead novo: {e}")
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def update_lead_historical(self, external_id: str, city: str, lead: "EnrichedLead") -> bool:
        """Atualiza os campos históricos de um lead existente, localizado por external_id+city."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                UPDATE leads SET
                  case_title=?, subject=?, reason=?, type=?, queue=?, department=?,
                  closure_reason=?, case_status=?, on_time=?, sla_target_dt=?, closed_dt=?,
                  submitted_photo=?, closed_photo=?, source=?, neighborhood=?, ward=?,
                  precinct=?, descriptor=?, resolution_description=?, resolution_action_updated_date=?
                WHERE external_id=? AND city=?
                """,
                (
                    lead.case_title, lead.subject, lead.reason, lead.type, lead.queue, lead.department,
                    lead.closure_reason, lead.case_status, lead.on_time, lead.sla_target_dt, lead.closed_dt,
                    lead.submitted_photo, lead.closed_photo, lead.source, lead.neighborhood, lead.ward,
                    lead.precinct, lead.descriptor, lead.resolution_description, lead.resolution_action_updated_date,
                    external_id, city,
                ),
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Erro ao atualizar histórico do lead {external_id}: {e}")
            return False
        finally:
            conn.close()

    def get_leads_by_city(self, city: str, limit: int = 100, source_type: Optional[str] = None, category: Optional[str] = None) -> List[dict]:
        """Retorna leads mais recentes de uma cidade com filtros opcionais no SQL."""
        conn = get_connection()
        try:
            sql = "SELECT * FROM leads WHERE city = ?"
            params = [city]

            if source_type:
                sql += " AND source_type = ?"
                params.append(source_type)
            if category:
                sql += " AND issue_category = ?"
                params.append(category)

            sql += " ORDER BY date_reported DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_all_leads(self, limit: int = 100) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM leads ORDER BY date_reported DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def count_leads(self) -> int:
        conn = get_connection()
        try:
            return conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
        finally:
            conn.close()

    def get_lead_by_id(self, lead_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM leads WHERE id = ?", (lead_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_lead_status(self, lead_id: int, status: str) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE leads SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, lead_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def toggle_favorite(self, lead_id: int) -> Optional[int]:
        conn = get_connection()
        try:
            cur = conn.execute("UPDATE leads SET favorited = 1 - favorited WHERE id = ?", (lead_id,))
            conn.commit()
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT favorited FROM leads WHERE id = ?", (lead_id,)
            ).fetchone()
            return int(row["favorited"]) if row else None
        finally:
            conn.close()

    def toggle_favorite_for_user(self, user_id: int, lead_id: int) -> Optional[bool]:
        """Alterna o status de favorito de um lead para um usuário específico.
        Retorna True se favoritado, False se desfavoritado, None se lead não encontrado."""
        conn = get_connection()
        try:
            # Verifica se o lead existe
            lead = conn.execute("SELECT id FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not lead:
                return None

            # Verifica se já é favorito
            existing = conn.execute(
                "SELECT id FROM user_favorites WHERE user_id = ? AND lead_id = ?",
                (user_id, lead_id)
            ).fetchone()

            if existing:
                # Remove dos favoritos
                conn.execute(
                    "DELETE FROM user_favorites WHERE user_id = ? AND lead_id = ?",
                    (user_id, lead_id)
                )
                conn.commit()
                return False
            else:
                # Adiciona aos favoritos
                conn.execute(
                    "INSERT INTO user_favorites (user_id, lead_id) VALUES (?, ?)",
                    (user_id, lead_id)
                )
                conn.commit()
                return True
        finally:
            conn.close()

    def is_favorite_for_user(self, user_id: int, lead_id: int) -> bool:
        """Verifica se um lead é favorito de um usuário específico."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id FROM user_favorites WHERE user_id = ? AND lead_id = ?",
                (user_id, lead_id)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_user_favorites(self, user_id: int) -> List[int]:
        """Retorna os IDs dos leads favoritos de um usuário."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT lead_id FROM user_favorites WHERE user_id = ?",
                (user_id,)
            ).fetchall()
            return [r["lead_id"] for r in rows]
        finally:
            conn.close()

    def update_owner(self, lead_id: int, owner_name: Optional[str]) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE leads SET owner_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (owner_name, lead_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def update_owner_phone(self, lead_id: int, owner_phone: Optional[str]) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE leads SET owner_phone = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (owner_phone, lead_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def update_owner_email(self, lead_id: int, owner_email: Optional[str]) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE leads SET owner_email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (owner_email, lead_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def update_mailing_address(self, lead_id: int, mailing_address: Optional[str]) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE leads SET mailing_address = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (mailing_address, lead_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def add_note(self, lead_id: int, note: str, user_id: Optional[int] = None) -> Optional[dict]:
        conn = get_connection()
        try:
            exists = conn.execute("SELECT id FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not exists:
                return None
            conn.execute(
                "INSERT INTO lead_notes (lead_id, note, user_id) VALUES (?, ?, ?)",
                (lead_id, note, user_id)
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM lead_notes WHERE id = last_insert_rowid()"
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def get_notes(self, lead_id: int) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM lead_notes WHERE lead_id = ? ORDER BY created_at DESC",
                (lead_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_note(self, note_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute("DELETE FROM lead_notes WHERE id = ?", (note_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def record_event(self, lead_id: int, event_type: str) -> bool:
        conn = get_connection()
        try:
            exists = conn.execute("SELECT id FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not exists:
                return False
            conn.execute(
                "INSERT INTO lead_events (lead_id, event_type) VALUES (?, ?)",
                (lead_id, event_type),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def search_leads(self, query: str, limit: int = 50) -> List[dict]:
        conn = get_connection()
        try:
            like = f"%{query}%"
            rows = conn.execute(
                """
                SELECT * FROM leads
                WHERE address LIKE ? OR owner_name LIKE ? OR owner_phone LIKE ?
                ORDER BY date_reported DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_cities(self) -> List[str]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT city, COUNT(*) AS c FROM leads GROUP BY city ORDER BY c DESC"
            ).fetchall()
            return [r["city"] for r in rows]
        finally:
            conn.close()

    def get_cities_with_counts(self) -> List[dict]:
        """Retorna cidades com contagem de leads (sem filtro de lixo)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT city, COUNT(*) AS count FROM leads GROUP BY city ORDER BY count DESC"
            ).fetchall()
            return [{"city": r["city"], "count": r["count"]} for r in rows]
        finally:
            conn.close()

    def get_cities_with_counts_filtered(self) -> List[dict]:
        """Retorna cidades com contagem de leads QUALIFICADOS
        (endereço + 16 ofícios + gatilho preditivo)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                f"""
                SELECT city, COUNT(*) AS count FROM leads
                WHERE {_qualified_where()}
                GROUP BY city ORDER BY count DESC
                """
            ).fetchall()
            return [{"city": r["city"], "count": r["count"]} for r in rows]
        finally:
            conn.close()

    def count_leads_by_interests(self, categories: List[str]) -> int:
        """Conta leads que correspondem às categorias de interesse do usuário."""
        if not categories:
            return 0
        conn = get_connection()
        try:
            placeholders = ",".join("?" * len(categories))
            rows = conn.execute(
                f"""
                SELECT COUNT(*) AS c FROM leads
                WHERE issue_category IN ({placeholders})
                  AND {_qualified_where()}
                """,
                categories,
            ).fetchone()
            return rows["c"] if rows else 0
        finally:
            conn.close()

    def count_leads_last_24h(self) -> int:
        """Conta leads criados nas últimas 24h."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE created_at >= datetime('now', '-1 day')"
            ).fetchone()
            return rows["c"] if rows else 0
        finally:
            conn.close()

    def count_leads_last_7d_filtered(self, city: Optional[str] = None) -> int:
        """Conta leads qualificados (endereço + 16 ofícios + gatilho) dos últimos 7 dias
        reportados."""
        conn = get_connection()
        try:
            sql = f"""
                SELECT COUNT(*) AS c FROM leads
                WHERE date_reported IS NOT NULL
                  AND date(date_reported) >= date('now', '-7 days')
                  AND {_qualified_where()}
            """
            params: list = []
            if city:
                sql += " AND city = ?"
                params.append(city)
            rows = conn.execute(sql, params).fetchone()
            return rows["c"] if rows else 0
        finally:
            conn.close()

    def get_locations_hierarchy(self) -> dict:
        """Retorna hierarquia: país → estado → cidades com contagens."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT COALESCE(NULLIF(TRIM(country), ''), 'US') AS country,
                       state, city, COUNT(*) AS c
                FROM leads
                GROUP BY 1, state, city
                ORDER BY c DESC
                """
            ).fetchall()
            hierarchy = {"US": {"name": "United States", "states": {}}}
            for r in rows:
                country = r["country"] or "US"
                state = r["state"] or "UNKNOWN"
                city = r["city"] or "UNKNOWN"
                count = r["c"]
                if country not in hierarchy:
                    hierarchy[country] = {"name": "United States" if country == "US" else country, "states": {}}
                if state not in hierarchy[country]["states"]:
                    hierarchy[country]["states"][state] = {"name": self._state_name(state), "cities": {}, "count": 0}
                state_node = hierarchy[country]["states"][state]
                if city not in state_node["cities"]:
                    state_node["cities"][city] = {"name": city, "count": 0}
                state_node["cities"][city]["count"] += count
                state_node["count"] += count
            return hierarchy
        finally:
            conn.close()

    def _state_name(self, code: str) -> str:
        names = {
            "NY": "New York",
            "TX": "Texas",
            "CA": "California",
            "FL": "Florida",
            "IL": "Illinois",
            "PA": "Pennsylvania",
            "OH": "Ohio",
            "GA": "Georgia",
            "NC": "North Carolina",
            "MI": "Michigan",
            "MA": "Massachusetts",
            "VA": "Virginia",
        }
        return names.get(code, code)

    # ---------------------------------------------------------------
    # Notificações
    # ---------------------------------------------------------------
    def add_notification(self, type: str, title: str, message: str, lead_id: Optional[int] = None) -> Optional[dict]:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO notifications (type, title, message, lead_id) VALUES (?, ?, ?, ?)",
                (type, title, message, lead_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM notifications WHERE id = last_insert_rowid()"
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Erro ao criar notificação: {e}")
            return None
        finally:
            conn.close()

    def get_notifications(self, filter: str = "recent", limit: int = 50) -> List[dict]:
        """Lista notificações com filtro opcional: 'recent' (7 dias), 'unread', 'all'."""
        conn = get_connection()
        try:
            if filter == "unread":
                rows = conn.execute(
                    """
                    SELECT * FROM notifications
                    WHERE read = 0
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            elif filter == "recent":
                rows = conn.execute(
                    """
                    SELECT * FROM notifications
                    WHERE created_at >= datetime('now', '-7 days')
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:  # 'all'
                rows = conn.execute(
                    """
                    SELECT * FROM notifications
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_notification_read(self, notification_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE notifications SET read = 1 WHERE id = ?", (notification_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def mark_all_notifications_read(self) -> int:
        conn = get_connection()
        try:
            cur = conn.execute("UPDATE notifications SET read = 1 WHERE read = 0")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def count_unread_notifications(self) -> int:
        conn = get_connection()
        try:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM notifications WHERE read = 0"
            ).fetchone()["c"]
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # Usuários
    # ---------------------------------------------------------------
    def create_user(self, email: str, password_hash: str, company_name: str, plan: str = "free",
                    subscription_status: Optional[str] = None, plan_until: Optional[str] = None) -> Optional[dict]:
        conn = get_connection()
        try:
            exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if exists:
                return None
            conn.execute(
                "INSERT INTO users (email, password_hash, company_name, plan, subscription_status, plan_until) VALUES (?, ?, ?, ?, ?, ?)",
                (email, password_hash, company_name, plan, subscription_status, plan_until),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM users WHERE id = last_insert_rowid()"
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_user_by_email(self, email: str) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_user_company(self, user_id: int, company_name: str) -> Optional[dict]:
        """Atualiza o nome da empresa (remetente nas mensagens aos clientes)."""
        conn = get_connection()
        try:
            conn.execute("UPDATE users SET company_name = ? WHERE id = ?", (company_name, user_id))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_user_plan(self, user_id: int, plan: str, subscription_status: str = "active") -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE users SET plan = ?, subscription_status = ? WHERE id = ?",
                (plan, subscription_status, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def set_user_stripe(self, user_id: int, customer_id: Optional[str], subscription_id: Optional[str]) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE users SET stripe_customer_id = ?, stripe_subscription_id = ? WHERE id = ?",
                (customer_id, subscription_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def activate_week(self, user_id: int, plan: str = "pro", subscription_status: str = "active",
                      days: int = 7) -> Optional[dict]:
        """Renova o acesso por mais uma semana (checkout/pagamento confirmado)."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE users SET plan = ?, subscription_status = ?, "
                "plan_until = datetime('now', ?) WHERE id = ?",
                (plan, subscription_status, f"+{days} day", user_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
            return self.get_user_by_id(user_id)
        finally:
            conn.close()

    def extend_access(self, user_id: int, days: int = 7) -> Optional[dict]:
        """Estende o acesso pago em +days dias.

        A base é max(agora, plan_until atual): pagar com acesso ativo soma à
        expiração existente (não reinicia); pagar expirado conta a partir de agora.
        Usado pelo webhook Stripe (checkout.session.completed / pagamento avulso).
        """
        conn = get_connection()
        try:
            user = conn.execute("SELECT plan_until FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                return None
            now = datetime.utcnow()
            current = self._parse_dt(user["plan_until"])
            base = max(now, current) if current else now
            new_until = base + timedelta(days=days)
            conn.execute(
                "UPDATE users SET plan = 'pro', subscription_status = 'active', "
                "plan_until = ? WHERE id = ?",
                (new_until.isoformat(), user_id),
            )
            conn.commit()
            return self.get_user_by_id(user_id)
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # Pagamentos avulsos (Stripe) — idempotência por event_id
    # ---------------------------------------------------------------
    def record_stripe_event(self, event_id: str, event_type: str,
                            user_id: Optional[int] = None) -> bool:
        """Registra um evento Stripe. Retorna True se é novo, False se já processado."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO stripe_events (event_id, event_type, user_id) "
                "VALUES (?, ?, ?)",
                (event_id, event_type, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def has_stripe_event(self, event_id: str) -> bool:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT 1 FROM stripe_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # Interesses por usuário
    # ---------------------------------------------------------------
    def set_user_interests(self, user_id: int, categories: List[str]) -> bool:
        conn = get_connection()
        try:
            _cur = conn.execute("DELETE FROM user_interests WHERE user_id = ?", (user_id,))
            for cat in categories:
                if cat:
                    conn.execute(
                        "INSERT OR IGNORE INTO user_interests (user_id, category) VALUES (?, ?)",
                        (user_id, cat),
                    )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_user_interests(self, user_id: int) -> List[str]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT category FROM user_interests WHERE user_id = ?", (user_id,)
            ).fetchall()
            return [r["category"] for r in rows]
        finally:
            conn.close()

    def set_user_cities_filter(self, user_id: int, cities: Optional[List[str]]) -> bool:
        """Define as cidades de interesse do usuário (None = todas)."""
        import json
        conn = get_connection()
        try:
            cities_json = json.dumps(cities) if cities else None
            conn.execute(
                "UPDATE users SET cities_filter = ? WHERE id = ?",
                (cities_json, user_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_user_cities_filter(self, user_id: int) -> Optional[List[str]]:
        """Retorna as cidades de interesse do usuário (None = todas)."""
        import json
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT cities_filter FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row and row["cities_filter"]:
                return json.loads(row["cities_filter"])
            return None
        finally:
            conn.close()

    def get_users_interested_in(self, category: str, city: Optional[str] = None) -> List[dict]:
        """Usuários elegíveis a receber alerta de uma categoria.

        Elegibilidade (nesta ordem):
          1. ACESSO VIGENTE — decidido por services.access.is_access_active()
             (fonte única de verdade; nada de whitelist local de status aqui).
          2. RECORTE DE CATEGORIA — usuários que marcaram a categoria OU que NÃO
             têm nenhum interesse gravado (fallback inteligente: sem configuração
             = todas as categorias, para nunca zerar o despacho por lacuna).
          3. RECORTE DE CIDADE — se `city` informado e o usuário tiver
             `cities_filter`, a cidade precisa estar na lista.
        """
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT u.* FROM users u
                WHERE EXISTS (
                    SELECT 1 FROM user_interests ui
                    WHERE ui.user_id = u.id AND ui.category = ?
                )
                OR NOT EXISTS (
                    SELECT 1 FROM user_interests ui2 WHERE ui2.user_id = u.id
                )
                """,
                (category,),
            ).fetchall()
            candidates = [dict(r) for r in rows]
        finally:
            conn.close()

        # (1) Acesso vigente — fonte única de verdade (fail-closed).
        users = [
            u for u in candidates
            if is_access_active(u.get("subscription_status"), u.get("plan_until"))
        ]

        # (3) Recorte por cidade.
        if city and users:
            import json
            filtered = []
            for u in users:
                cities_filter = u.get("cities_filter")
                if cities_filter:
                    try:
                        allowed_cities = json.loads(cities_filter)
                    except (ValueError, TypeError):
                        allowed_cities = None
                    if allowed_cities and city not in allowed_cities:
                        continue
                filtered.append(u)
            return filtered
        return users

    # ---------------------------------------------------------------
    # Push Subscriptions (Web Push)
    # ---------------------------------------------------------------
    def add_push_subscription(self, user_id: int, endpoint: str, p256dh: str, auth: str) -> bool:
        """Salva ou atualiza uma push subscription para o usuário."""
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(endpoint) DO UPDATE SET
                    p256dh = excluded.p256dh,
                    auth = excluded.auth,
                    user_id = excluded.user_id
                """,
                (user_id, endpoint, p256dh, auth),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def remove_push_subscription(self, user_id: int, endpoint: str) -> bool:
        """Remove uma push subscription do usuário."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
                (user_id, endpoint),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_user_push_subscriptions(self, user_id: int) -> List[dict]:
        """Retorna todas as push subscriptions de um usuário."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_all_push_subscriptions(self) -> List[dict]:
        """Retorna todas as push subscriptions (para envio em lote)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT user_id, endpoint, p256dh, auth, created_at FROM push_subscriptions"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def set_user_push_enabled(self, user_id: int, enabled: bool) -> bool:
        """Atualiza o flag push_enabled do usuário."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE users SET push_enabled = ? WHERE id = ?",
                (1 if enabled else 0, user_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def is_push_enabled(self, user_id: int) -> bool:
        """Verifica se push_enabled está ativo para o usuário."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT push_enabled FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            return bool(row["push_enabled"]) if row else False
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # User Sessions (Concurrent login control - max 2 per user)
    # ---------------------------------------------------------------
    def create_user_session(
        self, user_id: int, token_hash: str, device_info: Optional[str], ip_address: Optional[str]
    ) -> bool:
        """
        Cria uma nova sessão para o usuário.
        Se já existirem 2 sessões ativas, remove a mais antiga (FIFO).
        """
        conn = get_connection()
        try:
            # Conta sessões atuais
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM user_sessions WHERE user_id = ?",
                (user_id,),
            ).fetchone()["cnt"]

            if count >= 2:
                # Remove a sessão mais antiga (FIFO)
                conn.execute(
                    """
                    DELETE FROM user_sessions
                    WHERE id = (
                        SELECT id FROM user_sessions
                        WHERE user_id = ?
                        ORDER BY last_active_at ASC
                        LIMIT 1
                    )
                    """,
                    (user_id,),
                )

            # Insere a nova sessão
            conn.execute(
                """
                INSERT INTO user_sessions (user_id, token_hash, device_info, ip_address)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, token_hash, device_info, ip_address),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def validate_user_session(self, token_hash: str) -> Optional[int]:
        """
        Verifica se o token_hash corresponde a uma sessão válida.
        Retorna o user_id se válido, None caso contrário.
        Atualiza last_active_at em caso de sucesso.
        """
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT user_id FROM user_sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE user_sessions SET last_active_at = CURRENT_TIMESTAMP WHERE token_hash = ?",
                    (token_hash,),
                )
                conn.commit()
                return row["user_id"]
            return None
        finally:
            conn.close()

    def remove_user_session(self, token_hash: str) -> bool:
        """Remove uma sessão específica pelo token_hash."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "DELETE FROM user_sessions WHERE token_hash = ?",
                (token_hash,),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def remove_user_sessions(self, user_id: int) -> int:
        """Remove todas as sessões de um usuário."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "DELETE FROM user_sessions WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def get_user_active_sessions(self, user_id: int) -> List[dict]:
        """Retorna todas as sessões ativas de um usuário."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, token_hash, device_info, ip_address, created_at, last_active_at
                FROM user_sessions WHERE user_id = ?
                ORDER BY last_active_at DESC
                """,
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_all_users(self) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # Notificações por usuário
    # ---------------------------------------------------------------
    def add_notification_for_user(self, user_id: int, type: str, title: str, message: str, lead_id: Optional[int] = None) -> Optional[dict]:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO notifications (user_id, type, title, message, lead_id) VALUES (?, ?, ?, ?, ?)",
                (user_id, type, title, message, lead_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM notifications WHERE id = last_insert_rowid()"
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Erro ao inserir notificação para user {user_id}: {e}")
            # Salva no DLQ para reprocessamento posterior
            self._save_notification_dlq(user_id, type, title, message, lead_id, str(e))
            return None
        finally:
            conn.close()

    def _save_notification_dlq(self, user_id: int, type: str, title: str, message: str, lead_id: Optional[int], error: str) -> None:
        """Salva notificação falha no DLQ para reprocessamento posterior."""
        try:
            import json
            import os
            from datetime import datetime
            dlq_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "dlq", "notifications")
            os.makedirs(dlq_dir, exist_ok=True)
            filename = f"notif_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{user_id}.json"
            path = os.path.join(dlq_dir, filename)
            payload = {
                "user_id": user_id,
                "type": type,
                "title": title,
                "message": message,
                "lead_id": lead_id,
                "error": error,
                "saved_at": datetime.utcnow().isoformat(),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.warning(f"DLQ Notification: user {user_id} salvo em {filename}")
        except Exception as e:
            logger.error(f"Erro ao salvar notificação no DLQ: {e}")

    def reprocess_notification_dlq(self) -> int:
        """Reprocessa notificações pendentes no DLQ. Retorna qtd reinseridas."""
        import json
        import os
        dlq_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "dlq", "notifications")
        if not os.path.exists(dlq_dir):
            return 0
        reprocessed = 0
        for filename in os.listdir(dlq_dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(dlq_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                user_id = payload.get("user_id")
                ntype = payload.get("type")
                title = payload.get("title")
                message = payload.get("message")
                lead_id = payload.get("lead_id")
                if not all([user_id, ntype, title, message]):
                    logger.warning(f"DLQ Notification {filename}: payload incompleto, removendo")
                    os.remove(path)
                    continue
                conn = get_connection()
                try:
                    conn.execute(
                        "INSERT INTO notifications (user_id, type, title, message, lead_id) VALUES (?, ?, ?, ?, ?)",
                        (user_id, ntype, title, message, lead_id),
                    )
                    conn.commit()
                    reprocessed += 1
                    logger.info(f"DLQ Notification reprocessado: {filename}")
                    os.remove(path)
                finally:
                    conn.close()
            except Exception as e:
                logger.error(f"Erro ao reprocessar DLQ notification {filename}: {e}")
        return reprocessed

    def get_notifications_for_user(self, user_id: int, filter: str = "recent", limit: int = 50) -> List[dict]:
        conn = get_connection()
        try:
            if filter == "unread":
                rows = conn.execute(
                    """
                    SELECT * FROM notifications
                    WHERE (user_id = ? OR user_id IS NULL) AND read = 0
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
            elif filter == "recent":
                rows = conn.execute(
                    """
                    SELECT * FROM notifications
                    WHERE (user_id = ? OR user_id IS NULL) AND created_at >= datetime('now', '-7 days')
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM notifications
                    WHERE (user_id = ? OR user_id IS NULL)
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_notification_read_for_user(self, notification_id: int, user_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
                (notification_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def mark_all_notifications_read_for_user(self, user_id: int) -> int:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE notifications SET read = 1 WHERE user_id = ? AND read = 0",
                (user_id,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def count_unread_notifications_for_user(self, user_id: int) -> int:
        conn = get_connection()
        try:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM notifications WHERE (user_id = ? OR user_id IS NULL) AND read = 0",
                (user_id,),
            ).fetchone()["c"]
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # Daily alert cap (10/day, dedup, digest)
    # ---------------------------------------------------------------
    def get_new_lead_alert_counts_today(self) -> List[dict]:
        """Retorna [{user_id, n}] com contagem de alertas new_lead hoje, agrupado por usuário."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT user_id, COUNT(*) AS n FROM notifications "
                "WHERE user_id IS NOT NULL AND type = 'new_lead' "
                "AND DATE(created_at) = DATE('now') GROUP BY user_id"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def has_alerted_user_for_lead(self, user_id: int, lead_id: int) -> bool:
        """True se já existe notificação new_lead para (user_id, lead_id) — dedup."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT 1 FROM notifications "
                "WHERE user_id = ? AND lead_id = ? AND type = 'new_lead' LIMIT 1",
                (user_id, lead_id),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_alerted_pairs_for_leads(self, lead_ids: List[int]) -> List[dict]:
        """Retorna [{user_id, lead_id}] de alertas new_lead já criados para os leads informados."""
        if not lead_ids:
            return []
        conn = get_connection()
        try:
            ph = ",".join("?" * len(lead_ids))
            rows = conn.execute(
                f"SELECT DISTINCT user_id, lead_id FROM notifications "
                f"WHERE type = 'new_lead' AND user_id IS NOT NULL AND lead_id IN ({ph})",
                lead_ids,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def upsert_daily_digest(self, user_id: int, extra_count: int) -> Optional[dict]:
        """Insere ou atualiza a notificação de resumo diário para um usuário.
        O digest NÃO conta no teto de 10 (tipo 'digest', não 'new_lead')."""
        import re
        conn = get_connection()
        try:
            existing = conn.execute(
                "SELECT id, message FROM notifications "
                "WHERE user_id = ? AND type = 'digest' AND DATE(created_at) = DATE('now')",
                (user_id,),
            ).fetchone()
            if existing:
                prev = 0
                m = re.search(r"Mais (\d+)", existing["message"] or "")
                if m:
                    prev = int(m.group(1))
                total = prev + extra_count
                new_msg = (
                    f"Mais {total} ofertas chegaram hoje "
                    f"— o limite de 10 renova amanhã."
                )
                conn.execute(
                    "UPDATE notifications SET message = ? WHERE id = ?",
                    (new_msg, existing["id"]),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM notifications WHERE id = ?", (existing["id"],)
                ).fetchone()
                return dict(row) if row else None
            else:
                new_msg = (
                    f"Mais {extra_count} ofertas chegaram hoje "
                    f"— o limite de 10 renova amanhã."
                )
                conn.execute(
                    "INSERT INTO notifications (user_id, type, title, message, lead_id) "
                    "VALUES (?, 'digest', 'Resumo diário de alertas', ?, NULL)",
                    (user_id, new_msg),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM notifications WHERE id = last_insert_rowid()"
                ).fetchone()
                return dict(row) if row else None
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # Hold / Reserva / Release / Score / Histórico estruturado
    # ---------------------------------------------------------------
    def _expire_lead_holds(self, conn: sqlite3.Connection) -> None:
        """Expira holds vencidos (volta o lead para available)."""
        conn.execute(
            """
            UPDATE leads SET lead_status = 'available', reserved_by = NULL, reserved_until = NULL
            WHERE lead_status = 'reserved' AND reserved_until IS NOT NULL
              AND reserved_until < datetime('now')
            """
        )
        conn.execute(
            "UPDATE lead_holds SET status = 'expired' WHERE status = 'active' AND expires_at < datetime('now')"
        )

    def _event(self, conn: sqlite3.Connection, lead_id: int, user_id: Optional[int], event_type: str, detail: Optional[str] = None) -> None:
        conn.execute(
            "INSERT INTO lead_events (lead_id, event_type, user_id, detail) VALUES (?, ?, ?, ?)",
            (lead_id, event_type, user_id, detail),
        )

    def get_lead_with_status(self, lead_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            self._expire_lead_holds(conn)
            conn.commit()
            row = conn.execute(
                """
                SELECT l.*, u.company_name AS reserved_by_name
                FROM leads l
                LEFT JOIN users u ON u.id = l.reserved_by
                WHERE l.id = ?
                """,
                (lead_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_leads_with_status(self, limit: int = 100, status: Optional[str] = None) -> List[dict]:
        conn = get_connection()
        try:
            self._expire_lead_holds(conn)
            conn.commit()
            sql = """
                SELECT l.*, u.company_name AS reserved_by_name
                FROM leads l
                LEFT JOIN users u ON u.id = l.reserved_by
            """
            params: tuple = ()
            if status:
                sql += " WHERE l.lead_status = ?"
                params = (status,)
            sql += " ORDER BY l.date_reported DESC LIMIT ?"
            rows = conn.execute(sql, params + (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def reserve_lead(self, lead_id: int, user_id: int, minutes: int = 60, skip_daily_increment: bool = False) -> Optional[dict]:
        conn = get_connection()
        try:
            self._expire_lead_holds(conn)
            # Penalidade level 3 (suspenso): bloqueia novas reservas
            pen = conn.execute(
                "SELECT * FROM contractor_metrics WHERE contractor_id = ?", (user_id,)
            ).fetchone()
            if pen and pen["penalty_level"] == self.PENALTY_LEVEL_SUSPENDED:
                penalizado_ate = pen["penalty_until"] or ""
                if penalizado_ate >= datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"):
                    return {"error": "suspended", "penalty_until": penalizado_ate}
                else:
                    conn.execute(
                        "UPDATE contractor_metrics SET penalty_level = 0, penalty_until = NULL WHERE contractor_id = ?",
                        (user_id,),
                    )
            # Penalidade level 2 (reduced): delay de 5min entre reservas
            if pen and pen["penalty_level"] == self.PENALTY_LEVEL_REDUCED:
                last_hold = conn.execute(
                    "SELECT expires_at FROM lead_holds WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
                if last_hold and last_hold["expires_at"] and last_hold["expires_at"] > datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"):
                    return {"error": "reduced_delay", "message": "Prioridade reduzida: aguarde 5min entre reservas"}
            lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not lead:
                return None
            if lead["lead_status"] == "reserved" and lead["reserved_by"] != user_id:
                return {"error": "already_reserved", "lead": dict(lead)}
            conn.execute(
                "UPDATE leads SET lead_status = 'reserved', reserved_by = ?, reserved_until = datetime('now', ?), updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (user_id, f"+{int(minutes)} minutes", lead_id),
            )
            conn.execute(
                "INSERT INTO lead_holds (lead_id, user_id, expires_at, status) VALUES (?, ?, datetime('now', ?), 'active')",
                (lead_id, user_id, f"+{int(minutes)} minutes"),
            )
            if not skip_daily_increment:
                conn.execute("UPDATE users SET leads_taken = leads_taken + 1 WHERE id = ?", (user_id,))
            self._event(conn, lead_id, user_id, "reserved", f"Reservado por {minutes}min")
            conn.commit()
            lead_dict = dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
            # Retorna campos necessários para phone lookup
            return {
                **lead_dict,
                "address": lead_dict.get("address"),
                "city": lead_dict.get("city"),
                "state": lead_dict.get("state"),
                "_skip_daily_increment": skip_daily_increment
            }
        finally:
            conn.close()

    # Motivos de release considerados suspeitos (geram penalidade)
    SUSPICIOUS_REASONS = {"changed_mind", "lazy"}
    PENALTY_LEVEL_WARNING = 1
    PENALTY_LEVEL_REDUCED = 2
    PENALTY_LEVEL_SUSPENDED = 3

    def release_lead(self, lead_id: int, user_id: int, reason: Optional[str] = None, note: Optional[str] = None) -> Optional[dict]:
        conn = get_connection()
        try:
            lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not lead:
                return None
            if lead["reserved_by"] and lead["reserved_by"] != user_id:
                return {"error": "not_owner", "lead": dict(lead)}
            prev = conn.execute(
                "SELECT id FROM lead_holds WHERE lead_id = ? ORDER BY id DESC LIMIT 1",
                (lead_id,),
            ).fetchone()
            if prev:
                conn.execute(
                    "UPDATE lead_holds SET status = 'released', release_reason = ?, release_note = ?, released_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (reason, note, prev["id"]),
                )
            conn.execute(
                "UPDATE leads SET lead_status = 'available', reserved_by = NULL, reserved_until = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (lead_id,),
            )
            conn.execute(
                """
                INSERT INTO contractor_release_tracking (contractor_id, lead_id, release_count, release_reasons, last_released_at)
                VALUES (?, ?, 1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(contractor_id, lead_id) DO UPDATE SET
                  release_count = release_count + 1,
                  release_reasons = ?,
                  last_released_at = CURRENT_TIMESTAMP
                """,
                (user_id, lead_id, reason, reason),
            )
            self._event(conn, lead_id, user_id, "released", f"Liberado: {reason or 'sem motivo'}")
            penalty = self._apply_release_penalty(conn, user_id, reason)
            conn.commit()
            result = dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
            if penalty:
                result["_penalty"] = penalty
            return result
        finally:
            conn.close()

    def _apply_release_penalty(self, conn, contractor_id: int, reason: Optional[str]) -> Optional[dict]:
        """Atualiza contractor_metrics com base no motivo do release.
        Suspeitos = changed_mind | lazy.
        Level 1 (warning) ao atingir 3 suspeitos, Level 2 (reduced) ao 5,
        Level 3 (suspended 30d) ao 10."""
        suspicious = reason in self.SUSPICIOUS_REASONS

        row = conn.execute(
            "SELECT * FROM contractor_metrics WHERE contractor_id = ?", (contractor_id,)
        ).fetchone()
        releases_this_month = (row["releases_this_month"] or 0) + 1 if row else 1
        suspicious_releases = (row["suspicious_releases"] or 0) + (1 if suspicious else 0) if row else (1 if suspicious else 0)

        now = datetime.utcnow()
        _now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        penalty_level = (row["penalty_level"] or 0) if row else 0
        penalty_until = row["penalty_until"] if row else None

        # Suspensão expirada: volta para 0? NÃO contabiliza como novo release — preserva nível
        # atual e só atualiza se novo limite for atingido daqui pra frente.
        if suspicious:
            if suspicious_releases >= 10:
                penalty_level = self.PENALTY_LEVEL_SUSPENDED
                penalty_until = (now + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            elif suspicious_releases >= 5:
                if penalty_level < self.PENALTY_LEVEL_REDUCED:
                    penalty_level = self.PENALTY_LEVEL_REDUCED
                    penalty_until = (now + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            elif suspicious_releases >= 3:
                if penalty_level < self.PENALTY_LEVEL_WARNING:
                    penalty_level = self.PENALTY_LEVEL_WARNING
                    penalty_until = (now + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """
            INSERT INTO contractor_metrics
              (contractor_id, releases_this_month, suspicious_releases, penalty_level, penalty_until, last_penalty_reason, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(contractor_id) DO UPDATE SET
              releases_this_month = excluded.releases_this_month,
              suspicious_releases = excluded.suspicious_releases,
              penalty_level = excluded.penalty_level,
              penalty_until = excluded.penalty_until,
              last_penalty_reason = excluded.last_penalty_reason,
              updated_at = CURRENT_TIMESTAMP
            """,
            (contractor_id, releases_this_month, suspicious_releases, penalty_level, penalty_until, reason),
        )

        penalty_labels = {1: "warning", 2: "reduced", 3: "suspended"}
        return {
            "penalty_level": penalty_level,
            "penalty_label": penalty_labels.get(penalty_level, "none"),
            "suspicious_releases": suspicious_releases,
            "penalty_until": penalty_until if penalty_level > 0 else None,
            "is_suspicious": suspicious,
        }

    def get_contractor_metrics(self, contractor_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM contractor_metrics WHERE contractor_id = ?", (contractor_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ===== HISTÓRICO DE OCORRÊNCIAS POR IMÓVEL (Parte B) =====

    def save_lead_case_history(self, lead_id: int, occurrences: List[dict]) -> int:
        """Substitui o histórico de ocorrências do imóvel (mesma rua) para o lead."""
        conn = get_connection()
        try:
            conn.execute("DELETE FROM lead_case_history WHERE lead_id = ?", (lead_id,))
            saved = 0
            for o in occurrences:
                conn.execute(
                    """INSERT OR IGNORE INTO lead_case_history
                       (lead_id, external_id, case_title, descriptor, subject, reason,
                        case_status, department, opened_at, closed_at,
                        resolution_description, closure_reason, source, source_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        lead_id,
                        o.get("external_id"),
                        o.get("case_title"),
                        o.get("descriptor"),
                        o.get("subject"),
                        o.get("reason"),
                        o.get("case_status"),
                        o.get("department"),
                        o.get("opened_at"),
                        o.get("closed_at"),
                        o.get("resolution_description"),
                        o.get("closure_reason"),
                        o.get("source"),
                        o.get("source_url"),
                    ),
                )
                saved += 1
            conn.commit()
            return saved
        finally:
            conn.close()

    def get_lead_case_history(self, lead_id: int) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM lead_case_history WHERE lead_id = ?
                   ORDER BY opened_at DESC, id DESC""",
                (lead_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_leads_for_case_history(
        self, city: Optional[str] = None, limit: int = 50, only_missing: bool = True
    ) -> List[dict]:
        """Leads candidatos a ter o histórico de ocorrências capturado."""
        conn = get_connection()
        try:
            q = (
                "SELECT l.id, l.address, l.city, l.state, l.external_id FROM leads l "
                "WHERE LENGTH(TRIM(IFNULL(l.address,''))) > 0 "
            )
            params: list = []
            if city:
                q += " AND l.city = ?"
                params.append(city)
            if only_missing:
                q += " AND NOT EXISTS (SELECT 1 FROM lead_case_history h WHERE h.lead_id = l.id)"
            q += " ORDER BY l.date_reported DESC LIMIT ?"
            params.append(limit)
            return [dict(r) for r in conn.execute(q, params).fetchall()]
        finally:
            conn.close()

    # ===== MEUS LEADS / HISTÓRICO (sobrevive a release e expiração) =====

    def _ts(self, value) -> float:
        """Converte timestamp string para epoch (float). 0.0 se inválido."""
        dt = self._parse_dt(value)
        return dt.timestamp() if dt else 0.0

    def _within_period(self, value: Optional[str], period: str, now: datetime) -> bool:
        dt = self._parse_dt(value)
        if not dt:
            return False
        if period == "today":
            return dt.date() == now.date()
        if period == "7d":
            return (now - dt).days <= 7
        if period == "month":
            return (now - dt).days <= 30
        return True

    def _derive_my_status(self, d: dict, user_id: int) -> str:
        """Status 'do ponto de vista do usuário' em Meus Leads."""
        ls = d.get("lead_status")
        if ls == "reserved" and d.get("reserved_by") == user_id:
            return "reserved"
        if ls == "converted" and d.get("converted_by") == user_id:
            return "converted"
        if ls in ("contacted", "in_negotiation") and d.get("reserved_by") == user_id:
            return "negotiating"
        if d.get("hold_status") == "expired":
            return "hold_expired"
        if d.get("hold_status") == "released":
            return "released"
        return "available"

    def get_user_leads_history(
        self,
        user_id: int,
        status: Optional[str] = None,
        category: Optional[str] = None,
        period: Optional[str] = None,
        search: Optional[str] = None,
        needs_action: bool = False,
        limit: int = 100,
    ):
        """Histórico 'Meus Leads' do usuário.

        Fonte: lead_holds (persiste mesmo após release/expiração) + leads.
        Retorna (itens_ordenados, kpis).
        """
        conn = get_connection()
        try:
            now = datetime.utcnow()
            rows = conn.execute(
                """
                SELECT l.*, h.held_at, h.expires_at AS hold_expires_at, h.released_at AS hold_released_at,
                       h.release_reason, h.status AS hold_status
                FROM lead_holds h
                JOIN leads l ON l.id = h.lead_id
                JOIN (
                    SELECT lead_id, MAX(id) AS max_id
                    FROM lead_holds WHERE user_id = ? GROUP BY lead_id
                ) m ON h.id = m.max_id
                WHERE h.user_id = ?
                """,
                (user_id, user_id),
            ).fetchall()

            items = []
            for r in rows:
                d = dict(r)
                d["my_status"] = self._derive_my_status(d, user_id)
                items.append(d)

            # ===== KPIs (sobre o histórico completo, antes dos filtros) =====
            total_reserved = len(items)
            converted = sum(1 for d in items if d["my_status"] == "converted")
            conversion_rate = round(converted / total_reserved * 100, 1) if total_reserved else 0.0
            needs_action_count = sum(
                1 for d in items if d["my_status"] in ("reserved", "negotiating", "hold_expired")
            )
            daily = self.get_daily_leads_used(user_id)
            kpis = {
                "total_reserved": total_reserved,
                "converted": converted,
                "conversion_rate": conversion_rate,
                "today_used": daily.get("used", 0),
                "today_limit": daily.get("limit", 10),
                "needs_action": needs_action_count,
            }

            # ===== Filtros =====
            if search:
                sl = search.lower()
                items = [
                    d for d in items
                    if sl in (d.get("address") or "").lower()
                    or sl in (d.get("owner_name") or "").lower()
                    or sl in (d.get("owner_phone") or "")
                ]
            if category:
                items = [d for d in items if (d.get("issue_category") or "") == category]
            if status:
                statuses = {s.strip() for s in status.split(",") if s.strip()}
                items = [d for d in items if d["my_status"] in statuses]
            if needs_action:
                items = [d for d in items if d["my_status"] in ("reserved", "negotiating", "hold_expired")]
            if period:
                items = [d for d in items if self._within_period(d.get("held_at"), period, now)]

            # ===== Ordenação: urgência primeiro =====
            def sort_key(d):
                s = d["my_status"]
                if s == "reserved":
                    return (0, self._ts(d.get("hold_expires_at") or "9999-12-31"))
                if s == "negotiating":
                    return (1, -self._ts(d.get("held_at") or "0"))
                if s == "hold_expired":
                    return (2, -self._ts(d.get("hold_released_at") or d.get("held_at") or "0"))
                if s == "converted":
                    return (3, -self._ts(d.get("converted_at") or "0"))
                if s == "released":
                    return (4, -self._ts(d.get("hold_released_at") or "0"))
                return (5, -self._ts(d.get("held_at") or "0"))

            items.sort(key=sort_key)
            return items[:limit], kpis
        finally:
            conn.close()

    def expire_holds(self) -> int:
        """Libera (auto-expira) os holds cujo expires_at passou.
        Retorna quantos leads foram expirados."""
        conn = get_connection()
        try:
            expired = conn.execute(
                """
                SELECT h.lead_id, h.user_id FROM lead_holds h
                JOIN leads l ON l.id = h.lead_id
                WHERE h.status = 'active' AND h.expires_at < datetime('now')
                  AND l.lead_status = 'reserved' AND l.reserved_by = h.user_id
                """
            ).fetchall()
            count = 0
            for row in expired:
                conn.execute(
                    "UPDATE lead_holds SET status = 'expired', released_at = CURRENT_TIMESTAMP WHERE lead_id = ? AND user_id = ? AND status = 'active'",
                    (row["lead_id"], row["user_id"]),
                )
                conn.execute(
                    "UPDATE leads SET lead_status = 'available', reserved_by = NULL, reserved_until = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND lead_status = 'reserved'",
                    (row["lead_id"],),
                )
                self._event(conn, row["lead_id"], row["user_id"], "auto_expired", "Hold expirou (24h)")
                count += 1
            if count:
                conn.commit()
            return count
        finally:
            conn.close()

    def record_contact(self, lead_id: int, user_id: int, channel: str) -> Optional[dict]:
        conn = get_connection()
        try:
            lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not lead:
                return None
            if lead["lead_status"] == "reserved" and lead["reserved_by"] != user_id:
                return {"error": "already_reserved", "lead": dict(lead)}
            conn.execute(
                "UPDATE leads SET contact_count = contact_count + 1, lead_status = 'contacted', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (lead_id,),
            )
            self._event(conn, lead_id, user_id, "contact", f"Contato via {channel}")
            conn.commit()
            return dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
        finally:
            conn.close()

    def mark_negotiation(self, lead_id: int, user_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            _leads = conn.execute("UPDATE leads SET lead_status = 'in_negotiation', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND (reserved_by = ? OR reserved_by IS NULL)", (lead_id, user_id))
            conn.execute(
                "UPDATE leads SET reserved_by = COALESCE(reserved_by, ?) WHERE id = ?",
                (user_id, lead_id),
            )
            self._event(conn, lead_id, user_id, "negotiation", "Cliente respondeu")
            conn.commit()
            return dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
        finally:
            conn.close()

    def convert_lead(self, lead_id: int, user_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not lead:
                return None
            conn.execute(
                "UPDATE leads SET lead_status = 'converted', converted_by = ?, converted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (user_id, lead_id),
            )
            conn.execute(
                "UPDATE users SET conversions = conversions + 1 WHERE id = ?", (user_id,)
            )
            # score: +100 por conversão, -1 por release, +1 por lead tomado
            conn.execute(
                "UPDATE users SET score = score + 100 WHERE id = ?", (user_id,)
            )
            self._event(conn, lead_id, user_id, "converted", "Contrato fechado")
            conn.commit()
            return dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
        finally:
            conn.close()

    def reject_lead(self, lead_id: int, user_id: int, reason: Optional[str] = None) -> Optional[dict]:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE leads SET lead_status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (lead_id,),
            )
            self._event(conn, lead_id, user_id, "rejected", reason or "Cliente recusou")
            conn.commit()
            return dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
        finally:
            conn.close()

    def add_user_penalty(self, contractor_id: int, penalty_type: str, reason: str, penalty_level: str = "warning", expires_hours: int = 24) -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO contractor_penalties (contractor_id, penalty_type, reason, penalty_level, penalty_expires_at) VALUES (?, ?, ?, ?, datetime('now', ?))",
                (contractor_id, penalty_type, reason, penalty_level, f"+{expires_hours} hours"),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def check_user_penalties(self, contractor_id: int) -> List[dict]:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE contractor_penalties SET is_active = 0 WHERE is_active = 1 AND penalty_expires_at < datetime('now')"
            )
            conn.commit()
            rows = conn.execute(
                "SELECT * FROM contractor_penalties WHERE contractor_id = ? AND is_active = 1",
                (contractor_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_user_score(self, contractor_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, company_name, score, leads_taken, conversions FROM users WHERE id = ?",
                (contractor_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_lead_history(self, lead_id: int) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT e.*, u.company_name AS user_name
                FROM lead_events e
                LEFT JOIN users u ON u.id = e.user_id
                WHERE e.lead_id = ?
                ORDER BY e.created_at ASC
                """,
                (lead_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_stats(self) -> dict:
        conn = get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
            with_owner = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE owner_name IS NOT NULL AND owner_name != ''"
            ).fetchone()["c"]
            by_category = {
                r["issue_category"]: r["c"]
                for r in conn.execute(
                    "SELECT issue_category, COUNT(*) AS c FROM leads GROUP BY issue_category ORDER BY c DESC"
                ).fetchall()
            }
            today = datetime.now().strftime("%Y-%m-%d")
            reported_today = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE date(date_reported) = ?", (today,)
            ).fetchone()["c"]
            contacted = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE lead_status = 'contacted'"
            ).fetchone()["c"]
            favorited = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE favorited = 1"
            ).fetchone()["c"]
            return {
                "total": total,
                "with_owner": with_owner,
                "reported_today": reported_today,
                "contacted": contacted,
                "favorited": favorited,
                "by_category": by_category,
            }
        finally:
            conn.close()

    def get_public_metrics(self) -> dict:
        """Fonte Única da Verdade dos contadores públicos (landing + dashboard).

        Chave canônica: last_scrape.novas_oportunidades.
        Cálculo: max(leads capturados nas últimas 24h, piso dinâmico).
        O piso é a média de inserted das últimas 10 execuções (mínimo 500),
        evitando que oscilações pontuais zerem a exibição.
        """
        conn = get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
            with_owner = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE owner_name IS NOT NULL AND owner_name != ''"
            ).fetchone()["c"]
            cities = [
                r["city"]
                for r in conn.execute(
                    "SELECT DISTINCT city FROM leads WHERE city IS NOT NULL AND city != '' ORDER BY city"
                ).fetchall()
            ]
            # Leads efetivamente inseridos nas últimas 24h
            captured_24h = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE created_at >= datetime('now', '-24 hours')"
            ).fetchone()["c"]
            # Piso dinâmico: média de inserted das últimas 10 execuções, mínimo 500
            recent = conn.execute(
                "SELECT inserted FROM scraper_runs ORDER BY id DESC LIMIT 10"
            ).fetchall()
            recent_vals = [r["inserted"] for r in recent if r["inserted"] is not None]
            avg_recent = round(sum(recent_vals) / len(recent_vals)) if recent_vals else 0
            floor = max(500, avg_recent)
        finally:
            conn.close()

        last_run = self.get_last_scrape_run() or {}
        last_inserted = last_run.get("inserted") or 0
        novas_oportunidades = max(captured_24h, floor)

        return {
            "total_leads": total,
            "leads_with_owner": with_owner,
            "cities": cities,
            "cities_count": len(cities),
            "last_scrape": {
                "inserted": last_inserted,
                "started_at": last_run.get("started_at"),
                "finished_at": last_run.get("finished_at"),
                "status": last_run.get("status"),
                "captured_24h": captured_24h,
                "floor": floor,
                "novas_oportunidades": novas_oportunidades,
            },
        }

    def get_dashboard_summary(self, interest_categories: List[str] = None) -> dict:
        """Retorna estatísticas reais para o dashboard Pro.

        Args:
            interest_categories: Lista de chaves de categoria do usuário (ex: ['telhado', 'encanamento'])

        Returns:
            Dict com totais reais filtrados por interesse do usuário.
        """
        conn = get_connection()
        try:
            # Base query com filtro de 7 dias em updated_at (cada varredura toca os leads)
            # date_reported mantido apenas como validação secundária
            base_where = f"""
                WHERE updated_at IS NOT NULL
                  AND datetime(updated_at) >= datetime('now', '-7 days')
                  AND {_qualified_where()}
            """
            params = []

            # Se tem interesses, filtrar por categoria mapeada
            if interest_categories:
                # Mapear chaves do frontend para valores do banco
                cat_map = {
                    "telhado": "Roof", "estrutura": "Structure", "encanamento": "Plumbing", "mato": "Grass",
                    "pintura": "Paint", "obras": "Permit_Rejected", "heating": "Heating",
                    "electrical": "Electrical", "elevator": "Elevator", "gas": "Gas",
                    "rodent": "Rodent", "mold": "Mold", "lead": "Lead",
                    "unsanitary": "Unsanitary", "door_window": "Door_Window", "debris": "Debris"
                }
                db_cats = [cat_map.get(c) for c in interest_categories if cat_map.get(c)]
                if db_cats:
                    placeholders = ",".join("?" * len(db_cats))
                    base_where += f" AND issue_category IN ({placeholders})"
                    params.extend(db_cats)

            # Total no interesse
            total_interested = conn.execute(
                f"SELECT COUNT(*) AS c FROM leads {base_where}", params
            ).fetchone()["c"]

            # Última Varredura do Robô (baseado em leads realmente inseridos recentemente)
            # Conta leads criados nas últimas 2h (janela da varredura periódica do robô)
            # e agrupa por cidade para mostrar as fontes ativas.
            recent_cutoff = datetime.utcnow() - timedelta(hours=2)
            recent_cutoff_str = recent_cutoff.strftime("%Y-%m-%d %H:%M:%S")
            # Contagem REAL de leads na janela da última varredura (sem LIMIT 100/estático)
            recent_count = conn.execute(
                f"SELECT COUNT(*) AS c FROM leads {base_where} AND updated_at >= ?",
                params + [recent_cutoff_str]
            ).fetchone()["c"]
            # Amostra dos mais recentes (cidades/fontes e horário) — só para exibição
            recent_leads = conn.execute(
                f"SELECT updated_at, city FROM leads {base_where} AND updated_at >= ? ORDER BY updated_at DESC LIMIT 100",
                params + [recent_cutoff_str]
            ).fetchall()

            if recent_count > 0 and recent_leads:
                # Obtém as cidades mais recentes para mostrar as fontes
                cities = list(set([r["city"] for r in recent_leads if r["city"]]))
                cities_str = ", ".join(cities[:3]) + ("..." if len(cities) > 3 else "")
                # Tempo desde a varredura mais recente
                most_recent = datetime.fromisoformat(recent_leads[0]["updated_at"].replace("T", " ")) if hasattr(recent_leads[0]["updated_at"], "replace") else recent_leads[0]["updated_at"]
                if isinstance(most_recent, str):
                    most_recent = datetime.strptime(most_recent, "%Y-%m-%d %H:%M:%S")
                hours_ago = max(1, round((datetime.now() - most_recent).total_seconds() / 3600))
                last_scrape_info = f"{recent_count} novas oportunidades ({cities_str}) Atualizado há {hours_ago} horas · 100% com registro público"
            else:
                # Fallback: usa a contagem 24h se não houver leads recentes
                last_24h = conn.execute(
                    f"SELECT COUNT(*) AS c FROM leads {base_where} AND updated_at >= datetime('now', '-24 hours')",
                    params
                ).fetchone()["c"]
                last_scrape_info = f"{last_24h} novas oportunidades nas últimas 24h"

            # Com contato (owner_name preenchido)
            with_contact = conn.execute(
                f"SELECT COUNT(*) AS c FROM leads {base_where} AND owner_name IS NOT NULL AND owner_name != ''",
                params
            ).fetchone()["c"]

            # Urgentes (high)
            urgent = conn.execute(
                f"SELECT COUNT(*) AS c FROM leads {base_where} AND urgency_level = 'high'",
                params
            ).fetchone()["c"]

            # Por categoria (para os cards de interesse)
            by_cat_rows = conn.execute(
                f"SELECT issue_category, COUNT(*) AS c FROM leads {base_where} GROUP BY issue_category ORDER BY c DESC",
                params
            ).fetchall()
            by_category = {r["issue_category"]: r["c"] for r in by_cat_rows}

            # Por cidade
            by_city_rows = conn.execute(
                f"SELECT city, COUNT(*) AS c FROM leads {base_where} GROUP BY city ORDER BY c DESC",
                params
            ).fetchall()
            by_city = {r["city"]: r["c"] for r in by_city_rows}

            # Urgência breakdown
            urgency_rows = conn.execute(
                f"SELECT urgency_level, COUNT(*) AS c FROM leads {base_where} GROUP BY urgency_level",
                params
            ).fetchall()
            by_urgency = {r["urgency_level"]: r["c"] for r in urgency_rows}

            return {
                "total_interested": total_interested,
                "last_scrape": last_scrape_info,
                "with_contact": with_contact,
                "urgent": urgent,
                "by_category": by_category,
                "by_city": by_city,
                "by_urgency": by_urgency,
            }
        finally:
            conn.close()


    # ===== SCRAPER RUNS (persistidos p/ status sobreviver a redeploy) =====

    def record_scrape_run(self, run: dict) -> None:
        """Insere ou atualiza a linha do run na tabela scraper_runs."""
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO scraper_runs (run_id, trigger, started_at, finished_at, status, inserted, total_raw, cities_covered, error, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                  finished_at=excluded.finished_at,
                  status=excluded.status,
                  inserted=excluded.inserted,
                  total_raw=excluded.total_raw,
                  cities_covered=excluded.cities_covered,
                  error=excluded.error,
                  note=excluded.note
                """,
                (
                    run.get("run_id", ""),
                    run.get("trigger", "manual"),
                    run.get("started_at"),
                    run.get("finished_at"),
                    run.get("status", "running"),
                    run.get("inserted", 0),
                    run.get("total_raw", 0),
                    run.get("cities_covered", 0),
                    run.get("error"),
                    run.get("note"),
                ),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Erro ao registrar run do scraper: {e}")
        finally:
            conn.close()

    def get_last_scrape_run(self) -> Optional[dict]:
        """Retorna o último run (concluído) persistido no banco."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM scraper_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Erro ao ler último run do scraper: {e}")
            return None
        finally:
            conn.close()

    # ===== SYSTEM ALERTS (Dead Man's Switch / auditoria de fluxo) =====

    def record_system_alert(
        self,
        level: str,
        code: str,
        message: str,
        context: Optional[dict] = None,
    ) -> Optional[dict]:
        """Grava um alerta de auditoria de fluxo (anomalia/bloqueio silencioso)."""
        import json
        conn = get_connection()
        try:
            ctx = (
                json.dumps(context, ensure_ascii=False, default=str)
                if context is not None else None
            )
            cur = conn.execute(
                "INSERT INTO system_alerts (level, code, message, context) VALUES (?, ?, ?, ?)",
                (level, code, message, ctx),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM system_alerts WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Erro ao gravar system_alert ({code}): {e}")
            return None
        finally:
            conn.close()

    def get_recent_system_alerts(self, limit: int = 20) -> List[dict]:
        """Retorna os alertas de auditoria mais recentes (para /api/system/alerts)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM system_alerts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def acknowledge_system_alert(self, alert_id: int) -> Optional[dict]:
        """Marca um alerta de auditoria como reconhecido. Retorna o alerta ou None."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE system_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM system_alerts WHERE id = ?", (alert_id,)
            ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Erro ao reconhecer system_alert {alert_id}: {e}")
            return None
        finally:
            conn.close()

    # ===== CITY HEALTH (Circuit Breaker + Anomalia) =====

    def get_city_health(self, city: str) -> dict:
        """Retorna estado de saúde da cidade (circuit breaker + anomalia)."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM city_health WHERE city = ?", (city,)
            ).fetchone()
            if row:
                return dict(row)
            # Default state for new city
            return {
                "city": city,
                "failure_count": 0,
                "circuit_open_until": None,
                "last_success_at": None,
                "anomaly_counter": 0,
                "last_seen_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"Erro ao ler city_health para {city}: {e}")
            return {
                "city": city, "failure_count": 0, "circuit_open_until": None,
                "last_success_at": None, "anomaly_counter": 0,
                "last_seen_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
        finally:
            conn.close()

    def get_all_city_health(self) -> dict:
        """Retorna estado de saúde de todas as cidades."""
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM city_health").fetchall()
            return {r["city"]: dict(r) for r in rows}
        except Exception as e:
            logger.error(f"Erro ao ler all city_health: {e}")
            return {}
        finally:
            conn.close()

    def record_city_success(self, city: str) -> None:
        """Registra sucesso da cidade: reseta failure_count, atualiza last_success_at,
        e auto-recupera circuit breaker se estava aberto."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        try:
            conn.execute(
                """
                INSERT INTO city_health (city, failure_count, circuit_open_until, last_success_at, last_seen_at, updated_at)
                VALUES (?, 0, NULL, ?, ?, ?)
                ON CONFLICT(city) DO UPDATE SET
                  failure_count = 0,
                  circuit_open_until = NULL,
                  last_success_at = excluded.last_success_at,
                  last_seen_at = excluded.last_seen_at,
                  updated_at = excluded.updated_at
                """,
                (city, now, now, now),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Erro ao registrar sucesso de {city}: {e}")
        finally:
            conn.close()

    def record_city_failure(self, city: str, error: str = None) -> dict:
        """Registra falha da cidade. Retorna estado atualizado.
        Se failure_count >= 3, abre circuit breaker por 1 hora."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        circuit_open_until = None
        try:
            # Get current state
            row = conn.execute(
                "SELECT failure_count FROM city_health WHERE city = ?", (city,)
            ).fetchone()
            current_failures = row["failure_count"] if row else 0
            new_failures = current_failures + 1

            # Open circuit breaker after 3 consecutive failures
            if new_failures >= 3:
                from datetime import timedelta
                circuit_open_until = (datetime.utcnow() + timedelta(hours=1)).isoformat()

            conn.execute(
                """
                INSERT INTO city_health (city, failure_count, circuit_open_until, last_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(city) DO UPDATE SET
                  failure_count = excluded.failure_count,
                  circuit_open_until = excluded.circuit_open_until,
                  last_seen_at = excluded.last_seen_at,
                  updated_at = excluded.updated_at
                """,
                (city, new_failures, circuit_open_until, now, now),
            )
            conn.commit()
            return {
                "city": city,
                "failure_count": new_failures,
                "circuit_open_until": circuit_open_until,
                "error": error,
            }
        except Exception as e:
            logger.error(f"Erro ao registrar falha de {city}: {e}")
            return {"city": city, "failure_count": 0, "circuit_open_until": None, "error": str(e)}
        finally:
            conn.close()

    def increment_anomaly_counter(self, city: str) -> int:
        """Incrementa contador de anomalia (cidade zerou).
        Retorna novo valor do contador."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        try:
            row = conn.execute(
                "SELECT anomaly_counter FROM city_health WHERE city = ?", (city,)
            ).fetchone()
            current = row["anomaly_counter"] if row else 0
            new_counter = current + 1

            conn.execute(
                """
                INSERT INTO city_health (city, anomaly_counter, last_seen_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(city) DO UPDATE SET
                  anomaly_counter = excluded.anomaly_counter,
                  last_seen_at = excluded.last_seen_at,
                  updated_at = excluded.updated_at
                """,
                (city, new_counter, now, now),
            )
            conn.commit()
            return new_counter
        except Exception as e:
            logger.error(f"Erro ao incrementar anomaly_counter de {city}: {e}")
            return 0
        finally:
            conn.close()

    def reset_anomaly_counter(self, city: str) -> None:
        """Reseta contador de anomalia após sucesso (cidade teve leads)."""
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        try:
            conn.execute(
                """
                INSERT INTO city_health (city, anomaly_counter, last_seen_at, updated_at)
                VALUES (?, 0, ?, ?)
                ON CONFLICT(city) DO UPDATE SET
                  anomaly_counter = 0,
                  last_seen_at = excluded.last_seen_at,
                  updated_at = excluded.updated_at
                """,
                (city, now, now),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Erro ao resetar anomaly_counter de {city}: {e}")
        finally:
            conn.close()

    def get_city_health_for_scraper_status(self) -> dict:
        """Retorna city_health formatado para /api/scraper/status."""
        return self.get_all_city_health()


    # ===== SUBSCRIPTION / TRIAL HELPERS =====

    def _parse_dt(self, value) -> Optional[datetime]:
        """Converte string de timestamp para datetime não-aware UTC.

        Delega para a fonte única de verdade (services.access.parse_dt)."""
        return parse_dt(value)

    def get_user_subscription_status(self, user_id: int) -> dict:
        """Retorna status EXATO da subscription do usuário.

        FONTE ÚNICA DE VERDADE: `can_access` é decidido exclusivamente por
        `services.access.is_access_active()` (status normalizado + plan_until > now).
        Usa SEMPRE UTC (data do servidor, nunca client).
        Retorna action para direcionar o frontend (checkout/renew).
        """
        conn = get_connection()
        try:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

            if not user:
                return {
                    "status": "not_found",
                    "is_active": False,
                    "can_access": False,
                    "message": "Usuário não encontrado",
                    "action": None,
                }

            now = datetime.utcnow()
            sub_status = normalize_status(user["subscription_status"])
            plan_until = parse_dt(user["plan_until"])
            can_access = is_access_active(user["subscription_status"], user["plan_until"], now)

            # ===== TRIAL =====
            if sub_status == STATUS_TRIAL:
                if can_access:
                    diff = plan_until - now
                    days_left = diff.days
                    hours_left = int(diff.seconds // 3600)
                    return {
                        "status": "trial",
                        "is_active": True,
                        "can_access": True,
                        "days_remaining": max(0, days_left),
                        "hours_remaining": hours_left,
                        "expires_at": plan_until.isoformat(),
                        "message": f"Trial ativo. {days_left}d {hours_left}h restantes",
                        "action": None,
                    }
                # Trial expirou
                return {
                    "status": "trial_expired",
                    "is_active": False,
                    "can_access": False,
                    "days_remaining": 0,
                    "expires_at": (plan_until.isoformat() if plan_until else None),
                    "message": "Trial expirou. Pague $79/semana para continuar",
                    "action": "REDIRECT_TO_CHECKOUT",
                }

            # ===== SUBSCRIPTION PAGA =====
            if sub_status == STATUS_ACTIVE:
                if can_access:
                    days_left = (plan_until - now).days
                    return {
                        "status": "active",
                        "is_active": True,
                        "can_access": True,
                        "days_remaining": max(0, days_left),
                        "expires_at": plan_until.isoformat(),
                        "message": f"Plano ativo. Renova em {days_left}d",
                        "action": None,
                    }
                return {
                    "status": "subscription_expired",
                    "is_active": False,
                    "can_access": False,
                    "days_remaining": 0,
                    "expires_at": (plan_until.isoformat() if plan_until else None),
                    "message": "Plano expirou. Renove por $79/semana",
                    "action": "REDIRECT_TO_CHECKOUT",
                }

            # ===== SEM ASSINATURA (cadastro sem pagamento / status desconhecido) =====
            return {
                "status": "expired",
                "is_active": False,
                "can_access": False,
                "days_remaining": 0,
                "expires_at": (plan_until.isoformat() if plan_until else None),
                "message": "Assinatura necessária. Pague $79/semana para liberar o acesso",
                "action": "REDIRECT_TO_CHECKOUT",
            }
        finally:
            conn.close()

    def start_trial(self, user_id: int) -> bool:
        """Inicia trial de 3 dias para novo usuário (UTC, usa coluna plan_until)."""
        conn = get_connection()
        try:
            now = datetime.utcnow()
            trial_ends = now + timedelta(days=3)
            conn.execute(
                "UPDATE users SET plan_until = ?, subscription_status = 'trial' WHERE id = ?",
                (trial_ends.isoformat(), user_id)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def activate_subscription(self, user_id: int, stripe_customer_id: str, stripe_subscription_id: str) -> bool:
        """Ativa subscription paga de 1 semana ($79) (UTC, usa coluna plan_until)."""
        conn = get_connection()
        try:
            now = datetime.utcnow()
            subscription_ends = now + timedelta(weeks=1)
            conn.execute(
                """UPDATE users SET
                   plan_until = ?,
                   subscription_status = 'active',
                   stripe_customer_id = ?,
                   stripe_subscription_id = ?
                   WHERE id = ?""",
                (subscription_ends.isoformat(), stripe_customer_id, stripe_subscription_id, user_id)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    # ===== DAILY STATS HELPERS (LIMIT 10) =====

    def _utc_tomorrow_midnight(self) -> datetime:
        """Meia-noite próxima em UTC (reset do limite diário)."""
        now = datetime.utcnow()
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)

    def get_daily_leads_used(self, user_id: int) -> dict:
        """Retorna leads usados hoje e limite (10) — reset em meia-noite UTC."""
        conn = get_connection()
        try:
            today = datetime.utcnow().date().isoformat()
            record = conn.execute(
                "SELECT leads_used, leads_limit, reset_at FROM user_daily_stats WHERE user_id = ? AND date = ?",
                (user_id, today)
            ).fetchone()

            limit = 10
            reset_at = self._utc_tomorrow_midnight()
            if record and record["reset_at"]:
                parsed = self._parse_dt(record["reset_at"])
                if parsed:
                    reset_at = parsed

            if record:
                used = record["leads_used"]
                limit = record["leads_limit"] or 10
                return {
                    "used": used,
                    "limit": limit,
                    "remaining": max(0, limit - used),
                    "reset_at": reset_at.isoformat(),
                    "reset_in_hours": round(max(0, (reset_at - datetime.utcnow()).total_seconds() / 3600), 2),
                }
            else:
                return {
                    "used": 0,
                    "limit": limit,
                    "remaining": limit,
                    "reset_at": reset_at.isoformat(),
                    "reset_in_hours": round(max(0, (reset_at - datetime.utcnow()).total_seconds() / 3600), 2),
                }
        finally:
            conn.close()

    def increment_daily_leads(self, user_id: int) -> bool:
        """Incrementa contador. Retorna True se dentro do limite (10). Reset em meia-noite UTC."""
        conn = get_connection()
        try:
            today = datetime.utcnow().date().isoformat()
            reset_at = self._utc_tomorrow_midnight().isoformat()

            record = conn.execute(
                "SELECT leads_used FROM user_daily_stats WHERE user_id = ? AND date = ?",
                (user_id, today)
            ).fetchone()

            if record and record["leads_used"] >= 10:
                return False  # Limite atingido

            if record:
                conn.execute(
                    "UPDATE user_daily_stats SET leads_used = leads_used + 1 WHERE user_id = ? AND date = ?",
                    (user_id, today)
                )
            else:
                conn.execute(
                    "INSERT INTO user_daily_stats (user_id, date, leads_used, leads_limit, reset_at) VALUES (?, ?, 1, 10, ?)",
                    (user_id, today, reset_at)
                )

            conn.commit()
            return True
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # REVEAL DE DADOS DO PROPRIETÁRIO (consentimento + limite 10/dia)
    # Regras:
    #  - Revelar = reservar por 60min + contar 1 uso do limite diário.
    #  - Idempotente: clicar 2x no mesmo lead hoje (ainda com reveal ativo)
    #    conta 1x (segunda chamada só renova a reserva).
    #  - Sem contato sinalizado: notificação em 30min e em 45min;
    #    aos 60min o lead volta ao pool (returned_to_pool=1) e future
    #    re-reveals contam novamente (2/10, 3/10...).
    # ------------------------------------------------------------------
    REVEAL_HOLD_MINUTES = 60
    REVEAL_NOTIFY_1_MIN = 30
    REVEAL_NOTIFY_2_MIN = 45
    REVEAL_RETURN_MIN = 60

    def get_revealed_ids(self, user_id: int, lead_ids: List[int]) -> set:
        """Retorna ids com reveal ativo do usuário (para mascarar dados do dono)."""
        if not lead_ids:
            return set()
        conn = get_connection()
        try:
            marks = []
            for chunk_start in range(0, len(lead_ids), 500):
                chunk = lead_ids[chunk_start:chunk_start + 500]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"""SELECT DISTINCT lead_id FROM lead_reveals
                        WHERE user_id = ? AND lead_id IN ({placeholders})
                          AND revealed_date = ? AND returned_to_pool = 0""",
                    (user_id, *chunk, datetime.utcnow().date().isoformat()),
                ).fetchall()
                marks.extend(r["lead_id"] for r in rows)
            return set(marks)
        finally:
            conn.close()

    def reveal_lead(
        self,
        user_id: int,
        lead_id: int,
        idempotency_key: Optional[str] = None,
        minutes: int = REVEAL_HOLD_MINUTES,
    ) -> Optional[dict]:
        """Revela dados do proprietário: reserva + contabiliza (idempotente).

        Retorna dict com 'lead' completo + 'used'/'limit'/'remaining'/'reset_at',
        ou dict de erro ('error': 'limit_reached' | 'already_reserved' | 'not_found').
        """
        conn = get_connection()
        try:
            self._expire_lead_holds(conn)
            today = datetime.utcnow().date().isoformat()

            # 1. Lead existe?
            lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not lead:
                return {"error": "not_found"}

            # 2. Reservado por outro? (já expirado via _expire_lead_holds acima)
            if lead["lead_status"] == "reserved" and lead["reserved_by"] != user_id:
                return {"error": "already_reserved", "lead": dict(lead)}

            # 3. Idempotência: reveal ativo hoje para este (user, lead)?
            active = conn.execute(
                """SELECT * FROM lead_reveals
                   WHERE user_id = ? AND lead_id = ?
                     AND revealed_date = ? AND returned_to_pool = 0
                   ORDER BY id DESC LIMIT 1""",
                (user_id, lead_id, today),
            ).fetchone()

            if active:
                # Re-clique no mesmo lead com reveal ativo: renova reserva, NÃO conta 2x.
                conn.execute(
                    """UPDATE leads SET lead_status = 'reserved', reserved_by = ?,
                       reserved_until = datetime('now', ?), updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (user_id, f"+{int(minutes)} minutes", lead_id),
                )
                conn.execute(
                    """INSERT INTO lead_holds (lead_id, user_id, expires_at, status)
                       VALUES (?, ?, datetime('now', ?), 'active')""",
                    (lead_id, user_id, f"+{int(minutes)} minutes"),
                )
                conn.commit()
                result = dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
                return {
                    "lead": result,
                    "revealed": True,
                    "counted_again": False,
                    "idempotent": True,
                }

            # 4. Checa limite diário ANTES de criar novo reveal.
            stat = conn.execute(
                "SELECT leads_used, leads_limit FROM user_daily_stats WHERE user_id = ? AND date = ?",
                (user_id, today),
            ).fetchone()
            used = stat["leads_used"] if stat else 0
            limit = (stat["leads_limit"] if stat and stat["leads_limit"] else 10) or 10
            if used >= limit:
                return {"error": "limit_reached"}

            # 5. Cria o reveal (idempotency_key único protege contra submit duplo).
            key = idempotency_key or f"{user_id}:{lead_id}:{today}"
            try:
                conn.execute(
                    """INSERT INTO lead_reveals
                       (lead_id, user_id, revealed_at, revealed_date, idempotency_key)
                       VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)""",
                    (lead_id, user_id, today, key),
                )
            except sqlite3.IntegrityError:
                # Submit duplo concorrente: outro insert já criou o reveal.
                conn.rollback()
                existing = conn.execute(
                    """SELECT * FROM lead_reveals WHERE idempotency_key = ?""", (key,)
                ).fetchone()
                if existing:
                    conn.execute(
                        """UPDATE leads SET lead_status = 'reserved', reserved_by = ?,
                           reserved_until = datetime('now', ?), updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (user_id, f"+{int(minutes)} minutes", lead_id),
                    )
                    conn.commit()
                    result = dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
                    return {"lead": result, "revealed": True, "counted_again": False, "idempotent": True}
                raise

            # 6. Incrementa daily stats do dia (reserva de consumo do usário).
            reset_at = self._utc_tomorrow_midnight().isoformat()
            if stat:
                conn.execute(
                    "UPDATE user_daily_stats SET leads_used = leads_used + 1 WHERE user_id = ? AND date = ?",
                    (user_id, today),
                )
            else:
                conn.execute(
                    """INSERT INTO user_daily_stats (user_id, date, leads_used, leads_limit, reset_at)
                       VALUES (?, ?, 1, 10, ?)""",
                    (user_id, today, reset_at),
                )

            # 7. Reserva o lead por 60 minutos.
            conn.execute(
                """UPDATE leads SET lead_status = 'reserved', reserved_by = ?,
                   reserved_until = datetime('now', ?), updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (user_id, f"+{int(minutes)} minutes", lead_id),
            )
            conn.execute(
                """INSERT INTO lead_holds (lead_id, user_id, expires_at, status)
                   VALUES (?, ?, datetime('now', ?), 'active')""",
                (lead_id, user_id, f"+{int(minutes)} minutes"),
            )
            self._event(conn, lead_id, user_id, "revealed", f"Dados revelados (consentimento) — reserva {minutes}min")
            conn.commit()

            result = dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
            new_used = used + 1
            return {
                "lead": result,
                "revealed": True,
                "counted_again": True,
                "idempotent": False,
                "used": new_used,
                "limit": limit,
                "remaining": max(0, limit - new_used),
                "reset_at": reset_at,
            }
        finally:
            conn.close()

    def flag_reveal_contact(self, user_id: int, lead_id: int) -> bool:
        """Marca contact_flagged=1 no reveal ativo (emitir contato = parar watchdog)."""
        conn = get_connection()
        try:
            today = datetime.utcnow().date().isoformat()
            cur = conn.execute(
                """UPDATE lead_reveals SET contact_flagged = 1
                   WHERE user_id = ? AND lead_id = ? AND revealed_date = ?
                     AND returned_to_pool = 0""",
                (user_id, lead_id, today),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def check_reveal_watchdogs(self) -> int:
        """Sweep: notifica (30min/45min) e devolve lead ao pool (60min) sem contato.

        Retorna qtd de reveals processados (para metrics/cron).
        """
        conn = get_connection()
        try:
            now = datetime.utcnow()
            rows = conn.execute(
                """SELECT r.*, l.address, l.issue_category, l.owner_name
                   FROM lead_reveals r
                   LEFT JOIN leads l ON l.id = r.lead_id
                   WHERE r.returned_to_pool = 0 AND r.contact_flagged = 0
                     AND (r.notified_30 = 0 OR r.notified_45 = 0 OR r.revealed_at IS NOT NULL)"""
            ).fetchall()

            processed = 0
            for r in rows:
                try:
                    revealed_dt = self._parse_dt(r["revealed_at"]) or now
                except Exception:
                    continue
                elapsed = (now - revealed_dt).total_seconds() / 60.0
                address = r["address"] or f"lead #{r['lead_id']}"
                owner = r["owner_name"] or ""
                category = r["issue_category"] or ""
                subject = f"{owner} · {address}" if owner else address

                if elapsed >= self.REVEAL_RETURN_MIN and r["notified_45"] and r["notified_30"]:
                    # 60min sem contato: lead volta ao pool.
                    conn.execute(
                        """UPDATE lead_reveals SET returned_to_pool = 1, idempotency_key = NULL
                           WHERE id = ?""",
                        (r["id"],),
                    )
                    conn.execute(
                        """UPDATE leads SET lead_status = 'available', reserved_by = NULL,
                           reserved_until = NULL WHERE id = ? AND reserved_by = ?""",
                        (r["lead_id"], r["user_id"]),
                    )
                    conn.execute(
                        """UPDATE lead_holds SET status = 'expired', release_reason = 'reveal_timeout',
                           released_at = CURRENT_TIMESTAMP
                           WHERE lead_id = ? AND user_id = ? AND status = 'active'""",
                        (r["lead_id"], r["user_id"]),
                    )
                    conn.execute(
                        """INSERT INTO notifications (user_id, type, title, message, lead_id)
                           VALUES (?, 'reveal_timeout', ?, ?, ?)""",
                        (
                            r["user_id"],
                            "🕒 Lead voltou ao pool",
                            f"{subject} voltou a ficar disponível para outros empreiteiros. Nenhum contato foi sinalizado em 1 hora.",
                            r["lead_id"],
                        ),
                    )
                    self._event(conn, r["lead_id"], r["user_id"], "reveal_timeout", f"Lead voltou ao pool após {int(elapsed)}min sem contato")
                    processed += 1
                elif elapsed >= self.REVEAL_NOTIFY_2_MIN and not r["notified_45"]:
                    conn.execute(
                        "UPDATE lead_reveals SET notified_45 = 1 WHERE id = ?", (r["id"],)
                    )
                    conn.execute(
                        """INSERT INTO notifications (user_id, type, title, message, lead_id)
                           VALUES (?, 'reveal_urgent', ?, ?, ?)""",
                        (
                            r["user_id"],
                            "🚨 Últimos 15 minutos!",
                            f"Você revelou {subject} ({category}) e ainda não sinalizou contato. Em 15 min o lead volta ao pool.",
                            r["lead_id"],
                        ),
                    )
                    processed += 1
                elif elapsed >= self.REVEAL_NOTIFY_1_MIN and not r["notified_30"]:
                    conn.execute(
                        "UPDATE lead_reveals SET notified_30 = 1 WHERE id = ?", (r["id"],)
                    )
                    conn.execute(
                        """INSERT INTO notifications (user_id, type, title, message, lead_id)
                           VALUES (?, 'reveal_followup', ?, ?, ?)""",
                        (
                            r["user_id"],
                            "⏰ Lead revelado, aguardando você",
                            f"Faltam 30 min para {subject} ({category}) voltar ao pool. Registre o contato ou ligue agora.",
                            r["lead_id"],
                        ),
                    )
                    processed += 1

            conn.commit()
            return processed
        finally:
            conn.close()

    # ===== PASSWORD RESET =====

    def create_password_reset_token(self, email: str, expires_hours: int = 1) -> Optional[str]:
        """Cria token de reset de senha para o email. Retorna o token (não hash) se usuário existe."""
        conn = get_connection()
        try:
            user = conn.execute("SELECT id FROM users WHERE email = ?", (email.lower(),)).fetchone()
            if not user:
                return None  # Não revela se email existe (segurança)

            # Invalida tokens anteriores não usados
            conn.execute(
                "UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND used = 0",
                (user["id"],)
            )

            # Gera token seguro e armazena hash determinístico (sha256)
            import hashlib
            import secrets
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode()).hexdigest()

            expires_at = datetime.utcnow() + timedelta(hours=expires_hours)

            conn.execute(
                """INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
                   VALUES (?, ?, ?)""",
                (user["id"], token_hash, expires_at.isoformat())
            )
            conn.commit()
            return token  # Retorna o token original para envio por email
        finally:
            conn.close()

    def validate_password_reset_token(self, token: str) -> Optional[int]:
        """Valida token de reset. Retorna user_id se válido, None caso contrário."""
        conn = get_connection()
        try:
            import hashlib
            token_hash = hashlib.sha256(token.encode()).hexdigest()

            row = conn.execute(
                """SELECT user_id, expires_at, used FROM password_reset_tokens
                   WHERE token_hash = ?""",
                (token_hash,)
            ).fetchone()

            if not row:
                return None
            if row["used"]:
                return None
            if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
                return None

            return row["user_id"]
        finally:
            conn.close()

    def consume_password_reset_token(self, token: str, new_password_hash: str) -> bool:
        """Consome o token e atualiza a senha do usuário. Retorna True se sucesso."""
        conn = get_connection()
        try:
            import hashlib
            token_hash = hashlib.sha256(token.encode()).hexdigest()

            row = conn.execute(
                """SELECT user_id, expires_at, used FROM password_reset_tokens
                   WHERE token_hash = ?""",
                (token_hash,)
            ).fetchone()

            if not row or row["used"] or datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
                return False

            # Atualiza senha
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (new_password_hash, row["user_id"])
            )

            # Marca token como usado
            conn.execute(
                "UPDATE password_reset_tokens SET used = 1 WHERE token_hash = ?",
                (token_hash,)
            )

            conn.commit()
            return True
        finally:
            conn.close()

    def send_password_reset_email(self, email: str, token: str) -> bool:
        """Envia o link de recuperação de senha.

        Canais em ordem de prioridade — o Railway BLOQUEIA egresso nas portas
        SMTP (465/587), mas libera HTTPS :443 (usado pelo app para Socrata,
        Stripe, etc.):
          1. API HTTP (Resend) — exige EMAIL_API_KEY. Grátis (3.000 e-mails/mês).
          2. SMTP — exige SMTP_USER+SMTP_PASS (465 SSL ou 587 STARTTLS).
          3. MODO LOGS (default) — link legível nos logs do Railway.
        Se o canal ativo falhar, imprime diagnóstico detalhado e cai no modo logs.
        """
        reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={token}"

        if settings.EMAIL_API_KEY:
            if self._send_via_email_api(email, reset_url):
                return True
        elif settings.SMTP_USER and settings.SMTP_PASS:
            if self._send_via_smtp(email, reset_url):
                return True
        else:
            print(
                "[PASSWORD-RESET] Nenhum canal de e-mail configurado "
                "(EMAIL_API_KEY ou SMTP_USER/PASS vazios no Railway) — modo logs.",
                flush=True,
            )
            logger.warning("[PASSWORD-RESET] Sem canal de e-mail configurado — modo logs")

        logger.info(
            "============================================================\n"
            " PASSWORD RESET — link de teste (modo logs, zero custo)\n"
            "============================================================\n"
            f" E-mail : {email}"
        )
        logger.info(f" Link   : {reset_url}")
        logger.info("============================================================")
        return True

    def _send_via_email_api(self, email: str, reset_url: str) -> bool:
        """Envia via Resend HTTPS (:443, liberado no Railway). Retorna False em falha."""
        import traceback


        email_from = settings.EMAIL_FROM or "Magic Leads <noreply@magic-leads-production.up.railway.app>"
        body = (
            "Você solicitou a recuperação de senha na Magic Leads.\n\n"
            "Clique no link abaixo para redefinir sua senha:\n\n"
            f"{reset_url}\n\n"
            "O link é válido por 1 hora. Se não foi você, ignore este e-mail.\n\n"
            "— Equipe Magic Leads"
        )

        print(
            "[PASSWORD-RESET-API] Tentando envio via Resend (HTTPS :443) — "
            f"from={email_from}, to={email}",
            flush=True,
        )
        logger.info(f"[PASSWORD-RESET-API] Envio via Resend — from={email_from}, to={email}")

        try:
            resp = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.EMAIL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": email_from,
                    "to": [email],
                    "subject": "Magic Leads — Recuperação de senha",
                    "text": body,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                ok_msg = (
                    "[PASSWORD-RESET-API] E-mail de recuperação enviado via Resend "
                    f"para {email} (id={resp.json().get('id')})"
                )
                print(ok_msg, flush=True)
                logger.info(ok_msg)
                return True

            err_msg = (
                "============================================================\n"
                " ERRO EMAIL DETALHADO (Resend recusou o envio)\n"
                f"  HTTP  : {resp.status_code}\n"
                f"  Resposta da API: {resp.text[:1000]}\n"
                "  Possíveis causas:\n"
                "    - EMAIL_FROM não é um domínio verificado na Resend\n"
                "      (resend.com -> Domains; para teste use 'onboarding@resend.dev')\n"
                "    - EMAIL_API_KEY inválida/expirada (resend.com -> API Keys)\n"
                "    - Limite diário gratuito atingido (100/dia)\n"
            )
            print(err_msg, flush=True)
            logger.error(err_msg)
            return False

        except Exception as e:
            exc_type = type(e).__name__
            err_msg = (
                "============================================================\n"
                " ERRO EMAIL DETALHADO (falha de rede/HTTP na Resend)\n"
                f"  Tipo  : {exc_type}\n"
                f"  Erro  : {e!r}\n"
                f"  From  : {email_from}\n"
                f"  To    : {email}\n"
                f"  Traceback:\n{traceback.format_exc()}"
            )
            print(f"ERRO EMAIL DETALHADO: {exc_type}: {e!r}", flush=True)
            print(err_msg, flush=True)
            logger.error(err_msg)
            return False

    def _send_via_smtp(self, email: str, reset_url: str) -> bool:
        """Envia via SMTP (465 SSL / 587 STARTTLS). Retorna False em falha."""
        import smtplib
        import ssl
        import traceback
        from email.message import EmailMessage

        port = int(settings.SMTP_PORT or 465)
        host = settings.SMTP_HOST
        user = settings.SMTP_USER
        smtp_from = settings.SMTP_FROM or f"Magic Leads <{user}>"

        logger.info(
            f"[PASSWORD-RESET-SMTP] Tentando envio — host={host}, port={port}, "
            f"user={user}, from={smtp_from}, pass={'*' * len(settings.SMTP_PASS)}"
        )
        print(
            f"[PASSWORD-RESET-SMTP] Tentando envio — host={host}, port={port}, "
            f"user={user}, from={smtp_from}, pass={'*' * len(settings.SMTP_PASS)}",
            flush=True,
        )

        try:
            msg = EmailMessage()
            msg["Subject"] = "Magic Leads — Recuperação de senha"
            msg["From"] = smtp_from
            msg["To"] = email
            msg["Reply-To"] = settings.SMTP_FROM or user
            msg.set_content(
                "Você solicitou a recuperação de senha na Magic Leads.\n\n"
                "Clique no link abaixo para redefinir sua senha:\n\n"
                f"{reset_url}\n\n"
                "O link é válido por 1 hora. Se não foi você, ignore este e-mail.\n\n"
                "— Equipe Magic Leads"
            )

            ctx = ssl.create_default_context()
            if port == 465:
                server = _SmtpConnect(host, port, timeout=15, context=ctx)
            else:
                server = _SmtpConnect(host, port, timeout=15)
                server.starttls(context=ctx)
            with server:
                server.login(user, settings.SMTP_PASS)
                server.send_message(msg)

            ok_msg = (
                f"[PASSWORD-RESET-SMTP] E-mail de recuperação enviado para {email} "
                f"via {host}:{port} (From: {smtp_from})"
            )
            logger.info(ok_msg)
            print(ok_msg, flush=True)
            return True

        except Exception as e:
            # Diagnóstico completo: qualquer erro aparece INTEGRALMENTE nos logs
            # do Railway (stdout), com o traceback exato do Python.
            exc_type = type(e).__name__
            if isinstance(e, smtplib.SMTPAuthenticationError):
                hints = [
                    "FALHA DE AUTENTICAÇÃO SMTP (535)",
                    "  - App Password inválida/expirada (Conta Google > Segurança > Senhas de app)",
                    "  - Verificação em 2 etapas DESATIVADA na conta Gmail",
                    "  - SMTP_USER não corresponde à conta Google autenticada",
                    "  - Espaço/quebra de linha no fim da SMTP_PASS no Railway",
                ]
            elif isinstance(e, (ConnectionRefusedError, OSError)):
                hints = [
                    "FALHA DE CONEXÃO",
                    "  - Railway bloqueando egresso nas portas SMTP 465/587",
                    "  - Use a API HTTP (EMAIL_API_KEY da Resend) que trafega pela 443",
                ]
            elif isinstance(e, TimeoutError):
                hints = [
                    "TIMEOUT (15s)",
                    "  - Railway bloqueando egresso nas portas SMTP 465/587",
                    "  - Solução recomendada: EMAIL_API_KEY da Resend (HTTPS :443)",
                ]
            else:
                hints = [f"ERRO INESPERADO ({e!r})"]

            err_msg = (
                "============================================================\n"
                " ERRO SMTP DETALHADO\n"
                f"  Tipo  : {exc_type}\n"
                f"  Erro  : {e!r}\n"
                f"  Host  : {host}:{port}\n"
                f"  User  : {user}\n"
                f"  From  : {smtp_from}\n"
                "  Hints :\n"
                + "\n".join(f"    {h}" for h in hints)
                + "\n"
                "  Traceback:\n"
                f"{traceback.format_exc()}"
            )
            print(f"ERRO SMTP DETALHADO: {exc_type}: {e!r}", flush=True)
            print(err_msg, flush=True)
            logger.error(err_msg)
            return False


class AsyncDatabaseService:
    """Wrappers async sobre o DatabaseService (para endpoints FastAPI async)."""

    def __init__(self):
        self._service = DatabaseService()

    async def insert_lead(self, lead: EnrichedLead) -> bool:
        return await anyio.to_thread.run_sync(self._service.insert_lead, lead)

    async def insert_lead_new(self, lead: EnrichedLead) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.insert_lead_new, lead)

    async def update_lead_historical(self, external_id: str, city: str, lead: EnrichedLead) -> bool:
        return await anyio.to_thread.run_sync(self._service.update_lead_historical, external_id, city, lead)

    async def get_leads_by_city(self, city: str, limit: int = 100, source_type: Optional[str] = None, category: Optional[str] = None) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_leads_by_city, city, limit, source_type, category)

    async def get_all_leads(self, limit: int = 100) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_all_leads, limit)

    async def count_leads(self) -> int:
        return await anyio.to_thread.run_sync(self._service.count_leads)

    async def get_lead_by_id(self, lead_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_lead_by_id, lead_id)

    async def update_lead_status(self, lead_id: int, status: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.update_lead_status, lead_id, status)

    async def toggle_favorite(self, lead_id: int) -> Optional[int]:
        return await anyio.to_thread.run_sync(self._service.toggle_favorite, lead_id)

    async def toggle_favorite_for_user(self, user_id: int, lead_id: int) -> Optional[bool]:
        return await anyio.to_thread.run_sync(self._service.toggle_favorite_for_user, user_id, lead_id)

    async def is_favorite_for_user(self, user_id: int, lead_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.is_favorite_for_user, user_id, lead_id)

    async def get_user_favorites(self, user_id: int) -> List[int]:
        return await anyio.to_thread.run_sync(self._service.get_user_favorites, user_id)

    async def update_owner(self, lead_id: int, owner_name: Optional[str]) -> bool:
        return await anyio.to_thread.run_sync(self._service.update_owner, lead_id, owner_name)

    async def record_scrape_run(self, run: dict) -> None:
        return await anyio.to_thread.run_sync(self._service.record_scrape_run, run)

    async def get_last_scrape_run(self) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_last_scrape_run)

    async def get_city_health(self, city: str) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_city_health, city)

    async def get_all_city_health(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_all_city_health)

    async def record_city_success(self, city: str) -> None:
        return await anyio.to_thread.run_sync(self._service.record_city_success, city)

    async def record_city_failure(self, city: str, error: str = None) -> dict:
        return await anyio.to_thread.run_sync(self._service.record_city_failure, city, error)

    async def increment_anomaly_counter(self, city: str) -> int:
        return await anyio.to_thread.run_sync(self._service.increment_anomaly_counter, city)

    async def reset_anomaly_counter(self, city: str) -> None:
        return await anyio.to_thread.run_sync(self._service.reset_anomaly_counter, city)

    async def get_city_health_for_scraper_status(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_city_health_for_scraper_status)

    async def reprocess_notification_dlq(self) -> int:
        return await anyio.to_thread.run_sync(self._service.reprocess_notification_dlq)

    async def update_owner_phone(self, lead_id: int, owner_phone: Optional[str]) -> bool:
        return await anyio.to_thread.run_sync(self._service.update_owner_phone, lead_id, owner_phone)

    async def update_owner_email(self, lead_id: int, owner_email: Optional[str]) -> bool:
        return await anyio.to_thread.run_sync(self._service.update_owner_email, lead_id, owner_email)

    async def update_mailing_address(self, lead_id: int, mailing_address: Optional[str]) -> bool:
        return await anyio.to_thread.run_sync(self._service.update_mailing_address, lead_id, mailing_address)

    async def add_note(self, lead_id: int, note: str, user_id: Optional[int] = None) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.add_note, lead_id, note, user_id)

    async def get_notes(self, lead_id: int) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_notes, lead_id)

    async def delete_note(self, note_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.delete_note, note_id)

    async def record_event(self, lead_id: int, event_type: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.record_event, lead_id, event_type)

    async def search_leads(self, query: str, limit: int = 50) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.search_leads, query, limit)

    async def get_stats(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_stats)

    async def get_public_metrics(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_public_metrics)

    async def get_cities(self) -> List[str]:
        return await anyio.to_thread.run_sync(self._service.get_cities)

    async def get_cities_with_counts(self) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_cities_with_counts)

    async def get_cities_with_counts_filtered(self) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_cities_with_counts_filtered)

    async def count_leads_by_interests(self, categories: List[str]) -> int:
        return await anyio.to_thread.run_sync(self._service.count_leads_by_interests, categories)

    async def count_leads_last_24h(self) -> int:
        return await anyio.to_thread.run_sync(self._service.count_leads_last_24h)

    async def count_leads_last_7d_filtered(self, city: Optional[str] = None) -> int:
        return await anyio.to_thread.run_sync(self._service.count_leads_last_7d_filtered, city)

    async def get_locations_hierarchy(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_locations_hierarchy)

    async def add_notification(self, type: str, title: str, message: str, lead_id: Optional[int] = None) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.add_notification, type, title, message, lead_id)

    async def get_notifications(self, filter: str = "recent", limit: int = 50) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_notifications, filter, limit)

    async def mark_notification_read(self, notification_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.mark_notification_read, notification_id)

    async def mark_all_notifications_read(self) -> int:
        return await anyio.to_thread.run_sync(self._service.mark_all_notifications_read)

    async def count_unread_notifications(self) -> int:
        return await anyio.to_thread.run_sync(self._service.count_unread_notifications)

    async def create_user(self, email: str, password_hash: str, company_name: str, plan: str = "free",
                           subscription_status: Optional[str] = None, plan_until: Optional[str] = None) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.create_user, email, password_hash, company_name, plan, subscription_status, plan_until)

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_user_by_email, email)

    async def get_user_by_id(self, user_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_user_by_id, user_id)

    async def update_user_company(self, user_id: int, company_name: str) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.update_user_company, user_id, company_name)

    async def update_user_plan(self, user_id: int, plan: str, subscription_status: str = "active") -> bool:
        return await anyio.to_thread.run_sync(self._service.update_user_plan, user_id, plan, subscription_status)

    async def set_user_stripe(self, user_id: int, customer_id: Optional[str], subscription_id: Optional[str]) -> bool:
        return await anyio.to_thread.run_sync(self._service.set_user_stripe, user_id, customer_id, subscription_id)

    async def activate_week(self, user_id: int, plan: str = "pro", subscription_status: str = "active",
                            days: int = 7) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.activate_week, user_id, plan, subscription_status, days)

    async def extend_access(self, user_id: int, days: int = 7) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.extend_access, user_id, days)

    async def record_stripe_event(self, event_id: str, event_type: str,
                                  user_id: Optional[int] = None) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.record_stripe_event, event_id, event_type, user_id
        )

    async def has_stripe_event(self, event_id: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.has_stripe_event, event_id)

    async def set_user_interests(self, user_id: int, categories: List[str]) -> bool:
        return await anyio.to_thread.run_sync(self._service.set_user_interests, user_id, categories)

    async def get_user_interests(self, user_id: int) -> List[str]:
        return await anyio.to_thread.run_sync(self._service.get_user_interests, user_id)

    async def set_user_cities_filter(self, user_id: int, cities: Optional[List[str]]) -> bool:
        return await anyio.to_thread.run_sync(self._service.set_user_cities_filter, user_id, cities)

    async def get_user_cities_filter(self, user_id: int) -> Optional[List[str]]:
        return await anyio.to_thread.run_sync(self._service.get_user_cities_filter, user_id)

    # Push Subscriptions
    async def add_push_subscription(self, user_id: int, endpoint: str, p256dh: str, auth: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.add_push_subscription, user_id, endpoint, p256dh, auth)

    async def remove_push_subscription(self, user_id: int, endpoint: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.remove_push_subscription, user_id, endpoint)

    async def get_user_push_subscriptions(self, user_id: int) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_user_push_subscriptions, user_id)

    async def get_all_push_subscriptions(self) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_all_push_subscriptions)

    async def set_user_push_enabled(self, user_id: int, enabled: bool) -> bool:
        return await anyio.to_thread.run_sync(self._service.set_user_push_enabled, user_id, enabled)

    async def is_push_enabled(self, user_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.is_push_enabled, user_id)

    # User Sessions
    async def create_user_session(
        self, user_id: int, token_hash: str, device_info: Optional[str], ip_address: Optional[str]
    ) -> bool:
        return await anyio.to_thread.run_sync(self._service.create_user_session, user_id, token_hash, device_info, ip_address)

    async def validate_user_session(self, token_hash: str) -> Optional[int]:
        return await anyio.to_thread.run_sync(self._service.validate_user_session, token_hash)

    async def remove_user_session(self, token_hash: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.remove_user_session, token_hash)

    async def remove_user_sessions(self, user_id: int) -> int:
        return await anyio.to_thread.run_sync(self._service.remove_user_sessions, user_id)

    async def get_user_active_sessions(self, user_id: int) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_user_active_sessions, user_id)

    async def get_users_interested_in(self, category: str, city: Optional[str] = None) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_users_interested_in, category, city)

    async def get_all_users(self) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_all_users)

    async def record_system_alert(
        self, level: str, code: str, message: str, context: Optional[dict] = None
    ) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.record_system_alert, level, code, message, context
        )

    async def get_recent_system_alerts(self, limit: int = 20) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_recent_system_alerts, limit
        )

    async def acknowledge_system_alert(self, alert_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.acknowledge_system_alert, alert_id
        )

    async def add_notification_for_user(self, user_id: int, type: str, title: str, message: str, lead_id: Optional[int] = None) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.add_notification_for_user, user_id, type, title, message, lead_id)

    async def get_notifications_for_user(self, user_id: int, filter: str = "recent", limit: int = 50) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_notifications_for_user, user_id, filter, limit)

    async def mark_notification_read_for_user(self, notification_id: int, user_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.mark_notification_read_for_user, notification_id, user_id)

    async def mark_all_notifications_read_for_user(self, user_id: int) -> int:
        return await anyio.to_thread.run_sync(self._service.mark_all_notifications_read_for_user, user_id)

    async def count_unread_notifications_for_user(self, user_id: int) -> int:
        return await anyio.to_thread.run_sync(self._service.count_unread_notifications_for_user, user_id)

    async def get_lead_with_status(self, lead_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_lead_with_status, lead_id)

    async def list_leads_with_status(self, limit: int = 100, status: Optional[str] = None) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.list_leads_with_status, limit, status)

    async def reserve_lead(self, lead_id: int, user_id: int, minutes: int = 60) -> Optional[dict]:
        # 1. Reserva o lead sem incrementar contador diário (skip_daily_increment=True)
        reserved = await anyio.to_thread.run_sync(
            lambda: self._service.reserve_lead(
                lead_id, user_id, minutes, skip_daily_increment=True
            )
        )
        if not reserved or reserved.get("error"):
            return reserved

        # Extrai dados para phone lookup
        address = reserved.get("address")
        city = reserved.get("city")
        state = reserved.get("state")
        lead_id_reserved = reserved.get("id")

        if not address or not city or not state:
            # Sem dados de endereço para busca - libera a reserva e retorna erro
            await self.release_lead(lead_id_reserved, user_id, reason="no_address_for_phone_lookup")
            return {"error": "no_address", "message": "Lead sem endereço completo para busca de telefone"}

        # 2. Busca telefone do dono
        phone_result: PhoneResult = await phone_lookup_service.lookup(address, city, state)

        if not phone_result.success:
            # Falha na busca - libera a reserva, não incrementa contador
            await self.release_lead(lead_id, user_id, reason="phone_lookup_failed")
            _error_msg = phone_result.error or "busca_falhou"
            return {
                "error": "phone_lookup_failed",
                "message": f"Não foi possível obter telefone do proprietário: {phone_result.error or 'indisponível'}",
                "phone_error": phone_result.error,
                "credit_preserved": True
            }

        # 3. Sucesso - atualiza lead com telefone, incrementa contador diário
        phone_updated = await anyio.to_thread.run_sync(
            self._service.update_owner_phone, lead_id, phone_result.phone
        )
        if not phone_updated:
            await self.release_lead(lead_id, user_id, reason="phone_update_failed")
            return {"error": "phone_update_failed", "message": "Falha ao salvar telefone no lead"}

        # Incrementa contador diário (respeita limite de 10/dia)
        incremented = await self.increment_daily_leads(user_id)
        if not incremented:
            # Limite diário atingido - não deveria acontecer pois checamos antes, mas por segurança
            await self.release_lead(lead_id, user_id, reason="daily_limit_exceeded")
            return {"error": "daily_limit_exceeded", "message": "Limite diário de 10 leads atingido"}

        # Busca lead atualizado para retornar
        lead_data = await self.get_lead_by_id(lead_id)
        if lead_data:
            lead_data["owner_phone"] = phone_result.phone
            lead_data["_phone_lookup"] = {
                "provider": phone_result.provider,
                "success": True
            }
        return lead_data

    async def release_lead(self, lead_id: int, user_id: int, reason: Optional[str] = None, note: Optional[str] = None) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.release_lead, lead_id, user_id, reason, note)

    async def record_contact(self, lead_id: int, user_id: int, channel: str) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.record_contact, lead_id, user_id, channel)

    async def mark_negotiation(self, lead_id: int, user_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.mark_negotiation, lead_id, user_id)

    async def convert_lead(self, lead_id: int, user_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.convert_lead, lead_id, user_id)

    async def reject_lead(self, lead_id: int, user_id: int, reason: Optional[str] = None) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.reject_lead, lead_id, user_id, reason)

    async def add_user_penalty(self, contractor_id: int, penalty_type: str, reason: str, penalty_level: str = "warning", expires_hours: int = 24) -> bool:
        return await anyio.to_thread.run_sync(self._service.add_user_penalty, contractor_id, penalty_type, reason, penalty_level, expires_hours)

    async def check_user_penalties(self, contractor_id: int) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.check_user_penalties, contractor_id)

    async def get_user_score(self, contractor_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_user_score, contractor_id)

    async def get_lead_history(self, lead_id: int) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_lead_history, lead_id)

    async def get_contractor_metrics(self, contractor_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_contractor_metrics, contractor_id)

    async def get_user_leads_history(self, user_id: int, **kwargs):
        return await anyio.to_thread.run_sync(
            lambda: self._service.get_user_leads_history(user_id, **kwargs)
        )

    async def save_lead_case_history(self, lead_id: int, occurrences: list) -> int:
        return await anyio.to_thread.run_sync(self._service.save_lead_case_history, lead_id, occurrences)

    async def get_lead_case_history(self, lead_id: int) -> list:
        return await anyio.to_thread.run_sync(self._service.get_lead_case_history, lead_id)

    async def list_leads_for_case_history(self, **kwargs) -> list:
        return await anyio.to_thread.run_sync(
            lambda: self._service.list_leads_for_case_history(**kwargs)
        )

    async def get_dashboard_summary(self, interest_categories: List[str] = None) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_dashboard_summary, interest_categories)

    async def expire_holds(self) -> int:
        return await anyio.to_thread.run_sync(self._service.expire_holds)

    # ===== SUBSCRIPTION / TRIAL ASYNC WRAPPERS =====

    async def get_user_subscription_status(self, user_id: int) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_user_subscription_status, user_id)

    async def start_trial(self, user_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.start_trial, user_id)

    async def activate_subscription(self, user_id: int, stripe_customer_id: str, stripe_subscription_id: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.activate_subscription, user_id, stripe_customer_id, stripe_subscription_id)

    # ===== DAILY STATS ASYNC WRAPPERS =====

    async def get_daily_leads_used(self, user_id: int) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_daily_leads_used, user_id)

    async def increment_daily_leads(self, user_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.increment_daily_leads, user_id)

    async def reveal_lead(self, user_id: int, lead_id: int, idempotency_key: Optional[str] = None, minutes: int = DatabaseService.REVEAL_HOLD_MINUTES) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.reveal_lead, user_id, lead_id, idempotency_key, minutes)

    async def get_revealed_ids(self, user_id: int, lead_ids: List[int]) -> set:
        return await anyio.to_thread.run_sync(self._service.get_revealed_ids, user_id, lead_ids)

    async def flag_reveal_contact(self, user_id: int, lead_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.flag_reveal_contact, user_id, lead_id)

    async def check_reveal_watchdogs(self) -> int:
        return await anyio.to_thread.run_sync(self._service.check_reveal_watchdogs)

    # ===== DAILY ALERT CAP (10/day, dedup, digest) =====

    async def get_new_lead_alert_counts_today(self) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_new_lead_alert_counts_today)

    async def has_alerted_user_for_lead(self, user_id: int, lead_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.has_alerted_user_for_lead, user_id, lead_id)

    async def get_alerted_pairs_for_leads(self, lead_ids: List[int]) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_alerted_pairs_for_leads, lead_ids)

    async def upsert_daily_digest(self, user_id: int, extra_count: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.upsert_daily_digest, user_id, extra_count)

    # ===== PASSWORD RESET ASYNC =====

    async def create_password_reset_token(self, email: str, expires_hours: int = 1) -> Optional[str]:
        return await anyio.to_thread.run_sync(self._service.create_password_reset_token, email, expires_hours)

    async def validate_password_reset_token(self, token: str) -> Optional[int]:
        return await anyio.to_thread.run_sync(self._service.validate_password_reset_token, token)

    async def consume_password_reset_token(self, token: str, new_password_hash: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.consume_password_reset_token, token, new_password_hash)

    async def send_password_reset_email(self, email: str, token: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.send_password_reset_email, email, token)


# Instância global (interface async, compatível com o antigo supabase_service)
db_service = AsyncDatabaseService()
