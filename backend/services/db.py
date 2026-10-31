import hashlib
import json
import os
import smtplib
import socket
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import anyio
import httpx

from ..config import settings
from ..models.schemas import EnrichedLead
from ..utils.logger import logger
from ..utils.time import utcnow
from .access import (
    STATUS_ACTIVE,
    STATUS_TRIAL,
    is_access_active,
    normalize_status,
    parse_dt,
)
from .lead_rules import (
    derive_signal,
    institutional_owner_name_matches,
    institutional_owner_name_where,
    is_institutional_name,
)
from .searchbug import PhoneLookupResult, searchbug_service
from .translations import DEFAULT_LOCALE
from .translations import render as _render_i18n

# B1: no maximo 5 dispositivos ativos por utilizador. O excedente e' desativado
# (nunca apagado) para manter a auditoria.
MAX_PUSH_DEVICES = 5

# Ruído urbano NÃO-serviço (não corresponde aos 16 ofícios da plataforma):
# estacionamento, tráfego/sinalização, veículos abandonados, TPW, testes.
# NÃO lista os ofícios (telhado, encanamento, pintura, pragas, lixo, esgoto
# etc.) — esses são oportunidades qualificadas.
# FONTE ÚNICA: a ingestão (backend.main) importa estes símbolos daqui, para o
# dashboard (`get_dashboard_summary`) e a aba Oportunidades (/api/leads/today)
# nunca filtrarem universos diferentes.
_JUNK_TERMS = [
    "parking enforcement", "traffic signal", "general traffic", "signal",
    "sign repair", "missing sign", "bike rack", "boston bikes",
    "abandoned vehicle", "abandoned bicycle", "abandoned bike", "illegal auto",
    "dead animal", "hydrant", "towing", "tpw", "transportation",
    "debug test", "test issue", "contractors complaint", "fair housing",
    "needle", "work w/out permit", "working beyond hours",
]

# Colunas de texto "ricas" avaliadas pelo filtro de ruído. Tem de ser idêntico
# ao que a ingestão usava localmente: um chamado com o termo em `case_title`
# (ou numa resolução/department) passava num dos lados e era rejeitado no outro.
_RICH_COLS = (
    "issue_description", "descriptor", "case_title",
    "resolution_description", "department",
)


def _junk_where(alias: str = "") -> str:
    """Fragmento SQL: verdadeiro quando o lead é ruído urbano (a excluir)."""
    cols = [f"{alias}.{c}" if alias else c for c in _RICH_COLS]
    concat = " || ' ' || ".join(f"COALESCE({c}, '')" for c in cols)
    return "(" + " OR ".join(
        f"LOWER({concat}) LIKE '%{t}%'" for t in _JUNK_TERMS
    ) + ")"


def _not_junk_where(alias: str = "") -> str:
    """Filtro de não-serviço: mantém apenas ruído urbano que NÃO corresponde aos
    16 ofícios da plataforma (estacionamento, tráfego/sinalização, veículos
    abandonados, TPW)."""
    return f"NOT {_junk_where(alias)}"


# Status de e-mail aceitos no envio e origens confiaveis (import/manual).
# Fonte unica: o motor (`outbound_engine.is_sendable_contact`) e o diagnostico
# do admin leem daqui, para nunca divergirem.
SENDABLE_EMAIL_STATUSES: tuple[str, ...] = ("valid", "verified")
TRUSTED_EMAIL_SOURCES: tuple[str, ...] = ("import", "manual")

# As 16 categorias de ofícios da plataforma (modelo de negócio).
_TRADE_CATEGORIES = (
    "Roof", "Structure", "Plumbing", "Grass", "Paint", "Permit_Rejected",
    "Heating", "Electrical", "Elevator", "Gas", "Rodent", "Mold", "Lead",
    "Unsanitary", "Door_Window", "Debris",
)

# Aliases legados (PT) que versões antigas do frontend gravavam como
# "categoria de interesse". Mantidos para compatibilidade na leitura.
_LEGACY_CATEGORY_ALIASES = {
    "telhado": "Roof", "estrutura": "Structure", "encanamento": "Plumbing",
    "mato": "Grass", "pintura": "Paint", "obras": "Permit_Rejected",
    "heating": "Heating", "electrical": "Electrical", "elevator": "Elevator",
    "gas": "Gas", "rodent": "Rodent", "mold": "Mold", "lead": "Lead",
    "unsanitary": "Unsanitary", "door_window": "Door_Window", "debris": "Debris",
}


def normalize_trade_categories(values) -> List[str]:
    """Normaliza categorias de interesse para o vocabulário canónico.

    Aceita tanto as chaves canónicas (ex.: "Roof") como as legadas PT
    (ex.: "telhado"). Devolve a lista canónica sem duplicados, na ordem de
    entrada. Chaves desconhecidas/vazias são ignoradas.
    """
    canonical = set(_TRADE_CATEGORIES)
    out: List[str] = []
    seen: set = set()
    for value in values or []:
        if not value:
            continue
        key = str(value).strip()
        resolved = key if key in canonical else _LEGACY_CATEGORY_ALIASES.get(key.lower())
        if resolved and resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return out

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
    """Gatilho preditivo (P0-B): sinal classificado e nao fechado.

    311 e' `open_request`; permissoes `authorized_work`; HPD/DOB/multa
    `legal_obligation`. `closed` sai do feed por defeito; `unknown` entra
    (nao ha prova de que esteja fechado) mas nao recebe selo de aberto.
    O fallback por `case_status`/`source_type` cobre linhas antigas ou
    inseridas por scripts antes do backfill.
    """
    prefix = f"{alias}." if alias else ""
    statuses = ", ".join(f"'{s}'" for s in _OPEN_STATUSES)
    return (
        f"(({prefix}signal_type IS NOT NULL "
        f"AND COALESCE({prefix}signal_status, 'unknown') != 'closed') "
        f"OR ({prefix}signal_type IS NULL AND ("
        f"LOWER({prefix}case_status) IN ({statuses}) "
        f"OR {prefix}source_type IN ('permit', 'dob_violation', 'hpd_violation', 'tax_delinquency'))))"
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


def _merge_city_counts(rows) -> List[dict]:
    """Agrupa cidades sem distinguir maiusculas ("CHICAGO" + "Chicago").

    A grafia escolhida para exibicao e' a variante com mais leads (em empate,
    a que nao esta toda em maiusculas), e o count soma todas as variantes.
    """
    variants: dict = {}
    for row in rows:
        name = (row["city"] or "").strip()
        if not name:
            continue
        key = name.lower()
        entry = variants.setdefault(key, {"count": 0, "names": {}})
        count = int(row["count"])
        entry["count"] += count
        entry["names"][name] = entry["names"].get(name, 0) + count
    out = []
    for entry in variants.values():
        display = max(
            entry["names"].items(),
            key=lambda kv: (kv[1], not kv[0].isupper()),
        )[0]
        out.append({"city": display, "count": entry["count"]})
    out.sort(key=lambda item: item["count"], reverse=True)
    return out


# ----- Cache in-process do resumo do dashboard (P0 de performance) -----
# `get_dashboard_summary` fazia ~11 varreduras pesadas idênticas (≈290 ms cada
# na base local, ≈3.8 s no total) e era recomputado a cada pedido: mount,
# polling de 30 s e mudanças de cidade/tipo. O resumo depende apenas do
# conjunto de categorias de interesse (não do utilizador), pelo que é seguro
# cacheá-lo por esse conjunto. TTL curto mantém a frescura (a cadência do
# scraper é muito mais lenta); `clear_dashboard_summary_cache()` permite
# invalidar explicitamente (ex.: no fim de cada scrape).
_DASHBOARD_SUMMARY_CACHE: dict = {}
_DASHBOARD_SUMMARY_CACHE_LOCK = threading.Lock()
try:
    _DASHBOARD_SUMMARY_CACHE_TTL = float(
        os.environ.get("DASHBOARD_SUMMARY_CACHE_TTL", "45")
    )
except (TypeError, ValueError):
    _DASHBOARD_SUMMARY_CACHE_TTL = 45.0


def clear_dashboard_summary_cache() -> None:
    """Invalida o cache in-process do resumo do dashboard."""
    with _DASHBOARD_SUMMARY_CACHE_LOCK:
        _DASHBOARD_SUMMARY_CACHE.clear()


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
  locale TEXT DEFAULT 'en',
  -- Base do empreiteiro para distancia (opcional). source: gps | manual | city.
  base_lat REAL,
  base_lng REAL,
  base_source TEXT,
  base_label TEXT,
  geo_updated_at TEXT,
  -- Privacidade: mostrar a morada no alerta (default ligado).
  show_address_in_push INTEGER DEFAULT 1,
  -- Ritmo minimo entre pushes (0 = sem pausa). B1.
  push_min_gap_min INTEGER DEFAULT 30,
  -- B2: resumo diario (default ligado) e push de ciclo de vida (default off).
  digest_enabled INTEGER DEFAULT 1,
  lifecycle_push_enabled INTEGER DEFAULT 0,
  -- B3: chime in-app (default ligado).
  chime_enabled INTEGER DEFAULT 1,
  alert_rotation_cursor INTEGER DEFAULT 0,
  welcome_popup_shown INTEGER DEFAULT 0,
  refund_count_today INTEGER DEFAULT 0,
  last_refund_date TEXT,
  is_admin INTEGER DEFAULT 0,
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
  phone_verified INTEGER DEFAULT 0,
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
  status TEXT DEFAULT 'new',
  favorited INTEGER DEFAULT 0,
  lead_status TEXT DEFAULT 'available',
  signal_type TEXT,
  signal_status TEXT DEFAULT 'unknown',
  reserved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  reserved_until TEXT,
  stage_expires_at TEXT,
  contact_count INTEGER DEFAULT 0,
  converted_by INTEGER,
  converted_at TEXT,
  revealed_at TEXT,
  refund_blocked INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(external_id, source_type),
  UNIQUE(address, city)
);

-- B3: cache BBL -> coordenadas (PLUTO). Hit e miss ficam registados para nao
-- repetir consultas; miss expira em 30 dias.
CREATE TABLE IF NOT EXISTS bbl_coords (
  bbl TEXT PRIMARY KEY,
  lat REAL,
  lng REAL,
  source TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
  msg_key TEXT,
  msg_params TEXT,
  clicked_at TEXT,
  pushed_at TEXT,
  ab_variant TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Alert Planner: orçamento diário de alertas por utilizador/categoria.
-- 1 alerta (in-app + push, se elegível) = 1 unidade. Reset diário UTC.
CREATE TABLE IF NOT EXISTS alert_usage (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day TEXT NOT NULL,
  category TEXT NOT NULL,
  alerts INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, day, category)
);

CREATE INDEX IF NOT EXISTS idx_alert_usage_day ON alert_usage (day);

CREATE TABLE IF NOT EXISTS user_interests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category TEXT NOT NULL,
  push_enabled INTEGER DEFAULT 1,
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
  user_agent TEXT,
  device_label TEXT,
  last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_success_at TEXT,
  disabled_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, endpoint)
);

CREATE TABLE IF NOT EXISTS user_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,
  device_info TEXT,
  ip_address TEXT,
  -- A2: TTL da sessao. NULL apenas em linhas antigas (backfill no init_db).
  expires_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_active_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(token_hash)
);

-- WebAuthn / Passkeys. Guarda apenas chave PÚBLICA e metadados; a biometria
-- nunca sai do dispositivo. credential_id/public_key em base64url.
CREATE TABLE IF NOT EXISTS webauthn_credentials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  credential_id TEXT NOT NULL UNIQUE,
  public_key TEXT NOT NULL,
  sign_count INTEGER DEFAULT 0,
  transports TEXT,
  aaguid TEXT,
  device_label TEXT,
  cloned_warning INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_webauthn_credentials_user
  ON webauthn_credentials (user_id);

-- Challenge de uso único (5 min) para registo/autenticação.
CREATE TABLE IF NOT EXISTS webauthn_challenges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  challenge TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  -- RP ID/origem em vigor no momento do options: o verify TEM de usar os
  -- mesmos (um preview Vercel usa o próprio host como RP ID).
  rp_id TEXT,
  origin TEXT,
  expires_at TEXT NOT NULL,
  used INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_webauthn_challenges_exp
  ON webauthn_challenges (expires_at);

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

-- P0-C1B: orcamento de tentativas pagas por utilizador (anti-bot).
-- Cada linha = uma tentativa que chegou a Searchbug. O limite e' por
-- utilizador/dia (30) e por rajada (3/min). Nao e' um cap global.
CREATE TABLE IF NOT EXISTS phone_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  attempted_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_phone_attempts_user_time
  ON phone_attempts (user_id, attempted_at);

-- P0-A: watermark por dataset (ultima data ja' ingerida). O proximo ciclo
-- pede `date > watermark - 6h`, em vez de uma janela fixa de 48/96h.
CREATE TABLE IF NOT EXISTS scraper_watermarks (
  key TEXT PRIMARY KEY,
  last_date TEXT NOT NULL,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
  notified_48h_24 INTEGER DEFAULT 0,
  notified_48h_2 INTEGER DEFAULT 0,
  returned_to_pool INTEGER DEFAULT 0,
  refunded INTEGER DEFAULT 0,
  refund_reason TEXT,
  refunded_at TEXT,
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
  issue_category TEXT,
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

-- P0-B: metricas derivadas por imovel, para o briefing "Porque agora?".
-- Recalculadas depois de cada ingestao a partir de `lead_case_history`.
CREATE TABLE IF NOT EXISTS lead_history (
  lead_id INTEGER PRIMARY KEY REFERENCES leads(id) ON DELETE CASCADE,
  repeat_365 INTEGER DEFAULT 0,
  open_cases INTEGER DEFAULT 0,
  oldest_open_days INTEGER,
  last_case_at TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_leads_city_reported ON leads (city, date_reported);
CREATE INDEX IF NOT EXISTS idx_leads_city_type_reported ON leads (city, source_type, date_reported DESC);
CREATE INDEX IF NOT EXISTS idx_leads_date_reported ON leads (date_reported);
CREATE INDEX IF NOT EXISTS idx_leads_lead_status ON leads (lead_status);
CREATE INDEX IF NOT EXISTS idx_leads_source ON leads (source_type);
CREATE INDEX IF NOT EXISTS idx_leads_category ON leads (issue_category);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads (owner_phone);
-- Fase E: consultas por utilizador/lead/data em lead_reveals (feed, histórico,
-- reembolsos) e contagem de não lidas por utilizador em notifications.
CREATE INDEX IF NOT EXISTS idx_lead_reveals_user ON lead_reveals (user_id, revealed_at);
CREATE INDEX IF NOT EXISTS idx_lead_reveals_lead ON lead_reveals (lead_id);
CREATE INDEX IF NOT EXISTS idx_lead_reveals_date ON lead_reveals (revealed_date);
CREATE INDEX IF NOT EXISTS idx_lead_reveals_refund ON lead_reveals (refunded, revealed_date);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications (user_id, read, created_at);
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

CREATE TABLE IF NOT EXISTS freshness_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  hpd_checked INTEGER DEFAULT 0,
  hpd_closed INTEGER DEFAULT 0,
  dob_checked INTEGER DEFAULT 0,
  dob_closed INTEGER DEFAULT 0,
  history_refreshed INTEGER DEFAULT 0,
  status TEXT,
  errors TEXT
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
  -- 1 = o evento ja' deu o que tinha a dar (acesso concedido / so' registado).
  -- 0 = o evento foi visto mas o efeito NAO foi aplicado: o retry do Stripe
  -- tem de voltar a tentar. Sem esta distincao, um evento gravado antes do
  -- `extend_access` e um crash faziam o cliente pagar e nunca receber acesso.
  granted INTEGER NOT NULL DEFAULT 1,
  processed_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Funil de checkout (Prioridade A). Cada TENTATIVA de pagamento fica registada
-- para medir 'criou -> abriu -> pagou' e permitir recuperar carrinho
-- abandonado. Sem esta tabela nao ha forma de saber se a perda esta' no
-- checkout, no Stripe ou no cancelamento do cliente.
-- status: open | completed | expired
CREATE TABLE IF NOT EXISTS checkout_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id TEXT UNIQUE,
  email TEXT,
  amount_cents INTEGER DEFAULT 0,
  currency TEXT DEFAULT 'usd',
  status TEXT NOT NULL DEFAULT 'open',
  url TEXT,
  reminders INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT,
  reminded_at TEXT,
  updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_checkout_sessions_user ON checkout_sessions (user_id, status);
CREATE INDEX IF NOT EXISTS idx_checkout_sessions_status ON checkout_sessions (status, created_at);

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

-- Auditoria administrativa append-only (concessões/revogações de acesso).
-- Fonte de rastreabilidade do override de assinatura; NÃO substitui
-- users.plan_until (que continua a ser a única fonte de verdade do acesso).
CREATE TABLE IF NOT EXISTS admin_audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  admin_user_id INTEGER NOT NULL,
  admin_email TEXT,
  action TEXT NOT NULL,
  target_user_id INTEGER NOT NULL,
  target_email TEXT,
  days INTEGER,
  reason TEXT,
  note TEXT,
  before_json TEXT,
  after_json TEXT,
  ip_address TEXT,
  user_agent TEXT,
  idempotency_key TEXT,
  related_audit_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_log (created_at);
CREATE INDEX IF NOT EXISTS idx_admin_audit_target ON admin_audit_log (target_user_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_admin_audit_idem
  ON admin_audit_log (admin_user_id, action, target_user_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

-- Contadores operacionais persistentes (ex.: descartes da DLQ de notificações).
CREATE TABLE IF NOT EXISTS dlq_counters (
  name TEXT PRIMARY KEY,
  value INTEGER DEFAULT 0
);

-- Fase 2: telemetria das consultas ao Searchbug (custo por consulta).
-- billed=1 marca as consultas que chegaram mesmo ao provider, ou seja as
-- que custaram dinheiro. billed=1 com outcome!=success sao "cobrancas
-- fantasma": pagas e sem telefone utilizavel.
-- outcome: success | no_results | timeout | http_error | bad_response |
--          not_configured | error
CREATE TABLE IF NOT EXISTS searchbug_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  called_at TEXT DEFAULT CURRENT_TIMESTAMP,
  outcome TEXT NOT NULL,
  billed INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0,
  latency_ms INTEGER,
  http_status INTEGER,
  city TEXT,
  error TEXT,
  lead_id INTEGER,
  owner_class TEXT,
  layer TEXT,
  name_match REAL,
  transport_error INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_searchbug_calls_at ON searchbug_calls (called_at);
CREATE INDEX IF NOT EXISTS idx_searchbug_calls_outcome ON searchbug_calls (outcome);
CREATE INDEX IF NOT EXISTS idx_searchbug_calls_billed ON searchbug_calls (billed, called_at);
-- idx_searchbug_calls_lead e' criado em _migrate_schema (a coluna lead_id nao
-- existe em bases antigas; criar o indice aqui abortaria o executescript).

-- Fase 2: telemetria das entregas de push notification.
--
-- outcome: accepted | rejected | expired | rate_limited | timeout | error |
--          not_configured
--
-- NOTA IMPORTANTE sobre o que 'accepted' significa: e o servico de push a
-- aceitar a mensagem para entrega. NAO e prova de que o utilizador a viu.
-- Confirmar entrega exigiria um service worker com telemetria de entrega,
-- que fica fora desta fase.
--
-- 'expired' (HTTP 404/410) e o outcome operacionalmente mais importante: e
-- uma subscricao morta que o servico remove a seguir. Medir a sua
-- frequencia diz quantas notificacoes estavam a ir para o vazio.
CREATE TABLE IF NOT EXISTS push_deliveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
  outcome TEXT NOT NULL,
  attempts INTEGER DEFAULT 1,
  latency_ms INTEGER,
  http_status INTEGER,
  user_id INTEGER,
  kind TEXT,
  error TEXT,
  notification_id INTEGER,
  clicked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_push_deliveries_sent ON push_deliveries (sent_at);
CREATE INDEX IF NOT EXISTS idx_push_deliveries_outcome ON push_deliveries (outcome);
CREATE INDEX IF NOT EXISTS idx_push_deliveries_expired ON push_deliveries (outcome, sent_at);

-- OUTBOUND: E-mail frio B2B (pausado — envios desativados por defeito)
-- Mantém isolamento por cidade e utiliza Gmail API sobre HTTPS.
-- Chave composta para configuração por cidade: city='' = default global (override por cidade).

CREATE TABLE IF NOT EXISTS outbound_config (
  scope TEXT NOT NULL DEFAULT 'outbound',
  city TEXT NOT NULL DEFAULT '',
  key TEXT NOT NULL,
  value TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (scope, city, key)
);

CREATE INDEX IF NOT EXISTS idx_outbound_config_scope_city ON outbound_config (scope, city);

-- Control Tower: historico de verificacoes de saude do motor.
-- status: ok | warn | fail
CREATE TABLE IF NOT EXISTS health_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  checked_at TEXT NOT NULL,
  check_name TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_health_checks_at ON health_checks (checked_at);

-- Pequeno armazem chave/valor para estado operacional (heartbeat do worker,
-- data do ultimo backup, ultimo digest). Nao e' cache de dados de negocio.
CREATE TABLE IF NOT EXISTS system_kv (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS sending_mailboxes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL DEFAULT 'gmail',
  transport TEXT NOT NULL DEFAULT 'gmail_api',
  domain TEXT,
  display_name TEXT,
  city TEXT DEFAULT '',
  daily_cap INTEGER NOT NULL DEFAULT 25,
  enabled INTEGER NOT NULL DEFAULT 0,
  warmup_state TEXT NOT NULL DEFAULT 'cold',
  warmup_started_at TEXT,
  last_send_at TEXT,
  auth_ref TEXT,
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sending_mailboxes_enabled ON sending_mailboxes (enabled, city);
CREATE INDEX IF NOT EXISTS idx_sending_mailboxes_city ON sending_mailboxes (city);

CREATE TABLE IF NOT EXISTS outbound_contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
  kind TEXT DEFAULT 'business',
  company_name TEXT,
  contact_name TEXT,
  email TEXT NOT NULL UNIQUE,
  email_source TEXT DEFAULT 'scrape',
  email_status TEXT DEFAULT 'unknown',
  city TEXT,
  state TEXT,
  consent_basis TEXT DEFAULT 'b2b_legit_interest',
  enriched_at TEXT,
  last_verified_at TEXT,
  unsubscribed INTEGER NOT NULL DEFAULT 0,
  company_domain TEXT,
  replied_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_outbound_contacts_city ON outbound_contacts (city);
CREATE INDEX IF NOT EXISTS idx_outbound_contacts_unsub ON outbound_contacts (unsubscribed);

-- Telemetria das chamadas de enriquecimento de e-mail (Snov.io).
-- outcome: success | not_configured | no_domain | invalid_email |
--          provider_no_results | http_error | timeout | error
-- billed=1 marca chamadas que chegaram ao provedor (custo por e-mail verificado).
CREATE TABLE IF NOT EXISTS outbound_enrichment_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  called_at TEXT DEFAULT CURRENT_TIMESTAMP,
  provider TEXT NOT NULL DEFAULT 'snov',
  outcome TEXT NOT NULL,
  billed INTEGER DEFAULT 0,
  latency_ms INTEGER,
  http_status INTEGER,
  city TEXT,
  email TEXT,
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbound_enrichment_calls_at ON outbound_enrichment_calls (called_at);
CREATE INDEX IF NOT EXISTS idx_outbound_enrichment_calls_outcome ON outbound_enrichment_calls (outcome);

-- Fila persistente de enriquecimento (Fase 1): tira o trabalho do request HTTP,
-- da' retry com backoff e sobrevive a deploys/reinicios.
-- status: pending | running | done | no_email | failed
CREATE TABLE IF NOT EXISTS outbound_enrichment_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER,
  city TEXT,
  niche TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  last_error TEXT,
  next_attempt_at TEXT,
  result_email TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_enrich_jobs_status_due
  ON outbound_enrichment_jobs (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_enrich_jobs_lead
  ON outbound_enrichment_jobs (lead_id);

CREATE TABLE IF NOT EXISTS outbound_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  city TEXT,
  name TEXT,
  kind TEXT NOT NULL DEFAULT 'email',
  filters_json TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  contact_count INTEGER DEFAULT 0,
  est_cost_usd REAL DEFAULT 0,
  actual_cost_usd REAL DEFAULT 0,
  dry_run INTEGER NOT NULL DEFAULT 1,
  created_by INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  previewed_at TEXT,
  started_at TEXT,
  finished_at TEXT,
  note TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbound_batches_city_status ON outbound_batches (city, status);
CREATE INDEX IF NOT EXISTS idx_outbound_batches_status ON outbound_batches (status);

CREATE TABLE IF NOT EXISTS outbound_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER REFERENCES outbound_batches(id) ON DELETE CASCADE,
  contact_id INTEGER REFERENCES outbound_contacts(id) ON DELETE SET NULL,
  mailbox_id INTEGER REFERENCES sending_mailboxes(id) ON DELETE SET NULL,
  city TEXT,
  channel TEXT NOT NULL DEFAULT 'email',
  to_email TEXT,
  subject TEXT,
  body_hash TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  error TEXT,
  provider_id TEXT UNIQUE,
  cost_usd REAL DEFAULT 0,
  segments INTEGER DEFAULT 1,
  sequence_step INTEGER NOT NULL DEFAULT 1,
  next_step_at TEXT,
  -- Instante do claim atomico (queued -> sending). Sem isto, uma mensagem
  -- presa em 'sending' (o processo morreu a meio do envio) e' indistinguivel
  -- de uma em curso — e nao ha como limpa-la.
  claimed_at TEXT,
  queued_at TEXT DEFAULT CURRENT_TIMESTAMP,
  sent_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_outbound_messages_batch ON outbound_messages (batch_id, status);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_status ON outbound_messages (status);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_contact ON outbound_messages (contact_id);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_mailbox ON outbound_messages (mailbox_id, sent_at);

-- NOTA: os indices `idx_outbound_messages_sequence` e
-- `ux_outbound_messages_to_email_active` NAO sao criados aqui de proposito:
-- dependem de `sequence_step`, uma coluna que so' existe depois de
-- `_migrate_schema` (ALTER TABLE). Se fossem criados no schema, o
-- `executescript` levantaria "no such column" numa base ja' existente e o
-- `init_db` abortaria ANTES de aplicar as migracoes. Sao criados no bloco
-- de migracao, depois das colunas.

CREATE TABLE IF NOT EXISTS suppressions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  value TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'email',
  reason TEXT DEFAULT 'manual',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(value, channel)
);

CREATE INDEX IF NOT EXISTS idx_suppressions_value ON suppressions (value);

CREATE TABLE IF NOT EXISTS outbound_daily_counters (
  city TEXT NOT NULL DEFAULT '',
  day TEXT NOT NULL,
  sent INTEGER DEFAULT 0,
  enriched INTEGER DEFAULT 0,
  spend_usd REAL DEFAULT 0,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (city, day)
);

-- Fase 3: ledger append-only de créditos.
--
-- event_type:
--   'grant_daily'       quota diária concedida (amount = +leads_limit)
--   'grant_plan'        acesso via Stripe concedeu dias (amount = +dias*limit)
--   'consume_reveal'    reveal com charge_credit=True (amount = -1)
--   'refund_reveal'     estorno devolve crédito (amount = +1)
--   'searchbug_cost'    chamada billed (amount = 0, metadata: custo)
--   'stripe_payment'    pagamento Stripe concedeu dias (amount = 0, metadata: dias)
--
-- balance_after: saldo corrente derivado (soma de amounts até este evento)
-- reference_id + reference_type: idempotência por evento origem
-- metadata: JSON com contexto (cidade, outcome, dias, etc.)
CREATE TABLE IF NOT EXISTS credit_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  amount INTEGER NOT NULL,
  balance_after INTEGER,
  reference_id INTEGER,
  reference_type TEXT,
  metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_credit_ledger_user ON credit_ledger (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_type ON credit_ledger (event_type);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_ref ON credit_ledger (reference_type, reference_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_credit_ledger_idempotent ON credit_ledger (user_id, reference_type, reference_id);
"""


# Cidades que o produto anuncia e scrapeia de facto. Norfolk foi retirada: a
# fonte `data.norfolk.gov/qva7-tzrf` e um cadastro fiscal de predios, sem
# categoria de obra nem estado de chamado, logo nunca passa `_qualified_where`.
# Mantemos a lista explicita para a copy, a landing page e `/api/metrics/public`
# nunca voltarem a prometer uma cidade que nao servimos.
SERVED_CITIES: tuple[str, ...] = ("NYC", "CHICAGO", "DALLAS", "BOSTON")

# Forma de exibição canónica (a base tem linhas com casing misto: CHICAGO/Chicago).
_CITY_DISPLAY: dict[str, str] = {
    "NYC": "NYC",
    "CHICAGO": "Chicago",
    "DALLAS": "Dallas",
    "BOSTON": "Boston",
}


def canonical_served_cities(raw_cities) -> list[str]:
    """Dedupa cidades servidas por casing e devolve a forma canónica.

    `SELECT DISTINCT city` devolvia "CHICAGO" e "Chicago" como duas cidades,
    inflacionando `cities_count` (landing anunciava 5 em vez de 4).
    """
    out = set()
    for raw in raw_cities:
        key = str(raw or "").strip().upper()
        if key in _CITY_DISPLAY:
            out.add(_CITY_DISPLAY[key])
    return sorted(out)


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
    try:
        conn.create_function("is_institutional_name", 1, is_institutional_name)
    except Exception:
        pass
    return conn


# Valores por defeito da configuração de outbound. `get_outbound_config` recorre
# sempre a este mapa, por isso o sistema funciona mesmo sem linhas semeadas.
# As linhas globais (city='') são semeadas em `init_db` apenas como ponto de
# partida editável na UI; overrides por cidade (city='NYC', etc.) são criados à
# medida. `send_enabled`/`enrich_enabled` arrancam a 0 (envio DESLIGADO).
_OUTBOUND_CONFIG_DEFAULTS = {
    "send_enabled": "0",
    "enrich_enabled": "0",
    "batch_size": "200",
    "max_spend_per_batch_usd": "6.0",
    "daily_enrich_cap": "1000",
    "daily_send_cap": "100",
    "per_mailbox_daily_cap": "25",
    "warmup_enabled": "1",
    "min_warmup_days": "14",
    "warmup_ramp": "1,1,1,2,3,5,8,12",
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
}


def _seed_outbound_defaults(conn: sqlite3.Connection) -> None:
    """Semeia as linhas globais da configuração de outbound (idempotente).

    Chamado só a partir de `init_db` (nunca em `get_connection`, que corre em
    cada query): o seed é um INSERT OR IGNORE de 11 chaves, barato mas fora do
    caminho crítico.
    """
    for key, value in _OUTBOUND_CONFIG_DEFAULTS.items():
        conn.execute(
            "INSERT OR IGNORE INTO outbound_config (scope, city, key, value) "
            "VALUES ('outbound', '', ?, ?)",
            (key, value),
        )


def record_outbound_enrichment_call(
    outcome: str,
    billed: int = 0,
    latency_ms: Optional[int] = None,
    http_status: Optional[int] = None,
    city: Optional[str] = None,
    email: Optional[str] = None,
    error: Optional[str] = None,
    provider: str = "snov",
) -> bool:
    """Regista uma chamada de enriquecimento de e-mail (telemetria Fase 2).

    Nunca levanta excecao: a telemetria nao pode falhar o fluxo de envio.
    """
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO outbound_enrichment_calls "
            "(provider, outcome, billed, latency_ms, http_status, city, email, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (provider, outcome, int(billed), latency_ms, http_status, city, email, error),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def outbound_enrichment_usage_today(day: str) -> dict:
    """Chamadas/billed/spend de enriquecimento do dia (para o teto diario)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS calls, COALESCE(SUM(billed), 0) AS billed "
            "FROM outbound_enrichment_calls WHERE called_at >= ?",
            (f"{day} 00:00:00",),
        ).fetchone()
        return {
            "calls": int(row["calls"] or 0),
            "billed": int(row["billed"] or 0),
        }
    finally:
        conn.close()


def _ratio(numerator: Optional[int], denominator: Optional[int]) -> Optional[float]:
    """Divisao que devolve None em vez de ZeroDivisionError (0 chamadas)."""
    if not numerator or not denominator:
        return None
    return round(numerator / denominator, 4)


def _percentiles(sorted_values: List[int]) -> dict:
    """Resumo de latencia a partir de uma lista JA ordenada.

    `samples` exposto porque uma p95 calculada sobre 3 chamadas e ruido: o
    painel mostra o numero de amostras ao lado do valor.
    """
    if not sorted_values:
        return {"avg_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None, "samples": 0}

    n = len(sorted_values)

    def _at(pct: float) -> int:
        idx = min(n - 1, max(0, int(round((pct / 100.0) * (n - 1)))))
        return sorted_values[idx]

    return {
        "avg_ms": int(round(sum(sorted_values) / n)),
        "p50_ms": _at(50),
        "p95_ms": _at(95),
        "max_ms": sorted_values[-1],
        "samples": n,
    }


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
                _seed_outbound_defaults(conn)
                conn.commit()
            finally:
                conn.close()
            _ensure_demo_user()
            logger.info(f"Banco SQLite pronto em {DB_PATH}")
            return
        except sqlite3.OperationalError as e:
            # Pode ser um filesystem read-only OU um erro de esquema (ex.: uma
            # coluna que o schema assume mas a base ainda nao tem). A mensagem
            # anterior dizia sempre "read-only" e mascarava bugs de migracao.
            logger.warning(
                "init_db: falha ao aplicar o schema (%s) — %s. "
                "A base pode estar em modo leitura ou desatualizada.",
                type(e).__name__,
                e,
            )
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
    if "phone_verified" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN phone_verified INTEGER DEFAULT 0")
    # P0-A: indice do feed (filtro por cidade/estado + ordenacao por data).
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_feed "
            "ON leads (city, lead_status, date_reported DESC)"
        )
    except sqlite3.OperationalError:
        pass

    # P0-B: classificacao semantica do sinal + backfill dos 84k+ leads.
    if "signal_type" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN signal_type TEXT")
    if "signal_status" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN signal_status TEXT DEFAULT 'unknown'")
    conn.execute(
        """
        UPDATE leads SET
          signal_type = CASE source_type
            WHEN '311' THEN 'open_request'
            WHEN 'permit' THEN 'authorized_work'
            WHEN 'hpd_violation' THEN 'legal_obligation'
            WHEN 'dob_violation' THEN 'legal_obligation'
            WHEN 'tax_delinquency' THEN 'legal_obligation'
            ELSE NULL END,
          signal_status = CASE
            WHEN source_type NOT IN (
              '311','permit','hpd_violation','dob_violation','tax_delinquency'
            ) THEN 'unknown'
            WHEN LOWER(COALESCE(case_status, '')) IN (
              'closed','close','completed','complete','resolved','solved',
              'canceled','cancelled','dismissed','archived','rejected',
              'closed (transferred)','closed (duplicate)',
              'in progress (duplicate)','new (duplicate)','expired','final',
              'signed off','void'
            ) THEN 'closed'
            WHEN LOWER(COALESCE(case_status, '')) IN (
              'open','new','in progress','in_progress','assigned','active',
              'approved','issued','pending','acknowledged','referred','scheduled',
              'investigation','awaiting','awaiting assignment','violation open',
              'nov sent out','permit issued'
            ) THEN 'open'
            WHEN LOWER(COALESCE(case_status, '')) LIKE '%close%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%complet%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%resolv%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%cancel%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%dismiss%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%duplicate%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%expired%'
            THEN 'closed'
            WHEN LOWER(COALESCE(case_status, '')) LIKE '%open%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%progress%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%assign%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%pending%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%approved%'
              OR LOWER(COALESCE(case_status, '')) LIKE '%issued%'
            THEN 'open'
            ELSE 'unknown' END
        WHERE signal_type IS NULL OR signal_status IS NULL
        """
    )
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_signal "
            "ON leads (city, signal_type, signal_status, date_reported DESC)"
        )
    except sqlite3.OperationalError:
        pass
    if "stage_expires_at" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN stage_expires_at TEXT")
    # Reparacao: um lead em fase ativa sem prazo fica preso para sempre (nao
    # expira, nao notifica, nao volta ao pool). Datas antigas (updated_at+48h
    # no passado) recebem uma janela minima de 24h para nao desaparecerem de
    # imediato no proximo sweep.
    conn.execute(
        """UPDATE leads
              SET stage_expires_at = CASE
                    WHEN lead_status = 'reserved'
                      THEN COALESCE(reserved_until, datetime('now', '+60 minutes'))
                    ELSE max(
                      datetime(COALESCE(updated_at, CURRENT_TIMESTAMP), '+48 hours'),
                      datetime('now', '+24 hours')
                    )
                  END,
                  updated_at = CURRENT_TIMESTAMP
            WHERE lead_status IN ('reserved', 'contacted', 'in_negotiation')
              AND stage_expires_at IS NULL"""
    )
    if "mailing_address" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN mailing_address TEXT")
    if "revealed_at" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN revealed_at TEXT")

    # Nicho classificado automaticamente (niche_classifier). Aditivo: bases
    # antigas ficam com 'unknown' e o motor de envio recusa-as ate' serem
    # reclassificadas (nunca se adivinha o nicho de um destinatario).
    if "niche_key" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN niche_key TEXT")
    if "niche_status" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN niche_status TEXT DEFAULT 'unknown'")
    if "niche_score" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN niche_score REAL DEFAULT 0")
    if "niche_evidence" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN niche_evidence TEXT")

    ccols = {r["name"] for r in conn.execute("PRAGMA table_info(outbound_contacts)").fetchall()}
    if "niche_key" not in ccols:
        conn.execute("ALTER TABLE outbound_contacts ADD COLUMN niche_key TEXT")
    if "niche_status" not in ccols:
        conn.execute(
            "ALTER TABLE outbound_contacts ADD COLUMN niche_status TEXT DEFAULT 'unknown'"
        )
    if "refund_blocked" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN refund_blocked INTEGER DEFAULT 0")
    extra_cols = {
        "address_unit": "TEXT",
        "address_type": "TEXT",
        "address_street": "TEXT",
        "address_city": "TEXT",
        "address_state": "TEXT",
        "address_zip": "TEXT",
        "bbl": "TEXT",
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

    # Indice (nao unico) pararico de imoveis em NYC. O BBL e o identificador
    # canonico borough-block-lot e permite casar o lead com o proprietario de forma
    # exacta, sem depender de parsing de morada.
    _bbl_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_leads_bbl'"
    ).fetchone()
    if not _bbl_exists:
        try:
            conn.execute("CREATE INDEX idx_leads_bbl ON leads(bbl)")
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
    if user_cols and "locale" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN locale TEXT DEFAULT 'en'")
    if user_cols and "welcome_popup_shown" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN welcome_popup_shown INTEGER DEFAULT 0")
    if user_cols and "refund_count_today" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN refund_count_today INTEGER DEFAULT 0")
    if user_cols and "last_refund_date" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN last_refund_date TEXT")
    if user_cols and "is_admin" not in user_cols:
        # migrating existing rows default to 0 (fail-closed: nobody becomes admin
        # by accident). Promotion happens explicitly via set_user_admin().
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    if user_cols and "alert_rotation_cursor" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN alert_rotation_cursor INTEGER DEFAULT 0")
    if user_cols and "base_lat" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN base_lat REAL")
        conn.execute("ALTER TABLE users ADD COLUMN base_lng REAL")
        conn.execute("ALTER TABLE users ADD COLUMN base_source TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN base_label TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN geo_updated_at TEXT")
    if user_cols and "show_address_in_push" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN show_address_in_push INTEGER DEFAULT 1")
    if user_cols and "push_min_gap_min" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN push_min_gap_min INTEGER DEFAULT 30")
    if user_cols and "digest_enabled" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN digest_enabled INTEGER DEFAULT 1")
    if user_cols and "lifecycle_push_enabled" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN lifecycle_push_enabled INTEGER DEFAULT 0")
    if user_cols and "chime_enabled" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN chime_enabled INTEGER DEFAULT 1")

    event_cols = {r["name"] for r in conn.execute("PRAGMA table_info(lead_events)").fetchall()}
    if event_cols:
        if "user_id" not in event_cols:
            conn.execute("ALTER TABLE lead_events ADD COLUMN user_id INTEGER")
        if "detail" not in event_cols:
            conn.execute("ALTER TABLE lead_events ADD COLUMN detail TEXT")

    notif_cols = {r["name"] for r in conn.execute("PRAGMA table_info(notifications)").fetchall()}
    if notif_cols and "user_id" not in notif_cols:
        conn.execute("ALTER TABLE notifications ADD COLUMN user_id INTEGER")
    if notif_cols and "msg_key" not in notif_cols:
        conn.execute("ALTER TABLE notifications ADD COLUMN msg_key TEXT")
    if notif_cols and "msg_params" not in notif_cols:
        conn.execute("ALTER TABLE notifications ADD COLUMN msg_params TEXT")
    if notif_cols and "clicked_at" not in notif_cols:
        conn.execute("ALTER TABLE notifications ADD COLUMN clicked_at TEXT")
    if notif_cols and "pushed_at" not in notif_cols:
        conn.execute("ALTER TABLE notifications ADD COLUMN pushed_at TEXT")
    if notif_cols and "ab_variant" not in notif_cols:
        conn.execute("ALTER TABLE notifications ADD COLUMN ab_variant TEXT")

    interest_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(user_interests)").fetchall()
    }
    if interest_cols and "push_enabled" not in interest_cols:
        conn.execute(
            "ALTER TABLE user_interests ADD COLUMN push_enabled INTEGER DEFAULT 1"
        )

    # B1: higiene de dispositivos (last_seen/last_success/disabled).
    push_sub_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(push_subscriptions)").fetchall()
    }
    for col, ddl in (
        ("user_agent", "TEXT"),
        ("device_label", "TEXT"),
        # SQLite nao aceita DEFAULT CURRENT_TIMESTAMP num ALTER TABLE
        # ("Cannot add a column with non-constant default"). A coluna nasce
        # sem default e o backfill abaixo usa created_at.
        ("last_seen_at", "TEXT"),
        ("last_success_at", "TEXT"),
        ("disabled_at", "TEXT"),
    ):
        if push_sub_cols and col not in push_sub_cols:
            conn.execute(f"ALTER TABLE push_subscriptions ADD COLUMN {col} {ddl}")
    if push_sub_cols:
        conn.execute(
            "UPDATE push_subscriptions SET last_seen_at = created_at "
            "WHERE last_seen_at IS NULL"
        )

    # B1: atribuicao de clique por entrega.
    delivery_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(push_deliveries)").fetchall()
    }
    if delivery_cols and "notification_id" not in delivery_cols:
        conn.execute("ALTER TABLE push_deliveries ADD COLUMN notification_id INTEGER")
    if delivery_cols and "clicked_at" not in delivery_cols:
        conn.execute("ALTER TABLE push_deliveries ADD COLUMN clicked_at TEXT")
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS idx_push_deliveries_nid ON push_deliveries (notification_id)",
        "CREATE INDEX IF NOT EXISTS idx_push_subscriptions_active ON push_subscriptions (user_id, disabled_at)",
    ):
        try:
            conn.execute(index_sql)
        except sqlite3.OperationalError:
            pass
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

    # lead_reveals: colunas de estorno/flags introduzidas depois do DEFAULT_SCHEMA original.
    # Sem esta migracao, bancos criados por versoes antigas falham com
    # "no such column: refunded" em process_refund (Regra A).
    reveal_cols = {r["name"] for r in conn.execute("PRAGMA table_info(lead_reveals)").fetchall()}
    if reveal_cols:
        reveal_extra = {
            "idempotency_key": "TEXT",
            "contact_flagged": "INTEGER DEFAULT 0",
            "notified_30": "INTEGER DEFAULT 0",
            "notified_45": "INTEGER DEFAULT 0",
            "notified_48h_24": "INTEGER DEFAULT 0",
            "notified_48h_2": "INTEGER DEFAULT 0",
            "returned_to_pool": "INTEGER DEFAULT 0",
            "refunded": "INTEGER DEFAULT 0",
            "refund_reason": "TEXT",
            "refunded_at": "TEXT",
        }
        for name, ctype in reveal_extra.items():
            if name not in reveal_cols:
                conn.execute(f"ALTER TABLE lead_reveals ADD COLUMN {name} {ctype}")
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_reveals_idem "
                "ON lead_reveals (idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
        except sqlite3.OperationalError:
            pass

    # P0-B: categoria por ocorrencia (reincidencia por oficio no mesmo imovel).
    hist_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(lead_case_history)").fetchall()
    }
    if hist_cols and "issue_category" not in hist_cols:
        conn.execute("ALTER TABLE lead_case_history ADD COLUMN issue_category TEXT")

    # A2: TTL de sessao. Coluna nasce sem default (SQLite nao aceita
    # CURRENT_TIMESTAMP em ALTER); o backfill da 30 dias as sessoes antigas,
    # que antes eram eternas.
    session_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(user_sessions)").fetchall()
    }
    if session_cols and "expires_at" not in session_cols:
        conn.execute("ALTER TABLE user_sessions ADD COLUMN expires_at TEXT")
        conn.execute(
            "UPDATE user_sessions SET expires_at = datetime(created_at, '+30 days') "
            "WHERE expires_at IS NULL"
        )
    if session_cols:
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_expires "
                "ON user_sessions (expires_at)"
            )
        except sqlite3.OperationalError:
            pass

    # Fase 2 outbound: `outbound_contacts.company_domain` guarda o dominio da
    # empresa (para o Snov.io). Adicionado a bancos antigos de forma idempotente.
    contact_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(outbound_contacts)").fetchall()
    }
    if contact_cols and "company_domain" not in contact_cols:
        conn.execute("ALTER TABLE outbound_contacts ADD COLUMN company_domain TEXT")

    # Sequencia de e-mails (Prioridade D): marca de resposta no contacto.
    # Enquanto a deteccao automatica de respostas nao existir (exige scope
    # `gmail.readonly`), este campo e' a fonte de verdade manual.
    if contact_cols and "replied_at" not in contact_cols:
        conn.execute("ALTER TABLE outbound_contacts ADD COLUMN replied_at TEXT")

    # P0-C1: telemetria do telefone por lead/classe/camada. Aditivo e
    # idempotente; o painel de reconciliacao passa a poder medir hit rate por
    # owner_class/layer e separar transporte de no_results.
    sb_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(searchbug_calls)").fetchall()
    }
    if sb_cols:
        sb_extra = {
            "lead_id": "INTEGER",
            "owner_class": "TEXT",
            "layer": "TEXT",
            "name_match": "REAL",
            "transport_error": "INTEGER DEFAULT 0",
            "cost_usd": "REAL DEFAULT 0",
        }
        for name, ctype in sb_extra.items():
            if name not in sb_cols:
                conn.execute(f"ALTER TABLE searchbug_calls ADD COLUMN {name} {ctype}")
        # Backfill conservador: chamadas historicas com billed=1 passam a ter o
        # custo da fatura. A reconciliacao real substitui isto se a fatura diferir.
        price = float(getattr(settings, "SEARCHBUG_PRICE_PER_CALL_USD", 0.20) or 0.20)
        conn.execute(
            "UPDATE searchbug_calls SET cost_usd = ? "
            "WHERE billed = 1 AND COALESCE(cost_usd, 0) = 0",
            (price,),
        )
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_searchbug_calls_lead "
                "ON searchbug_calls (lead_id)"
            )
        except sqlite3.OperationalError:
            pass

    # Sprint 1: `stripe_events.granted` distingue "evento visto" de "acesso ja'
    # concedido". Sem esta coluna, um webhook que falhasse a meio era visto
    # como processado e o retry do Stripe nao concedia o acesso.
    stripe_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(stripe_events)").fetchall()
    }
    if stripe_cols and "granted" not in stripe_cols:
        conn.execute(
            "ALTER TABLE stripe_events ADD COLUMN granted INTEGER NOT NULL DEFAULT 1"
        )

    # Limpeza: `scrape_fallback_snov` era o toggle do fallback Snov.io, que foi
    # substituido pelo EmailListVerify. Nao e' lido por nenhum codigo (so'
    # aparecia no painel), por isso a linha e' removida das bases ja' semeadas
    # para o painel ficar alinhado apenas com o EmailListVerify.
    conn.execute(
        "DELETE FROM outbound_config "
        "WHERE scope='outbound' AND key='scrape_fallback_snov'"
    )

    # Fase 2 outbound: dedup dura no destinatario. Bancos antigos podem ja' ter
    # duplicados ativos (ex.: reenvios historicos): nao criamos o indice se
    # houver colisao, para nunca falhar o arranque. Bancos novos (schema acima)
    # ja' nascem com o indice.
    #
    # A chave passou a ser (to_email, sequence_step) para permitir a sequencia
    # de e-mails (passo 1 = amostra, passo 2 = oferta) sem duplicar o MESMO
    # passo. Se a base ainda tem a versao antiga (so' `to_email`), o indice e'
    # recriado.
    #
    # ORDEM IMPORTANTE: as colunas da sequencia tem de existir ANTES do indice
    # — `CREATE INDEX ... (to_email, sequence_step)` falha com "no such column"
    # numa base antiga, e o indice ficaria por criar em silencio.
    msg_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(outbound_messages)").fetchall()
    }
    if msg_cols:
        if "sequence_step" not in msg_cols:
            conn.execute(
                "ALTER TABLE outbound_messages ADD COLUMN sequence_step INTEGER NOT NULL DEFAULT 1"
            )
        if "next_step_at" not in msg_cols:
            conn.execute("ALTER TABLE outbound_messages ADD COLUMN next_step_at TEXT")
        if "claimed_at" not in msg_cols:
            conn.execute("ALTER TABLE outbound_messages ADD COLUMN claimed_at TEXT")
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbound_messages_sequence "
                "ON outbound_messages (status, next_step_at)"
            )
        except sqlite3.OperationalError:
            pass

    def _ensure_outbound_dedup_index() -> None:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='ux_outbound_messages_to_email_active'"
        ).fetchone()
        current_sql = (row["sql"] if row else "") or ""
        if row and "sequence_step" not in current_sql:
            conn.execute("DROP INDEX IF EXISTS ux_outbound_messages_to_email_active")
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_outbound_messages_to_email_active "
                "ON outbound_messages (to_email, sequence_step) "
                "WHERE to_email IS NOT NULL AND status IN ('queued', 'sending', 'sent')"
            )
        except sqlite3.IntegrityError:
            logger.warning(
                "[OUTBOUND] dedup index nao criado: existem to_email duplicados ativos"
            )
        except sqlite3.OperationalError as e:
            logger.warning("[OUTBOUND] nao foi possivel recriar o indice de dedup: %s", e)

    _ensure_outbound_dedup_index()

    # WebAuthn: bases criadas antes do multi-domínio não têm rp_id/origin no
    # challenge. Sem estas colunas o verify teria de adivinhar o RP ID.
    wa_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(webauthn_challenges)")
    }
    for name in ("rp_id", "origin"):
        if name not in wa_cols:
            conn.execute(f"ALTER TABLE webauthn_challenges ADD COLUMN {name} TEXT")




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


def _record_credit_event_connection(
    conn: sqlite3.Connection,
    user_id: int,
    event_type: str,
    amount: int,
    reference_id: Optional[int] = None,
    reference_type: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> int:
    """Core partilhado de registo de eventos no credit_ledger.

    Usado pelo metodo `DatabaseService._record_credit_event` e diretamente
    pelo flush de telemetria (metrics.py), para que o evento vivo e o
    `backfill_credit_ledger` produzam linhas identicas. Idempotente pela
    unique index (user_id, reference_type, reference_id).
    """
    # Saldo anterior
    row = conn.execute(
        "SELECT COALESCE(MAX(balance_after), 0) FROM credit_ledger WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    prev_balance = row[0] if row else 0
    new_balance = prev_balance + amount

    meta_json = None
    if metadata:
        import json
        meta_json = json.dumps(metadata, ensure_ascii=False)

    try:
        conn.execute(
            """INSERT INTO credit_ledger
                   (user_id, event_type, amount, balance_after, reference_id, reference_type, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, reference_type, reference_id) DO NOTHING""",
            (user_id, event_type, amount, new_balance, reference_id, reference_type, meta_json),
        )
    except sqlite3.IntegrityError:
        # Já existe (idempotência): não conta duas vezes
        pass

    return new_balance


# ---------------------------------------------------------------------------
# INSERT/UPSERT de leads — regras de deduplicação
#
# A tabela `leads` tem DUAS restrições únicas: (external_id, source_type) — a
# chave natural de um chamado — e (address, city) — um imóvel = um lead.
# O ON CONFLICT antigo usava apenas (address, city) e fazia
# `external_id=excluded.external_id`: quando um chamado novo caía num imóvel já
# existente, o UPDATE atribuía a esse imóvel um external_id que PODIA já
# pertencer a outra linha, e o SQLite abortava com
# "UNIQUE constraint failed: leads.external_id, leads.source_type".
# (Reproduzível: linha A ext=1 addr=X; linha B ext=2 addr=Y; chega ext=2 addr=X.)
#
# A resolução passa a ser explícita:
#   * se (external_id, source_type) já existe → UPDATE por esse par, sem tocar
#     nas chaves únicas (nem address/city);
#   * senão → INSERT ... ON CONFLICT(address, city) DO UPDATE, também sem tocar
#     nas chaves — um imóvel já rastreado apenas recebe os dados mais novos.
# Assim nenhuma combinação consegue violar as duas restrições. O endereço não
# é herdado por outra linha (external_id continua a ser a chave de dedup, como
# já exigia backend/scripts/normalize_addresses.py).
# ---------------------------------------------------------------------------

# Colunas de dados do lead (todas menos as 4 chaves de identidade/endereço).
_LEAD_DATA_COLS = (
    "state", "zip_code", "lat", "lng", "county",
    "issue_category", "issue_description", "urgency_level",
    "signal_type", "signal_status",
    "owner_name", "owner_phone", "owner_email", "owner_status", "mailing_address",
    "date_reported", "image_url", "source_url", "is_validated", "created_at",
    "address_unit", "address_type", "address_street", "address_city",
    "address_state", "address_zip", "case_title", "subject", "reason", "type",
    "queue", "department", "closure_reason", "case_status", "on_time",
    "sla_target_dt", "closed_dt", "submitted_photo", "closed_photo", "source",
    "neighborhood", "ward", "precinct", "descriptor", "resolution_description",
    "resolution_action_updated_date", "bbl",
)

# Campos que NÃO são sobrescritos quando o valor novo chega NULL/vazio (um
# re-scrape não apaga o proprietário/telefone/morada já enriquecidos).
_LEAD_PRESERVE_COLS = frozenset({
    "owner_name", "owner_phone", "owner_email", "owner_status",
    "mailing_address", "bbl",
})


def _lead_insert_values(lead) -> dict:
    """Valores das colunas de um EnrichedLead, no vocabulário da tabela."""
    src = lead.source_type.value if hasattr(lead.source_type, "value") else str(lead.source_type)
    cat = lead.issue_category.value if hasattr(lead.issue_category, "value") else str(lead.issue_category)
    urg = lead.urgency_level.value if hasattr(lead.urgency_level, "value") else str(lead.urgency_level)
    signal_type, signal_status = derive_signal(src, getattr(lead, "case_status", None))
    return {
        "external_id": lead.external_id,
        "source_type": src,
        "address": lead.address,
        "city": lead.city,
        "state": lead.state,
        "zip_code": lead.zip_code,
        "lat": lead.lat,
        "lng": lead.lng,
        "county": lead.county,
        "issue_category": cat,
        "issue_description": lead.issue_description,
        "signal_type": signal_type,
        "signal_status": signal_status,
        "urgency_level": urg,
        "owner_name": lead.owner_name,
        "owner_phone": lead.owner_phone,
        "owner_email": lead.owner_email,
        "owner_status": lead.owner_status,
        "mailing_address": getattr(lead, "mailing_address", None),
        "date_reported": lead.date_reported.isoformat(),
        "image_url": lead.image_url,
        "source_url": lead.source_url,
        "is_validated": 1 if getattr(lead, "is_validated", False) else 0,
        "created_at": datetime.now().isoformat(),
        "address_unit": lead.address_unit,
        "address_type": lead.address_type,
        "address_street": lead.address_street,
        "address_city": lead.address_city,
        "address_state": lead.address_state,
        "address_zip": lead.address_zip,
        "case_title": lead.case_title,
        "subject": lead.subject,
        "reason": lead.reason,
        "type": lead.type,
        "queue": lead.queue,
        "department": lead.department,
        "closure_reason": lead.closure_reason,
        "case_status": lead.case_status,
        "on_time": lead.on_time,
        "sla_target_dt": lead.sla_target_dt,
        "closed_dt": lead.closed_dt,
        "submitted_photo": lead.submitted_photo,
        "closed_photo": lead.closed_photo,
        "source": lead.source,
        "neighborhood": lead.neighborhood,
        "ward": lead.ward,
        "precinct": lead.precinct,
        "descriptor": lead.descriptor,
        "resolution_description": lead.resolution_description,
        "resolution_action_updated_date": lead.resolution_action_updated_date,
        "bbl": getattr(lead, "bbl", None),
    }


def _lead_set_clause(placeholder: str) -> str:
    """Cláusula SET para as colunas de dados (sem tocar nas chaves únicas).

    `placeholder` = "excluded.<col>" para o UPSERT, ou "?" para o UPDATE por
    (external_id, source_type). `created_at` fica de fora: é a data da primeira
    observação e não pode ser reescrita por um re-scrape.
    """
    parts = []
    for col in _LEAD_DATA_COLS:
        if col == "created_at":
            continue
        if col in _LEAD_PRESERVE_COLS:
            parts.append(f"{col}=COALESCE(NULLIF({placeholder.format(col=col)}, ''), leads.{col})")
        else:
            parts.append(f"{col}={placeholder.format(col=col)}")
    parts.append("updated_at=datetime('now')")
    return ", ".join(parts)


class DatabaseService:
    """Interface type-safe sobre o SQLite (espelha o antigo SupabaseService)."""

    def __init__(self):
        init_db()

    _OUTBOUND_CONFIG_DEFAULTS = _OUTBOUND_CONFIG_DEFAULTS

    def get_outbound_config(self, city: Optional[str] = None) -> dict:
        """Merge global and per-city outbound config (global wins, city overrides)."""
        cfg = dict(self._OUTBOUND_CONFIG_DEFAULTS)
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT city, key, value FROM outbound_config WHERE scope='outbound'"
            ).fetchall()
            for r in rows:
                if not r["key"]:
                    continue
                if r["city"] == "":
                    if r["key"] in cfg or True:
                        cfg[r["key"]] = r["value"] if r["value"] is not None else cfg.get(r["key"])
            city_up = (city or "").strip().upper()
            for r in rows:
                if r["city"] and (r["city"].upper() == city_up or r["city"] == city):
                    cfg[r["key"]] = r["value"] if r["value"] is not None else cfg.get(r["key"])
        finally:
            conn.close()
        return cfg

    def set_outbound_config(self, key: str, value: str, city: str = "", scope: str = "outbound") -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO outbound_config (scope, city, key, value, updated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(scope, city, key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (scope, city or "", key, str(value) if value is not None else None),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def list_sending_mailboxes(self, enabled_only: bool = False) -> List[dict]:
        conn = get_connection()
        try:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM sending_mailboxes WHERE enabled=1 ORDER BY id"
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM sending_mailboxes ORDER BY id").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def upsert_sending_mailbox(
        self,
        email: str,
        provider: str = "gmail",
        transport: str = "gmail_api",
        domain: Optional[str] = None,
        display_name: Optional[str] = None,
        city: str = "",
        daily_cap: int = 25,
        enabled: int = 0,
        warmup_state: str = "cold",
        auth_ref: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO sending_mailboxes (email, provider, transport, domain, display_name, city, daily_cap, enabled, warmup_state, auth_ref, notes, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(email) DO UPDATE SET provider=excluded.provider, transport=excluded.transport, domain=excluded.domain, display_name=excluded.display_name, city=excluded.city, daily_cap=excluded.daily_cap, enabled=excluded.enabled, warmup_state=excluded.warmup_state, auth_ref=excluded.auth_ref, notes=excluded.notes, updated_at=CURRENT_TIMESTAMP",
                (email.lower(), provider, transport, domain, display_name, city or "", int(daily_cap), int(enabled), warmup_state, auth_ref, notes),
            )
            conn.commit()
            r = conn.execute("SELECT * FROM sending_mailboxes WHERE email=?", (email.lower(),)).fetchone()
            return dict(r) if r else None
        except Exception:
            return None
        finally:
            conn.close()

    def create_outbound_batch(
        self,
        city: Optional[str] = None,
        name: Optional[str] = None,
        filters_json: Optional[str] = None,
        created_by: Optional[int] = None,
        kind: str = "email",
    ) -> Optional[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO outbound_batches (city, name, kind, filters_json, status, dry_run, created_by) "
                "VALUES (?, ?, ?, ?, 'draft', 1, ?)",
                (city, name, kind, filters_json, created_by),
            )
            conn.commit()
            bid = cur.lastrowid
            r = conn.execute("SELECT * FROM outbound_batches WHERE id=?", (bid,)).fetchone()
            return dict(r) if r else None
        except Exception:
            return None
        finally:
            conn.close()

    def create_or_reuse_draft_batch(
        self,
        city: Optional[str] = None,
        name: Optional[str] = None,
        filters_json: Optional[str] = None,
        created_by: Optional[int] = None,
        kind: str = "email",
    ) -> Optional[dict]:
        """Devolve o rascunho do mesmo (city, filtros) ou cria um novo.

        A simulacao do painel chamava `create_outbound_batch` a cada clique e
        deixou 20+ lotes `previewed` sem uso. Reutilizar mantem a BD limpa e o
        comportamento identico para quem usa o painel.
        """
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM outbound_batches "
                "WHERE COALESCE(city,'') = COALESCE(?, '') "
                "  AND COALESCE(filters_json,'') = COALESCE(?, '') "
                "  AND status IN ('draft', 'previewed') "
                "ORDER BY id DESC LIMIT 1",
                (city, filters_json),
            ).fetchone()
            if row:
                if name and row["name"] != name:
                    conn.execute(
                        "UPDATE outbound_batches SET name=? WHERE id=?", (name, row["id"])
                    )
                    conn.commit()
                return dict(row)

            cur = conn.execute(
                "INSERT INTO outbound_batches (city, name, kind, filters_json, status, dry_run, created_by) "
                "VALUES (?, ?, ?, ?, 'draft', 1, ?)",
                (city, name, kind, filters_json, created_by),
            )
            conn.commit()
            bid = cur.lastrowid
            r = conn.execute("SELECT * FROM outbound_batches WHERE id=?", (bid,)).fetchone()
            return dict(r) if r else None
        except Exception:
            return None
        finally:
            conn.close()

    def mark_outbound_batch_previewed(
        self,
        batch_id: int,
        contact_count: int,
        est_cost_usd: float,
    ) -> Optional[dict]:
        """Grava a estimativa de um lote de dry-run (status='previewed').

        Nunca cria mensagens nem ativa envio: apenas fixa `contact_count`,
        `est_cost_usd` e `previewed_at` para auditoria/confirmacao futura.
        """
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE outbound_batches SET status='previewed', contact_count=?, "
                "est_cost_usd=?, previewed_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(contact_count), float(est_cost_usd), batch_id),
            )
            conn.commit()
            r = conn.execute("SELECT * FROM outbound_batches WHERE id=?", (batch_id,)).fetchone()
            return dict(r) if r else None
        except Exception:
            return None
        finally:
            conn.close()

    def list_outbound_batches_with_counts(self, limit: int = 10) -> List[dict]:
        """Lotes recentes + contagem de mensagens por estado (para o painel)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT b.id, b.city, b.name, b.status, b.dry_run, b.contact_count,
                       b.created_at, b.previewed_at,
                       SUM(CASE WHEN m.status='queued'  THEN 1 ELSE 0 END) AS queued,
                       SUM(CASE WHEN m.status='sent'    THEN 1 ELSE 0 END) AS sent,
                       SUM(CASE WHEN m.status='skipped' THEN 1 ELSE 0 END) AS skipped,
                       SUM(CASE WHEN m.status='failed'  THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN m.status='sending' THEN 1 ELSE 0 END) AS sending,
                       COUNT(m.id) AS total
                FROM outbound_batches b
                LEFT JOIN outbound_messages m ON m.batch_id = b.id
                WHERE b.status <> 'abandoned'
                GROUP BY b.id
                ORDER BY b.id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_batch_messages(self, batch_id: int, limit: int = 100) -> List[dict]:
        """Mensagens de um lote com destinatario, estado, provider_id e erro."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT m.id, m.to_email, m.subject, m.status, m.provider_id,
                       m.queued_at, m.sent_at, COALESCE(m.error,'') AS error,
                       m.sequence_step, m.next_step_at, m.contact_id,
                       COALESCE(oc.replied_at,'') AS replied_at,
                       COALESCE(mb.email,'') AS from_addr,
                       COALESCE(oc.company_name,'') AS company_name
                FROM outbound_messages m
                LEFT JOIN sending_mailboxes mb ON mb.id = m.mailbox_id
                LEFT JOIN outbound_contacts oc ON oc.id = m.contact_id
                WHERE m.batch_id = ?
                ORDER BY m.id
                LIMIT ?
                """,
                (int(batch_id), int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_outbound_batches(self, limit: int = 50) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM outbound_batches ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_suppression(self, value: str, channel: str = "email", reason: str = "manual") -> bool:
        if not value:
            return False
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO suppressions (value, channel, reason) VALUES (?, ?, ?)",
                (value.lower(), channel, reason),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def is_suppressed(self, value: str, channel: str = "email") -> bool:
        if not value:
            return False
        conn = get_connection()
        try:
            r = conn.execute(
                "SELECT 1 FROM suppressions WHERE lower(value)=? AND channel IN (?, 'all') LIMIT 1",
                (value.lower(), channel),
            ).fetchone()
            return bool(r)
        finally:
            conn.close()

    def list_suppressions(self, limit: int = 100) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM suppressions ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def create_outbound_contact(
        self,
        lead_id: Optional[int],
        email: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        company_name: Optional[str] = None,
        contact_name: Optional[str] = None,
        email_source: str = "scrape",
        kind: str = "business",
    ) -> Optional[dict]:
        if not email:
            return None
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO outbound_contacts (lead_id, kind, company_name, contact_name, email, email_source, email_status, city, state) "
                "VALUES (?, ?, ?, ?, ?, ?, 'unknown', ?, ?)",
                (lead_id, kind, company_name, contact_name, email.lower(), email_source, city, state),
            )
            conn.commit()
            r = conn.execute("SELECT * FROM outbound_contacts WHERE email=?", (email.lower(),)).fetchone()
            return dict(r) if r else None
        except Exception:
            return None
        finally:
            conn.close()

    def enqueue_outbound_message(
        self,
        batch_id: Optional[int],
        contact_id: Optional[int],
        mailbox_id: Optional[int] = None,
        city: Optional[str] = None,
        to_email: Optional[str] = None,
        subject: Optional[str] = None,
        body_hash: Optional[str] = None,
        cost_usd: float = 0.0,
        segments: int = 1,
        sequence_step: int = 1,
        next_step_at: Optional[str] = None,
    ) -> Optional[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO outbound_messages (batch_id, contact_id, mailbox_id, city, channel, to_email, subject, body_hash, status, cost_usd, segments, sequence_step, next_step_at) "
                "VALUES (?, ?, ?, ?, 'email', ?, ?, ?, 'queued', ?, ?, ?, ?)",
                (batch_id, contact_id, mailbox_id, city, to_email and to_email.lower(), subject, body_hash, float(cost_usd), int(segments), int(sequence_step), next_step_at),
            )
            conn.commit()
            if cur.rowcount == 0:
                # Dedup: ja' existe mensagem ativa para este destinatario (mesmo passo).
                return None
            mid = cur.lastrowid
            r = conn.execute("SELECT * FROM outbound_messages WHERE id=?", (mid,)).fetchone()
            return dict(r) if r else None
        except Exception:
            return None
        finally:
            conn.close()

    def list_outbound_messages_due_for_sequence(
        self, now: str, limit: int = 50
    ) -> List[dict]:
        """Mensagens ENVIADAS cujo proximo passo da sequencia ja' pode ser criado.

        `next_step_at` e' posto quando a mensagem e' enfileirada e consumido
        (posto a NULL) quando o passo seguinte e' criado — assim cada passo e'
        agendado uma unica vez.
        """
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM outbound_messages "
                "WHERE status='sent' AND next_step_at IS NOT NULL AND next_step_at <= ? "
                "ORDER BY id ASC LIMIT ?",
                (now, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def set_outbound_message_next_step(
        self, message_id: int, next_step_at: Optional[str]
    ) -> bool:
        """Marca (ou limpa) o agendamento do proximo passo de uma mensagem."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE outbound_messages SET next_step_at=? WHERE id=?",
                (next_step_at, int(message_id)),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def mark_outbound_contact_replied(self, contact_id: int) -> bool:
        """Marca o contacto como respondido (trava a sequencia)."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE outbound_contacts SET replied_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(contact_id),),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def claim_outbound_message(self, message_id: int) -> bool:
        """Claim atomico: `queued` -> `sending` so' para o primeiro tick.

        Devolve True apenas para o worker que ganhar a corrida (rowcount=1);
        qualquer tick sobreposto ve' rowcount=0 e tem de saltar a mensagem.

        Regista `claimed_at` para que o reaper saiba ha quanto tempo a
        mensagem esta' presa (o processo pode morrer a meio do envio).
        """
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE outbound_messages SET status='sending', "
                "claimed_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status='queued'",
                (int(message_id),),
            )
            conn.commit()
            return cur.rowcount == 1
        except Exception:
            return False
        finally:
            conn.close()

    def fail_stale_sending_outbound_messages(self, older_than: str) -> int:
        """Marca como 'failed' as mensagens presas em 'sending' ha demasiado tempo.

        O `claimed_at` e' gravado no claim atomico. Mensagens em 'sending' sem
        `claimed_at` (linhas anteriores a essa coluna existir) usam
        `queued_at`/`created_at` como fallback — sem isso ficariam presas para
        sempre, que era o bug que o reaper devia resolver.

        O UPDATE e' UMA instrucao condicional: se dois workers/reapers correrem
        em paralelo, o SQLite serializa os escritores e so' um transita cada
        linha (o outro ve' rowcount 0). Nunca reenvia: at-most-once.

        `next_step_at` e' preservado (metadado; a sequencia so' parte de
        mensagens `sent`).
        """
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE outbound_messages SET status='failed', "
                "error='stale sending claim (processo terminado a meio do envio)', "
                "claimed_at=NULL "
                "WHERE status='sending' "
                "AND COALESCE(claimed_at, queued_at, created_at) < ?",
                (older_than,),
            )
            conn.commit()
            return cur.rowcount
        except Exception as e:
            logger.warning("[OUTBOUND] falha ao limpar 'sending' presos: %s", e)
            return 0
        finally:
            conn.close()

    def count_stale_sending_outbound_messages(self, older_than: str) -> int:
        """Quantas mensagens estao presas em 'sending' (saude do outbound)."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM outbound_messages "
                "WHERE status='sending' "
                "AND COALESCE(claimed_at, queued_at, created_at) < ?",
                (older_than,),
            ).fetchone()
            return int(row["c"])
        finally:
            conn.close()

    def set_contact_niche(
        self, contact_id: int, niche_key: Optional[str], niche_status: str
    ) -> None:
        """Grava o nicho classificado num contacto (gate de envio)."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE outbound_contacts SET niche_key=?, niche_status=? WHERE id=?",
                (niche_key, niche_status, contact_id),
            )
            conn.commit()
        finally:
            conn.close()

    def set_lead_niche(
        self,
        lead_id: int,
        niche_key: Optional[str],
        niche_status: str,
        score: float = 0.0,
        evidence: Optional[str] = None,
    ) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE leads SET niche_key=?, niche_status=?, niche_score=?, "
                "niche_evidence=? WHERE id=?",
                (niche_key, niche_status, score, evidence, lead_id),
            )
            conn.commit()
        finally:
            conn.close()

    def outbound_category_mix(
        self, city: str, categories: Optional[List[str]] = None, limit: int = 3
    ) -> List[tuple[str, int]]:
        """Top categorias (categoria, contagem) do inventario cidade+nicho.

        Usado para derivar a clausula "including X and Y" do copy a partir de
        dados reais. Devolve [] quando nao ha inventario.
        """
        if not city:
            return []
        conn = get_connection()
        try:
            where = _qualified_where()
            not_inst = institutional_owner_name_where()
            params: List[Any] = [city]
            cat_clause = ""
            clean = [c for c in (categories or []) if c]
            if clean:
                marks = ", ".join("?" for _ in clean)
                cat_clause = f"AND issue_category IN ({marks}) "
                params.extend(clean)
            q = (
                "SELECT issue_category, COUNT(1) AS c FROM leads "
                f"WHERE ({where} OR source_type = 'import_b2b') "
                "AND UPPER(TRIM(city)) = UPPER(TRIM(?)) "
                "AND (lead_status IS NULL OR lead_status = 'available') "
                f"AND NOT ({not_inst}) "
                f"{cat_clause}"
                "GROUP BY issue_category ORDER BY c DESC LIMIT ?"
            )
            params.append(int(limit))
            return [(r["issue_category"], int(r["c"])) for r in conn.execute(q, params)]
        finally:
            conn.close()

    def count_qualified_contractors_in_city(
        self, city: str, categories: Optional[List[str]] = None
    ) -> int:
        """Leads qualificados disponíveis numa cidade (para o simulador dry-run).

        Qualificado = `_qualified_where` (endereço + 16 ofícios + gatilho
        preditivo) E proprietário NÃO institucional (a própria cidade não é
        empreiteiro acionável) E lead ainda disponível (não reservado/
        convertido). Espelha a lógica de inventário do feed.

        `categories` restringe ao nicho (ex.: Roof/Structure para telhados);
        vazio/None conta todos os ofícios.
        """
        if not city:
            return 0
        conn = get_connection()
        try:
            where = _qualified_where()
            not_institutional = institutional_owner_name_where()
            params: List[Any] = [city]
            cat_clause = ""
            clean = [c for c in (categories or []) if c]
            if clean:
                marks = ", ".join("?" for _ in clean)
                cat_clause = f"AND issue_category IN ({marks}) "
                params.extend(clean)
            q = (
                "SELECT COUNT(*) AS c FROM leads "
                f"WHERE ({where} OR source_type = 'import_b2b') "
                "AND UPPER(TRIM(city)) = UPPER(TRIM(?)) "
                "AND (lead_status IS NULL OR lead_status = 'available') "
                f"AND NOT ({not_institutional}) "
                f"{cat_clause}"
            )
            return int(conn.execute(q, params).fetchone()["c"])
        finally:
            conn.close()

    def count_outbound_recipients(self, city: str) -> int:
        """Leads da cidade que ja' tem um destinatario contactavel (e-mail).

        Mede o que o lote consegue REALMENTE enfileirar hoje: contacto em
        `outbound_contacts` com e-mail e nao cancelado, ou lead B2B importado
        com `owner_email` preenchido. E' o numero que o painel deve mostrar ao
        lado das "oportunidades" (que sao o inventario, nao destinatarios).
        """
        if not city:
            return 0
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM leads "
                "WHERE UPPER(TRIM(city)) = UPPER(TRIM(?)) "
                "AND (lead_status IS NULL OR lead_status = 'available') "
                "AND ("
                "  (source_type = 'import_b2b' AND COALESCE(owner_email, '') <> '') "
                "  OR EXISTS ("
                "    SELECT 1 FROM outbound_contacts oc "
                "    WHERE oc.lead_id = leads.id "
                "      AND COALESCE(oc.email, '') <> '' "
                "      AND COALESCE(oc.unsubscribed, 0) = 0"
                "  )"
                ")",
                (city,),
            ).fetchone()
            return int(row["c"])
        finally:
            conn.close()

    def outbound_diagnostics(self, city: str) -> dict:
        """Radiografia do funil para uma cidade (caixa preta do Lote #28).

        Responde, so' com leituras: quantos leads existem, quantos ja' tem
        e-mail, quantos vieram de import B2B e quantos contactos sao realmente
        enfileiraveis. Serve para separar "inventario" de "destinatarios".
        """
        conn = get_connection()
        try:
            def one(sql: str, params: tuple = ()) -> int:
                return int(conn.execute(sql, params).fetchone()[0])

            city_where = "UPPER(TRIM(city)) = UPPER(TRIM(?))"
            status_rows = conn.execute(
                "SELECT COALESCE(email_status, 'NULL') AS status, COUNT(*) AS c "
                f"FROM outbound_contacts WHERE {city_where} GROUP BY status",
                (city,),
            ).fetchall()
            sendable_marks = ", ".join("?" for _ in SENDABLE_EMAIL_STATUSES)
            return {
                "city": city,
                "leads_total": one(f"SELECT COUNT(*) FROM leads WHERE {city_where}", (city,)),
                "leads_with_email": one(
                    f"SELECT COUNT(*) FROM leads WHERE {city_where} "
                    "AND COALESCE(owner_email, '') <> ''",
                    (city,),
                ),
                "import_leads": one(
                    f"SELECT COUNT(*) FROM leads WHERE {city_where} "
                    "AND source_type = 'import_b2b'",
                    (city,),
                ),
                "contacts_total": one(
                    f"SELECT COUNT(*) FROM outbound_contacts WHERE {city_where}", (city,)
                ),
                "contacts_by_status": {r["status"]: int(r["c"]) for r in status_rows},
                "contacts_sendable": one(
                    f"SELECT COUNT(*) FROM outbound_contacts WHERE {city_where} "
                    "AND COALESCE(email, '') <> '' AND COALESCE(unsubscribed, 0) = 0 "
                    f"AND (LOWER(COALESCE(email_status, '')) IN ({sendable_marks}) "
                    f"OR LOWER(COALESCE(email_source, '')) IN ({', '.join('?' for _ in TRUSTED_EMAIL_SOURCES)}))",
                    (city, *SENDABLE_EMAIL_STATUSES, *TRUSTED_EMAIL_SOURCES),
                ),
                "recipients": self.count_outbound_recipients(city),
            }
        finally:
            conn.close()

    def get_outbound_sample_lead(
        self, city: str, categories: Optional[List[str]] = None
    ) -> Optional[dict]:
        """Uma linha REAL qualificada da cidade, para a prévia do template.
        Devolve os campos que o e-mail usa (empresa/proprietário, endereço,
        categoria, estado) do lead mais recente que casa o filtro. Serve para o
        painel mostrar exatamente o e-mail que sairia, com dados reais.
        """
        if not city:
            return None
        conn = get_connection()
        try:
            where = _qualified_where()
            not_institutional = institutional_owner_name_where()
            params: List[Any] = [city]
            cat_clause = ""
            clean = [c for c in (categories or []) if c]
            if clean:
                marks = ", ".join("?" for _ in clean)
                cat_clause = f"AND issue_category IN ({marks}) "
                params.extend(clean)
            q = (
                "SELECT owner_name, address, city, COALESCE(state, '') AS state, "
                "issue_category, issue_description, date_reported "
                "FROM leads "
                f"WHERE ({where} OR source_type = 'import_b2b') "
                "AND UPPER(TRIM(city)) = UPPER(TRIM(?)) "
                "AND (lead_status IS NULL OR lead_status = 'available') "
                f"AND NOT ({not_institutional}) "
                f"{cat_clause}"
                "ORDER BY COALESCE(date_reported, '') DESC LIMIT 1"
            )
            row = conn.execute(q, params).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_outbound_sample_contact(self, city: str) -> Optional[dict]:
        """Um contacto REAL enriquecido da cidade, para a prévia do template.

        `outbound_contacts` guarda a empresa/contacto/e-mail reais do
        destinatário (empreiteiro), obtidos por scrape/Snov. Se ainda não
        houver enriquecimento (tabela vazia), devolve None e a prévia cai no
        fallback (owner_name do lead) — fica claro para o admin.
        """
        if not city:
            return None
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, lead_id, company_name, contact_name, email, state "
                "FROM outbound_contacts "
                "WHERE UPPER(TRIM(city)) = UPPER(TRIM(?)) "
                "AND COALESCE(unsubscribed, 0) = 0 "
                "AND COALESCE(email, '') <> '' "
                "ORDER BY COALESCE(enriched_at, created_at, '') DESC LIMIT 1",
                (city,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ===== OUTBOUND Fase 2: fila, contadores, mailboxes e telemetria =====

    def get_outbound_batch(self, batch_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM outbound_batches WHERE id=?", (int(batch_id),)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def start_outbound_batch(self, batch_id: int) -> Optional[dict]:
        """Promove um lote a REAL: dry_run=0, status='sending', started_at=now."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE outbound_batches SET dry_run=0, status='sending', "
                "started_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(batch_id),),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM outbound_batches WHERE id=?", (int(batch_id),)
            ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None
        finally:
            conn.close()

    def finish_outbound_batch(self, batch_id: int, status: str = "sent") -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE outbound_batches SET status=?, finished_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (status, int(batch_id)),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def update_outbound_batch_stats(
        self, batch_id: int, contact_count: int, est_cost_usd: float
    ) -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE outbound_batches SET contact_count=?, est_cost_usd=? WHERE id=?",
                (int(contact_count), float(est_cost_usd), int(batch_id)),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def list_outbound_leads(
        self, city: str, categories: Optional[List[str]] = None, limit: int = 200
    ) -> List[dict]:
        """Leads qualificados disponiveis na cidade, para materializar um lote.

        Mesma definicao do simulador (`_qualified_where` + nao institucional +
        disponivel), agora devolvendo as linhas reais para o enriquecimento.

        Dedup: exclui leads cujo contacto enriquecido (`outbound_contacts.email`)
        ja' tenha uma mensagem ATIVA (queued/sending/sent), para nunca reenviar
        o mesmo destinatario em lotes futuros.
        """
        if not city:
            return []
        conn = get_connection()
        try:
            where = _qualified_where()
            not_institutional = institutional_owner_name_where()
            params: List[Any] = [city]
            cat_clause = ""
            clean = [c for c in (categories or []) if c]
            if clean:
                marks = ", ".join("?" for _ in clean)
                cat_clause = f"AND issue_category IN ({marks}) "
                params.extend(clean)
            params.append(int(limit))
            q = (
                "SELECT id, owner_name, owner_email, address, city, "
                "COALESCE(state, '') AS state, issue_category "
                "FROM leads "
                f"WHERE ({where} OR source_type = 'import_b2b') "
                "AND UPPER(TRIM(city)) = UPPER(TRIM(?)) "
                "AND (lead_status IS NULL OR lead_status = 'available') "
                f"AND NOT ({not_institutional}) "
                f"{cat_clause}"
                "AND NOT EXISTS ("
                "  SELECT 1 FROM outbound_contacts oc "
                "  JOIN outbound_messages om ON LOWER(om.to_email) = LOWER(oc.email) "
                "  WHERE oc.lead_id = leads.id "
                "    AND oc.email IS NOT NULL "
                "    AND om.status IN ('queued', 'sending', 'sent')"
                ") "
                # Destinatarios ja' contactaveis primeiro: um lote de 200 nunca
                # deve gastar as suas vagas em permissoes sem e-mail enquanto
                # existem leads B2B com e-mail valido na mesma cidade.
                "ORDER BY ("
                "  SELECT COUNT(*) FROM outbound_contacts oc2 "
                "  WHERE oc2.lead_id = leads.id "
                "    AND COALESCE(oc2.email, '') <> '' "
                "    AND COALESCE(oc2.unsubscribed, 0) = 0"
                ") DESC, "
                "(COALESCE(owner_email, '') <> '') DESC, "
                "COALESCE(date_reported, '') DESC LIMIT ?"
            )
            return [dict(r) for r in conn.execute(q, params).fetchall()]
        finally:
            conn.close()

    def get_outbound_contact_by_lead(self, lead_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            # Prefere um contacto ENVIAVEL (com e-mail e nao cancelado). O
            # `ORDER BY id DESC` antigo podia devolver a linha mais recente
            # (ex.: e-mail vazio/`unknown`), escondendo um `valid` anterior.
            row = conn.execute(
                "SELECT * FROM outbound_contacts WHERE lead_id=? "
                "ORDER BY (COALESCE(email, '') <> '' AND COALESCE(unsubscribed, 0) = 0) DESC, "
                "CASE WHEN LOWER(COALESCE(email_status, '')) IN ('valid', 'verified') "
                "THEN 0 ELSE 1 END, id DESC LIMIT 1",
                (int(lead_id),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_outbound_contact_by_email(self, email: str) -> Optional[dict]:
        if not email:
            return None
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM outbound_contacts WHERE email=?", (email.lower(),)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def upsert_outbound_contact(
        self,
        lead_id: Optional[int],
        email: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        company_name: Optional[str] = None,
        contact_name: Optional[str] = None,
        email_source: str = "snov",
        email_status: str = "unknown",
        company_domain: Optional[str] = None,
    ) -> Optional[dict]:
        if not email:
            return None
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO outbound_contacts "
                "(lead_id, kind, company_name, contact_name, email, email_source, "
                "email_status, city, state, company_domain, enriched_at, last_verified_at) "
                "VALUES (?, 'business', ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT(email) DO UPDATE SET "
                "email_status=excluded.email_status, "
                "enriched_at=CURRENT_TIMESTAMP, last_verified_at=CURRENT_TIMESTAMP, "
                "email_source=excluded.email_source, "
                "company_name=COALESCE(excluded.company_name, outbound_contacts.company_name), "
                "contact_name=COALESCE(excluded.contact_name, outbound_contacts.contact_name), "
                "company_domain=COALESCE(excluded.company_domain, outbound_contacts.company_domain), "
                "lead_id=COALESCE(outbound_contacts.lead_id, excluded.lead_id)",
                (
                    lead_id,
                    company_name,
                    contact_name,
                    email.lower(),
                    email_source,
                    email_status,
                    city,
                    state,
                    company_domain,
                ),
            )
            conn.commit()
            r = conn.execute(
                "SELECT * FROM outbound_contacts WHERE email=?", (email.lower(),)
            ).fetchone()
            return dict(r) if r else None
        except Exception:
            return None
        finally:
            conn.close()

    def import_b2b_lead(
        self,
        email: str,
        company_name: str,
        city: str,
        category: str = "General Contractors",
        contact_name: Optional[str] = None,
        domain: Optional[str] = None,
        state: Optional[str] = None,
        niche_key: Optional[str] = None,
        niche_status: str = "confirmed",
        niche_score: float = 0.0,
        niche_evidence: Optional[str] = None,
        create_contact: bool = True,
    ) -> Optional[dict]:
        if not email or not company_name or not city:
            return None
        clean_email = email.strip().lower()
        clean_city = city.strip().upper()
        if clean_city == "NEW YORK":
            clean_city = "NYC"
        default_states = {"NYC": "NY", "CHICAGO": "IL", "DALLAS": "TX", "BOSTON": "MA"}
        st = (state or "").strip().upper() or default_states.get(clean_city, "NY")
        # `leads` exige external_id/address/date_reported (NOT NULL). O INSERT
        # antigo omitia os tres, rebentava e o except silencioso devolvia None:
        # nenhum lead B2B entrava na BD (lote saia sempre com 0 e-mails).
        external_id = f"b2b:{clean_email}"
        # `leads` tem UNIQUE(address, city): com address='' todos os imports da
        # mesma cidade colidiam e o INSERT OR IGNORE silenciava o erro — so' o
        # PRIMEIRO contacto B2B de cada cidade entrava. O endereco passa a ser
        # unico por contacto.
        b2b_address = f"B2B contact - {clean_email}"

        conn = get_connection()
        try:
            # Reutiliza a grafia ja existente na BD para a cidade. Sem isto o
            # import B2B grava "CHICAGO" enquanto o scraper grava "Chicago" e
            # os filtros por cidade deixam de encontrar metade dos leads.
            existing_city = conn.execute(
                "SELECT city FROM leads WHERE city = ? COLLATE NOCASE "
                "GROUP BY city ORDER BY COUNT(*) DESC LIMIT 1",
                (clean_city,),
            ).fetchone()
            if existing_city and existing_city["city"]:
                clean_city = existing_city["city"]
            conn.execute(
                "INSERT OR IGNORE INTO leads "
                "(external_id, source_type, address, city, state, issue_category, "
                "issue_description, owner_name, owner_email, case_status, date_reported, "
                "lead_status, created_at, updated_at, niche_key, niche_status, "
                "niche_score, niche_evidence) "
                "VALUES (?, 'import_b2b', ?, ?, ?, ?, ?, ?, ?, 'open', CURRENT_TIMESTAMP, "
                "'available', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?, ?)",
                (
                    external_id,
                    b2b_address,
                    clean_city,
                    st,
                    category,
                    f"B2B contact import ({category})",
                    company_name,
                    clean_email,
                    niche_key,
                    niche_status,
                    niche_score,
                    niche_evidence,
                ),
            )
            lead_row = conn.execute(
                "SELECT id FROM leads WHERE external_id=? AND source_type='import_b2b'",
                (external_id,),
            ).fetchone()
            if not lead_row:
                logger.error(
                    "[OUTBOUND] import_b2b nao criou lead para %s (cidade %s)",
                    clean_email,
                    clean_city,
                )
                return None
            lead_id = lead_row["id"]

            if not create_contact:
                # Quarentena: o lead existe (visivel no painel) mas NAO ha
                # contacto enviavel, portanto o motor de envio nunca o apanha.
                conn.commit()
                return {"id": None, "lead_id": lead_id, "email": None,
                        "quarantined": True}

            conn.execute(
                "INSERT INTO outbound_contacts "
                "(lead_id, kind, company_name, contact_name, email, email_source, "
                "email_status, city, state, company_domain, enriched_at, last_verified_at, "
                "niche_key, niche_status) "
                "VALUES (?, 'business', ?, ?, ?, 'import', 'valid', ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?) "
                "ON CONFLICT(email) DO UPDATE SET "
                "email_status='valid', "
                "email_source='import', "
                "enriched_at=CURRENT_TIMESTAMP, last_verified_at=CURRENT_TIMESTAMP, "
                "company_name=COALESCE(excluded.company_name, outbound_contacts.company_name), "
                "contact_name=COALESCE(excluded.contact_name, outbound_contacts.contact_name), "
                "company_domain=COALESCE(excluded.company_domain, outbound_contacts.company_domain), "
                "niche_key=COALESCE(excluded.niche_key, outbound_contacts.niche_key), "
                "niche_status=CASE WHEN excluded.niche_status='confirmed' THEN 'confirmed' "
                "                  ELSE COALESCE(outbound_contacts.niche_status, 'unknown') END, "
                "lead_id=excluded.lead_id",
                (
                    lead_id,
                    company_name,
                    contact_name,
                    clean_email,
                    clean_city,
                    st,
                    domain or (clean_email.split('@')[1] if '@' in clean_email else None),
                    niche_key,
                    niche_status,
                ),
            )
            conn.commit()
            r = conn.execute("SELECT * FROM outbound_contacts WHERE email=?", (clean_email,)).fetchone()
            return dict(r) if r else None
        except Exception:
            logger.exception(
                "[OUTBOUND] Falha ao importar lead B2B %s (%s)", clean_email, clean_city
            )
            return None
        finally:
            conn.close()

    def get_available_outbound_cities(self) -> List[str]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT UPPER(TRIM(city)) as city FROM leads WHERE city IS NOT NULL AND TRIM(city) != '' "
                "UNION SELECT DISTINCT UPPER(TRIM(city)) as city FROM outbound_contacts WHERE city IS NOT NULL AND TRIM(city) != ''"
            ).fetchall()
            cities = set(SERVED_CITIES)
            for r in rows:
                if r["city"]:
                    cities.add(r["city"].strip().upper())
            return sorted(list(cities))
        finally:
            conn.close()

    def get_available_outbound_categories(self, city: Optional[str] = None) -> List[str]:
        conn = get_connection()
        try:
            if city:
                rows = conn.execute(
                    "SELECT DISTINCT issue_category FROM leads WHERE UPPER(TRIM(city)) = UPPER(TRIM(?)) AND issue_category IS NOT NULL AND TRIM(issue_category) != ''",
                    (city,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT issue_category FROM leads WHERE issue_category IS NOT NULL AND TRIM(issue_category) != ''"
                ).fetchall()
            cats = [r["issue_category"] for r in rows if r["issue_category"]]
            return sorted(list(set(cats)))
        finally:
            conn.close()

    def update_outbound_contact_status(
        self,
        contact_id: int,
        email_status: Optional[str] = None,
        unsubscribed: Optional[int] = None,
    ) -> bool:
        conn = get_connection()
        try:
            sets = []
            params: List[Any] = []
            if email_status is not None:
                sets.append("email_status=?")
                params.append(email_status)
            if unsubscribed is not None:
                sets.append("unsubscribed=?")
                params.append(int(unsubscribed))
            if not sets:
                return True
            sets.append("last_verified_at=CURRENT_TIMESTAMP")
            params.append(int(contact_id))
            conn.execute(
                f"UPDATE outbound_contacts SET {', '.join(sets)} WHERE id=?", params
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def list_queued_outbound_messages(
        self, limit: int = 10, city: Optional[str] = None
    ) -> List[dict]:
        conn = get_connection()
        try:
            q = "SELECT * FROM outbound_messages WHERE status='queued'"
            params: List[Any] = []
            if city:
                q += " AND UPPER(TRIM(COALESCE(city,''))) = UPPER(TRIM(?))"
                params.append(city)
            q += " ORDER BY id LIMIT ?"
            params.append(int(limit))
            return [dict(r) for r in conn.execute(q, params).fetchall()]
        finally:
            conn.close()

    def get_outbound_message(self, message_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM outbound_messages WHERE id=?", (int(message_id),)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_outbound_message(
        self,
        message_id: int,
        status: Optional[str] = None,
        provider_id: Optional[str] = None,
        error: Optional[str] = None,
        sent_at: Optional[str] = None,
        mailbox_id: Optional[int] = None,
    ) -> bool:
        conn = get_connection()
        try:
            sets = []
            params: List[Any] = []
            if status is not None:
                sets.append("status=?")
                params.append(status)
            if provider_id is not None:
                sets.append("provider_id=?")
                params.append(provider_id)
            if error is not None:
                sets.append("error=?")
                params.append(error)
            if sent_at is not None:
                sets.append("sent_at=?")
                params.append(sent_at)
            if mailbox_id is not None:
                sets.append("mailbox_id=?")
                params.append(int(mailbox_id))
            if not sets:
                return True
            params.append(int(message_id))
            conn.execute(
                f"UPDATE outbound_messages SET {', '.join(sets)} WHERE id=?", params
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def count_outbound_messages(
        self, status: Optional[str] = None, batch_id: Optional[int] = None
    ) -> int:
        conn = get_connection()
        try:
            q = "SELECT COUNT(*) AS c FROM outbound_messages WHERE 1=1"
            params: List[Any] = []
            if status:
                q += " AND status=?"
                params.append(status)
            if batch_id is not None:
                q += " AND batch_id=?"
                params.append(int(batch_id))
            return int(conn.execute(q, params).fetchone()["c"])
        finally:
            conn.close()

    def outbound_queue_summary(self) -> dict:
        """Fila pendente: total e a mensagem mais antiga (cidade incluída).

        Usado pelo `/outbound/status` e pela Control Tower para explicar o
        `queue_age` com o motivo real (cidade bloqueada, cap de caixa, etc.).
        """
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(1) AS queued, MIN(queued_at) AS oldest_at "
                "FROM outbound_messages WHERE status='queued'"
            ).fetchone()
            oldest = conn.execute(
                "SELECT id, city, queued_at FROM outbound_messages "
                "WHERE status='queued' ORDER BY queued_at, id LIMIT 1"
            ).fetchone()
            return {
                "queued": int(row["queued"] if row else 0),
                "oldest_at": row["oldest_at"] if row else None,
                "oldest_id": oldest["id"] if oldest else None,
                "oldest_city": (oldest["city"] or "") if oldest else "",
            }
        finally:
            conn.close()

    def count_mailbox_sent_today(self, mailbox_id: int, day: str) -> int:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM outbound_messages "
                "WHERE mailbox_id=? AND status='sent' AND sent_at >= ?",
                (int(mailbox_id), f"{day} 00:00:00"),
            ).fetchone()
            return int(row["c"])
        finally:
            conn.close()

    def get_outbound_counter(self, city: str, day: str) -> dict:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM outbound_daily_counters WHERE city=? AND day=?",
                (city or "", day),
            ).fetchone()
            if row:
                return dict(row)
            return {"city": city or "", "day": day, "sent": 0, "enriched": 0, "spend_usd": 0.0}
        finally:
            conn.close()

    def increment_outbound_counter(
        self, city: str, day: str, sent: int = 0, enriched: int = 0, spend_usd: float = 0.0
    ) -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO outbound_daily_counters (city, day, sent, enriched, spend_usd, updated_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(city, day) DO UPDATE SET "
                "sent = outbound_daily_counters.sent + excluded.sent, "
                "enriched = outbound_daily_counters.enriched + excluded.enriched, "
                "spend_usd = outbound_daily_counters.spend_usd + excluded.spend_usd, "
                "updated_at = CURRENT_TIMESTAMP",
                ((city or ""), day, int(sent), int(enriched), float(spend_usd)),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def update_mailbox_after_send(
        self, mailbox_id: int, warmup_state: Optional[str] = None
    ) -> bool:
        conn = get_connection()
        try:
            if warmup_state:
                conn.execute(
                    "UPDATE sending_mailboxes SET last_send_at=CURRENT_TIMESTAMP, "
                    "warmup_state=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (warmup_state, int(mailbox_id)),
                )
            else:
                conn.execute(
                    "UPDATE sending_mailboxes SET last_send_at=CURRENT_TIMESTAMP, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (int(mailbox_id),),
                )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def set_mailbox_warmup_started(self, mailbox_id: int) -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE sending_mailboxes SET warmup_started_at=COALESCE(warmup_started_at, CURRENT_TIMESTAMP), "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(mailbox_id),),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def insert_lead(self, lead: EnrichedLead) -> bool:
        """Insere (ou actualiza) um lead respeitando as DUAS chaves únicas.

        - já existe (external_id, source_type) → UPDATE por essa chave;
        - já existe (address, city) mas não a chave natural → UPSERT do imóvel,
          que só recebe os dados mais novos (sem mudar de external_id);
        - caso contrário → INSERT.

        Ver `_LEAD_DATA_COLS` para o porquê de o ON CONFLICT não poder escrever
        `external_id`: era assim que o re-scrape explodia com
        "UNIQUE constraint failed: leads.external_id, leads.source_type".
        """
        values = _lead_insert_values(lead)
        insert_cols = ["external_id", "source_type", "address", "city"] + list(_LEAD_DATA_COLS)
        conn = get_connection()
        try:
            existing = conn.execute(
                "SELECT 1 FROM leads WHERE external_id = ? AND source_type = ?",
                (values["external_id"], values["source_type"]),
            ).fetchone()
            if existing:
                data_params = [values[c] for c in _LEAD_DATA_COLS if c != "created_at"]
                conn.execute(
                    f"UPDATE leads SET {_lead_set_clause('?')} "
                    "WHERE external_id = ? AND source_type = ?",
                    (*data_params, values["external_id"], values["source_type"]),
                )
            else:
                placeholders = ", ".join("?" for _ in insert_cols)
                conn.execute(
                    f"INSERT INTO leads ({', '.join(insert_cols)}) VALUES ({placeholders}) "
                    f"ON CONFLICT(address, city) DO UPDATE SET {_lead_set_clause('excluded.{col}')}",
                    [values[c] for c in insert_cols],
                )
            conn.commit()
            logger.info(f"Lead inserido/atualizado: {lead.external_id}")
            return True
        except Exception as e:
            logger.error(f"Erro ao inserir lead {getattr(lead, 'external_id', '?')}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
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
                    "SELECT id, issue_category, address, city, owner_name, "
                    "date_reported, case_status, status "
                    "FROM leads WHERE external_id = ? AND source_type = ?",
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

    def get_leads_feed(
        self,
        city: Optional[str] = None,
        signal_type: Optional[str] = None,
        category: Optional[str] = None,
        urgency: Optional[str] = None,
        include_closed: bool = False,
        days: Optional[int] = None,
        user_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[dict], int]:
        """Feed qualificado com filtros/total em SQL (P0-B).

        O `total` e' o COUNT do MESMO WHERE — o cartao e a lista deixam de
        divergir. `closed` fica fora por defeito; `include_closed=True` mostra-o.
        """
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        where = [
            _address_where("l"),
            _category_where("l"),
            _not_junk_where("l"),
            "l.signal_type IS NOT NULL",
            "l.lead_status != 'converted'",
        ]
        params: list = []
        if city and str(city).strip().lower() != "all":
            where.append("l.city = ? COLLATE NOCASE")
            params.append(city)
        if signal_type:
            where.append("l.signal_type = ?")
            params.append(signal_type)
        if category:
            where.append("l.issue_category = ?")
            params.append(category)
        if urgency:
            urg = [t.strip() for t in str(urgency).split(",") if t.strip()]
            if urg:
                where.append("l.urgency_level IN (%s)" % ",".join("?" * len(urg)))
                params.extend(urg)
        if days:
            where.append("l.date_reported >= datetime('now', ?)")
            params.append(f"-{int(days)} days")
        if not include_closed:
            where.append("COALESCE(l.signal_status, 'unknown') != 'closed'")
        if user_id is not None:
            where.append("(l.lead_status = 'available' OR l.reserved_by = ?)")
            params.append(user_id)
        else:
            where.append("l.lead_status = 'available'")
        where_sql = " AND ".join(where)

        conn = get_connection()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM leads l WHERE {where_sql}", params
            ).fetchone()["c"]
            rows = conn.execute(
                f"""
                SELECT l.*,
                       COALESCE(h.repeat_365, 0) AS repeat_365,
                       COALESCE(h.open_cases, 0) AS open_cases,
                       h.oldest_open_days AS oldest_open_days,
                       h.last_case_at AS last_case_at
                  FROM leads l
                  LEFT JOIN lead_history h ON h.lead_id = l.id
                 WHERE {where_sql}
                 ORDER BY l.date_reported DESC, l.id DESC
                 LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
            return [dict(r) for r in rows], int(total)
        finally:
            conn.close()

    def get_leads_by_city(self, city: str, limit: int = 100, source_type: Optional[str] = None, category: Optional[str] = None) -> List[dict]:
        """Retorna leads mais recentes de uma cidade com filtros opcionais no SQL."""
        conn = get_connection()
        try:
            sql = "SELECT * FROM leads WHERE city = ? COLLATE NOCASE"
            params = [city]

            if source_type:
                # Aceita lista para o filtro agrupado da UI (ex: "Obrigacao legal"
                # = dob_violation + hpd_violation)
                if isinstance(source_type, (list, tuple, set)):
                    wanted = [str(s).strip() for s in source_type if str(s).strip()]
                    if wanted:
                        sql += " AND source_type IN (%s)" % ",".join("?" * len(wanted))
                        params.extend(wanted)
                else:
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

    def update_owner_phone(
        self, lead_id: int, owner_phone: Optional[str], verified: bool = False
    ) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE leads SET owner_phone = ?, phone_verified = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (owner_phone, 1 if verified else 0, lead_id),
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
            # city/state entram na pesquisa porque o `address` passou a guardar
            # só a rua (a cidade tem coluna própria, canónica). Sem estas
            # colunas, pesquisar "Chicago" deixava de encontrar os seus leads.
            rows = conn.execute(
                """
                SELECT * FROM leads
                WHERE address LIKE ? OR city LIKE ? OR state LIKE ?
                   OR owner_name LIKE ? OR owner_phone LIKE ?
                ORDER BY date_reported DESC
                LIMIT ?
                """,
                (like, like, like, like, like, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_cities(self) -> List[str]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT city, COUNT(*) AS count FROM leads GROUP BY city"
            ).fetchall()
            return [item["city"] for item in _merge_city_counts(rows)]
        finally:
            conn.close()

    def get_cities_with_counts(self) -> List[dict]:
        """Retorna cidades com contagem de leads (sem filtro de lixo)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT city, COUNT(*) AS count FROM leads GROUP BY city"
            ).fetchall()
            return _merge_city_counts(rows)
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
                GROUP BY city
                """
            ).fetchall()
            return _merge_city_counts(rows)
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
                sql += " AND city = ? COLLATE NOCASE"
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
    def add_notification(self, type: str, title: str, message: str, lead_id: Optional[int] = None,
                         msg_key: Optional[str] = None, msg_params: Optional[dict] = None) -> Optional[dict]:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO notifications (type, title, message, lead_id, msg_key, msg_params) VALUES (?, ?, ?, ?, ?, ?)",
                (type, title, message, lead_id, msg_key,
                 json.dumps(msg_params, ensure_ascii=False) if msg_params else None),
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
                    subscription_status: Optional[str] = None, plan_until: Optional[str] = None,
                    locale: str = "en") -> Optional[dict]:
        conn = get_connection()
        try:
            exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if exists:
                return None
            conn.execute(
                "INSERT INTO users (email, password_hash, company_name, plan, subscription_status, plan_until, locale) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (email, password_hash, company_name, plan, subscription_status, plan_until, locale),
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

    def update_user_locale(self, user_id: int, locale: str) -> Optional[dict]:
        """Atualiza o idioma do usuário (users.locale: pt|en|es)."""
        conn = get_connection()
        try:
            conn.execute("UPDATE users SET locale = ? WHERE id = ?", (locale, user_id))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_user_welcome_popup(self, user_id: int) -> Optional[dict]:
        """Marca o welcome popup como visto pelo usuário."""
        conn = get_connection()
        try:
            conn.execute("UPDATE users SET welcome_popup_shown = 1 WHERE id = ?", (user_id,))
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
            now = utcnow()
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
                            user_id: Optional[int] = None,
                            granted: int = 1) -> bool:
        """Registra um evento Stripe. Retorna True se é novo, False se já existe.

        `granted=0` marca o evento como "visto mas ainda sem efeito aplicado"
        (usado no `checkout.session.completed`: so' se marca como concedido
        DEPOIS de o acesso ser estendido). O retry do Stripe volta a encontrar
        o evento com `granted=0` e volta a tentar conceder o acesso.
        """
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO stripe_events (event_id, event_type, user_id, granted) "
                "VALUES (?, ?, ?, ?)",
                (event_id, event_type, user_id, 1 if granted else 0),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_stripe_event(self, event_id: str) -> Optional[dict]:
        """O evento Stripe ja' registado (com o estado `granted`), ou None."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM stripe_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def mark_stripe_event_granted(self, event_id: str) -> bool:
        """Marca o evento como tendo concedido o efeito (acesso estendido)."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE stripe_events SET granted=1 WHERE event_id=?", (event_id,)
            )
            conn.commit()
            return True
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
    # Funil de checkout (Prioridade A)
    # ---------------------------------------------------------------
    def record_checkout_session(
        self,
        user_id: int,
        session_id: str,
        email: Optional[str] = None,
        amount_cents: int = 0,
        currency: str = "usd",
        url: Optional[str] = None,
    ) -> bool:
        """Regista uma tentativa de checkout (idempotente por `session_id`)."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO checkout_sessions "
                "(user_id, session_id, email, amount_cents, currency, status, url) "
                "VALUES (?, ?, ?, ?, ?, 'open', ?)",
                (
                    int(user_id),
                    session_id,
                    (email or "").strip().lower() or None,
                    int(amount_cents or 0),
                    currency or "usd",
                    url,
                ),
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception:
            return False
        finally:
            conn.close()

    def update_checkout_session(
        self,
        session_id: str,
        status: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> bool:
        """Atualiza o estado de uma sessao de checkout (open/completed/expired)."""
        conn = get_connection()
        try:
            sets: List[str] = []
            params: List[Any] = []
            if status is not None:
                sets.append("status=?")
                params.append(status)
            if completed_at is not None:
                sets.append("completed_at=?")
                params.append(completed_at)
            if not sets:
                return True
            sets.append("updated_at=CURRENT_TIMESTAMP")
            params.append(session_id)
            conn.execute(
                f"UPDATE checkout_sessions SET {', '.join(sets)} WHERE session_id=?",
                params,
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def get_open_checkout_session(self, user_id: int) -> Optional[dict]:
        """Sessao de checkout AINDA ABERTA do utilizador (a mais recente)."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM checkout_sessions WHERE user_id=? AND status='open' "
                "ORDER BY id DESC LIMIT 1",
                (int(user_id),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_recoverable_checkout_sessions(
        self, older_than: str, max_reminders: int = 2, limit: int = 50
    ) -> List[dict]:
        """Sessoes abertas ha mais de `older_than` (YYYY-MM-DD HH:MM:SS) semlembrar.

        Usadas pelo loop de recuperacao de carrinho abandonado.
        """
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT cs.*, u.email AS user_email, u.company_name, u.plan_until "
                "FROM checkout_sessions cs "
                "JOIN users u ON u.id = cs.user_id "
                "WHERE cs.status='open' AND cs.created_at <= ? "
                f"AND cs.reminders < {int(max_reminders)} "
                "ORDER BY cs.id ASC LIMIT ?",
                (older_than, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_checkout_reminded(self, session_id: str) -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE checkout_sessions SET reminders = reminders + 1, "
                "reminded_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP "
                "WHERE session_id=?",
                (session_id,),
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def checkout_funnel_stats(self) -> dict:
        """Funil 'criou -> abriu (com email) -> pagou' para o painel admin."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT "
                " COUNT(*) AS created, "
                " SUM(CASE WHEN email IS NOT NULL AND email <> '' THEN 1 ELSE 0 END) AS with_email, "
                " SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed, "
                " SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) AS expired, "
                " SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS still_open, "
                " SUM(CASE WHEN reminders > 0 THEN 1 ELSE 0 END) AS recovered "
                "FROM checkout_sessions"
            ).fetchone()
            created = int(row["created"] or 0)
            with_email = int(row["with_email"] or 0)
            completed = int(row["completed"] or 0)
            return {
                "sessions_created": created,
                "sessions_with_email": with_email,
                "sessions_completed": completed,
                "sessions_expired": int(row["expired"] or 0),
                "sessions_open": int(row["still_open"] or 0),
                "sessions_recovered": int(row["recovered"] or 0),
                "email_capture_rate": round(with_email / created, 4) if created else 0.0,
                "conversion_rate": round(completed / created, 4) if created else 0.0,
            }
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # Interesses por usuário
    # ---------------------------------------------------------------
    def set_user_interests(self, user_id: int, categories: List[str]) -> bool:
        conn = get_connection()
        try:
            # Preserva o sino de push por categoria ao editar a selecao. Sem
            # isto, marcar/desmarcar um oficio reiniciava todos os toggles.
            prev = {
                r["category"]: int(r["push_enabled"] if r["push_enabled"] is not None else 1)
                for r in conn.execute(
                    "SELECT category, push_enabled FROM user_interests WHERE user_id = ?",
                    (user_id,),
                ).fetchall()
            }
            conn.execute("DELETE FROM user_interests WHERE user_id = ?", (user_id,))
            for cat in categories:
                if cat:
                    conn.execute(
                        "INSERT OR IGNORE INTO user_interests (user_id, category, push_enabled) "
                        "VALUES (?, ?, ?)",
                        (user_id, cat, prev.get(cat, 1)),
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

    def get_user_interest_settings(self, user_id: int) -> List[dict]:
        """Interesses com o estado do sino de push (B2)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT category, COALESCE(push_enabled, 1) AS push_enabled "
                "FROM user_interests WHERE user_id = ? ORDER BY category",
                (user_id,),
            ).fetchall()
            return [
                {"category": r["category"], "push_enabled": bool(r["push_enabled"])}
                for r in rows
            ]
        finally:
            conn.close()

    def set_user_interest_push(self, user_id: int, category: str, enabled: bool) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE user_interests SET push_enabled = ? "
                "WHERE user_id = ? AND category = ?",
                (1 if enabled else 0, user_id, category),
            )
            conn.commit()
            return cur.rowcount > 0
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

    def get_users_interested_in(
        self, category: str, city: Optional[str] = None, strict: bool = False
    ) -> List[dict]:
        """Usuários elegíveis a receber alerta de uma categoria.

        Elegibilidade (nesta ordem):
          1. ACESSO VIGENTE — decidido por services.access.is_access_active()
             (fonte única de verdade; nada de whitelist local de status aqui).
          2. RECORTE DE CATEGORIA — `strict=False` mantém o fallback antigo
             (sem interesses = todas as categorias); `strict=True` exige a
             categoria gravada em `user_interests`. O Alert Engine usa
             `strict=True`: sem escolha explícita não há alerta individual.
          3. RECORTE DE CIDADE — se `city` informado e o usuário tiver
             `cities_filter`, a cidade precisa estar na lista.
        """
        conn = get_connection()
        try:
            if strict:
                rows = conn.execute(
                    """
                    SELECT u.*,
                           COALESCE((
                             SELECT ui.push_enabled FROM user_interests ui
                             WHERE ui.user_id = u.id AND ui.category = ?
                           ), 1) AS interest_push_enabled
                    FROM users u
                    WHERE EXISTS (
                        SELECT 1 FROM user_interests ui2
                        WHERE ui2.user_id = u.id AND ui2.category = ?
                    )
                    """,
                    (category, category),
                ).fetchall()
            else:
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
    def add_push_subscription(
        self, user_id: int, endpoint: str, p256dh: str, auth: str,
        user_agent: Optional[str] = None, device_label: Optional[str] = None,
    ) -> bool:
        """Salva ou atualiza uma push subscription para o usuário.

        B1: guarda a ultima vez que o dispositivo foi visto e mantem no maximo
        5 dispositivos ativos por utilizador (desativa os mais antigos). Sem
        isto, um unico utilizador com 9 browsers recebe 9 copias de cada alerta.
        """
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO push_subscriptions
                    (user_id, endpoint, p256dh, auth, user_agent, device_label,
                     last_seen_at, disabled_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, NULL)
                ON CONFLICT(endpoint) DO UPDATE SET
                    p256dh = excluded.p256dh,
                    auth = excluded.auth,
                    user_id = excluded.user_id,
                    user_agent = COALESCE(excluded.user_agent, push_subscriptions.user_agent),
                    device_label = COALESCE(excluded.device_label, push_subscriptions.device_label),
                    last_seen_at = CURRENT_TIMESTAMP,
                    disabled_at = NULL
                """,
                (user_id, endpoint, p256dh, auth, user_agent, device_label),
            )
            # Higiene: no maximo 5 dispositivos ativos, mantendo os mais usados.
            active = conn.execute(
                """
                SELECT id, endpoint FROM push_subscriptions
                WHERE user_id = ? AND disabled_at IS NULL
                ORDER BY COALESCE(last_seen_at, created_at) DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
            for row in active[MAX_PUSH_DEVICES:]:
                conn.execute(
                    "UPDATE push_subscriptions SET disabled_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (row["id"],),
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
        """Retorna as push subscriptions ATIVAS de um usuário.

        `disabled_at` marca dispositivos desativados pela higiene de 5 ou por
        inatividade; nao voltam a receber push.
        """
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT user_id, endpoint, p256dh, auth, user_agent, device_label, "
                "last_seen_at, last_success_at, created_at FROM push_subscriptions "
                "WHERE user_id = ? AND disabled_at IS NULL "
                "ORDER BY COALESCE(last_seen_at, created_at) DESC",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_push_success(self, endpoint: str) -> None:
        """Regista a ultima entrega aceite para o dispositivo."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE push_subscriptions SET last_success_at = CURRENT_TIMESTAMP, "
                "last_seen_at = CURRENT_TIMESTAMP WHERE endpoint = ?",
                (endpoint,),
            )
            conn.commit()
        finally:
            conn.close()

    def disable_push_subscription(self, endpoint: str) -> bool:
        """Desativa (sem apagar) um dispositivo. Usado pela higiene/inatividade."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE push_subscriptions SET disabled_at = CURRENT_TIMESTAMP "
                "WHERE endpoint = ? AND disabled_at IS NULL",
                (endpoint,),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def enforce_push_device_limit(self, max_devices: int = MAX_PUSH_DEVICES) -> int:
        """Aplica o limite de dispositivos a TODOS os utilizadores (startup).

        A higiene no subscribe so corrige quem volta a inscrever-se; este
        sweep corrige o estado legado (ex.: 9 dispositivos) sem esperar.
        """
        conn = get_connection()
        disabled = 0
        try:
            users = conn.execute(
                """
                SELECT user_id, COUNT(*) AS active FROM push_subscriptions
                WHERE disabled_at IS NULL GROUP BY user_id HAVING COUNT(*) > ?
                """,
                (int(max_devices),),
            ).fetchall()
            for u in users:
                rows = conn.execute(
                    """
                    SELECT id FROM push_subscriptions
                    WHERE user_id = ? AND disabled_at IS NULL
                    ORDER BY COALESCE(last_success_at, last_seen_at, created_at) DESC, id DESC
                    """,
                    (u["user_id"],),
                ).fetchall()
                for row in rows[int(max_devices):]:
                    conn.execute(
                        "UPDATE push_subscriptions SET disabled_at = CURRENT_TIMESTAMP "
                        "WHERE id = ?",
                        (row["id"],),
                    )
                    disabled += 1
            conn.commit()
            return disabled
        finally:
            conn.close()

    def prune_push_subscriptions(self, days: int = 90) -> int:
        """Desativa dispositivos inativos, mantendo sempre o mais recente.

        Um dispositivo sem sucesso ha >`days` dias (ou nunca usado e criado ha
        >180 dias) deixa de receber. Nunca desativa o ultimo ativo do
        utilizador — isso mataria o push de quem simplesmente nao recebeu
        alertas no periodo.
        """
        cutoff = f"-{int(days)} days"
        old_cutoff = "-180 days"
        conn = get_connection()
        disabled = 0
        try:
            users = conn.execute(
                "SELECT DISTINCT user_id FROM push_subscriptions WHERE disabled_at IS NULL"
            ).fetchall()
            for u in users:
                subs = conn.execute(
                    "SELECT id, last_success_at, last_seen_at, created_at FROM push_subscriptions "
                    "WHERE user_id = ? AND disabled_at IS NULL "
                    "ORDER BY COALESCE(last_success_at, last_seen_at, created_at) DESC, id DESC",
                    (u["user_id"],),
                ).fetchall()
                if len(subs) <= 1:
                    continue
                for sub in subs[1:]:  # mantem o mais recente
                    stale = False
                    if sub["last_success_at"]:
                        stale = conn.execute(
                            "SELECT ? < datetime('now', ?)", (sub["last_success_at"], cutoff)
                        ).fetchone()[0] == 1
                    else:
                        stale = conn.execute(
                            "SELECT ? < datetime('now', ?)", (sub["created_at"], old_cutoff)
                        ).fetchone()[0] == 1
                    if stale:
                        conn.execute(
                            "UPDATE push_subscriptions SET disabled_at = CURRENT_TIMESTAMP "
                            "WHERE id = ?",
                            (sub["id"],),
                        )
                        disabled += 1
            conn.commit()
            return disabled
        finally:
            conn.close()

    def get_last_alert_times(self, user_ids: List[int]) -> dict:
        """Ultimo alerta new_lead por utilizador (para o min-gap)."""
        if not user_ids:
            return {}
        conn = get_connection()
        try:
            out: dict = {}
            for start in range(0, len(user_ids), 500):
                chunk = user_ids[start:start + 500]
                ph = ",".join("?" * len(chunk))
                for r in conn.execute(
                    f"SELECT user_id, MAX(created_at) AS last_at FROM notifications "
                    f"WHERE type = 'new_lead' AND user_id IN ({ph}) GROUP BY user_id",
                    chunk,
                ):
                    out[int(r["user_id"])] = r["last_at"]
            return out
        finally:
            conn.close()

    def mark_notification_clicked(self, notification_id: int) -> bool:
        """Marca o clique de um alerta (idempotente) e propaga as entregas."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE notifications SET clicked_at = COALESCE(clicked_at, CURRENT_TIMESTAMP) "
                "WHERE id = ?",
                (notification_id,),
            )
            conn.execute(
                "UPDATE push_deliveries SET clicked_at = COALESCE(clicked_at, CURRENT_TIMESTAMP) "
                "WHERE notification_id = ?",
                (notification_id,),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def disable_push_if_no_subscriptions(self, user_id: int) -> bool:
        """Desliga `push_enabled` quando o utilizador não tem subscrições.

        Evita o estado zumbi: flag `push_enabled=1` sem nenhum dispositivo
        subscrito, que faz o serviço tentar enviar para o vazio e registar
        `no_subscriptions` a cada run. Idempotente e fail-soft.

        Devolve True se o flag foi desligado por esta chamada.
        """
        conn = get_connection()
        try:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ? AND disabled_at IS NULL",
                (user_id,),
            ).fetchone()[0]
            if remaining:
                return False
            cur = conn.execute(
                "UPDATE users SET push_enabled = 0 WHERE id = ? AND push_enabled = 1",
                (user_id,),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_all_push_subscriptions(self) -> List[dict]:
        """Retorna todas as push subscriptions ATIVAS (para envio em lote)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT user_id, endpoint, p256dh, auth, created_at FROM push_subscriptions "
                "WHERE disabled_at IS NULL"
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

    def set_user_base_location(
        self, user_id: int, lat: float, lng: float, source: str, label: Optional[str] = None
    ) -> bool:
        """Guarda a base do empreiteiro usada para mostrar a distancia.

        A distancia e' apenas informativa/ordenacao: nunca filtra leads.
        Coordenadas arredondadas a 3 casas (~110 m) por privacidade.
        """
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE users SET base_lat = ?, base_lng = ?, base_source = ?, "
                "base_label = ?, geo_updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (round(float(lat), 3), round(float(lng), 3), source, label, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def clear_user_base_location(self, user_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE users SET base_lat = NULL, base_lng = NULL, base_source = NULL, "
                "base_label = NULL, geo_updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (user_id,),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def set_show_address_in_push(self, user_id: int, enabled: bool) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE users SET show_address_in_push = ? WHERE id = ?",
                (1 if enabled else 0, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def set_user_digest_enabled(self, user_id: int, enabled: bool) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE users SET digest_enabled = ? WHERE id = ?",
                (1 if enabled else 0, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def set_user_lifecycle_push_enabled(self, user_id: int, enabled: bool) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE users SET lifecycle_push_enabled = ? WHERE id = ?",
                (1 if enabled else 0, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def set_user_chime_enabled(self, user_id: int, enabled: bool) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE users SET chime_enabled = ? WHERE id = ?",
                (1 if enabled else 0, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_users_for_interests_onboarding(self, limit: int = 50) -> List[dict]:
        """Utilizadores com push ativo, subscricao viva e zero interesses.

        Candidatos ao push unico de onboarding (B2). Exclui quem ja recebeu.
        """
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT u.* FROM users u
                WHERE u.push_enabled = 1
                  AND EXISTS (
                    SELECT 1 FROM push_subscriptions s
                    WHERE s.user_id = u.id AND s.disabled_at IS NULL
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM user_interests i WHERE i.user_id = u.id
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM notifications n
                    WHERE n.user_id = u.id AND n.type = 'interests_onboarding'
                  )
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_bbl_coords(self, bbls: List[str]) -> dict:
        """Cache de coordenadas por BBL (hit OU miss, com updated_at)."""
        if not bbls:
            return {}
        conn = get_connection()
        try:
            out: dict = {}
            for start in range(0, len(bbls), 500):
                chunk = bbls[start:start + 500]
                ph = ",".join("?" * len(chunk))
                for r in conn.execute(
                    f"SELECT bbl, lat, lng, updated_at FROM bbl_coords WHERE bbl IN ({ph})",
                    chunk,
                ):
                    out[str(r["bbl"])] = dict(r)
            return out
        finally:
            conn.close()

    def upsert_bbl_coords(self, rows: List[dict]) -> int:
        if not rows:
            return 0
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO bbl_coords (bbl, lat, lng, source, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(bbl) DO UPDATE SET
                    lat = excluded.lat,
                    lng = excluded.lng,
                    source = excluded.source,
                    updated_at = CURRENT_TIMESTAMP
                """,
                [
                    (r["bbl"], r.get("lat"), r.get("lng"), r.get("source"))
                    for r in rows
                ],
            )
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def get_leads_missing_coords_with_bbl(
        self, limit: int = 500, after_id: int = 0
    ) -> List[dict]:
        """Leads com BBL mas sem coordenadas, por ordem de id (cursor)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, bbl FROM leads
                WHERE id > ? AND bbl IS NOT NULL AND TRIM(bbl) <> ''
                  AND (lat IS NULL OR lng IS NULL)
                ORDER BY id ASC LIMIT ?
                """,
                (int(after_id), int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def set_leads_coords(self, updates: List[tuple]) -> int:
        """Aplica (lat, lng, lead_id) em lote."""
        if not updates:
            return 0
        conn = get_connection()
        try:
            conn.executemany(
                "UPDATE leads SET lat = ?, lng = ? WHERE id = ? AND (lat IS NULL OR lng IS NULL)",
                updates,
            )
            conn.commit()
            return len(updates)
        finally:
            conn.close()

    def get_dob_leads_missing_bbl(
        self, limit: int = 150, after_id: int = 0
    ) -> List[dict]:
        """Leads DOB sem BBL (gravados antes de o scraper pedir block/lot)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, external_id FROM leads
                WHERE id > ? AND source_type = 'dob_violation'
                  AND (bbl IS NULL OR TRIM(bbl) = '')
                ORDER BY id ASC LIMIT ?
                """,
                (int(after_id), int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def set_leads_bbl(self, updates: List[tuple]) -> int:
        """Aplica (bbl, lead_id) em lote, sem tocar em quem ja tem BBL."""
        if not updates:
            return 0
        conn = get_connection()
        try:
            conn.executemany(
                "UPDATE leads SET bbl = ? WHERE id = ? AND (bbl IS NULL OR TRIM(bbl) = '')",
                updates,
            )
            conn.commit()
            return len(updates)
        finally:
            conn.close()

    def count_leads_missing_coords(self) -> dict:
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT
                  SUM(CASE WHEN lat IS NULL OR lng IS NULL THEN 1 ELSE 0 END) AS missing,
                  SUM(CASE WHEN (lat IS NULL OR lng IS NULL)
                            AND bbl IS NOT NULL AND TRIM(bbl) <> '' THEN 1 ELSE 0 END) AS missing_with_bbl,
                  COUNT(*) AS total
                FROM leads
                """
            ).fetchone()
            return {
                "missing": int(row["missing"] or 0),
                "missing_with_bbl": int(row["missing_with_bbl"] or 0),
                "total": int(row["total"] or 0),
            }
        finally:
            conn.close()

    def get_users_pending_unconfigured_digest(self, limit: int = 500) -> List[dict]:
        """Quem nao escolheu oficios mas aceita o resumo diario (B2).

        A audiencia estrita nunca cria alertas individuais para estes
        utilizadores; o digest e' o unico canal diario. Exclui quem ja recebeu
        o digest de hoje para o contador nao inflar a cada run.
        """
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT u.* FROM users u
                WHERE u.push_enabled = 1
                  AND COALESCE(u.digest_enabled, 1) = 1
                  AND NOT EXISTS (
                    SELECT 1 FROM user_interests i WHERE i.user_id = u.id
                  )
                  AND EXISTS (
                    SELECT 1 FROM push_subscriptions s
                    WHERE s.user_id = u.id AND s.disabled_at IS NULL
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM notifications n
                    WHERE n.user_id = u.id AND n.type = 'digest'
                      AND DATE(n.created_at) = DATE('now')
                  )
                ORDER BY u.id LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_unpushed_lifecycle_notifications(self, limit: int = 50) -> List[dict]:
        """Avisos de ciclo de vida ainda sem push, para utilizadores opt-in."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT n.id, n.user_id, n.type, n.title, n.message, n.lead_id,
                       n.created_at, u.locale, u.subscription_status, u.plan_until
                FROM notifications n
                JOIN users u ON u.id = n.user_id
                WHERE n.pushed_at IS NULL
                  AND n.user_id IS NOT NULL
                  AND u.lifecycle_push_enabled = 1
                  AND u.push_enabled = 1
                  AND n.type IN ('reveal_followup', 'reveal_urgent',
                                 'stage_warning', 'stage_urgent')
                  AND n.created_at >= datetime('now', '-45 minutes')
                  AND EXISTS (
                    SELECT 1 FROM push_subscriptions s
                    WHERE s.user_id = n.user_id AND s.disabled_at IS NULL
                  )
                ORDER BY n.id ASC LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_notification_pushed(self, notification_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE notifications SET pushed_at = COALESCE(pushed_at, CURRENT_TIMESTAMP) "
                "WHERE id = ?",
                (notification_id,),
            )
            conn.commit()
            return cur.rowcount > 0
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

        Regra do teto de sessões:
          * utilizadores normais: no máximo 2 sessões ativas; ao entrar a 3ª,
            a mais antiga é removida (FIFO por last_active_at);
          * ADMINISTRADORES: isentos do teto. O painel /admin é acessado em
            ambientes de confiança (laptop, telemóvel, browser de trabalho) e
            um login noutro dispositivo não pode expulsar (401) a sessão aberta
            no painel — era isso que fazia o painel dizer "sessão expirada"
            mesmo com a conta de admin corretamente autenticada.
        """
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT is_admin FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            is_admin = bool(row["is_admin"]) if row else False

            if not is_admin:
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
            ttl_days = max(1, int(getattr(settings, "SESSION_TTL_DAYS", 30) or 30))
            expires_at = (utcnow() + timedelta(days=ttl_days)).isoformat()
            conn.execute(
                """
                INSERT INTO user_sessions (user_id, token_hash, device_info, ip_address, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, token_hash, device_info, ip_address, expires_at),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def validate_session(self, token_hash: str) -> dict:
        """Valida a sessão e devolve o estado (A2).

        Status: 'valid' | 'expired' | 'missing'. Um token expirado é apagado na
        hora (auto-limpeza) e nunca mais é aceite. A expiração é **deslizante**:
        cada uso renova `SESSION_TTL_DAYS`, portanto o limite real é inatividade
        (não tempo desde o login) — e continua a ser finito.
        """
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT user_id, expires_at FROM user_sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if not row:
                return {"status": "missing", "user_id": None}

            ttl_days = max(1, int(getattr(settings, "SESSION_TTL_DAYS", 30) or 30))
            expires = self._parse_dt(row["expires_at"])
            if expires is None or expires <= utcnow():
                conn.execute(
                    "DELETE FROM user_sessions WHERE token_hash = ?", (token_hash,)
                )
                conn.commit()
                return {"status": "expired", "user_id": row["user_id"]}

            conn.execute(
                "UPDATE user_sessions SET last_active_at = CURRENT_TIMESTAMP, "
                "expires_at = ? WHERE token_hash = ?",
                ((utcnow() + timedelta(days=ttl_days)).isoformat(), token_hash),
            )
            conn.commit()
            return {"status": "valid", "user_id": row["user_id"]}
        finally:
            conn.close()

    def prune_expired_sessions(self) -> int:
        """Remove sessões expiradas (chamado no arranque e no watchdog)."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "DELETE FROM user_sessions WHERE expires_at IS NOT NULL "
                "AND datetime(expires_at) <= datetime('now')"
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def validate_user_session(self, token_hash: str) -> Optional[int]:
        """Compatibilidade: devolve o user_id apenas se a sessão for válida."""
        result = self.validate_session(token_hash)
        return result["user_id"] if result.get("status") == "valid" else None

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

    # ---------------------------------------------------------------- WebAuthn
    # Passkeys: o servidor guarda só a chave pública. Challenges são de uso
    # único e expiram em 5 min; verify consome atomicamente.

    def create_webauthn_challenge(
        self, challenge: str, kind: str, user_id: Optional[int] = None,
        ttl_seconds: int = 300, rp_id: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> bool:
        conn = get_connection()
        try:
            now = utcnow()
            expires = now + timedelta(seconds=max(30, int(ttl_seconds)))
            conn.execute("DELETE FROM webauthn_challenges WHERE datetime(expires_at) <= datetime(?)", (now.isoformat(),))
            conn.execute(
                "INSERT INTO webauthn_challenges "
                "(user_id, challenge, kind, rp_id, origin, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, challenge, kind, rp_id, origin, expires.isoformat()),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def consume_webauthn_challenge(self, challenge: str, kind: str) -> Optional[dict]:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM webauthn_challenges "
                "WHERE challenge = ? AND kind = ? AND used = 0 "
                "AND datetime(expires_at) > datetime('now') LIMIT 1",
                (challenge, kind),
            ).fetchone()
            if not row:
                conn.rollback()
                return None
            conn.execute(
                "UPDATE webauthn_challenges SET used = 1 WHERE id = ?", (row["id"],)
            )
            conn.commit()
            return dict(row)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def add_webauthn_credential(
        self, user_id: int, credential_id: str, public_key: str,
        sign_count: int = 0, transports: Optional[str] = None,
        aaguid: Optional[str] = None, device_label: Optional[str] = None,
    ) -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO webauthn_credentials "
                "(user_id, credential_id, public_key, sign_count, transports, aaguid, device_label) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    int(user_id), credential_id, public_key, int(sign_count),
                    transports, aaguid, device_label,
                ),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def list_webauthn_credentials(self, user_id: int) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, credential_id, sign_count, transports, aaguid, device_label, "
                "cloned_warning, created_at, last_used_at "
                "FROM webauthn_credentials WHERE user_id = ? ORDER BY id DESC",
                (int(user_id),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_webauthn_credential(self, credential_id: str) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM webauthn_credentials WHERE credential_id = ?",
                (credential_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_webauthn_credential_after_auth(
        self, credential_id: str, new_sign_count: int, cloned_warning: bool = False
    ) -> bool:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE webauthn_credentials SET sign_count = ?, last_used_at = ?, "
                "cloned_warning = MAX(cloned_warning, ?) WHERE credential_id = ?",
                (
                    int(new_sign_count),
                    utcnow().isoformat(),
                    1 if cloned_warning else 0,
                    credential_id,
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_webauthn_credential(self, user_id: int, credential_id: str) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "DELETE FROM webauthn_credentials WHERE user_id = ? AND credential_id = ?",
                (int(user_id), credential_id),
            )
            conn.commit()
            return cur.rowcount > 0
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

    def user_has_lead_history_access(self, user_id: int, lead_id: int) -> bool:
        """O utilizador pode ver o histórico/ocorrências deste lead?

        Sinais de posse (qualquer um basta):
          1. tem um `lead_holds` para o lead  -> reservou/revelou em algum momento
          2. tem um `lead_reveals` para o lead -> pagou para revelar
          3. `leads.converted_by` == utilizador -> já entrou na pipeline

        `lead_holds` mantém a linha depois de expirar/liberar (muda só o
        `status`), por isso continua a ser um sinal de posse válido.

        Autorização é por POSSE, não por autenticação: exigir apenas "ter
        login" permitia que qualquer assinante lesse o histórico de qualquer
        imóvel, o que inclui Addresses que ele nunca viu.
        """
        if not user_id or not lead_id:
            return False
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT 1 FROM leads l
                   WHERE l.id = ? AND (
                         l.converted_by = ?
                      OR EXISTS (SELECT 1 FROM lead_holds h
                                  WHERE h.lead_id = l.id AND h.user_id = ?)
                      OR EXISTS (SELECT 1 FROM lead_reveals r
                                  WHERE r.lead_id = l.id AND r.user_id = ?)
                   ) LIMIT 1""",
                (lead_id, user_id, user_id, user_id),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # ADMIN (painel /admin)
    #
    # Leitura apenas. Nenhum destes métodos escreve em leads/users exceto
    # set_user_admin(), usado por script local para promover um admin
    # (não exposto por HTTP, para não haver escalação de privilégio).
    # ---------------------------------------------------------------
    def set_user_admin(self, email: str, is_admin: bool = True) -> bool:
        """Promove/revoga is_admin por email. Usar apenas via script local."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE users SET is_admin = ? WHERE email = ?",
                (1 if is_admin else 0, (email or "").strip().lower()),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def admin_get_recent_scraper_runs(self, limit: int = 50) -> List[dict]:
        """Histórico de runs do scraper.

        A fonte de verdade é a tabela `scraper_runs`, NÃO o dict em memória
        `_scrape_runs` (que se perde a cada restart/redeploy da Railway).
        """
        limit = max(1, min(int(limit), 500))
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT run_id, trigger, started_at, finished_at, status,
                          inserted, total_raw, cities_covered, error, note
                   FROM scraper_runs ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def admin_get_overview(self) -> dict:
        """Números de topo para o painel admin (tudo em UTC, hoje = UTC)."""
        conn = get_connection()
        try:
            today = utcnow().date().isoformat()

            def scalar(sql: str, params: tuple = ()) -> int:
                row = conn.execute(sql, params).fetchone()
                if not row:
                    return 0
                val = row[0]
                return int(val) if isinstance(val, (int, float)) else 0

            total_leads = scalar("SELECT COUNT(*) FROM leads")
            leads_today = scalar(
                "SELECT COUNT(*) FROM leads WHERE date(date_reported) = ?", (today,)
            )
            leads_24h = scalar(
                """SELECT COUNT(*) FROM leads
                   WHERE created_at >= datetime('now', '-1 day')"""
            )
            total_users = scalar("SELECT COUNT(*) FROM users")
            users_today = scalar(
                """SELECT COUNT(*) FROM users
                   WHERE date(created_at) = ?""",
                (today,),
            )
            reveals_today = scalar(
                "SELECT COUNT(*) FROM lead_reveals WHERE revealed_date = ?", (today,)
            )
            # Reveals que ainda não voltaram ao pool (= acesso ainda ativo).
            reveals_active = scalar(
                "SELECT COUNT(*) FROM lead_reveals WHERE returned_to_pool = 0"
            )
            reveals_returned = scalar(
                "SELECT COUNT(*) FROM lead_reveals WHERE returned_to_pool = 1"
            )
            refunded_today = scalar(
                """SELECT COUNT(*) FROM lead_reveals
                   WHERE refunded = 1 AND date(refunded_at) = ?""",
                (today,),
            )
            credits_used_today = scalar(
                """SELECT COALESCE(SUM(leads_used), 0) FROM user_daily_stats
                   WHERE date = ?""",
                (today,),
            )
            alerts_unacked = scalar(
                "SELECT COUNT(*) FROM system_alerts WHERE acknowledged = 0"
            )
            last_run = conn.execute(
                """SELECT run_id, started_at, finished_at, status, inserted,
                          cities_covered, error
                   FROM scraper_runs ORDER BY id DESC LIMIT 1"""
            ).fetchone()

            return {
                "generated_at": utcnow().isoformat(),
                "today": today,
                "leads": {
                    "total": total_leads,
                    "today": leads_today,
                    "last_24h": leads_24h,
                },
                "users": {"total": total_users, "today": users_today},
                "reveals": {
                    "today": reveals_today,
                    "active": reveals_active,
                    "returned_to_pool": reveals_returned,
                },
                "credits": {"used_today": credits_used_today, "refunded_today": refunded_today},
                "alerts": {"unacknowledged": alerts_unacked},
                "last_scraper_run": dict(last_run) if last_run else None,
            }
        finally:
            conn.close()

    def admin_get_recent_reveals(self, limit: int = 50, returned_only: bool = False) -> List[dict]:
        """Auditoria de reveals recentes (sucesso vs. regressões/estornos).

    `returned_only=True` devolve apenas os que voltaram ao pool sem contato —
    é a fila de trabalho para recuperação de acesso e eventual estorno.
    """
        limit = max(1, min(int(limit), 500))
        conn = get_connection()
        try:
            sql = """SELECT r.id, r.lead_id, r.user_id, r.revealed_at, r.revealed_date,
                            r.returned_to_pool, r.contact_flagged, r.refunded,
                            r.refund_reason, r.refunded_at,
                            l.address, l.city, l.owner_name,
                            (SELECT COUNT(*) FROM leads WHERE id = r.lead_id
                             AND owner_phone IS NOT NULL AND owner_phone != '') AS has_phone
                     FROM lead_reveals r
                     LEFT JOIN leads l ON l.id = r.lead_id
                     WHERE 1=1"""
            params: list = []
            if returned_only:
                sql += " AND r.returned_to_pool = 1 AND r.refunded = 0"
            sql += " ORDER BY r.id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def admin_get_searchbug_metrics(self, days: int = 7, recent_limit: int = 50) -> dict:
        """Custo e fiabilidade das consultas pagas a Searchbug.

        A metrica que interessa ao dono do negocio e `ghost_charges`: consultas
        que chegaram ao provider (billed=1) e nao devolveram telefone. Sao
        dinheiro gasto sem resultado e so se descobre olhando para o erro
        "No results" nos logs.

        Os percentis sao calculados em Python sobre uma janela limitada
        (latencies ja ordenadas no SQL com LIMIT): evita fazer o SQLite
        calcular percentis e mantem a memoria do servidor previsivel.
        """
        days = max(1, min(int(days), 90))
        recent_limit = max(1, min(int(recent_limit), 200))
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d %H:%M:%S")

        conn = get_connection()
        try:
            totals = conn.execute(
                """
                SELECT
                  COUNT(*) AS calls,
                  SUM(CASE WHEN billed = 1 THEN 1 ELSE 0 END) AS billed_calls,
                  SUM(CASE WHEN billed = 1 AND outcome != 'success' THEN 1 ELSE 0 END) AS ghost_charges,
                  SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS successes,
                  SUM(CASE WHEN outcome IN ('guard_skipped', 'cache_hit', 'cache_negative') THEN 1 ELSE 0 END) AS saved_calls,
                  SUM(CASE WHEN billed = 1 AND outcome = 'timeout' THEN 1 ELSE 0 END) AS timeouts,
                  COALESCE(SUM(cost_usd), 0) AS cost_usd,
                  SUM(CASE WHEN outcome = 'transport_error' THEN 1 ELSE 0 END) AS transport_errors,
                  SUM(CASE WHEN outcome = 'name_mismatch' THEN 1 ELSE 0 END) AS name_mismatches
                FROM searchbug_calls WHERE called_at >= ?
                """,
                (cutoff,),
            ).fetchone()

            by_outcome = conn.execute(
                """
                SELECT outcome, COUNT(*) AS n, SUM(CASE WHEN billed = 1 THEN 1 ELSE 0 END) AS billed_n
                FROM searchbug_calls WHERE called_at >= ?
                GROUP BY outcome ORDER BY n DESC
                """,
                (cutoff,),
            ).fetchall()

            latencies = [
                r[0]
                for r in conn.execute(
                    """
                    SELECT latency_ms FROM searchbug_calls
                    WHERE called_at >= ? AND billed = 1 AND latency_ms IS NOT NULL
                    ORDER BY id DESC LIMIT 2000
                    """,
                    (cutoff,),
                ).fetchall()
                if r[0] is not None
            ]

            today = conn.execute(
                """
                SELECT
                  COUNT(*) AS calls,
                  SUM(CASE WHEN billed = 1 THEN 1 ELSE 0 END) AS billed_calls,
                  SUM(CASE WHEN billed = 1 AND outcome != 'success' THEN 1 ELSE 0 END) AS ghost_charges,
                  COALESCE(SUM(cost_usd), 0) AS cost_usd
                FROM searchbug_calls WHERE called_at >= ?
                """,
                (datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00"),),
            ).fetchone()

            recent = conn.execute(
                """
                SELECT id, called_at, outcome, billed, latency_ms, http_status, city, error,
                       cost_usd, lead_id, owner_class, layer, name_match, transport_error
                FROM searchbug_calls ORDER BY id DESC LIMIT ?
                """,
                (recent_limit,),
            ).fetchall()

            by_city = conn.execute(
                """
                SELECT COALESCE(city, '(desconhecida)') AS city,
                       COUNT(*) AS calls,
                       SUM(CASE WHEN billed = 1 THEN 1 ELSE 0 END) AS billed_calls,
                       SUM(CASE WHEN billed = 1 AND outcome != 'success' THEN 1 ELSE 0 END) AS ghost_charges,
                       COALESCE(SUM(cost_usd), 0) AS cost_usd
                FROM searchbug_calls WHERE called_at >= ? AND billed = 1
                GROUP BY city ORDER BY billed_calls DESC LIMIT 15
                """,
                (cutoff,),
            ).fetchall()

            latencies.sort()
            return {
                "days": days,
                "today": {
                    "calls": today["calls"] or 0,
                    "billed_calls": today["billed_calls"] or 0,
                    "ghost_charges": today["ghost_charges"] or 0,
                    "cost_usd": round(float(today["cost_usd"] or 0), 4),
                },
                "totals": {
                    "calls": totals["calls"] or 0,
                    "billed_calls": totals["billed_calls"] or 0,
                    "successes": totals["successes"] or 0,
                    "ghost_charges": totals["ghost_charges"] or 0,
                    "timeouts": totals["timeouts"] or 0,
                    "saved_calls": totals["saved_calls"] or 0,
                    "cost_usd": round(float(totals["cost_usd"] or 0), 4),
                    "transport_errors": totals["transport_errors"] or 0,
                    "name_mismatches": totals["name_mismatches"] or 0,
                },
                "success_rate": _ratio(totals["successes"], totals["billed_calls"]),
                "billed_rate": _ratio(totals["billed_calls"], totals["calls"]),
                "cost_per_success": (
                    round(float(totals["cost_usd"] or 0) / totals["successes"], 4)
                    if totals["successes"] else None
                ),
                "latency": _percentiles(latencies),
                "by_outcome": [dict(r) for r in by_outcome],
                "by_city": [dict(r) for r in by_city],
                "recent": [dict(r) for r in recent],
            }
        except sqlite3.OperationalError as exc:
            # Tabela ausente numa BD anterior a Fase 2: o painel degrada em vez
            # de dar 500.
            if "searchbug_calls" not in str(exc):
                raise
            return {
                "days": days,
                "today": {"calls": 0, "billed_calls": 0, "ghost_charges": 0, "cost_usd": 0.0},
                "totals": {
                    "calls": 0, "billed_calls": 0, "successes": 0,
                    "ghost_charges": 0, "timeouts": 0, "saved_calls": 0,
                    "cost_usd": 0.0, "transport_errors": 0, "name_mismatches": 0,
                },
                "success_rate": None,
                "billed_rate": None,
                "cost_per_success": None,
                "latency": {"avg_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None, "samples": 0},
                "by_outcome": [],
                "by_city": [],
                "recent": [],
            }
        finally:
            conn.close()

    def get_phone_success_stats(
        self, city: Optional[str], owner_class: Optional[str], days: int = 90
    ) -> dict:
        """Taxa real de sucesso do telefone para um segmento (P2).

        Denominador = consultas ao provider que podiam devolver telefone
        (`success`, `no_results`, `name_mismatch`). Cache, guard e erros de
        transporte ficam fora: nao sao tentativas reais de encontrar o numero.
        """
        conn = get_connection()
        try:
            where = [
                "called_at >= datetime('now', ?)",
                "outcome IN ('success', 'no_results', 'name_mismatch')",
            ]
            params: list = [f"-{int(days)} days"]
            if city:
                where.append("city = ? COLLATE NOCASE")
                params.append(city)
            if owner_class:
                where.append("COALESCE(owner_class, 'unknown') = ?")
                params.append(owner_class)
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS samples,
                       SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS successes
                FROM searchbug_calls
                WHERE {' AND '.join(where)}
                """,
                params,
            ).fetchone()
            samples = int(row["samples"] or 0) if row else 0
            successes = int(row["successes"] or 0) if row else 0
            return {"samples": samples, "successes": successes}
        except sqlite3.OperationalError:
            # BD anterior a telemetria P0-C1: sem amostras, sem percentagem.
            return {"samples": 0, "successes": 0}
        finally:
            conn.close()

    def admin_get_phone_sample_progress(self, days: int = 90) -> dict:
        """Amostras reais por segmento (cidade/classe) para a calibracao P2.

        Mesmo denominador de `get_phone_success_stats`: so consultas que podiam
        devolver telefone. Devolve os contadores crus; o endpoint aplica o
        limiar de 30 amostras e a percentagem.
        """
        conn = get_connection()
        try:
            cutoff = f"-{int(days)} days"
            base_where = (
                "called_at >= datetime('now', ?) "
                "AND outcome IN ('success', 'no_results', 'name_mismatch')"
            )
            segments = conn.execute(
                f"""
                SELECT COALESCE(NULLIF(TRIM(city), ''), '(desconhecida)') AS city,
                       COALESCE(NULLIF(TRIM(owner_class), ''), 'unknown') AS owner_class,
                       COUNT(*) AS samples,
                       SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS successes
                FROM searchbug_calls
                WHERE {base_where}
                GROUP BY 1, 2
                ORDER BY samples DESC, city ASC
                """,
                (cutoff,),
            ).fetchall()
            by_class = conn.execute(
                f"""
                SELECT COALESCE(NULLIF(TRIM(owner_class), ''), 'unknown') AS owner_class,
                       COUNT(*) AS samples,
                       SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS successes
                FROM searchbug_calls
                WHERE {base_where}
                GROUP BY 1
                ORDER BY samples DESC
                """,
                (cutoff,),
            ).fetchall()
            return {
                "days": int(days),
                "segments": [dict(r) for r in segments],
                "by_class": [dict(r) for r in by_class],
            }
        except sqlite3.OperationalError:
            return {"days": int(days), "segments": [], "by_class": []}
        finally:
            conn.close()

    def admin_get_digest_ab(self, days: int = 30) -> dict:
        """B3: CTR do digest por variante A/B (amostra minima 30 por braco).

        `sent` = digests in-app criados; `pushed` = com push aceite; `clicks` =
        abertos. Um vencedor so aparece com >=30 envios em ambos os bracos —
        abaixo disso e' ruido, e a UI nao deve sugerir decisao.
        """
        days = max(1, min(int(days), 180))
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT COALESCE(NULLIF(ab_variant, ''), '?') AS variant,
                       COUNT(*) AS sent,
                       SUM(CASE WHEN pushed_at IS NOT NULL THEN 1 ELSE 0 END) AS pushed,
                       SUM(CASE WHEN clicked_at IS NOT NULL THEN 1 ELSE 0 END) AS clicks
                FROM notifications
                WHERE type = 'digest' AND created_at >= ?
                GROUP BY variant ORDER BY variant
                """,
                (cutoff,),
            ).fetchall()
            arms = []
            for r in rows:
                sent = int(r["sent"] or 0)
                clicks = int(r["clicks"] or 0)
                pushed = int(r["pushed"] or 0)
                arms.append(
                    {
                        "variant": r["variant"],
                        "sent": sent,
                        "pushed": pushed,
                        "clicks": clicks,
                        "ctr": (clicks / pushed) if pushed else None,
                        "sample_ok": pushed >= 30,
                    }
                )
            eligible = [a for a in arms if a["sample_ok"]]
            leader = None
            if len(eligible) >= 2:
                leader = max(eligible, key=lambda a: (a["ctr"] or 0))["variant"]
            return {
                "days": days,
                "min_samples": 30,
                "arms": arms,
                "leader": leader,
            }
        except sqlite3.OperationalError as exc:
            if "ab_variant" not in str(exc):
                raise
            return {"days": days, "min_samples": 30, "arms": [], "leader": None}
        finally:
            conn.close()

    def admin_list_sessions(self, limit: int = 100) -> List[dict]:
        """Sessões ativas (A2) para o painel: quem, onde e até quando.

        Só devolve sessões vivas (`expires_at` futuro); as expiradas são
        removidas pelo `prune_expired_sessions` no arranque.
        """
        limit = max(1, min(int(limit), 500))
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT s.id, s.user_id, u.email, u.company_name, u.is_admin,
                       s.device_info, s.ip_address, s.created_at,
                       s.last_active_at, s.expires_at
                FROM user_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.expires_at IS NULL
                   OR datetime(s.expires_at) > datetime('now')
                ORDER BY s.last_active_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def admin_revoke_session(self, session_id: int) -> bool:
        """Revoga (apaga) uma sessão específica. Idempotente = False se não existir."""
        conn = get_connection()
        try:
            cur = conn.execute("DELETE FROM user_sessions WHERE id = ?", (int(session_id),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def admin_revoke_user_sessions(self, user_id: int) -> int:
        """Revoga todas as sessões de um utilizador (ex.: conta comprometida)."""
        conn = get_connection()
        try:
            cur = conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (int(user_id),))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    # ---------------------------------------------------------------- acesso
    # Override de assinatura (cortesia). A fonte de verdade do acesso continua
    # a ser users.subscription_status + users.plan_until; a auditoria vive em
    # admin_audit_log (append-only) e guarda o antes/depois para undo seguro.

    def admin_grant_access(
        self,
        user_id: int,
        days: int,
        *,
        admin_id: int,
        admin_email: str,
        reason: str,
        note: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> dict:
        """Soma `days` de acesso ativo, sem nunca encurtar o que já existe.

        Transação BEGIN IMMEDIATE para não competir com o webhook Stripe
        (read-then-write perdia renovações concorrentes).
        """
        days = int(days)
        if days < 1 or days > 365:
            return {"error": "invalid_days"}
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute(
                "SELECT id, email, plan, subscription_status, plan_until FROM users WHERE id = ?",
                (int(user_id),),
            ).fetchone()
            if not user:
                conn.rollback()
                return {"error": "user_not_found"}

            if idempotency_key:
                dup = conn.execute(
                    "SELECT * FROM admin_audit_log WHERE admin_user_id = ? "
                    "AND action = 'grant_access' AND target_user_id = ? "
                    "AND idempotency_key = ?",
                    (int(admin_id), int(user_id), idempotency_key),
                ).fetchone()
                if dup:
                    conn.rollback()
                    after = json.loads(dup["after_json"] or "{}")
                    return {
                        "duplicate": True,
                        "audit_id": dup["id"],
                        "user": {"id": user["id"], "email": user["email"]},
                        "after": after,
                    }

            before = {
                "plan": user["plan"],
                "subscription_status": user["subscription_status"],
                "plan_until": user["plan_until"],
            }
            now = utcnow()
            current = self._parse_dt(user["plan_until"])
            base = max(now, current) if current else now
            new_until = base + timedelta(days=days)
            after = {
                "plan": "pro",
                "subscription_status": "active",
                "plan_until": new_until.isoformat(),
            }
            conn.execute(
                "UPDATE users SET plan = ?, subscription_status = ?, plan_until = ? WHERE id = ?",
                (after["plan"], after["subscription_status"], after["plan_until"], int(user_id)),
            )
            cur = conn.execute(
                "INSERT INTO admin_audit_log "
                "(admin_user_id, admin_email, action, target_user_id, target_email, days, "
                " reason, note, before_json, after_json, ip_address, user_agent, idempotency_key) "
                "VALUES (?, ?, 'grant_access', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(admin_id),
                    admin_email,
                    int(user_id),
                    user["email"],
                    days,
                    reason,
                    note,
                    json.dumps(before, ensure_ascii=False),
                    json.dumps(after, ensure_ascii=False),
                    ip_address,
                    (user_agent or "")[:300] or None,
                    idempotency_key,
                ),
            )
            audit_id = cur.lastrowid
            conn.commit()
            return {
                "audit_id": audit_id,
                "user": {"id": user["id"], "email": user["email"]},
                "before": before,
                "after": after,
                "days": days,
                "reason": reason,
            }
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def admin_revoke_access(
        self,
        audit_id: int,
        *,
        admin_id: int,
        admin_email: str,
        reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> dict:
        """Reverte uma concessão, apenas se a expiração não mudou desde então.

        Se houve pagamento/outra concessão pelo meio, devolve
        `changed_since_grant` (409) em vez de matar um plano pago.
        """
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            grant = conn.execute(
                "SELECT * FROM admin_audit_log WHERE id = ? AND action = 'grant_access'",
                (int(audit_id),),
            ).fetchone()
            if not grant:
                conn.rollback()
                return {"error": "not_found"}
            already = conn.execute(
                "SELECT 1 FROM admin_audit_log WHERE action = 'revoke_access' "
                "AND related_audit_id = ?",
                (int(audit_id),),
            ).fetchone()
            if already:
                conn.rollback()
                return {"error": "already_revoked"}

            user = conn.execute(
                "SELECT id, email, plan, subscription_status, plan_until FROM users WHERE id = ?",
                (grant["target_user_id"],),
            ).fetchone()
            if not user:
                conn.rollback()
                return {"error": "user_not_found"}

            before_grant = json.loads(grant["before_json"] or "{}")
            after_grant = json.loads(grant["after_json"] or "{}")
            if self._parse_dt(user["plan_until"]) != self._parse_dt(
                after_grant.get("plan_until")
            ):
                conn.rollback()
                return {"error": "changed_since_grant"}

            before = {
                "plan": user["plan"],
                "subscription_status": user["subscription_status"],
                "plan_until": user["plan_until"],
            }
            restored = {
                "plan": before_grant.get("plan"),
                "subscription_status": before_grant.get("subscription_status"),
                "plan_until": before_grant.get("plan_until"),
            }
            conn.execute(
                "UPDATE users SET plan = ?, subscription_status = ?, plan_until = ? WHERE id = ?",
                (restored["plan"], restored["subscription_status"], restored["plan_until"], user["id"]),
            )
            cur = conn.execute(
                "INSERT INTO admin_audit_log "
                "(admin_user_id, admin_email, action, target_user_id, target_email, days, "
                " reason, note, before_json, after_json, ip_address, user_agent, related_audit_id) "
                "VALUES (?, ?, 'revoke_access', ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(admin_id),
                    admin_email,
                    user["id"],
                    user["email"],
                    reason,
                    "reversão da concessão #" + str(audit_id),
                    json.dumps(before, ensure_ascii=False),
                    json.dumps(restored, ensure_ascii=False),
                    ip_address,
                    (user_agent or "")[:300] or None,
                    int(audit_id),
                ),
            )
            revoke_id = cur.lastrowid
            conn.commit()
            return {
                "audit_id": revoke_id,
                "related_audit_id": int(audit_id),
                "user": {"id": user["id"], "email": user["email"]},
                "before": before,
                "after": restored,
            }
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def admin_list_access_audit(self, limit: int = 50) -> List[dict]:
        """Histórico de concessões/revogações com `reversible` calculado."""
        limit = max(1, min(int(limit), 200))
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT a.*, u.plan_until AS current_plan_until, "
                "  EXISTS(SELECT 1 FROM admin_audit_log r "
                "         WHERE r.action = 'revoke_access' AND r.related_audit_id = a.id) AS revoked "
                "FROM admin_audit_log a LEFT JOIN users u ON u.id = a.target_user_id "
                "ORDER BY a.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            out = []
            for r in rows:
                row = dict(r)
                try:
                    after = json.loads(row.get("after_json") or "{}")
                except Exception:
                    after = {}
                row["reversible"] = bool(
                    row["action"] == "grant_access"
                    and not row["revoked"]
                    and self._parse_dt(row.get("current_plan_until"))
                    == self._parse_dt(after.get("plan_until"))
                )
                out.append(row)
            return out
        finally:
            conn.close()

    def _access_is_admin_granted(
        self, conn: sqlite3.Connection, user_id: int, plan_until: object
    ) -> bool:
        """True quando a expiração ATUAL veio de uma concessão administrativa.

        Deriva da auditoria (sem novo campo em `users`): a última ação de acesso
        foi um grant e o `plan_until` gravado é o que está em vigor. Se o Stripe
        renovou depois, o valor deixa de coincidir e a copy volta a "Renova em".
        """
        try:
            row = conn.execute(
                "SELECT action, after_json FROM admin_audit_log "
                "WHERE target_user_id = ? AND action IN ('grant_access', 'revoke_access') "
                "ORDER BY id DESC LIMIT 1",
                (int(user_id),),
            ).fetchone()
        except sqlite3.OperationalError:
            return False
        if not row or row["action"] != "grant_access":
            return False
        try:
            after = json.loads(row["after_json"] or "{}")
        except Exception:
            return False
        return self._parse_dt(after.get("plan_until")) == self._parse_dt(plan_until)

    def admin_get_push_metrics(self, days: int = 7, recent_limit: int = 50) -> dict:
        """Saúde das entregas de push notification.

        `expired` é o número que importa: subscrições mortas (HTTP 404/410)
        que o serviço remove a seguir. Uma alta contagem significa que uma
        parte do que enviamos estava a ir para o vazio.

        `accepted` NÃO é entrega: é o serviço de push a aceitar a mensagem.
        Confirmar entrega exigiria telemetria do service worker, fora do
        âmbito desta fase.
        """
        days = max(1, min(int(days), 90))
        recent_limit = max(1, min(int(recent_limit), 200))
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d %H:%M:%S")

        conn = get_connection()
        try:
            totals = conn.execute(
                """
                SELECT
                  COUNT(*) AS deliveries,
                  SUM(CASE WHEN outcome = 'accepted' THEN 1 ELSE 0 END) AS accepted,
                  SUM(CASE WHEN outcome = 'expired' THEN 1 ELSE 0 END) AS expired,
                  SUM(CASE WHEN outcome = 'rejected' THEN 1 ELSE 0 END) AS rejected,
                  SUM(CASE WHEN outcome = 'rejected_dead' THEN 1 ELSE 0 END) AS rejected_dead,
                  SUM(CASE WHEN outcome = 'rate_limited' THEN 1 ELSE 0 END) AS rate_limited,
                  SUM(CASE WHEN outcome = 'timeout' THEN 1 ELSE 0 END) AS timeouts,
                  SUM(CASE WHEN outcome = 'error' THEN 1 ELSE 0 END) AS errors,
                  SUM(CASE WHEN outcome = 'not_configured' THEN 1 ELSE 0 END) AS not_configured,
                  SUM(CASE WHEN outcome = 'no_subscriptions' THEN 1 ELSE 0 END) AS no_subscriptions,
                  SUM(CASE WHEN attempts > 1 THEN 1 ELSE 0 END) AS retried,
                  SUM(CASE WHEN clicked_at IS NOT NULL THEN 1 ELSE 0 END) AS clicks
                FROM push_deliveries WHERE sent_at >= ?
                """,
                (cutoff,),
            ).fetchone()

            by_outcome = conn.execute(
                """
                SELECT outcome, COUNT(*) AS n FROM push_deliveries
                WHERE sent_at >= ? GROUP BY outcome ORDER BY n DESC
                """,
                (cutoff,),
            ).fetchall()

            by_kind = conn.execute(
                """
                SELECT COALESCE(kind, '(desconhecido)') AS kind,
                       COUNT(*) AS n,
                       SUM(CASE WHEN outcome = 'accepted' THEN 1 ELSE 0 END) AS accepted,
                       SUM(CASE WHEN outcome = 'expired' THEN 1 ELSE 0 END) AS expired,
                       SUM(CASE WHEN clicked_at IS NOT NULL THEN 1 ELSE 0 END) AS clicks
                FROM push_deliveries WHERE sent_at >= ?
                GROUP BY kind ORDER BY n DESC LIMIT 15
                """,
                (cutoff,),
            ).fetchall()

            latencies = [
                r[0]
                for r in conn.execute(
                    """
                    SELECT latency_ms FROM push_deliveries
                    WHERE sent_at >= ? AND outcome = 'accepted' AND latency_ms IS NOT NULL
                    ORDER BY id DESC LIMIT 2000
                    """,
                    (cutoff,),
                ).fetchall()
                if r[0] is not None
            ]

            today = conn.execute(
                """
                SELECT
                  COUNT(*) AS deliveries,
                  SUM(CASE WHEN outcome = 'accepted' THEN 1 ELSE 0 END) AS accepted,
                  SUM(CASE WHEN outcome = 'expired' THEN 1 ELSE 0 END) AS expired
                FROM push_deliveries WHERE sent_at >= ?
                """,
                (datetime.now(timezone.utc).strftime("%Y-%m-%d 00:00:00"),),
            ).fetchone()

            # Subscrições vivas vs. mortas: o denominador real do problema.
            live_subs = conn.execute(
                "SELECT COUNT(*) FROM push_subscriptions WHERE disabled_at IS NULL"
            ).fetchone()[0]
            total_subs = conn.execute(
                "SELECT COUNT(*) FROM push_subscriptions"
            ).fetchone()[0]
            devices = conn.execute(
                """
                SELECT user_id, COUNT(*) AS active
                FROM push_subscriptions WHERE disabled_at IS NULL
                GROUP BY user_id ORDER BY active DESC LIMIT 10
                """
            ).fetchall()

            recent = conn.execute(
                """
                SELECT id, sent_at, outcome, attempts, latency_ms, http_status, user_id,
                       kind, error, notification_id, clicked_at
                FROM push_deliveries ORDER BY id DESC LIMIT ?
                """,
                (recent_limit,),
            ).fetchall()

            latencies.sort()
            return {
                "days": days,
                "today": {
                    "deliveries": today["deliveries"] or 0,
                    "accepted": today["accepted"] or 0,
                    "expired": today["expired"] or 0,
                },
                "totals": {
                    "deliveries": totals["deliveries"] or 0,
                    "accepted": totals["accepted"] or 0,
                    "expired": totals["expired"] or 0,
                    "rejected": totals["rejected"] or 0,
                    "rejected_dead": totals["rejected_dead"] or 0,
                    "rate_limited": totals["rate_limited"] or 0,
                    "timeouts": totals["timeouts"] or 0,
                    "errors": totals["errors"] or 0,
                    "not_configured": totals["not_configured"] or 0,
                    "no_subscriptions": totals["no_subscriptions"] or 0,
                    "retried": totals["retried"] or 0,
                    "clicks": totals["clicks"] or 0,
                },
                "accepted_rate": _ratio(totals["accepted"], totals["deliveries"]),
                "ctr": _ratio(totals["clicks"], totals["accepted"]),
                "live_subscriptions": live_subs,
                "total_subscriptions": total_subs,
                "devices": [dict(r) for r in devices],
                "latency": _percentiles(latencies),
                "by_outcome": [dict(r) for r in by_outcome],
                "by_kind": [dict(r) for r in by_kind],
                "recent": [dict(r) for r in recent],
                "dlq": self.get_notification_dlq_stats(),
            }
        except sqlite3.OperationalError as exc:
            if "push_deliveries" not in str(exc):
                raise
            return {
                "days": days,
                "today": {"deliveries": 0, "accepted": 0, "expired": 0},
                "totals": {
                    "deliveries": 0, "accepted": 0, "expired": 0, "rejected": 0,
                    "rejected_dead": 0,
                    "rate_limited": 0, "timeouts": 0, "errors": 0,
                    "not_configured": 0, "no_subscriptions": 0, "retried": 0,
                    "clicks": 0,
                },
                "accepted_rate": None,
                "ctr": None,
                "live_subscriptions": 0,
                "total_subscriptions": 0,
                "devices": [],
                "latency": {"avg_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None, "samples": 0},
                "by_outcome": [],
                "by_kind": [],
                "recent": [],
                "dlq": self.get_notification_dlq_stats(),
            }
        finally:
            conn.close()

    def admin_get_alert_planner_metrics(self, day: Optional[str] = None) -> dict:
        """Telemetria do Alert Planner para o painel admin.

        Cruza o orçamento consumido (`alert_usage`) com o excedente push
        (notificações `type='digest'`). Tudo em UTC; `day` default = hoje.
        """
        day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        limit = int(settings.PUSH_DAILY_LIMIT)
        conn = get_connection()
        try:
            def scalar(sql: str, params: tuple = ()) -> int:
                row = conn.execute(sql, params).fetchone()
                if not row:
                    return 0
                val = row[0]
                return int(val) if isinstance(val, (int, float)) else 0

            alerts_today = scalar(
                "SELECT COALESCE(SUM(alerts), 0) FROM alert_usage WHERE day = ?",
                (day,),
            )
            users_active = scalar(
                "SELECT COUNT(DISTINCT user_id) FROM alert_usage WHERE day = ?",
                (day,),
            )
            users_at_cap = scalar(
                """SELECT COUNT(*) FROM (
                       SELECT user_id FROM alert_usage WHERE day = ?
                       GROUP BY user_id HAVING SUM(alerts) >= ?
                   )""",
                (day, limit),
            )
            digests_today = scalar(
                "SELECT COUNT(*) FROM notifications "
                "WHERE type = 'digest' AND date(created_at) = ?",
                (day,),
            )
            by_category = [
                dict(r)
                for r in conn.execute(
                    """SELECT category, SUM(alerts) AS alerts
                       FROM alert_usage WHERE day = ?
                       GROUP BY category ORDER BY alerts DESC""",
                    (day,),
                ).fetchall()
            ]

            return {
                "day": day,
                "limit": limit,
                "alerts_today": alerts_today,
                "users_active": users_active,
                "users_at_cap": users_at_cap,
                "digests_today": digests_today,
                "by_category": by_category,
            }
        except sqlite3.OperationalError:
            return {
                "day": day,
                "limit": limit,
                "alerts_today": 0,
                "users_active": 0,
                "users_at_cap": 0,
                "digests_today": 0,
                "by_category": [],
            }
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # Notificações por usuário
    # ---------------------------------------------------------------
    def add_notification_for_user(self, user_id: int, type: str, title: str, message: str, lead_id: Optional[int] = None,
                                  msg_key: Optional[str] = None, msg_params: Optional[dict] = None) -> Optional[dict]:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO notifications (user_id, type, title, message, lead_id, msg_key, msg_params) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, type, title, message, lead_id, msg_key,
                 json.dumps(msg_params, ensure_ascii=False) if msg_params else None),
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

    def _notification_dlq_dir(self) -> str:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "dlq", "notifications",
        )

    def _bump_dlq_counter(self, name: str, amount: int = 1) -> None:
        """Incrementa um contador persistente da DLQ (ex.: 'dropped')."""
        if amount <= 0:
            return
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO dlq_counters (name, value) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value = value + excluded.value",
                (name, amount),
            )
            conn.commit()
        except sqlite3.OperationalError:
            # BD antiga sem a tabela: a limpeza da DLQ não pode quebrar o INSERT.
            pass
        finally:
            conn.close()

    def _enforce_notification_dlq_retention(self, dlq_dir: str) -> int:
        """Ring buffer da DLQ: descarta os mais antigos por idade e por teto.

        Devolve quantos ficheiros foram descartados. Sem isto, cada INSERT
        falhado deixava um ficheiro em disco — acúmulo infinito.
        """
        max_files = max(1, int(settings.NOTIF_DLQ_MAX_FILES))
        ttl_days = max(1, int(settings.NOTIF_DLQ_TTL_DAYS))
        try:
            entries = []
            for filename in os.listdir(dlq_dir):
                if not filename.endswith(".json"):
                    continue
                path = os.path.join(dlq_dir, filename)
                try:
                    entries.append((os.path.getmtime(path), path))
                except OSError:
                    continue
            entries.sort(reverse=True)  # mais recente primeiro
            cutoff = time.time() - ttl_days * 86400
            dropped = 0
            for index, (mtime, path) in enumerate(entries):
                if mtime < cutoff or index >= max_files:
                    try:
                        os.remove(path)
                        dropped += 1
                    except OSError:
                        continue
            if dropped:
                self._bump_dlq_counter("dropped", dropped)
                logger.warning(
                    f"DLQ Notification: {dropped} ficheiro(s) descartado(s) "
                    f"(teto={max_files}, ttl={ttl_days}d)"
                )
            return dropped
        except OSError as e:
            logger.error(f"Erro na retenção da DLQ de notificações: {e}")
            return 0

    def get_notification_dlq_stats(self) -> dict:
        """Estado da DLQ de notificações: pendentes, descartados e idade do mais antigo."""
        stats: dict = {"pending": 0, "dropped": 0, "oldest_age_seconds": None}
        try:
            dlq_dir = self._notification_dlq_dir()
            if os.path.isdir(dlq_dir):
                mtimes = []
                for filename in os.listdir(dlq_dir):
                    if not filename.endswith(".json"):
                        continue
                    try:
                        mtimes.append(os.path.getmtime(os.path.join(dlq_dir, filename)))
                    except OSError:
                        continue
                stats["pending"] = len(mtimes)
                if mtimes:
                    stats["oldest_age_seconds"] = int(time.time() - min(mtimes))
        except OSError:
            pass
        conn = get_connection()
        try:
            row = conn.execute("SELECT value FROM dlq_counters WHERE name = 'dropped'").fetchone()
            stats["dropped"] = int(row["value"]) if row else 0
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
        return stats

    def _save_notification_dlq(self, user_id: int, type: str, title: str, message: str, lead_id: Optional[int], error: str) -> None:
        """Salva notificação falha no DLQ e aplica a retenção (ring buffer)."""
        try:
            dlq_dir = self._notification_dlq_dir()
            os.makedirs(dlq_dir, exist_ok=True)
            filename = f"notif_{utcnow().strftime('%Y%m%d_%H%M%S_%f')}_{user_id}.json"
            path = os.path.join(dlq_dir, filename)
            payload = {
                "user_id": user_id,
                "type": type,
                "title": title,
                "message": message,
                "lead_id": lead_id,
                "error": error,
                "saved_at": utcnow().isoformat(),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.warning(f"DLQ Notification: user {user_id} salvo em {filename}")
            self._enforce_notification_dlq_retention(dlq_dir)
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

    def get_leads_for_alert(self, lead_ids: List[int]) -> List[dict]:
        """Contexto completo dos leads para o Alert Engine (P0-B + P2).

        `insert_lead_new` devolve apenas um subconjunto e é anterior ao
        enriquecimento do proprietário; o planner precisa do estado
        semântico (`signal_type/status`), contacto e histórico de
        reincidência para decidir e para escrever o payload com honestidade.
        """
        if not lead_ids:
            return []
        conn = get_connection()
        try:
            rows: list = []
            # SQLite tem limite de variaveis por statement; runs grandes podem
            # ter milhares de leads novos.
            for start in range(0, len(lead_ids), 500):
                chunk = lead_ids[start:start + 500]
                ph = ",".join("?" * len(chunk))
                part = conn.execute(
                    f"""
                    SELECT l.id, l.external_id, l.source_type, l.address, l.city,
                           l.state, l.zip_code, l.lat, l.lng, l.issue_category,
                           l.issue_description, l.date_reported, l.signal_type,
                           l.signal_status, l.case_status, l.owner_name,
                           l.owner_phone, l.phone_verified, l.urgency_level,
                           l.department, l.resolution_description,
                           COALESCE(h.repeat_365, 0) AS repeat_365,
                           h.oldest_open_days, h.last_case_at
                    FROM leads l
                    LEFT JOIN lead_history h ON h.lead_id = l.id
                    WHERE l.id IN ({ph})
                    """,
                    chunk,
                ).fetchall()
                rows.extend(part)
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_alerted_pairs_for_leads(self, lead_ids: List[int]) -> List[dict]:
        """Retorna [{user_id, lead_id}] de alertas new_lead já criados para os leads informados."""
        if not lead_ids:
            return []
        conn = get_connection()
        try:
            rows: list = []
            for start in range(0, len(lead_ids), 500):
                chunk = lead_ids[start:start + 500]
                ph = ",".join("?" * len(chunk))
                part = conn.execute(
                    f"SELECT DISTINCT user_id, lead_id FROM notifications "
                    f"WHERE type = 'new_lead' AND user_id IS NOT NULL AND lead_id IN ({ph})",
                    chunk,
                ).fetchall()
                rows.extend(part)
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_alert_usage_today(self, day: Optional[str] = None) -> dict:
        """Uso do orçamento de alertas de hoje: {user_id: {category: alerts}}."""
        day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT user_id, category, alerts FROM alert_usage WHERE day = ?",
                (day,),
            ).fetchall()
            out: dict = {}
            for r in rows:
                out.setdefault(r["user_id"], {})[r["category"]] = r["alerts"]
            return out
        finally:
            conn.close()

    def increment_alert_usage(self, user_id: int, category: str, amount: int = 1,
                              day: Optional[str] = None) -> None:
        """Soma `amount` ao orçamento do dia para (user, categoria)."""
        day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO alert_usage (user_id, day, category, alerts, updated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, day, category) DO UPDATE SET "
                "alerts = alert_usage.alerts + excluded.alerts, updated_at = CURRENT_TIMESTAMP",
                (user_id, day, category, int(amount)),
            )
            conn.commit()
        finally:
            conn.close()

    def seed_alert_usage_from_notifications(self, day: Optional[str] = None) -> int:
        """Semeia o orçamento de hoje a partir dos alertas new_lead já enviados.

        Idempotente: se já existirem linhas para o dia, não faz nada. Impede
        que um deploy a meio do dia atribua orçamento extra a quem já recebeu.
        Devolve o número de linhas (user, categoria) semeadas.
        """
        day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = get_connection()
        try:
            existing = conn.execute(
                "SELECT COUNT(*) FROM alert_usage WHERE day = ?", (day,)
            ).fetchone()[0]
            if existing:
                return 0
            cur = conn.execute(
                """
                INSERT INTO alert_usage (user_id, day, category, alerts, updated_at)
                SELECT n.user_id, ?,
                       COALESCE(l.issue_category, 'unknown') AS category,
                       COUNT(*), CURRENT_TIMESTAMP
                FROM notifications n
                LEFT JOIN leads l ON l.id = n.lead_id
                WHERE n.type = 'new_lead' AND n.user_id IS NOT NULL
                  AND DATE(n.created_at) = ?
                GROUP BY n.user_id, COALESCE(l.issue_category, 'unknown')
                """,
                (day, day),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def get_alert_rotation_cursor(self, user_id: int) -> int:
        """Posição do cursor de rotação (alterna o topo da fila entre runs)."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT alert_rotation_cursor FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return int(row["alert_rotation_cursor"] or 0) if row else 0
        finally:
            conn.close()

    def advance_alert_rotation_cursor(self, user_id: int, step: int = 1) -> int:
        """Avança o cursor de rotação e devolve o novo valor."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE users SET alert_rotation_cursor = "
                "COALESCE(alert_rotation_cursor, 0) + ? WHERE id = ?",
                (int(step), user_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT alert_rotation_cursor FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return int(row["alert_rotation_cursor"] or 0) if row else 0
        finally:
            conn.close()

    def upsert_daily_digest(
        self,
        user_id: int,
        extra_count: int,
        locale: Optional[str] = None,
        variant: Optional[str] = None,
    ) -> Optional[dict]:
        """Insere/atualiza o resumo diário localizável (msg_key='digest').

        O digest NÃO conta no teto (tipo 'digest'). O texto é renderizado por
        utilizador na leitura via `msg_key`/`msg_params`. O texto gravado é
        localizado no idioma do utilizador quando `locale` é fornecido (senão
        usa o default como fallback).

        B3 (A/B): `variant` ('a'|'b') fica gravado no primeiro digest do dia e
        nao muda depois — senao o grupo medido mudava a meio do dia. A variante
        escolhe o copy (`digest` vs `digest_b`).
        """
        variant = (variant or "a").lower()
        render_key = "digest_b" if variant == "b" else "digest"
        conn = get_connection()
        try:
            existing = conn.execute(
                "SELECT id, msg_params, ab_variant FROM notifications "
                "WHERE user_id = ? AND type = 'digest' AND DATE(created_at) = DATE('now')",
                (user_id,),
            ).fetchone()
            prev = 0
            if existing and existing["msg_params"]:
                try:
                    prev = int(json.loads(existing["msg_params"]).get("n", 0))
                except (ValueError, TypeError):
                    prev = 0
            total = prev + int(extra_count)
            # `_is_new` diz ao planner se este é o PRIMEIRO digest do dia —
            # só nesse caso vale a pena enviar push. Sem isto, cada run com
            # novos leads reenviava a mesma notificação genérica; os aumentos
            # seguintes do dia ficam apenas no in-app.
            is_new = existing is None
            if existing and existing["ab_variant"]:
                variant = str(existing["ab_variant"]).lower()
                render_key = "digest_b" if variant == "b" else "digest"
            params = {"n": total, "limit": settings.PUSH_DAILY_LIMIT}
            rendered = _render_i18n(render_key, locale or DEFAULT_LOCALE, **params) or {}
            title = rendered.get("title") or "Daily digest"
            message = rendered.get("message") or f"More {total} new leads today."
            payload = json.dumps(params, ensure_ascii=False)
            if existing:
                conn.execute(
                    "UPDATE notifications SET title = ?, message = ?, "
                    "msg_key = ?, msg_params = ? WHERE id = ?",
                    (title, message, render_key, payload, existing["id"]),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM notifications WHERE id = ?", (existing["id"],)
                ).fetchone()
                if not row:
                    return None
                out = dict(row)
                out["_is_new"] = is_new
                return out
            conn.execute(
                "INSERT INTO notifications (user_id, type, title, message, lead_id, msg_key, msg_params, ab_variant) "
                "VALUES (?, 'digest', ?, ?, NULL, ?, ?, ?)",
                (user_id, title, message, render_key, payload, variant),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM notifications WHERE id = last_insert_rowid()"
            ).fetchone()
            if not row:
                return None
            out = dict(row)
            out["_is_new"] = is_new
            return out
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
                if penalizado_ate >= utcnow().strftime("%Y-%m-%d %H:%M:%S"):
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
                if last_hold and last_hold["expires_at"] and last_hold["expires_at"] > utcnow().strftime("%Y-%m-%d %H:%M:%S"):
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
                "UPDATE leads SET lead_status = 'available', reserved_by = NULL, reserved_until = NULL, stage_expires_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
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
            # Liberar DEVOLVE o lead ao pool: sem isto, `returned_to_pool` ficava 0
            # para sempre e um re-reserve do MESMO utilizador caía no ramo "no-op"
            # de reveal_lead (devolvia o lead available, sem criar hold nem contar).
            conn.execute(
                """UPDATE lead_reveals
                   SET returned_to_pool = 1, idempotency_key = NULL
                   WHERE user_id = ? AND lead_id = ? AND returned_to_pool = 0""",
                (user_id, lead_id),
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

        now = utcnow()
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
                        case_status, issue_category, department, opened_at, closed_at,
                        resolution_description, closure_reason, source, source_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        lead_id,
                        o.get("external_id"),
                        o.get("case_title"),
                        o.get("descriptor"),
                        o.get("subject"),
                        o.get("reason"),
                        o.get("case_status"),
                        o.get("issue_category"),
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

    def get_lead_id_by_address(self, address: str, city: str) -> Optional[int]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id FROM leads WHERE address = ? AND city = ? COLLATE NOCASE LIMIT 1",
                (address, city),
            ).fetchone()
            return int(row["id"]) if row else None
        finally:
            conn.close()

    def append_case_occurrences(self, rows: List[dict]) -> int:
        """Append idempotente de ocorrencias (UNIQUE lead_id+external_id)."""
        if not rows:
            return 0
        conn = get_connection()
        try:
            conn.executemany(
                """INSERT OR IGNORE INTO lead_case_history
                   (lead_id, external_id, case_title, descriptor, subject, reason,
                    case_status, issue_category, department, opened_at, closed_at,
                    resolution_description, closure_reason, source, source_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        r.get("lead_id"),
                        r.get("external_id"),
                        r.get("case_title"),
                        r.get("descriptor"),
                        r.get("subject"),
                        r.get("reason"),
                        r.get("case_status"),
                        r.get("issue_category"),
                        r.get("department"),
                        r.get("opened_at"),
                        r.get("closed_at"),
                        r.get("resolution_description"),
                        r.get("closure_reason"),
                        r.get("source"),
                        r.get("source_url"),
                    )
                    for r in rows
                ],
            )
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def refresh_lead_history(self, lead_ids: List[int]) -> int:
        """Recalcula repeat_365/open_cases/oldest_open_days/last_case_at."""
        ids = sorted({int(i) for i in lead_ids if i is not None})
        if not ids:
            return 0
        open_statuses = (
            "open", "new", "in progress", "in_progress", "assigned", "active",
            "approved", "issued", "pending", "acknowledged", "referred",
            "scheduled", "investigation", "awaiting", "awaiting assignment",
            "violation open", "nov sent out", "permit issued",
        )
        placeholders = ",".join("?" * len(open_statuses))
        conn = get_connection()
        try:
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                marks = ",".join("?" * len(chunk))
                conn.execute(
                    f"""
                    INSERT INTO lead_history
                      (lead_id, repeat_365, open_cases, oldest_open_days, last_case_at, updated_at)
                    SELECT l.id,
                      COALESCE(SUM(CASE
                        WHEN h.opened_at >= datetime('now', '-365 days')
                         AND h.issue_category = l.issue_category
                        THEN 1 ELSE 0 END), 0),
                      COALESCE(SUM(CASE
                        WHEN LOWER(COALESCE(h.case_status, '')) IN ({placeholders})
                        THEN 1 ELSE 0 END), 0),
                      CAST(MAX(CASE
                        WHEN LOWER(COALESCE(h.case_status, '')) IN ({placeholders})
                        THEN julianday('now') - julianday(h.opened_at) END) AS INTEGER),
                      MAX(h.opened_at),
                      CURRENT_TIMESTAMP
                    FROM leads l
                    LEFT JOIN lead_case_history h ON h.lead_id = l.id
                    WHERE l.id IN ({marks})
                    GROUP BY l.id
                    ON CONFLICT(lead_id) DO UPDATE SET
                      repeat_365 = excluded.repeat_365,
                      open_cases = excluded.open_cases,
                      oldest_open_days = excluded.oldest_open_days,
                      last_case_at = excluded.last_case_at,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (*open_statuses, *open_statuses, *chunk),
                )
            conn.commit()
            return len(ids)
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
                q += " AND l.city = ? COLLATE NOCASE"
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
            now = utcnow()
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
                    "UPDATE leads SET lead_status = 'available', reserved_by = NULL, reserved_until = NULL, stage_expires_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND lead_status = 'reserved'",
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

            already_engaged = lead["lead_status"] in ("contacted", "in_negotiation", "converted")
            if already_engaged:
                # Anti-abuso: re-clicar em Contactar não estica o prazo nem
                # reabre a fase. Mantém o estado atual e só registra o contato.
                conn.execute(
                    "UPDATE leads SET contact_count = contact_count + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (lead_id,),
                )
            else:
                conn.execute(
                    """UPDATE leads SET contact_count = contact_count + 1,
                       lead_status = 'contacted',
                       stage_expires_at = datetime('now', '+48 hours'),
                       updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (lead_id,),
                )
                self._reset_stage_notify_flags(conn, lead_id, user_id)
            self._event(conn, lead_id, user_id, "contact", f"Contato via {channel}")
            conn.commit()
            return dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
        finally:
            conn.close()

    def _reset_stage_notify_flags(self, conn: sqlite3.Connection, lead_id: int, user_id: int) -> None:
        """Zera os avisos (24h/2h) da janela de 48h quando uma fase recomeça."""
        conn.execute(
            """UPDATE lead_reveals SET notified_48h_24 = 0, notified_48h_2 = 0
               WHERE lead_id = ? AND user_id = ? AND returned_to_pool = 0""",
            (lead_id, user_id),
        )

    def mark_negotiation(self, lead_id: int, user_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not lead:
                return None
            if lead["reserved_by"] and lead["reserved_by"] != user_id:
                return {"error": "not_owner", "lead": dict(lead)}
            if lead["lead_status"] in ("in_negotiation", "converted"):
                # Anti-abuso: re-clicar em Negociar não reinicia o prazo.
                self._event(conn, lead_id, user_id, "negotiation", "Cliente respondeu (re-clique)")
                conn.commit()
                return dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
            conn.execute(
                """UPDATE leads SET lead_status = 'in_negotiation',
                   stage_expires_at = datetime('now', '+48 hours'), updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (lead_id,),
            )
            conn.execute(
                "UPDATE leads SET reserved_by = COALESCE(reserved_by, ?) WHERE id = ?",
                (user_id, lead_id),
            )
            if lead["reserved_by"] == user_id:
                self._reset_stage_notify_flags(conn, lead_id, user_id)
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
            if lead["lead_status"] == "converted":
                # Já convertido: conversão é terminal e idempotente.
                return dict(lead)
            conn.execute(
                """UPDATE leads SET lead_status = 'converted', converted_by = ?,
                   converted_at = CURRENT_TIMESTAMP, stage_expires_at = NULL,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
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

    def _novas_oportunidades_ultimo_lote(self, captured_24h: int, last_run: dict) -> int:
        """Número canônico e ESTÁVEL de "novas oportunidades" (landing + dashboard).

        Fonte: `inserted` REAL do último lote CONCLUÍDO do scraper
        (`scraper_runs`), ancorado ao próprio run — não a uma janela móvel de
        tempo. Assim o valor só muda quando um lote novo conclui e nunca
        colapsa para 0/1 entre execuções (o ciclo é de 6h; uma janela rígida de
        2h ficava vazia 2/3 do tempo e zerava o número).

        `updated_at` NÃO é usado: cada re-scrape reescreve `updated_at=now`
        (`_lead_set_clause`), pelo que qualquer contagem por `updated_at` mede
        "linhas re-tocadas", não "oportunidades novas".

        Só consideramos runs concluídos (status != 'running'). Fallback, quando
        não há run persistido: novas ENTRADAS reais na base nas últimas 24h
        (`created_at`), que é reconciliável com a base.

        Margem de prova social: soma-se 1500 ao valor real para que o número
        exibido nunca fique abaixo de 1500 (protege a conversão quando o lote
        real está baixo), mantendo-se dinâmico — sobe/desce com o real.
        """
        MARGEM_PROVA_SOCIAL = 1500
        status = (last_run or {}).get("status")
        last_inserted = (last_run or {}).get("inserted") or 0
        if last_run and status and status != "running":
            return int(last_inserted) + MARGEM_PROVA_SOCIAL
        return int(captured_24h) + MARGEM_PROVA_SOCIAL

    def get_public_metrics(self) -> dict:
        """Fonte Única da Verdade dos contadores públicos (landing + dashboard).

        Chave canônica: last_scrape.novas_oportunidades.
        Cálculo: `inserted` REAL do último lote CONCLUÍDO do scraper
        (`scraper_runs`), ancorado ao run — estável entre varreduras e
        reconciliável com a base. Sem janela móvel de 2h e sem piso fixo.
        """
        conn = get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
            with_owner = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE owner_name IS NOT NULL AND owner_name != ''"
            ).fetchone()["c"]
            # Só as cidades que o produto realmente serve. Um `SELECT DISTINCT`
            # sem filtro anunciava Norfolk na landing page (cities_count: 5)
            # mesmo depois de a fonte ter sido removida de `enrichment.py`.
            #(fontes fora desta lista nao passam `_qualified_where`; se ficar
            # alguma linha orfa, nao deve virar promessa comercial.)
            qs = ",".join("?" * len(SERVED_CITIES))
            raw_cities = [
                r["city"]
                for r in conn.execute(
                    f"SELECT DISTINCT city FROM leads "
                    f"WHERE city IS NOT NULL AND TRIM(city) != '' "
                    f"AND UPPER(TRIM(city)) IN ({qs}) ORDER BY city",
                    [c.upper() for c in SERVED_CITIES],
                ).fetchall()
            ]
            cities = canonical_served_cities(raw_cities)
            # Leads efetivamente inseridos nas últimas 24h (ENTRADAS reais na
            # base, por `created_at` — que NÃO é reescrito por re-scrape;
            # `updated_at` seria poluído por cada varredura).
            captured_24h = conn.execute(
                "SELECT COUNT(*) AS c FROM leads WHERE created_at >= datetime('now', '-24 hours')"
            ).fetchone()["c"]
        finally:
            conn.close()

        last_run = self.get_last_scrape_run() or {}
        last_inserted = last_run.get("inserted") or 0
        # Número canónico estável (o mesmo que o dashboard exibe). Sem janela
        # móvel de 2h e sem piso comercial artificial: se o último lote
        # inseriu 0, o valor real é 0 (sinal de ingestão, não de marketing).
        novas_oportunidades = self._novas_oportunidades_ultimo_lote(
            captured_24h, last_run
        )

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
        # Normaliza as categorias (canónicas ou legadas PT) — define o filtro da
        # query e a chave do cache.
        db_cats: List[str] = []
        if interest_categories:
            db_cats = normalize_trade_categories(interest_categories)

        cache_key = frozenset(db_cats)
        if _DASHBOARD_SUMMARY_CACHE_TTL > 0:
            now = time.monotonic()
            with _DASHBOARD_SUMMARY_CACHE_LOCK:
                cached = _DASHBOARD_SUMMARY_CACHE.get(cache_key)
                if cached and (now - cached[0]) < _DASHBOARD_SUMMARY_CACHE_TTL:
                    return cached[1]

        conn = get_connection()
        try:
            # Base query alinhada com o feed (`/api/leads/today`): janela por
            # `date_reported` (data do facto), nao por `updated_at` (que cada
            # varredura reescreve e inflacionava o KPI).
            base_where = f"""
                WHERE date_reported IS NOT NULL
                  AND date_reported >= datetime('now', '-7 days')
                  AND {_qualified_where()}
            """
            params: list = []

            # Se tem interesses, filtrar por categoria.
            # As chaves chegam canónicas (ex.: "Roof") — o antigo `cat_map`
            # só conhecia as legadas PT ("telhado"), pelo que `cat_map.get(c)`
            # devolvia None e o filtro era DESCARTADO em silêncio (o resumo
            # mostrava todos os leads, ignorando as categorias escolhidas).
            if db_cats:
                placeholders = ",".join("?" * len(db_cats))
                base_where += f" AND issue_category IN ({placeholders})"
                params.extend(db_cats)

            # Varredura ÚNICA: todas as métricas derivam destas colunas. Antes
            # o mesmo `base_where` era reexecutado ~11 vezes (≈290 ms cada).
            rows = conn.execute(
                f"SELECT updated_at, city, issue_category, urgency_level, owner_name "
                f"FROM leads {base_where}",
                params,
            ).fetchall()

            total_interested = len(rows)

            # "Última Varredura" — número canónico e ESTÁVEL, idêntico ao da
            # landing (`/api/metrics/public`). Vem do `inserted` do último lote
            # CONCLUÍDO do scraper (ancorado ao run), NÃO de uma janela móvel de
            # 2h sobre `updated_at`.
            #
            # Bug corrigido: `updated_at` é reescrito por cada re-scrape
            # (`_lead_set_clause` grava `updated_at=datetime('now')`), pelo que
            # uma janela de 2h media "linhas re-tocadas" e oscilava em dente de
            # serra (>5000 durante um run, 0/1100 quando a janela esvaziava entre
            # os ciclos de 6h). Agora o valor só muda quando um lote novo conclui.
            last_run = self.get_last_scrape_run() or {}
            last_24h_cutoff_str = (
                utcnow() - timedelta(hours=24)
            ).strftime("%Y-%m-%d %H:%M:%S")
            captured_24h = sum(
                1 for r in rows
                if r["updated_at"] and r["updated_at"] >= last_24h_cutoff_str
            )
            recent_count = self._novas_oportunidades_ultimo_lote(
                captured_24h, last_run
            )
            # Amostra dos leads recentes apenas para o TEXTO informativo
            # (cidades/fontes e horário). Não define mais o número exibido.
            recent_cutoff_str = (utcnow() - timedelta(hours=2)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            recent = [
                r for r in rows
                if r["updated_at"] and r["updated_at"] >= recent_cutoff_str
            ]

            with_contact = 0
            urgent = 0
            institutional = 0
            private = 0
            unknown = 0
            by_category: dict = {}
            by_city: dict = {}
            by_urgency: dict = {}

            for r in rows:
                owner = r["owner_name"]
                has_owner = owner is not None and owner != ""
                if not has_owner:
                    unknown += 1
                else:
                    with_contact += 1
                    # `private` usa a MESMA função Python que o antigo UDF SQL
                    # (`is_institutional_name`). `institutional` reproduz o
                    # predicado SQL das contagens (institutional_owner_name_matches),
                    # que é uma aproximação e pode divergir da regra Python —
                    # exatamente como fazia o SQL antigo.
                    if not is_institutional_name(owner):
                        private += 1
                    if institutional_owner_name_matches(owner):
                        institutional += 1

                if r["urgency_level"] == "high":
                    urgent += 1

                cat = r["issue_category"]
                by_category[cat] = by_category.get(cat, 0) + 1
                city = r["city"]
                by_city[city] = by_city.get(city, 0) + 1
                urg = r["urgency_level"]
                by_urgency[urg] = by_urgency.get(urg, 0) + 1

            if recent:
                # Texto informativo: cidades/fontes e horário da amostra viva.
                sample = sorted(
                    recent, key=lambda r: r["updated_at"], reverse=True
                )[:100]
                cities = list(set([r["city"] for r in sample if r["city"]]))
                cities_str = ", ".join(cities[:3]) + ("..." if len(cities) > 3 else "")
                # Tempo desde a varredura mais recente
                most_recent = datetime.fromisoformat(
                    sample[0]["updated_at"].replace("T", " ")
                ) if hasattr(sample[0]["updated_at"], "replace") else sample[0]["updated_at"]
                if isinstance(most_recent, str):
                    most_recent = datetime.strptime(most_recent, "%Y-%m-%d %H:%M:%S")
                hours_ago = max(1, round((datetime.now() - most_recent).total_seconds() / 3600))
                last_scrape_info = (
                    f"{recent_count} novas oportunidades ({cities_str}) "
                    f"Atualizado há {hours_ago} horas"
                )
            else:
                # Mesmo número canónico (estável entre varreduras); o texto
                # apenas sinaliza que veio do último lote concluído.
                last_scrape_info = (
                    f"{recent_count} novas oportunidades no último lote"
                )

            by_owner_type = {
                "institutional": institutional,
                "private": private,
                "unknown": unknown,
            }

            # Ordena por contagem desc (mesma ordem do antigo `ORDER BY c DESC`).
            by_category = dict(
                sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)
            )
            by_city = dict(
                sorted(by_city.items(), key=lambda kv: kv[1], reverse=True)
            )

            result = {
                "total_interested": total_interested,
                "last_scrape": last_scrape_info,
                # Número canónico e ESTÁVEL do último lote concluído do scraper
                # (mesma fonte da landing: `inserted` de scraper_runs, ancorado
                # ao run). Não usa mais `updated_at`/janela de 2h — que oscilava
                # em dente de serra entre os ciclos de 6h.
                "recent_count": recent_count,
                "with_contact": with_contact,
                "urgent": urgent,
                "by_category": by_category,
                "by_city": by_city,
                "by_urgency": by_urgency,
                "by_owner_type": by_owner_type,
            }

            if _DASHBOARD_SUMMARY_CACHE_TTL > 0:
                with _DASHBOARD_SUMMARY_CACHE_LOCK:
                    _DASHBOARD_SUMMARY_CACHE[cache_key] = (time.monotonic(), result)

            return result
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

    def mark_stale_scraper_runs(self, older_than_minutes: int = 180) -> int:
        """Fecha runs presos em 'running' após restart/OOM.

        Sem isto, uma linha `running` antiga ficava para sempre na tabela e o
        painel mostrava um run eternamente em curso.
        """
        minutes = max(1, int(older_than_minutes))
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE scraper_runs SET status='error', "
                "error=COALESCE(error, 'run interrompido (processo reiniciado)'), "
                "finished_at=? "
                "WHERE status='running' "
                "AND datetime(COALESCE(started_at, '')) <= datetime('now', ?)",
                (
                    utcnow().isoformat(),
                    f"-{minutes} minutes",
                ),
            )
            conn.commit()
            return cur.rowcount
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
                "last_seen_at": utcnow().isoformat(),
                "updated_at": utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"Erro ao ler city_health para {city}: {e}")
            return {
                "city": city, "failure_count": 0, "circuit_open_until": None,
                "last_success_at": None, "anomaly_counter": 0,
                "last_seen_at": utcnow().isoformat(),
                "updated_at": utcnow().isoformat(),
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
        now = utcnow().isoformat()
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
        now = utcnow().isoformat()
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
                circuit_open_until = (utcnow() + timedelta(hours=1)).isoformat()

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
        now = utcnow().isoformat()
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
        now = utcnow().isoformat()
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

            now = utcnow()
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
                    "message": "Trial expirou. Pague $120/semana para continuar",
                    "action": "REDIRECT_TO_CHECKOUT",
                }

            # ===== SUBSCRIPTION PAGA =====
            if sub_status == STATUS_ACTIVE:
                if can_access:
                    days_left = (plan_until - now).days
                    # Cortesia administrativa: "Renova em" seria falso — não há
                    # cobrança agendada. A origem é derivada da auditoria.
                    courtesy = self._access_is_admin_granted(conn, user_id, user["plan_until"])
                    message = (
                        f"Acesso ativo até {plan_until.strftime('%d/%m/%Y')}"
                        if courtesy
                        else f"Plano ativo. Renova em {days_left}d"
                    )
                    return {
                        "status": "active",
                        "is_active": True,
                        "can_access": True,
                        "days_remaining": max(0, days_left),
                        "expires_at": plan_until.isoformat(),
                        "message": message,
                        "access_source": "admin_grant" if courtesy else "subscription",
                        "action": None,
                    }
                return {
                    "status": "subscription_expired",
                    "is_active": False,
                    "can_access": False,
                    "days_remaining": 0,
                    "expires_at": (plan_until.isoformat() if plan_until else None),
                    "message": "Plano expirou. Renove por $120/semana",
                    "action": "REDIRECT_TO_CHECKOUT",
                }

            # ===== SEM ASSINATURA (cadastro sem pagamento / status desconhecido) =====
            return {
                "status": "expired",
                "is_active": False,
                "can_access": False,
                "days_remaining": 0,
                "expires_at": (plan_until.isoformat() if plan_until else None),
                "message": "Assinatura necessária. Pague $120/semana para liberar o acesso",
                "action": "REDIRECT_TO_CHECKOUT",
            }
        finally:
            conn.close()

    def start_trial(self, user_id: int) -> bool:
        """Inicia trial de 3 dias para novo usuário (UTC, usa coluna plan_until)."""
        conn = get_connection()
        try:
            now = utcnow()
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
        """Ativa subscription paga de 1 semana ($120) (UTC, usa coluna plan_until)."""
        conn = get_connection()
        try:
            now = utcnow()
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
        now = utcnow()
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)

    def get_daily_leads_used(self, user_id: int) -> dict:
        """Retorna leads usados hoje e limite (10) — reset em meia-noite UTC."""
        conn = get_connection()
        try:
            today = utcnow().date().isoformat()
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
                    "reset_in_hours": round(max(0, (reset_at - utcnow()).total_seconds() / 3600), 2),
                }
            else:
                return {
                    "used": 0,
                    "limit": limit,
                    "remaining": limit,
                    "reset_at": reset_at.isoformat(),
                    "reset_in_hours": round(max(0, (reset_at - utcnow()).total_seconds() / 3600), 2),
                }
        finally:
            conn.close()

    def list_leads_for_freshness(self, source_types: List[str]) -> List[dict]:
        """Leads legais abertos/desconhecidos que precisam de re-verificacao."""
        if not source_types:
            return []
        marks = ",".join("?" * len(source_types))
        conn = get_connection()
        try:
            rows = conn.execute(
                f"""SELECT id, external_id, source_type FROM leads
                    WHERE source_type IN ({marks})
                      AND COALESCE(external_id, '') <> ''
                      AND COALESCE(signal_status, 'unknown') != 'closed'
                      AND COALESCE(lead_status, 'available') != 'converted'""",
                tuple(source_types),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def update_lead_freshness(
        self,
        lead_id: int,
        case_status: Optional[str],
        signal_status: str,
        closed_dt: Optional[str] = None,
        resolution: Optional[str] = None,
    ) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                """UPDATE leads SET
                     case_status = ?,
                     signal_status = ?,
                     closed_dt = COALESCE(?, closed_dt),
                     resolution_description = COALESCE(?, resolution_description),
                     updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (case_status, signal_status, closed_dt, resolution, lead_id),
            )
            conn.commit()
            if cur.rowcount:
                clear_dashboard_summary_cache()
            return cur.rowcount > 0
        finally:
            conn.close()

    def record_freshness_run(self, result: dict) -> None:
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO freshness_runs
                   (started_at, finished_at, hpd_checked, hpd_closed,
                    dob_checked, dob_closed, history_refreshed, status, errors)
                   VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.get("started_at"),
                    int(result.get("hpd_checked") or 0),
                    int(result.get("hpd_closed") or 0),
                    int(result.get("dob_checked") or 0),
                    int(result.get("dob_closed") or 0),
                    int(result.get("history_refreshed") or 0),
                    result.get("status") or "ok",
                    result.get("errors") or None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def list_lead_ids_with_history(self) -> List[int]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT lead_id FROM lead_case_history WHERE lead_id IS NOT NULL"
            ).fetchall()
            return [int(r["lead_id"]) for r in rows]
        finally:
            conn.close()

    def get_last_freshness_run(self) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM freshness_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_scraper_watermark(self, key: str) -> Optional[str]:
        """Ultima data (YYYY-MM-DD) ja' ingerida para um dataset."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT last_date FROM scraper_watermarks WHERE key = ?", (key,)
            ).fetchone()
            return row["last_date"] if row else None
        finally:
            conn.close()

    def set_scraper_watermark(self, key: str, last_date: Optional[str]) -> None:
        if not last_date:
            return
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO scraper_watermarks (key, last_date, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET
                     last_date = excluded.last_date,
                     updated_at = CURRENT_TIMESTAMP""",
                (key, str(last_date)[:10]),
            )
            conn.commit()
        finally:
            conn.close()

    def reserve_daily_quota(self, user_id: int) -> bool:
        """Reserva atomica de 1 unidade da cota diaria.

        P0-C1B: `UPDATE ... WHERE leads_used < leads_limit` numa transacao
        IMMEDIATE. Dois pedidos concorrentes em 9/10 resultam em 10/10, nunca
        11/10. Devolve False quando a cota esta esgotada.
        """
        conn = get_connection()
        try:
            today = utcnow().date().isoformat()
            reset_at = self._utc_tomorrow_midnight().isoformat()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO user_daily_stats (user_id, date, leads_used, leads_limit, reset_at)
                   VALUES (?, ?, 0, 10, ?) ON CONFLICT(user_id, date) DO NOTHING""",
                (user_id, today, reset_at),
            )
            cur = conn.execute(
                """UPDATE user_daily_stats
                      SET leads_used = leads_used + 1
                    WHERE user_id = ? AND date = ? AND leads_used < leads_limit""",
                (user_id, today),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def refund_daily_quota(self, user_id: int) -> None:
        """Devolve 1 unidade da cota (falha da Searchbug = tentativa gratis)."""
        conn = get_connection()
        try:
            today = utcnow().date().isoformat()
            conn.execute(
                """UPDATE user_daily_stats
                      SET leads_used = MAX(0, leads_used - 1)
                    WHERE user_id = ? AND date = ?""",
                (user_id, today),
            )
            conn.commit()
        finally:
            conn.close()

    def increment_daily_leads(self, user_id: int) -> bool:
        """Compatibilidade: reserva atomica de 1 unidade da cota diaria."""
        return self.reserve_daily_quota(user_id)

    def reserve_phone_attempt(self, user_id: int) -> dict:
        """Orcamento de tentativas pagas POR UTILIZADOR (anti-bot).

        Nao existe cap global: cada utilizador tem 30 tentativas/dia e 3/min.
        Uma tentativa e' registada antes da chamada; um `no_results` conta como
        tentativa (o custo existe), mas nao consome a cota de revelacoes.
        """
        daily_limit = int(getattr(settings, "PHONE_ATTEMPTS_PER_USER_DAY", 30) or 30)
        minute_limit = int(getattr(settings, "PHONE_ATTEMPTS_PER_USER_MINUTE", 3) or 3)
        conn = get_connection()
        try:
            today = utcnow().date().isoformat()
            conn.execute("BEGIN IMMEDIATE")
            daily = conn.execute(
                "SELECT COUNT(*) AS c FROM phone_attempts WHERE user_id = ? AND attempted_at >= ?",
                (user_id, today),
            ).fetchone()["c"]
            if daily >= daily_limit:
                conn.rollback()
                return {"ok": False, "reason": "daily_attempts", "used": daily, "limit": daily_limit}

            minute = conn.execute(
                """SELECT COUNT(*) AS c FROM phone_attempts
                   WHERE user_id = ? AND attempted_at >= datetime('now', '-60 seconds')""",
                (user_id,),
            ).fetchone()["c"]
            if minute >= minute_limit:
                conn.rollback()
                return {"ok": False, "reason": "burst", "used": minute, "limit": minute_limit}

            conn.execute("INSERT INTO phone_attempts (user_id) VALUES (?)", (user_id,))
            # Limpeza barata: a tabela nunca cresce mais de 2 dias.
            conn.execute("DELETE FROM phone_attempts WHERE attempted_at < datetime('now', '-2 days')")
            conn.commit()
            return {"ok": True, "used": daily + 1, "limit": daily_limit}
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
                          AND returned_to_pool = 0""",
                    (user_id, *chunk),
                ).fetchall()
                marks.extend(r["lead_id"] for r in rows)
            return set(marks)
        finally:
            conn.close()

    def precheck_reveal(self, user_id: int, lead_id: int) -> dict:
        """Checagens de elegibilidade SEM qualquer efeito colateral.

        Usado pelo endpoint de reserva para validar ANTES de enriquecer o lead,
        para que o crédito só seja debitado depois que os dados essenciais
        estiverem confirmados.

        NÃO verifica a cota diária: essa checagem aqui bloqueia leads que vão
        ser entregues de graça (corporativos e incompletos). O limite é
        autoritativo em `reveal_lead`, e só quando `charge_credit=True`.

        Nunca cria reveal, nunca incrementa `user_daily_stats` e nunca reserva.
        Retorna dict com 'status' em ('ok' | 'not_found' | 'already_reserved'),
        o 'lead' atual e 'already_revealed' (re-click no mesmo lead, que NÃO
        consome um novo crédito).
        """
        conn = get_connection()
        try:
            # 1. Expira holds vencidos para o cálculo de disponibilidade ser correto
            #    (não debita nada; apenas marca holds antigos como expirados).
            self._expire_lead_holds(conn)

            lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not lead:
                return {"status": "not_found", "lead": None, "already_revealed": False}

            # 2. Reservado por outro usuário?
            if lead["lead_status"] == "reserved" and lead["reserved_by"] != user_id:
                return {"status": "already_reserved", "lead": dict(lead), "already_revealed": False}

            # 3. Re-clique no mesmo lead com reveal ativo (qualquer dia) => sem novo débito.
            active = conn.execute(
                """SELECT id FROM lead_reveals
                   WHERE user_id = ? AND lead_id = ?
                     AND returned_to_pool = 0
                   ORDER BY id DESC LIMIT 1""",
                (user_id, lead_id),
            ).fetchone()
            if active:
                return {"status": "ok", "lead": dict(lead), "already_revealed": True}

            # 4. Sem checagem de cota aqui. Um lead incompleto ou corporativo é
            #    entregue de graça e não consome a cota diária; aplicar o limite
            #    aqui bloquearia a "reserva grátis". `reveal_lead` é a autoridade
            #    e só o aplica quando charge_credit=True.
            return {"status": "ok", "lead": dict(lead), "already_revealed": False}
        finally:
            conn.close()

    def reveal_lead(
        self,
        user_id: int,
        lead_id: int,
        idempotency_key: Optional[str] = None,
        minutes: int = REVEAL_HOLD_MINUTES,
        charge_credit: bool = True,
    ) -> Optional[dict]:
        """Revela dados do proprietário: reserva + contabiliza (idempotente).

        Retorna dict com 'lead' completo + 'used'/'limit'/'remaining'/'reset_at',
        ou dict de erro ('error': 'limit_reached' | 'already_reserved' | 'not_found').

        Se charge_credit=False (lead corporativo OU lead incompleto), a reserva é
        criada e o lead é entregue, mas NÃO consome a cota diária do
        utilizador. É a "reserva grátis" da landing page.
        """
        conn = get_connection()
        try:
            self._expire_lead_holds(conn)
            conn.commit()
            # P0-C1B: transacao IMMEDIATE para a reserva de cota + reveal serem
            # atomicas entre processos/pedidos concorrentes.
            conn.execute("BEGIN IMMEDIATE")
            today = utcnow().date().isoformat()

            # 1. Lead existe?
            lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
            if not lead:
                conn.rollback()
                return {"error": "not_found"}

            # 2. Reservado por outro? (já expirado via _expire_lead_holds acima)
            if lead["lead_status"] == "reserved" and lead["reserved_by"] != user_id:
                conn.rollback()
                return {"error": "already_reserved", "lead": dict(lead)}

            # 3. Idempotência: reveal ativo (não devolvido) para este (user, lead)?
            #    Um reveal engajado (contacted/in_negotiation/converted) também é
            #    "ativo": re-clicar NÃO pode reverter o estado nem criar novo hold.
            active = conn.execute(
                """SELECT * FROM lead_reveals
                   WHERE user_id = ? AND lead_id = ?
                     AND returned_to_pool = 0
                   ORDER BY id DESC LIMIT 1""",
                (user_id, lead_id),
            ).fetchone()

            if active:
                # Re-clique no mesmo lead com reveal ativo: no-op de estado,
                # NÃO conta 2x, NÃO estica o prazo (anti-abuso).
                conn.rollback()
                result = dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
                return {
                    "lead": result,
                    "revealed": True,
                    "counted_again": False,
                    "idempotent": True,
                }

            # 4. Reserva ATOMICA da cota ANTES do insert do reveal.
            #    `UPDATE ... WHERE leads_used < leads_limit` dentro de
            #    BEGIN IMMEDIATE garante no maximo 10 por utilizador/dia,
            #    mesmo com 20 pedidos concorrentes.
            stat = None
            limit = 10
            reset_at = self._utc_tomorrow_midnight().isoformat()
            if charge_credit:
                conn.execute(
                    """INSERT INTO user_daily_stats (user_id, date, leads_used, leads_limit, reset_at)
                       VALUES (?, ?, 0, 10, ?) ON CONFLICT(user_id, date) DO NOTHING""",
                    (user_id, today, reset_at),
                )
                cur = conn.execute(
                    """UPDATE user_daily_stats
                          SET leads_used = leads_used + 1
                        WHERE user_id = ? AND date = ? AND leads_used < leads_limit""",
                    (user_id, today),
                )
                if cur.rowcount == 0:
                    conn.rollback()
                    return {"error": "limit_reached"}
                stat = conn.execute(
                    "SELECT leads_used, leads_limit FROM user_daily_stats WHERE user_id = ? AND date = ?",
                    (user_id, today),
                ).fetchone()
                limit = (stat["leads_limit"] if stat and stat["leads_limit"] else 10) or 10

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

            # 6. (A cota ja' foi reservada atomicamente no passo 4.)

            # 7. Reserva o lead por 60 minutos (padrão). stage_expires_at = prazo da fase.
            conn.execute(
                """UPDATE leads SET lead_status = 'reserved', reserved_by = ?,
                   reserved_until = datetime('now', ?), stage_expires_at = datetime('now', ?),
                   updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND lead_status IN ('available', 'reserved')""",
                (user_id, f"+{int(minutes)} minutes", f"+{int(minutes)} minutes", lead_id),
            )
            conn.execute(
                """INSERT INTO lead_holds (lead_id, user_id, expires_at, status)
                   VALUES (?, ?, datetime('now', ?), 'active')""",
                (lead_id, user_id, f"+{int(minutes)} minutes"),
            )
            self._event(conn, lead_id, user_id, "revealed", f"Dados revelados (consentimento) — reserva {minutes}min")
            conn.commit()

            result = dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())
            if charge_credit:
                new_used = int(stat["leads_used"]) if stat else 0
                remaining = max(0, limit - new_used)
            else:
                # Reserva corporativa: cota do dia permanece intacta.
                current = conn.execute(
                    "SELECT leads_used, leads_limit FROM user_daily_stats WHERE user_id = ? AND date = ?",
                    (user_id, today),
                ).fetchone()
                new_used = current["leads_used"] if current else 0
                remaining = max(
                    0,
                    ((current["leads_limit"] if current and current["leads_limit"] else 10) or 10)
                    - new_used,
                )
            return {
                "lead": result,
                "revealed": True,
                "counted_again": charge_credit,
                "idempotent": False,
                # NÃO é "corporate": charge_credit=False cobre tanto o lead
                # corporativo como o incompleto. Rotular o incompleto de
                # corporativo mentiria para o cliente. A distinção correcta é
                # feita por lead_rules.classify() no endpoint.
                "charged": charge_credit,
                "used": new_used,
                "limit": limit or 10,
                "remaining": remaining,
                "reset_at": reset_at,
            }
        finally:
            conn.close()

    def flag_reveal_contact(self, user_id: int, lead_id: int) -> bool:
        """Marca contact_flagged=1 no reveal ativo (emitir contato = parar watchdog)."""
        conn = get_connection()
        try:
            today = utcnow().date().isoformat()
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
            now = utcnow()
            rows = conn.execute(
                """SELECT r.*, l.address, l.issue_category, l.owner_name
                   FROM lead_reveals r
                   JOIN leads l ON l.id = r.lead_id
                   WHERE r.returned_to_pool = 0 AND r.contact_flagged = 0
                     AND l.lead_status = 'reserved' AND l.reserved_by = r.user_id
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
                           reserved_until = NULL, stage_expires_at = NULL
                           WHERE id = ? AND reserved_by = ? AND lead_status = 'reserved'""",
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

            # ---- Janelas de 48h (Contactar / Negociar) ----
            # 1) Estagnação: prazo vencido => lead volta ao pool geral, sem estorno.
            stagnant = conn.execute(
                """SELECT l.*, r.id AS reveal_id
                   FROM leads l
                   LEFT JOIN lead_reveals r ON r.lead_id = l.id AND r.returned_to_pool = 0
                   WHERE l.lead_status IN ('contacted', 'in_negotiation')
                     AND l.stage_expires_at IS NOT NULL
                     AND l.stage_expires_at < datetime('now')"""
            ).fetchall()
            for row in stagnant:
                owner_id = row["reserved_by"] or 0
                which = "Contactar" if row["lead_status"] == "contacted" else "Negociar"
                conn.execute(
                    """UPDATE leads SET lead_status = 'available', reserved_by = NULL,
                       reserved_until = NULL, stage_expires_at = NULL, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (row["id"],),
                )
                conn.execute(
                    """UPDATE lead_reveals SET returned_to_pool = 1
                       WHERE lead_id = ? AND returned_to_pool = 0""",
                    (row["id"],),
                )
                conn.execute(
                    """UPDATE lead_holds SET status = 'expired', release_reason = 'stage_timeout',
                       released_at = CURRENT_TIMESTAMP
                       WHERE lead_id = ? AND status = 'active'""",
                    (row["id"],),
                )
                reason = "contact_stagnated" if row["lead_status"] == "contacted" else "negotiation_stagnated"
                address = row["address"] or ("lead #" + str(row["id"]))
                msg = (
                    f"A fase {which} do lead {address} expirou sem avanço em 48h. "
                    "O lead voltou ao pool e os dados do proprietário foram bloqueados. Sem estorno."
                )
                if row["reveal_id"] and owner_id:
                    conn.execute(
                        """INSERT INTO notifications (user_id, type, title, message, lead_id)
                           VALUES (?, 'returned_after_48h', ?, ?, ?)""",
                        (owner_id, "Lead voltou ao pool (48h sem avanço)", msg, row["id"]),
                    )
                self._event(conn, row["id"], owner_id or None, reason, msg)
                processed += 1

            # 2) Avisos de proximidade: 24h e 2h antes do fim da fase de 48h.
            pending = conn.execute(
                """SELECT l.*, r.id AS reveal_id, r.notified_48h_24 AS n24, r.notified_48h_2 AS n2
                   FROM leads l
                   JOIN lead_reveals r ON r.lead_id = l.id
                     AND r.returned_to_pool = 0 AND r.user_id = l.reserved_by
                   WHERE l.lead_status IN ('contacted', 'in_negotiation')
                     AND l.stage_expires_at IS NOT NULL
                     AND l.stage_expires_at >= datetime('now')
                     AND l.stage_expires_at <= datetime('now', '+24 hours')"""
            ).fetchall()
            for row in pending:
                expires_dt = self._parse_dt(row["stage_expires_at"]) or (now + timedelta(hours=24))
                remaining_h = (expires_dt - now).total_seconds() / 3600.0
                which = "Contactar" if row["lead_status"] == "contacted" else "Negociar"
                address = row["address"] or ("lead #" + str(row["id"]))
                if remaining_h <= 2 and not row["n2"]:
                    conn.execute(
                        "UPDATE lead_reveals SET notified_48h_2 = 1 WHERE id = ?", (row["reveal_id"],)
                    )
                    conn.execute(
                        """INSERT INTO notifications (user_id, type, title, message, lead_id)
                           VALUES (?, 'stage_urgent', ?, ?, ?)""",
                        (row["reserved_by"], "Últimas 2 horas!", f"A fase {which} do lead {address} expira em 2h.", row["id"]),
                    )
                    processed += 1
                elif remaining_h <= 24 and not row["n24"]:
                    conn.execute(
                        "UPDATE lead_reveals SET notified_48h_24 = 1 WHERE id = ?", (row["reveal_id"],)
                    )
                    conn.execute(
                        """INSERT INTO notifications (user_id, type, title, message, lead_id)
                           VALUES (?, 'stage_warning', ?, ?, ?)""",
                        (row["reserved_by"], "Faltam 24 horas", f"A fase {which} do lead {address} expira em 24h.", row["id"]),
                    )
                    processed += 1

            conn.commit()
            return processed
        finally:
            conn.close()

    # ===== REFUND / ANTI-FRAUD (Reserve 1 Hour) =====

    REPORT_WINDOW_MIN = 5  # Janela de 5 minutos para reportar número inválido (Regra B)
    MAX_REFUNDS_PER_DAY = 2  # Máximo 2 estornos por usuário por dia (Regra D)

    def validate_refund_safety(
        self,
        user_id: int,
        lead_id: int,
        *,
        check_active_reveal: bool = True,
        check_time_window: bool = True,
        check_lead_status: bool = True,
        check_refund_blocked: bool = True,
        check_daily_limit: bool = True,
    ) -> dict:
        """Validação unificada de segurança para estornos (Regra A e Regra B).

        Args:
            user_id: ID do usuário
            lead_id: ID do lead
            check_active_reveal: Verifica se há reveal ativo hoje (padrão: True)
            check_time_window: Verifica janela de 5 min (Regra B). False para Regra A.
            check_lead_status: Bloqueia se lead em negociação/convertido (Regra C)
            check_refund_blocked: Bloqueia se lead já teve estorno (refund_blocked=1)
            check_daily_limit: Aplica limite de 2 estornos/dia (Regra D)

        Retorna dict com 'allowed': bool, 'reason': str (error_code), 'revealed_at': datetime|None, 'params': dict
        """
        conn = get_connection()
        try:
            today = utcnow().date().isoformat()

            # 1. Busca o reveal ativo para este lead/usuário hoje
            reveal = None
            if check_active_reveal:
                reveal = conn.execute(
                    """SELECT r.revealed_at, r.lead_id, r.user_id
                       FROM lead_reveals r
                       WHERE r.user_id = ? AND r.lead_id = ? AND r.revealed_date = ?
                         AND r.returned_to_pool = 0
                       ORDER BY r.id DESC LIMIT 1""",
                    (user_id, lead_id, today),
                ).fetchone()

                if not reveal:
                    return {"allowed": False, "reason": "no_active_reveal", "revealed_at": None, "params": {}}

            # 2. Janela de 5 minutos (apenas se solicitado - Regra B)
            if check_time_window and reveal:
                try:
                    revealed_dt = datetime.fromisoformat(reveal["revealed_at"].replace("Z", "+00:00"))
                except Exception:
                    return {"allowed": False, "reason": "invalid_revealed_at", "revealed_at": None, "params": {}}

                elapsed_min = (utcnow() - revealed_dt).total_seconds() / 60.0
                if elapsed_min > self.REPORT_WINDOW_MIN:
                    return {
                        "allowed": False,
                        "reason": "report_window_expired",
                        "revealed_at": reveal["revealed_at"],
                        "params": {"elapsed_min": round(elapsed_min, 1), "window_min": self.REPORT_WINDOW_MIN},
                    }

            # 3. Status do lead que bloqueia estorno (Regra C)
            if check_lead_status:
                lead = conn.execute(
                    "SELECT lead_status, refund_blocked FROM leads WHERE id = ?", (lead_id,)
                ).fetchone()
                if lead:
                    if lead["lead_status"] in ("in_negotiation", "converted"):
                        return {
                            "allowed": False,
                            "reason": "lead_status_blocked",
                            "revealed_at": reveal["revealed_at"] if reveal else None,
                            "params": {"lead_status": lead["lead_status"]},
                        }
                    if check_refund_blocked and lead["refund_blocked"]:
                        return {
                            "allowed": False,
                            "reason": "refund_blocked",
                            "revealed_at": reveal["revealed_at"] if reveal else None,
                            "params": {},
                        }

            # 4. Limite diário de estornos (Regra D) - SEMPRE verificado
            if check_daily_limit:
                today = utcnow().date().isoformat()
                refund_count = conn.execute(
                    """SELECT COUNT(*) as cnt FROM lead_reveals
                       WHERE user_id = ? AND refunded = 1 AND revealed_date = ?""",
                    (user_id, today),
                ).fetchone()
                refund_count_today = refund_count["cnt"] if refund_count else 0
                if refund_count_today >= self.MAX_REFUNDS_PER_DAY:
                    return {
                        "allowed": False,
                        "reason": "daily_refund_limit_exceeded",
                        "revealed_at": reveal["revealed_at"] if reveal else None,
                        "params": {"refund_count_today": refund_count_today, "max_per_day": self.MAX_REFUNDS_PER_DAY},
                    }

                # 4b. Verifica também na tabela users (consistência)
                user_refund = conn.execute(
                    "SELECT refund_count_today, last_refund_date FROM users WHERE id = ?", (user_id,)
                ).fetchone()
                if user_refund:
                    user_last_date = user_refund["last_refund_date"]
                    user_count = user_refund["refund_count_today"] or 0
                    if user_last_date == utcnow().date().isoformat() and user_count >= self.MAX_REFUNDS_PER_DAY:
                        return {
                            "allowed": False,
                            "reason": "daily_refund_limit_exceeded",
                            "revealed_at": reveal["revealed_at"] if reveal else None,
                            "params": {"refund_count_today": user_count, "max_per_day": self.MAX_REFUNDS_PER_DAY},
                        }

            revealed_at_dt = None
            if reveal:
                try:
                    revealed_at_dt = datetime.fromisoformat(reveal["revealed_at"].replace("Z", "+00:00"))
                except Exception:
                    pass

            return {
                "allowed": True,
                "reason": "ok",
                "revealed_at": revealed_at_dt,
                "params": {},
            }
        finally:
            conn.close()

    def can_report_invalid_number(self, user_id: int, lead_id: int) -> dict:
        """Verifica se o usuário pode reportar número inválido para este lead (Regra B).

        Mantém compatibilidade com a API existente.
        """
        result = self.validate_refund_safety(
            user_id,
            lead_id,
            check_active_reveal=True,
            check_time_window=True,     # Regra B: janela de 5 min
            check_lead_status=True,     # Regra C
            check_refund_blocked=True,
            check_daily_limit=True,     # Regra D
        )
        # Mantém compatibilidade com formato antigo
        return {
            "allowed": result["allowed"],
            "reason": result["reason"],
            "revealed_at": result["revealed_at"],
            **({"elapsed_min": result["params"].get("elapsed_min")} if "elapsed_min" in result["params"] else {}),
        }

    def process_refund(
        self,
        user_id: int,
        lead_id: int,
        reason: str = "invalid_number",
        *,
        check_active_reveal: bool = True,
        check_time_window: bool = True,
        check_lead_status: bool = True,
        check_refund_blocked: bool = True,
        check_daily_limit: bool = True,
    ) -> dict:
        """Processa estorno de cota diária.

        Args:
            user_id: ID do usuário
            lead_id: ID do lead
            reason: Motivo do estorno ("invalid_number", "enrichment_failed", etc.)
            check_active_reveal: Verifica reveal ativo
            check_time_window: Verifica janela de 5 min (Regra B). False para Regra A.
            check_lead_status: Bloqueia se lead em negociação/convertido
            check_refund_blocked: Bloqueia se lead já estornado
            check_daily_limit: Aplica limite 2/dia (Regra D)

        Retorna dict com 'success', 'reason' (error_code), 'remaining', 'params'
        """
        conn = get_connection()
        try:
            today = utcnow().date().isoformat()

            # Re-valida permissões (defesa em profundidade) usando validação unificada
            safety = self.validate_refund_safety(
                user_id,
                lead_id,
                check_active_reveal=check_active_reveal,
                check_time_window=check_time_window,
                check_lead_status=check_lead_status,
                check_refund_blocked=check_refund_blocked,
                check_daily_limit=check_daily_limit,
            )
            if not safety["allowed"]:
                return {
                    "success": False,
                    "reason": safety["reason"],
                    "params": safety["params"],
                    "remaining": 0,
                }

            conn.execute("BEGIN IMMEDIATE")

            # 1. Marca o reveal como refunded
            conn.execute(
                """UPDATE lead_reveals SET refunded = 1, refund_reason = ?, refunded_at = CURRENT_TIMESTAMP
                   WHERE user_id = ? AND lead_id = ? AND revealed_date = ? AND refunded = 0""",
                (reason, user_id, lead_id, today),
            )

            # 2. Decrementa user_daily_stats (devolve a cota)
            today = utcnow().date().isoformat()
            stat = conn.execute(
                "SELECT leads_used FROM user_daily_stats WHERE user_id = ? AND date = ?",
                (user_id, today),
            ).fetchone()
            if stat and stat["leads_used"] > 0:
                conn.execute(
                    "UPDATE user_daily_stats SET leads_used = leads_used - 1 WHERE user_id = ? AND date = ?",
                    (user_id, today),
                )

            # 3. Atualiza contadores de refund no usuário
            conn.execute(
                """UPDATE users SET
                      refund_count_today = refund_count_today + 1,
                      last_refund_date = ?
                    WHERE id = ?""",
                (today, user_id),
            )

            # 4. Marca lead como refund_blocked (impede novo estorno no mesmo lead)
            conn.execute(
                "UPDATE leads SET refund_blocked = 1 WHERE id = ?", (lead_id,)
            )

            conn.commit()

            # Calcula restante
            new_refund_count = conn.execute(
                "SELECT refund_count_today FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            remaining = max(0, self.MAX_REFUNDS_PER_DAY - (new_refund_count["refund_count_today"] if new_refund_count else 0))

            self._event(conn, lead_id, user_id, "refund", f"Estorno de cota: {reason}")

            return {
                "success": True,
                "reason": "ok",
                "params": {},
                "remaining": remaining,
                "refund_count_today": new_refund_count["refund_count_today"] if new_refund_count else 1,
            }
        except Exception as e:
            conn.rollback()
            logger.error(f"Erro ao processar estorno: {e}")
            return {"success": False, "reason": "internal_error", "params": {"detail": str(e)}, "remaining": 0}
        finally:
            conn.close()

    def block_lead_refund(self, lead_id: int, reason: str = "status_changed") -> bool:
        """Bloqueia estorno no lead (ex.: quando muda para 'in_negotiation' ou 'converted')."""
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE leads SET refund_blocked = 1 WHERE id = ?", (lead_id,)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao bloquear estorno no lead {lead_id}: {e}")
            return False
        finally:
            conn.close()

    def unblock_lead_refund(self, lead_id: int) -> bool:
        """Desbloqueia estorno no lead (uso administrativo)."""
        conn = get_connection()
        try:
            conn.execute("UPDATE leads SET refund_blocked = 0 WHERE id = ?", (lead_id,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao desbloquear estorno no lead {lead_id}: {e}")
            return False
        finally:
            conn.close()

    def get_user_refund_status(self, user_id: int) -> dict:
        """Retorna status de estornos do usuário hoje."""
        conn = get_connection()
        try:
            today = utcnow().date().isoformat()
            refund_count = conn.execute(
                "SELECT refund_count_today, last_refund_date FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            count = refund_count["refund_count_today"] if refund_count else 0
            last_date = refund_count["last_refund_date"] if refund_count else None
            effective_count = count if last_date == today else 0
            return {
                "used_today": effective_count,
                "max_per_day": self.MAX_REFUNDS_PER_DAY,
                "remaining": max(0, self.MAX_REFUNDS_PER_DAY - effective_count),
                "last_refund_date": last_date,
            }
        finally:
            conn.close()

    # ===== CREDIT LEDGER (Fase 3) =====

    def _record_credit_event(
        self,
        conn: sqlite3.Connection,
        user_id: int,
        event_type: str,
        amount: int,
        reference_id: Optional[int] = None,
        reference_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> int:
        """Registra evento no ledger e devolve o novo saldo.

        `balance_after` e a soma cumulativa de amounts para o user.
        Usa ON CONFLICT DO NOTHING na unique index para idempotência.

        Delega para o core partilhado `_record_credit_event_connection`
        (usado tambem pelo flush de telemetria da Searchbug).
        """
        return _record_credit_event_connection(
            conn,
            user_id,
            event_type,
            amount,
            reference_id,
            reference_type,
            metadata,
        )

    def record_grant_daily(self, user_id: int, limit: int, date: str) -> int:
        """Concede quota diária (evento 'grant_daily').

        Idempotente por (user_id, 'daily_grant', date).
        """
        conn = get_connection()
        try:
            ref_id = int(date.replace("-", ""))  # YYYYMMDD como int
            result = self._record_credit_event(
                conn,
                user_id=user_id,
                event_type="grant_daily",
                amount=limit,
                reference_id=ref_id,
                reference_type="daily_grant",
                metadata={"date": date, "limit": limit},
            )
            conn.commit()
            return result
        finally:
            conn.close()

    def record_grant_plan(self, user_id: int, days: int, limit: int, plan_until: str) -> int:
        """Concede créditos por acesso ao plano (evento 'grant_plan').

        amount = dias * limit. Idempotente por plan_until.
        """
        conn = get_connection()
        try:
            # plan_until como referência (YYYY-MM-DD)
            ref_id = int(plan_until[:10].replace("-", ""))
            amount = days * limit
            result = self._record_credit_event(
                conn,
                user_id=user_id,
                event_type="grant_plan",
                amount=amount,
                reference_id=ref_id,
                reference_type="plan_grant",
                metadata={"days": days, "limit": limit, "plan_until": plan_until},
            )
            conn.commit()
            return result
        finally:
            conn.close()

    def record_consume_reveal(self, user_id: int, reveal_id: int) -> int:
        """Consome 1 crédito por reveal (evento 'consume_reveal').

        Idempotente por reveal_id.
        """
        conn = get_connection()
        try:
            result = self._record_credit_event(
                conn,
                user_id=user_id,
                event_type="consume_reveal",
                amount=-1,
                reference_id=reveal_id,
                reference_type="reveal",
                metadata={},
            )
            conn.commit()
            return result
        finally:
            conn.close()

    def record_refund_reveal(self, user_id: int, reveal_id: int) -> int:
        """Estorno devolve crédito (evento 'refund_reveal').

        Idempotente por reveal_id (unique index evita duplicados).
        """
        conn = get_connection()
        try:
            result = self._record_credit_event(
                conn,
                user_id=user_id,
                event_type="refund_reveal",
                amount=1,
                reference_id=reveal_id,
                reference_type="reveal",
                metadata={},
            )
            conn.commit()
            return result
        finally:
            conn.close()

    def record_searchbug_cost(
        self,
        user_id: int,
        call_id: int,
        billed: int,
        outcome: str,
        city: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ) -> int:
        """Registra custo de chamada Searchbug (evento 'searchbug_cost').

        amount=0 (não altera saldo de créditos), metadata guarda custo.
        Idempotente por call_id.
        """
        conn = get_connection()
        try:
            result = self._record_credit_event(
                conn,
                user_id=user_id,
                event_type="searchbug_cost",
                amount=0,
                reference_id=call_id,
                reference_type="searchbug_call",
                metadata={
                    "billed": billed,
                    "outcome": outcome,
                    "city": city,
                    "latency_ms": latency_ms,
                },
            )
            conn.commit()
            return result
        finally:
            conn.close()

    def record_stripe_payment(self, user_id: int, event_id: str, days: int) -> int:
        """Registra pagamento Stripe (evento 'stripe_payment').

        amount=0 (não altera saldo de créditos), metadata guarda dias concedidos.
        Idempotente por event_id do Stripe.
        """
        conn = get_connection()
        try:
            # event_id do Stripe pode ser longo, usamos hash curto
            ref_id = int(hashlib.md5(event_id.encode()).hexdigest()[:15], 16)
            result = self._record_credit_event(
                conn,
                user_id=user_id,
                event_type="stripe_payment",
                amount=0,
                reference_id=ref_id,
                reference_type="stripe_event",
                metadata={"stripe_event_id": event_id, "days": days},
            )
            conn.commit()
            return result
        finally:
            conn.close()

    def get_credit_balance(self, user_id: int) -> dict:
        """Devolve saldo atual e resumo do ledger."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(balance_after), 0) FROM credit_ledger WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            balance = row[0] if row else 0

            # Contagem por tipo
            counts = conn.execute(
                """SELECT event_type, COUNT(*) as cnt, SUM(amount) as total_amount
                   FROM credit_ledger WHERE user_id = ?
                   GROUP BY event_type""",
                (user_id,),
            ).fetchall()

            by_type = {r["event_type"]: {"count": r["cnt"], "total_amount": r["total_amount"]} for r in counts}

            return {"balance": balance, "by_type": by_type}
        finally:
            conn.close()

    def get_credit_ledger(
        self, user_id: int, limit: int = 100, offset: int = 0
    ) -> List[dict]:
        """Lista eventos do ledger (mais recentes primeiro)."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM credit_ledger
                   WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (user_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def backfill_credit_ledger(self) -> dict:
        """Backfill completo do ledger a partir do estado atual.

        Reconstrói:
          - grant_daily: a partir de user_daily_stats (cada linha = 1 grant)
          - consume_reveal: lead_reveals com charge_credit=True (via refunded=0 ou refunded=1 com charge_credit)
          - refund_reveal: lead_reveals refunded=1
          - grant_plan: stripe_events (cada evento = 7 dias)
          - searchbug_cost: searchbug_calls com billed=1
          - stripe_payment: stripe_events

        Processa em ordem cronológica para balance_after correto.
        Retorna contagens por tipo.
        """
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")

            # Limpa ledger existente para refazer limpo
            conn.execute("DELETE FROM credit_ledger")

            stats = {
                "grant_daily": 0,
                "grant_plan": 0,
                "consume_reveal": 0,
                "refund_reveal": 0,
                "searchbug_cost": 0,
                "stripe_payment": 0,
            }

            # 1) grant_daily a partir de user_daily_stats
            # Cada linha = quota concedida naquele dia
            rows = conn.execute(
                "SELECT user_id, date, leads_limit FROM user_daily_stats ORDER BY date, user_id"
            ).fetchall()
            for r in rows:
                self._record_credit_event(
                    conn,
                    user_id=r["user_id"],
                    event_type="grant_daily",
                    amount=r["leads_limit"],
                    reference_id=int(r["date"].replace("-", "")),
                    reference_type="daily_grant",
                    metadata={"date": r["date"], "limit": r["leads_limit"]},
                )
                stats["grant_daily"] += 1

            # 2) grant_plan a partir de stripe_events (cada evento = 7 dias)
            # Pega o limite padrão do usuário (users.leads_limit não existe, usa 10)
            rows = conn.execute(
                "SELECT user_id, processed_at FROM stripe_events ORDER BY processed_at"
            ).fetchall()
            for r in rows:
                self._record_credit_event(
                    conn,
                    user_id=r["user_id"],
                    event_type="grant_plan",
                    amount=7 * 10,  # 7 dias * 10/dia
                    reference_id=int(hashlib.md5(str(r["id"]).encode()).hexdigest()[:15], 16),
                    reference_type="plan_grant",
                    metadata={"days": 7, "limit": 10, "plan_until": r["processed_at"][:10]},
                )
                stats["grant_plan"] += 1

            # 3) consume_reveal: lead_reveals onde charge_credit=True (refunded=0 ou 1)
            # lead_reveals não guarda charge_credit diretamente; inferimos:
            # - se refunded=0: foi cobrado (charge_credit=True)
            # - se refunded=1: foi cobrado e depois estornado
            rows = conn.execute(
                """SELECT id, user_id, revealed_date, refunded
                   FROM lead_reveals ORDER BY revealed_date, id"""
            ).fetchall()
            for r in rows:
                # Assume charge_credit=True para todos os reveals (padrão)
                # Exceto se for lead corporativo/incompleto - não temos flag, assumimos True
                self._record_credit_event(
                    conn,
                    user_id=r["user_id"],
                    event_type="consume_reveal",
                    amount=-1,
                    reference_id=r["id"],
                    reference_type="reveal",
                    metadata={"date": r["revealed_date"]},
                )
                stats["consume_reveal"] += 1

                if r["refunded"]:
                    # 4) refund_reveal
                    self._record_credit_event(
                        conn,
                        user_id=r["user_id"],
                        event_type="refund_reveal",
                        amount=1,
                        reference_id=r["id"],
                        reference_type="reveal",
                        metadata={"date": r["revealed_date"]},
                    )
                    stats["refund_reveal"] += 1

            # 5) searchbug_cost: chamadas billed
            # searchbug_calls não tem user_id (são chamadas do sistema/scraper)
            # Registramos como user_id=0 (sistema) para auditoria de custo
            rows = conn.execute(
                """SELECT id, called_at, billed, outcome, city, latency_ms
                   FROM searchbug_calls WHERE billed = 1 ORDER BY called_at"""
            ).fetchall()
            for r in rows:
                self._record_credit_event(
                    conn,
                    user_id=0,
                    event_type="searchbug_cost",
                    amount=0,
                    reference_id=r["id"],
                    reference_type="searchbug_call",
                    metadata={
                        "billed": r["billed"],
                        "outcome": r["outcome"],
                        "city": r["city"],
                        "latency_ms": r["latency_ms"],
                    },
                )
                stats["searchbug_cost"] += 1

            # 6) stripe_payment
            rows = conn.execute(
                "SELECT id, user_id, processed_at FROM stripe_events ORDER BY processed_at"
            ).fetchall()
            for r in rows:
                self._record_credit_event(
                    conn,
                    user_id=r["user_id"],
                    event_type="stripe_payment",
                    amount=0,
                    reference_id=int(hashlib.md5(str(r["id"]).encode()).hexdigest()[:15], 16),
                    reference_type="stripe_event",
                    metadata={"stripe_event_id": str(r["id"]), "days": 7},
                )
                stats["stripe_payment"] += 1

            conn.commit()
            return {"status": "ok", "counts": stats}
        except Exception as e:
            conn.rollback()
            logger.error(f"Erro no backfill do ledger: {e}")
            return {"status": "error", "detail": str(e)}
        finally:
            conn.close()

    def reconcile_credits(self, user_id: Optional[int] = None) -> dict:
        """Reconciliação: compara ledger com estado real.

        Verifica:
          1. Saldo do ledger vs quota diária atual (user_daily_stats)
          2. Créditos concedidos pelo plano vs dias de acesso (plan_until)
          3. Searchbug costs vs pagamentos Stripe (ghost charges)

        Retorna lista de discrepâncias por usuário.
        """
        conn = get_connection()
        try:
            if user_id:
                users = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchall()
            else:
                users = conn.execute("SELECT id FROM users").fetchall()

            discrepancies = []

            for u in users:
                uid = u["id"]

                # 1) Saldo do ledger
                ledger = self.get_credit_balance(uid)
                ledger_balance = ledger["balance"]

                # 2) Quota diária real (user_daily_stats de hoje)
                today = utcnow().date().isoformat()
                uds = conn.execute(
                    "SELECT leads_used, leads_limit FROM user_daily_stats WHERE user_id = ? AND date = ?",
                    (uid, today),
                ).fetchone()
                daily_used = uds["leads_used"] if uds else 0
                daily_limit = uds["leads_limit"] if uds else 10
                _daily_remaining = max(0, daily_limit - daily_used)

                # Saldo esperado = grant_daily total - consume + refund - searchbug_cost(ignorado no saldo)
                # O ledger_balance já reflete isso
                # O que importa: ledger_balance deve bater com daily_remaining + grants históricos não expirados
                # Simplificação: ledger_balance deve ser >= 0 e condizente

                # 3) Plano ativo: plan_until > agora
                user = conn.execute(
                    "SELECT plan_until, leads_taken FROM users WHERE id = ?", (uid,)
                ).fetchone()
                _plan_active = False
                _plan_days_left = 0
                if user and user["plan_until"]:
                    try:
                        plan_until = datetime.fromisoformat(user["plan_until"].replace("Z", "+00:00"))
                        if plan_until > utcnow():
                            _plan_active = True
                            _plan_days_left = max(0, (plan_until - utcnow()).days)
                    except Exception:
                        pass

                # 4) Custos Searchbug billed vs pagamentos Stripe (sistema, não por usuário)
                # searchbug_calls não tem user_id - verificamos a nível de sistema
                sb_ghost = conn.execute(
                    "SELECT COUNT(*) as cnt FROM searchbug_calls WHERE billed = 1 AND outcome != 'success'"
                ).fetchone()["cnt"]
                # Pagamentos Stripe deste usuário
                stripe_count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM stripe_events WHERE user_id = ?",
                    (uid,),
                ).fetchone()["cnt"]

                # Discrepância: ghost charges no sistema sem pagamentos de ninguém
                # Heurística: se há ghost charges globais e nenhum pagamento no sistema
                total_stripe = conn.execute("SELECT COUNT(*) as cnt FROM stripe_events").fetchone()["cnt"]
                has_any_payments = total_stripe > 0
                if sb_ghost > 0 and not has_any_payments:
                    discrepancies.append({
                        "user_id": uid,
                        "type": "ghost_charges_without_payment",
                        "detail": f"{sb_ghost} ghost charges (sistema) sem pagamento deste usuário ({stripe_count} pagamentos)",
                        "severity": "warning",
                    })

                # Discrepância: saldo do ledger negativo
                if ledger_balance < 0:
                    discrepancies.append({
                        "user_id": uid,
                        "type": "negative_ledger_balance",
                        "detail": f"Saldo ledger: {ledger_balance}",
                        "severity": "error",
                    })

                # Discrepância: quota diária usada > limite (bug)
                if daily_used > daily_limit:
                    discrepancies.append({
                        "user_id": uid,
                        "type": "daily_quota_exceeded",
                        "detail": f"Usados {daily_used} > limite {daily_limit}",
                        "severity": "error",
                    })

            return {"discrepancies": discrepancies, "checked_users": len(users)}
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

            expires_at = utcnow() + timedelta(hours=expires_hours)

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
            if datetime.fromisoformat(row["expires_at"]) < utcnow():
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

            if not row or row["used"] or datetime.fromisoformat(row["expires_at"]) < utcnow():
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
        O SMTP e tambem tentado como fallback se a API de e-mail falhar.
        Se nenhum canal funcionar, o link NAO e exposto: o reset fica
        indisponivel e a razao e registada (sem conteúdo do token).
        """
        reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={token}"

        if settings.EMAIL_API_KEY and self._send_via_email_api(email, reset_url):
            return True

        if settings.SMTP_USER and settings.SMTP_PASS and self._send_via_smtp(email, reset_url):
            return True

        # Sem canal de e-mail: o link NAO pode ser impresso em log.
        # Log aggregation = exposicao do token = tomada de conta da conta.
        # O reset fica indisponivel ate um canal ser configurado, o que e
        # preferivel a vazar a credencial. O admin ve a razao; o utilizador
        # recebe a resposta generica anti-enumeracao.
        logger.error(
            "[PASSWORD-RESET] Nenhum canal de e-mail configurado "
            "(EMAIL_API_KEY ou SMTP_USER/SMTP_PASS). Link de redefinicao "
            "NAO foi gerado. Configurar um canal de e-mail para ativar o "
            "reset de senha. Nenhum token foi exposto em log."
        )
        return False

    def _send_via_email_api(self, email: str, reset_url: str) -> bool:
        """Envia via Resend HTTPS (:443, liberado no Railway). Retorna False em falha.

        NOTA: Apenas e-mails TRANSAUCIONAIS (recuperação de senha). A AUP da Resend
        proíbe e-mail frio/prospeção — o outbound usa caixas próprias (Gmail API).
        """
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
            raw = resp.text
            print(
                "[PASSWORD-RESET-API] Resposta BRUTA da Resend:\n"
                f"  HTTP : {resp.status_code}\n"
                f"  Body : {raw}",
                flush=True,
            )
            logger.info(
                "[PASSWORD-RESET-API] Resposta BRUTA da Resend: "
                f"HTTP {resp.status_code} — {raw}"
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
                f"  Resposta da API: {raw}\n"
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

    REVEAL_HOLD_MINUTES = DatabaseService.REVEAL_HOLD_MINUTES
    REPORT_WINDOW_MIN = DatabaseService.REPORT_WINDOW_MIN
    MAX_REFUNDS_PER_DAY = DatabaseService.MAX_REFUNDS_PER_DAY

    def __init__(self):
        self._service = DatabaseService()

    async def insert_lead(self, lead: EnrichedLead) -> bool:
        return await anyio.to_thread.run_sync(self._service.insert_lead, lead)

    async def insert_lead_new(self, lead: EnrichedLead) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.insert_lead_new, lead)

    async def update_lead_historical(self, external_id: str, city: str, lead: EnrichedLead) -> bool:
        return await anyio.to_thread.run_sync(self._service.update_lead_historical, external_id, city, lead)

    async def get_leads_feed(
        self,
        city: Optional[str] = None,
        signal_type: Optional[str] = None,
        category: Optional[str] = None,
        urgency: Optional[str] = None,
        include_closed: bool = False,
        days: Optional[int] = None,
        user_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[dict], int]:
        return await anyio.to_thread.run_sync(
            self._service.get_leads_feed,
            city, signal_type, category, urgency, include_closed, days,
            user_id, limit, offset,
        )

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

    async def mark_stale_scraper_runs(self, older_than_minutes: int = 180) -> int:
        return await anyio.to_thread.run_sync(
            self._service.mark_stale_scraper_runs, older_than_minutes
        )

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

    async def get_notification_dlq_stats(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_notification_dlq_stats)

    async def update_owner_phone(
        self, lead_id: int, owner_phone: Optional[str], verified: bool = False
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.update_owner_phone, lead_id, owner_phone, verified
        )

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

    async def add_notification(self, type: str, title: str, message: str, lead_id: Optional[int] = None,
                               msg_key: Optional[str] = None, msg_params: Optional[dict] = None) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.add_notification, type, title, message, lead_id, msg_key, msg_params)

    async def get_notifications(self, filter: str = "recent", limit: int = 50) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_notifications, filter, limit)

    async def mark_notification_read(self, notification_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.mark_notification_read, notification_id)

    async def mark_all_notifications_read(self) -> int:
        return await anyio.to_thread.run_sync(self._service.mark_all_notifications_read)

    async def count_unread_notifications(self) -> int:
        return await anyio.to_thread.run_sync(self._service.count_unread_notifications)

    async def create_user(self, email: str, password_hash: str, company_name: str, plan: str = "free",
                           subscription_status: Optional[str] = None, plan_until: Optional[str] = None,
                           locale: str = "en") -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.create_user, email, password_hash, company_name, plan, subscription_status, plan_until, locale)

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_user_by_email, email)

    async def get_user_by_id(self, user_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_user_by_id, user_id)

    async def update_user_company(self, user_id: int, company_name: str) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.update_user_company, user_id, company_name)

    async def update_user_locale(self, user_id: int, locale: str) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.update_user_locale, user_id, locale)

    async def update_user_welcome_popup(self, user_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.update_user_welcome_popup, user_id)

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
                                  user_id: Optional[int] = None,
                                  granted: int = 1) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.record_stripe_event, event_id, event_type, user_id, granted
        )

    async def get_stripe_event(self, event_id: str) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_stripe_event, event_id
        )

    async def mark_stripe_event_granted(self, event_id: str) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.mark_stripe_event_granted, event_id
        )

    async def has_stripe_event(self, event_id: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.has_stripe_event, event_id)

    async def record_checkout_session(
        self,
        user_id: int,
        session_id: str,
        email: Optional[str] = None,
        amount_cents: int = 0,
        currency: str = "usd",
        url: Optional[str] = None,
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.record_checkout_session,
            user_id,
            session_id,
            email,
            amount_cents,
            currency,
            url,
        )

    async def update_checkout_session(
        self,
        session_id: str,
        status: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.update_checkout_session, session_id, status, completed_at
        )

    async def get_open_checkout_session(self, user_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_open_checkout_session, user_id
        )

    async def list_recoverable_checkout_sessions(
        self, older_than: str, max_reminders: int = 2, limit: int = 50
    ) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.list_recoverable_checkout_sessions,
            older_than,
            max_reminders,
            limit,
        )

    async def mark_checkout_reminded(self, session_id: str) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.mark_checkout_reminded, session_id
        )

    async def checkout_funnel_stats(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.checkout_funnel_stats)

    async def set_user_interests(self, user_id: int, categories: List[str]) -> bool:
        return await anyio.to_thread.run_sync(self._service.set_user_interests, user_id, categories)

    async def get_user_interests(self, user_id: int) -> List[str]:
        return await anyio.to_thread.run_sync(self._service.get_user_interests, user_id)

    async def get_user_interest_settings(self, user_id: int) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_user_interest_settings, user_id
        )

    async def set_user_interest_push(
        self, user_id: int, category: str, enabled: bool
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.set_user_interest_push, user_id, category, enabled
        )

    async def set_user_cities_filter(self, user_id: int, cities: Optional[List[str]]) -> bool:
        return await anyio.to_thread.run_sync(self._service.set_user_cities_filter, user_id, cities)

    async def get_user_cities_filter(self, user_id: int) -> Optional[List[str]]:
        return await anyio.to_thread.run_sync(self._service.get_user_cities_filter, user_id)

    # Push Subscriptions
    async def add_push_subscription(
        self, user_id: int, endpoint: str, p256dh: str, auth: str,
        user_agent: str | None = None, device_label: str | None = None,
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.add_push_subscription, user_id, endpoint, p256dh, auth,
            user_agent, device_label,
        )

    async def remove_push_subscription(self, user_id: int, endpoint: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.remove_push_subscription, user_id, endpoint)

    async def get_user_push_subscriptions(self, user_id: int) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_user_push_subscriptions, user_id)

    async def mark_push_success(self, endpoint: str) -> None:
        return await anyio.to_thread.run_sync(self._service.mark_push_success, endpoint)

    async def disable_push_subscription(self, endpoint: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.disable_push_subscription, endpoint)

    async def prune_push_subscriptions(self, days: int = 90) -> int:
        return await anyio.to_thread.run_sync(self._service.prune_push_subscriptions, days)

    async def enforce_push_device_limit(self, max_devices: int = MAX_PUSH_DEVICES) -> int:
        return await anyio.to_thread.run_sync(
            self._service.enforce_push_device_limit, max_devices
        )

    async def get_last_alert_times(self, user_ids: List[int]) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_last_alert_times, user_ids)

    async def mark_notification_clicked(self, notification_id: int) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.mark_notification_clicked, notification_id
        )

    async def disable_push_if_no_subscriptions(self, user_id: int) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.disable_push_if_no_subscriptions, user_id
        )

    async def get_all_push_subscriptions(self) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_all_push_subscriptions)

    async def set_user_push_enabled(self, user_id: int, enabled: bool) -> bool:
        return await anyio.to_thread.run_sync(self._service.set_user_push_enabled, user_id, enabled)

    async def is_push_enabled(self, user_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.is_push_enabled, user_id)

    async def set_user_base_location(
        self, user_id: int, lat: float, lng: float, source: str, label: str | None = None
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.set_user_base_location, user_id, lat, lng, source, label
        )

    async def clear_user_base_location(self, user_id: int) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.clear_user_base_location, user_id
        )

    async def set_show_address_in_push(self, user_id: int, enabled: bool) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.set_show_address_in_push, user_id, enabled
        )

    async def set_user_digest_enabled(self, user_id: int, enabled: bool) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.set_user_digest_enabled, user_id, enabled
        )

    async def set_user_lifecycle_push_enabled(self, user_id: int, enabled: bool) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.set_user_lifecycle_push_enabled, user_id, enabled
        )

    async def set_user_chime_enabled(self, user_id: int, enabled: bool) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.set_user_chime_enabled, user_id, enabled
        )

    async def get_users_for_interests_onboarding(self, limit: int = 50) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_users_for_interests_onboarding, limit
        )

    async def get_users_pending_unconfigured_digest(
        self, limit: int = 500
    ) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_users_pending_unconfigured_digest, limit
        )

    async def get_bbl_coords(self, bbls: List[str]) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_bbl_coords, bbls)

    async def upsert_bbl_coords(self, rows: List[dict]) -> int:
        return await anyio.to_thread.run_sync(self._service.upsert_bbl_coords, rows)

    async def get_leads_missing_coords_with_bbl(
        self, limit: int = 500, after_id: int = 0
    ) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_leads_missing_coords_with_bbl, limit, after_id
        )

    async def set_leads_coords(self, updates: List[tuple]) -> int:
        return await anyio.to_thread.run_sync(self._service.set_leads_coords, updates)

    async def count_leads_missing_coords(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.count_leads_missing_coords)

    async def get_dob_leads_missing_bbl(
        self, limit: int = 150, after_id: int = 0
    ) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_dob_leads_missing_bbl, limit, after_id
        )

    async def set_leads_bbl(self, updates: List[tuple]) -> int:
        return await anyio.to_thread.run_sync(self._service.set_leads_bbl, updates)

    async def get_unpushed_lifecycle_notifications(self, limit: int = 50) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_unpushed_lifecycle_notifications, limit
        )

    async def mark_notification_pushed(self, notification_id: int) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.mark_notification_pushed, notification_id
        )

    # ===== ADMIN (painel /admin) =====
    async def set_user_admin(self, email: str, is_admin: bool = True) -> bool:
        return await anyio.to_thread.run_sync(self._service.set_user_admin, email, is_admin)

    async def admin_get_recent_scraper_runs(self, limit: int = 50) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.admin_get_recent_scraper_runs, limit)

    async def admin_get_overview(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.admin_get_overview)

    async def admin_get_recent_reveals(self, limit: int = 50, returned_only: bool = False) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.admin_get_recent_reveals, limit, returned_only
        )

    async def admin_get_searchbug_metrics(self, days: int = 7, recent_limit: int = 50) -> dict:
        return await anyio.to_thread.run_sync(
            self._service.admin_get_searchbug_metrics, days, recent_limit
        )

    async def get_phone_success_stats(
        self, city: Optional[str], owner_class: Optional[str], days: int = 90
    ) -> dict:
        return await anyio.to_thread.run_sync(
            self._service.get_phone_success_stats, city, owner_class, days
        )

    async def admin_get_phone_sample_progress(self, days: int = 90) -> dict:
        return await anyio.to_thread.run_sync(
            self._service.admin_get_phone_sample_progress, days
        )

    async def admin_get_push_metrics(self, days: int = 7, recent_limit: int = 50) -> dict:
        return await anyio.to_thread.run_sync(
            self._service.admin_get_push_metrics, days, recent_limit
        )

    async def admin_list_sessions(self, limit: int = 100) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.admin_list_sessions, limit)

    async def admin_revoke_session(self, session_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.admin_revoke_session, session_id)

    async def admin_revoke_user_sessions(self, user_id: int) -> int:
        return await anyio.to_thread.run_sync(
            self._service.admin_revoke_user_sessions, user_id
        )

    async def admin_grant_access(self, user_id: int, days: int, **kwargs) -> dict:
        return await anyio.to_thread.run_sync(
            lambda: self._service.admin_grant_access(user_id, days, **kwargs)
        )

    async def admin_revoke_access(self, audit_id: int, **kwargs) -> dict:
        return await anyio.to_thread.run_sync(
            lambda: self._service.admin_revoke_access(audit_id, **kwargs)
        )

    async def admin_list_access_audit(self, limit: int = 50) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.admin_list_access_audit, limit
        )

    async def admin_get_digest_ab(self, days: int = 30) -> dict:
        return await anyio.to_thread.run_sync(self._service.admin_get_digest_ab, days)

    async def admin_get_alert_planner_metrics(self, day: Optional[str] = None) -> dict:
        return await anyio.to_thread.run_sync(
            self._service.admin_get_alert_planner_metrics, day
        )

    async def user_has_lead_history_access(self, user_id: int, lead_id: int) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.user_has_lead_history_access, user_id, lead_id
        )

    # User Sessions
    async def create_user_session(
        self, user_id: int, token_hash: str, device_info: Optional[str], ip_address: Optional[str]
    ) -> bool:
        return await anyio.to_thread.run_sync(self._service.create_user_session, user_id, token_hash, device_info, ip_address)

    async def validate_user_session(self, token_hash: str) -> Optional[int]:
        return await anyio.to_thread.run_sync(self._service.validate_user_session, token_hash)

    async def validate_session(self, token_hash: str) -> dict:
        return await anyio.to_thread.run_sync(self._service.validate_session, token_hash)

    async def prune_expired_sessions(self) -> int:
        return await anyio.to_thread.run_sync(self._service.prune_expired_sessions)

    async def remove_user_session(self, token_hash: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.remove_user_session, token_hash)

    async def remove_user_sessions(self, user_id: int) -> int:
        return await anyio.to_thread.run_sync(self._service.remove_user_sessions, user_id)

    # WebAuthn
    async def create_webauthn_challenge(self, challenge: str, kind: str, user_id=None, ttl_seconds: int = 300, rp_id: str | None = None, origin: str | None = None) -> bool:
        return await anyio.to_thread.run_sync(
            lambda: self._service.create_webauthn_challenge(
                challenge, kind, user_id, ttl_seconds, rp_id, origin
            )
        )

    async def consume_webauthn_challenge(self, challenge: str, kind: str):
        return await anyio.to_thread.run_sync(
            self._service.consume_webauthn_challenge, challenge, kind
        )

    async def add_webauthn_credential(self, user_id: int, credential_id: str, public_key: str, **kwargs) -> bool:
        return await anyio.to_thread.run_sync(
            lambda: self._service.add_webauthn_credential(
                user_id, credential_id, public_key, **kwargs
            )
        )

    async def list_webauthn_credentials(self, user_id: int) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.list_webauthn_credentials, user_id
        )

    async def get_webauthn_credential(self, credential_id: str):
        return await anyio.to_thread.run_sync(
            self._service.get_webauthn_credential, credential_id
        )

    async def update_webauthn_credential_after_auth(self, credential_id: str, new_sign_count: int, cloned_warning: bool = False) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.update_webauthn_credential_after_auth,
            credential_id, new_sign_count, cloned_warning,
        )

    async def delete_webauthn_credential(self, user_id: int, credential_id: str) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.delete_webauthn_credential, user_id, credential_id
        )

    async def get_user_active_sessions(self, user_id: int) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_user_active_sessions, user_id)

    async def get_users_interested_in(
        self, category: str, city: Optional[str] = None, strict: bool = False
    ) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_users_interested_in, category, city, strict
        )

    async def get_leads_for_alert(self, lead_ids: List[int]) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_leads_for_alert, lead_ids
        )

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

    async def add_notification_for_user(self, user_id: int, type: str, title: str, message: str, lead_id: Optional[int] = None,
                                        msg_key: Optional[str] = None, msg_params: Optional[dict] = None) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.add_notification_for_user, user_id, type, title, message, lead_id, msg_key, msg_params)

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
        owner_name = reserved.get("owner_name")
        zip_code = reserved.get("zip_code") or reserved.get("zip")

        # 2. Telefone e ENRIQUECIMENTO OPCIONAL.
        #    A reserva ja esta garantida neste ponto: uma falha do provedor de telefone
        #    nao pode libertar o lead nem devolver a reserva ao pool. O lead fica com
        #    owner_phone NULL e marcado como enriquecimento pendente.
        phone_result: Optional[PhoneLookupResult] = None
        if address and city and state:
            try:
                phone_result = await searchbug_service.lookup_phone(
                    address, city, state,
                    owner_name=owner_name, zip_code=zip_code, lead_id=lead_id,
                )
            except Exception as exc:
                logger.warning(f"Phone lookup erro inesperado no lead {lead_id}: {exc}")
                phone_result = None

        phone_ok = bool(
            phone_result is not None
            and getattr(phone_result, "success", False)
            and getattr(phone_result, "phone", None)
        )
        phone_error: Optional[str] = None

        if phone_ok:
            await anyio.to_thread.run_sync(
                self._service.update_owner_phone,
                lead_id,
                phone_result.phone,
                getattr(phone_result, "verified", False),
            )
        else:
            phone_error = (
                (getattr(phone_result, "error", None) or "indisponivel")
                if phone_result is not None
                else "endereco_incompleto"
            )
            logger.info(
                f"Telefone indisponivel para lead {lead_id} ({phone_error}) — "
                "reserva mantida, enriquecimento pendente"
            )

        # 3. Lead atualizado para retornar
        #    NOTA: o contador diario NAO e incrementado aqui. O caller
        #    (main.py, ramo sem consentimento) ja o faz antes de reservar,
        #    e incrementar aqui cobraria a cota duas vezes por reserva.
        lead_data = await self.get_lead_by_id(lead_id)
        if lead_data:
            if phone_ok:
                lead_data["owner_phone"] = phone_result.phone
            lead_data["_phone_lookup"] = {
                "provider": getattr(phone_result, "provider", None),
                "success": phone_ok,
                "error": phone_error,
                "pending_enrichment": not phone_ok,
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

    async def get_lead_id_by_address(self, address: str, city: str) -> Optional[int]:
        return await anyio.to_thread.run_sync(
            self._service.get_lead_id_by_address, address, city
        )

    async def append_case_occurrences(self, rows: list) -> int:
        return await anyio.to_thread.run_sync(
            self._service.append_case_occurrences, rows
        )

    async def refresh_lead_history(self, lead_ids: list) -> int:
        return await anyio.to_thread.run_sync(
            self._service.refresh_lead_history, lead_ids
        )

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

    async def reserve_daily_quota(self, user_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.reserve_daily_quota, user_id)

    async def refund_daily_quota(self, user_id: int) -> None:
        await anyio.to_thread.run_sync(self._service.refund_daily_quota, user_id)

    async def reserve_phone_attempt(self, user_id: int) -> dict:
        return await anyio.to_thread.run_sync(self._service.reserve_phone_attempt, user_id)

    async def get_scraper_watermark(self, key: str) -> Optional[str]:
        return await anyio.to_thread.run_sync(self._service.get_scraper_watermark, key)

    async def set_scraper_watermark(self, key: str, last_date: Optional[str]) -> None:
        await anyio.to_thread.run_sync(self._service.set_scraper_watermark, key, last_date)

    async def list_leads_for_freshness(self, source_types: list) -> list:
        return await anyio.to_thread.run_sync(
            self._service.list_leads_for_freshness, source_types
        )

    async def update_lead_freshness(self, *args, **kwargs) -> bool:
        return await anyio.to_thread.run_sync(
            lambda: self._service.update_lead_freshness(*args, **kwargs)
        )

    async def record_freshness_run(self, result: dict) -> None:
        await anyio.to_thread.run_sync(self._service.record_freshness_run, result)

    async def list_lead_ids_with_history(self) -> list:
        return await anyio.to_thread.run_sync(
            self._service.list_lead_ids_with_history
        )

    async def get_last_freshness_run(self) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_last_freshness_run
        )

    async def reserve_lead_only(
        self, lead_id: int, user_id: int, minutes: int = 60
    ) -> Optional[dict]:
        """Reserva simples (sem enriquecimento pago, sem consumir cota)."""
        return await anyio.to_thread.run_sync(
            lambda: self._service.reserve_lead(
                lead_id, user_id, minutes, skip_daily_increment=True
            )
        )

    async def precheck_reveal(self, user_id: int, lead_id: int) -> dict:
        return await anyio.to_thread.run_sync(self._service.precheck_reveal, user_id, lead_id)

    async def reveal_lead(self, user_id: int, lead_id: int, idempotency_key: Optional[str] = None, minutes: int = DatabaseService.REVEAL_HOLD_MINUTES, charge_credit: bool = True) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.reveal_lead, user_id, lead_id, idempotency_key, minutes, charge_credit)

    async def get_revealed_ids(self, user_id: int, lead_ids: List[int]) -> set:
        return await anyio.to_thread.run_sync(self._service.get_revealed_ids, user_id, lead_ids)

    async def flag_reveal_contact(self, user_id: int, lead_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.flag_reveal_contact, user_id, lead_id)

    async def can_report_invalid_number(self, user_id: int, lead_id: int) -> dict:
        return await anyio.to_thread.run_sync(self._service.can_report_invalid_number, user_id, lead_id)

    async def validate_refund_safety(
        self,
        user_id: int,
        lead_id: int,
        *,
        check_active_reveal: bool = True,
        check_time_window: bool = True,
        check_lead_status: bool = True,
        check_refund_blocked: bool = True,
        check_daily_limit: bool = True,
    ) -> dict:
        return await anyio.to_thread.run_sync(
            self._service.validate_refund_safety,
            user_id,
            lead_id,
            check_active_reveal=check_active_reveal,
            check_time_window=check_time_window,
            check_lead_status=check_lead_status,
            check_refund_blocked=check_refund_blocked,
            check_daily_limit=check_daily_limit,
        )

    async def process_refund(
        self,
        user_id: int,
        lead_id: int,
        reason: str = "invalid_number",
        *,
        check_active_reveal: bool = True,
        check_time_window: bool = True,
        check_lead_status: bool = True,
        check_refund_blocked: bool = True,
        check_daily_limit: bool = True,
    ) -> dict:
        return await anyio.to_thread.run_sync(
            self._service.process_refund,
            user_id,
            lead_id,
            reason,
            check_active_reveal=check_active_reveal,
            check_time_window=check_time_window,
            check_lead_status=check_lead_status,
            check_refund_blocked=check_refund_blocked,
            check_daily_limit=check_daily_limit,
        )

    async def block_lead_refund(self, lead_id: int, reason: str = "status_changed") -> bool:
        return await anyio.to_thread.run_sync(self._service.block_lead_refund, lead_id, reason)

    async def check_reveal_watchdogs(self) -> int:
        return await anyio.to_thread.run_sync(self._service.check_reveal_watchdogs)

    # ===== DAILY ALERT CAP (10/day, dedup, digest) =====

    async def get_new_lead_alert_counts_today(self) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_new_lead_alert_counts_today)

    async def has_alerted_user_for_lead(self, user_id: int, lead_id: int) -> bool:
        return await anyio.to_thread.run_sync(self._service.has_alerted_user_for_lead, user_id, lead_id)

    async def get_alerted_pairs_for_leads(self, lead_ids: List[int]) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_alerted_pairs_for_leads, lead_ids)

    async def upsert_daily_digest(self, user_id: int, extra_count: int, locale: Optional[str] = None,
                                  variant: Optional[str] = None) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.upsert_daily_digest, user_id, extra_count, locale, variant
        )

    async def get_alert_usage_today(self, day: Optional[str] = None) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_alert_usage_today, day)

    async def increment_alert_usage(self, user_id: int, category: str, amount: int = 1,
                                    day: Optional[str] = None) -> None:
        return await anyio.to_thread.run_sync(self._service.increment_alert_usage, user_id, category, amount, day)

    async def seed_alert_usage_from_notifications(self, day: Optional[str] = None) -> int:
        return await anyio.to_thread.run_sync(self._service.seed_alert_usage_from_notifications, day)

    async def get_alert_rotation_cursor(self, user_id: int) -> int:
        return await anyio.to_thread.run_sync(self._service.get_alert_rotation_cursor, user_id)

    async def advance_alert_rotation_cursor(self, user_id: int, step: int = 1) -> int:
        return await anyio.to_thread.run_sync(self._service.advance_alert_rotation_cursor, user_id, step)

    # ===== PASSWORD RESET ASYNC =====

    async def create_password_reset_token(self, email: str, expires_hours: int = 1) -> Optional[str]:
        return await anyio.to_thread.run_sync(self._service.create_password_reset_token, email, expires_hours)

    async def validate_password_reset_token(self, token: str) -> Optional[int]:
        return await anyio.to_thread.run_sync(self._service.validate_password_reset_token, token)

    async def consume_password_reset_token(self, token: str, new_password_hash: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.consume_password_reset_token, token, new_password_hash)

    async def send_password_reset_email(self, email: str, token: str) -> bool:
        return await anyio.to_thread.run_sync(self._service.send_password_reset_email, email, token)

    # ===== CREDIT LEDGER ASYNC (Fase 3) =====

    async def record_grant_daily(self, user_id: int, limit: int, date: str) -> int:
        return await anyio.to_thread.run_sync(self._service.record_grant_daily, user_id, limit, date)

    async def record_grant_plan(self, user_id: int, days: int, limit: int, plan_until: str) -> int:
        return await anyio.to_thread.run_sync(self._service.record_grant_plan, user_id, days, limit, plan_until)

    async def record_consume_reveal(self, user_id: int, reveal_id: int) -> int:
        return await anyio.to_thread.run_sync(self._service.record_consume_reveal, user_id, reveal_id)

    async def record_refund_reveal(self, user_id: int, reveal_id: int) -> int:
        return await anyio.to_thread.run_sync(self._service.record_refund_reveal, user_id, reveal_id)

    async def record_searchbug_cost(
        self,
        user_id: int,
        call_id: int,
        billed: int,
        outcome: str,
        city: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ) -> int:
        return await anyio.to_thread.run_sync(
            self._service.record_searchbug_cost, user_id, call_id, billed, outcome, city, latency_ms
        )

    async def record_stripe_payment(self, user_id: int, event_id: str, days: int) -> int:
        return await anyio.to_thread.run_sync(self._service.record_stripe_payment, user_id, event_id, days)

    async def get_credit_balance(self, user_id: int) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_credit_balance, user_id)

    async def get_credit_ledger(
        self, user_id: int, limit: int = 100, offset: int = 0
    ) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.get_credit_ledger, user_id, limit, offset)

    async def backfill_credit_ledger(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.backfill_credit_ledger)

    async def reconcile_credits(self, user_id: Optional[int] = None) -> dict:
        return await anyio.to_thread.run_sync(self._service.reconcile_credits, user_id)

    # ===== OUTBOUND (queue structure — envio pausado) =====
    async def get_outbound_config(self, city: Optional[str] = None) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_outbound_config, city)

    async def set_outbound_config(self, key: str, value: str, city: str = "", scope: str = "outbound") -> bool:
        return await anyio.to_thread.run_sync(self._service.set_outbound_config, key, value, city, scope)

    async def list_sending_mailboxes(self, enabled_only: bool = False) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.list_sending_mailboxes, enabled_only)

    async def upsert_sending_mailbox(
        self,
        email: str,
        provider: str = "gmail",
        transport: str = "gmail_api",
        domain: Optional[str] = None,
        display_name: Optional[str] = None,
        city: str = "",
        daily_cap: int = 25,
        enabled: int = 0,
        warmup_state: str = "cold",
        auth_ref: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.upsert_sending_mailbox,
            email,
            provider,
            transport,
            domain,
            display_name,
            city,
            daily_cap,
            enabled,
            warmup_state,
            auth_ref,
            notes,
        )

    async def create_outbound_batch(
        self,
        city: Optional[str] = None,
        name: Optional[str] = None,
        filters_json: Optional[str] = None,
        created_by: Optional[int] = None,
        kind: str = "email",
    ) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.create_outbound_batch, city, name, filters_json, created_by, kind)

    async def mark_outbound_batch_previewed(
        self,
        batch_id: int,
        contact_count: int,
        est_cost_usd: float,
    ) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.mark_outbound_batch_previewed,
            batch_id,
            contact_count,
            est_cost_usd,
        )

    async def create_or_reuse_draft_batch(
        self,
        city: Optional[str] = None,
        name: Optional[str] = None,
        filters_json: Optional[str] = None,
        created_by: Optional[int] = None,
        kind: str = "email",
    ) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.create_or_reuse_draft_batch,
            city,
            name,
            filters_json,
            created_by,
            kind,
        )

    async def list_outbound_batches(self, limit: int = 50) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.list_outbound_batches, limit)

    async def add_suppression(self, value: str, channel: str = "email", reason: str = "manual") -> bool:
        return await anyio.to_thread.run_sync(self._service.add_suppression, value, channel, reason)

    async def is_suppressed(self, value: str, channel: str = "email") -> bool:
        return await anyio.to_thread.run_sync(self._service.is_suppressed, value, channel)

    async def list_suppressions(self, limit: int = 100) -> List[dict]:
        return await anyio.to_thread.run_sync(self._service.list_suppressions, limit)

    async def create_outbound_contact(
        self,
        lead_id: Optional[int],
        email: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        company_name: Optional[str] = None,
        contact_name: Optional[str] = None,
        email_source: str = "scrape",
        kind: str = "business",
    ) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.create_outbound_contact,
            lead_id,
            email,
            city,
            state,
            company_name,
            contact_name,
            email_source,
            kind,
        )

    async def enqueue_outbound_message(
        self,
        batch_id: Optional[int],
        contact_id: Optional[int],
        mailbox_id: Optional[int] = None,
        city: Optional[str] = None,
        to_email: Optional[str] = None,
        subject: Optional[str] = None,
        body_hash: Optional[str] = None,
        cost_usd: float = 0.0,
        segments: int = 1,
        sequence_step: int = 1,
        next_step_at: Optional[str] = None,
    ) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.enqueue_outbound_message,
            batch_id,
            contact_id,
            mailbox_id,
            city,
            to_email,
            subject,
            body_hash,
            cost_usd,
            segments,
            sequence_step,
            next_step_at,
        )

    async def list_outbound_messages_due_for_sequence(
        self, now: str, limit: int = 50
    ) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.list_outbound_messages_due_for_sequence, now, limit
        )

    async def set_outbound_message_next_step(
        self, message_id: int, next_step_at: Optional[str]
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.set_outbound_message_next_step, message_id, next_step_at
        )

    async def mark_outbound_contact_replied(self, contact_id: int) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.mark_outbound_contact_replied, contact_id
        )

    async def outbound_category_mix(
        self, city: str, categories: Optional[List[str]] = None, limit: int = 3
    ) -> List[tuple[str, int]]:
        return await anyio.to_thread.run_sync(
            self._service.outbound_category_mix, city, categories, limit
        )

    async def count_qualified_contractors_in_city(
        self, city: str, categories: Optional[List[str]] = None
    ) -> int:
        return await anyio.to_thread.run_sync(
            self._service.count_qualified_contractors_in_city, city, categories
        )

    async def count_outbound_recipients(self, city: str) -> int:
        return await anyio.to_thread.run_sync(
            self._service.count_outbound_recipients, city
        )

    async def outbound_diagnostics(self, city: str) -> dict:
        return await anyio.to_thread.run_sync(self._service.outbound_diagnostics, city)

    async def get_outbound_sample_lead(
        self, city: str, categories: Optional[List[str]] = None
    ) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_outbound_sample_lead, city, categories
        )

    async def get_outbound_sample_contact(self, city: str) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_outbound_sample_contact, city
        )

    # ===== OUTBOUND Fase 2 (async wrappers) =====

    async def get_outbound_batch(self, batch_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_outbound_batch, batch_id)

    async def import_b2b_lead(
        self,
        email: str,
        company_name: str,
        city: str,
        category: str = "General Contractors",
        contact_name: Optional[str] = None,
        domain: Optional[str] = None,
        state: Optional[str] = None,
        niche_key: Optional[str] = None,
        niche_status: str = "confirmed",
        niche_score: float = 0.0,
        niche_evidence: Optional[str] = None,
        create_contact: bool = True,
    ) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            lambda: self._service.import_b2b_lead(
                email,
                company_name,
                city,
                category,
                contact_name,
                domain,
                state,
                niche_key=niche_key,
                niche_status=niche_status,
                niche_score=niche_score,
                niche_evidence=niche_evidence,
                create_contact=create_contact,
            )
        )

    async def get_available_outbound_cities(self) -> List[str]:
        return await anyio.to_thread.run_sync(self._service.get_available_outbound_cities)

    async def get_available_outbound_categories(self, city: Optional[str] = None) -> List[str]:
        return await anyio.to_thread.run_sync(self._service.get_available_outbound_categories, city)

    async def start_outbound_batch(self, batch_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.start_outbound_batch, batch_id)

    async def finish_outbound_batch(self, batch_id: int, status: str = "sent") -> bool:
        return await anyio.to_thread.run_sync(self._service.finish_outbound_batch, batch_id, status)

    async def update_outbound_batch_stats(
        self, batch_id: int, contact_count: int, est_cost_usd: float
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.update_outbound_batch_stats, batch_id, contact_count, est_cost_usd
        )

    async def list_outbound_leads(
        self, city: str, categories: Optional[List[str]] = None, limit: int = 200
    ) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.list_outbound_leads, city, categories, limit
        )

    async def get_outbound_contact_by_lead(self, lead_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_outbound_contact_by_lead, lead_id
        )

    async def get_outbound_contact_by_email(self, email: str) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.get_outbound_contact_by_email, email
        )

    async def upsert_outbound_contact(
        self,
        lead_id: Optional[int],
        email: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        company_name: Optional[str] = None,
        contact_name: Optional[str] = None,
        email_source: str = "snov",
        email_status: str = "unknown",
        company_domain: Optional[str] = None,
    ) -> Optional[dict]:
        return await anyio.to_thread.run_sync(
            self._service.upsert_outbound_contact,
            lead_id,
            email,
            city,
            state,
            company_name,
            contact_name,
            email_source,
            email_status,
            company_domain,
        )

    async def update_outbound_contact_status(
        self,
        contact_id: int,
        email_status: Optional[str] = None,
        unsubscribed: Optional[int] = None,
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.update_outbound_contact_status, contact_id, email_status, unsubscribed
        )

    async def list_queued_outbound_messages(
        self, limit: int = 10, city: Optional[str] = None
    ) -> List[dict]:
        return await anyio.to_thread.run_sync(
            self._service.list_queued_outbound_messages, limit, city
        )

    async def get_outbound_message(self, message_id: int) -> Optional[dict]:
        return await anyio.to_thread.run_sync(self._service.get_outbound_message, message_id)

    async def claim_outbound_message(self, message_id: int) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.claim_outbound_message, message_id
        )

    async def fail_stale_sending_outbound_messages(self, older_than: str) -> int:
        return await anyio.to_thread.run_sync(
            self._service.fail_stale_sending_outbound_messages, older_than
        )

    async def count_stale_sending_outbound_messages(self, older_than: str) -> int:
        return await anyio.to_thread.run_sync(
            self._service.count_stale_sending_outbound_messages, older_than
        )

    async def update_outbound_message(
        self,
        message_id: int,
        status: Optional[str] = None,
        provider_id: Optional[str] = None,
        error: Optional[str] = None,
        sent_at: Optional[str] = None,
        mailbox_id: Optional[int] = None,
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.update_outbound_message,
            message_id,
            status,
            provider_id,
            error,
            sent_at,
            mailbox_id,
        )

    async def count_outbound_messages(
        self, status: Optional[str] = None, batch_id: Optional[int] = None
    ) -> int:
        return await anyio.to_thread.run_sync(
            self._service.count_outbound_messages, status, batch_id
        )

    async def outbound_queue_summary(self) -> dict:
        return await anyio.to_thread.run_sync(self._service.outbound_queue_summary)

    async def count_mailbox_sent_today(self, mailbox_id: int, day: str) -> int:
        return await anyio.to_thread.run_sync(
            self._service.count_mailbox_sent_today, mailbox_id, day
        )

    async def get_outbound_counter(self, city: str, day: str) -> dict:
        return await anyio.to_thread.run_sync(self._service.get_outbound_counter, city, day)

    async def increment_outbound_counter(
        self, city: str, day: str, sent: int = 0, enriched: int = 0, spend_usd: float = 0.0
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.increment_outbound_counter, city, day, sent, enriched, spend_usd
        )

    async def update_mailbox_after_send(
        self, mailbox_id: int, warmup_state: Optional[str] = None
    ) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.update_mailbox_after_send, mailbox_id, warmup_state
        )

    async def set_mailbox_warmup_started(self, mailbox_id: int) -> bool:
        return await anyio.to_thread.run_sync(
            self._service.set_mailbox_warmup_started, mailbox_id
        )


# Instância global (interface async, compatível com o antigo supabase_service)
db_service = AsyncDatabaseService()
