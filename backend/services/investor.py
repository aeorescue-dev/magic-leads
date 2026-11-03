"""Investor Room — motor de valuation patrimonial, proof e simulador (Fase 30).

Read-only sobre `leads.db`/`analytics.db`; escreve apenas em `investor.db`.
Nenhum PII é persistido nos snapshots. O preço de tabela é um weekly pass de
$120/7 dias; a normalização mensal usa 52/12 (não 4 semanas).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from ..config import settings
from ..utils.logger import logger
from . import analytics
from .db import get_connection

VERSION = "2026-11-02.14"
NDA_VERSION = "investor-nda-2026-11-02"
PRICE_WEEKLY = 120.0
WEEKS_PER_YEAR = 52.0
MONTHLY_FACTOR = WEEKS_PER_YEAR / 12.0
MRR_PER_PASS = PRICE_WEEKLY * MONTHLY_FACTOR
ARR_PER_PASS = MRR_PER_PASS * 12.0

# ---------------------------------------------------------------------------
# Claims Register — cada afirmação concorrencial tem de ter fonte, data e
# citação. Nada de preços ou acurácias inventadas. As fontes oficiais são da
# Angi/FTC; a estimativa de terceiros vai marcada como tal.
# ---------------------------------------------------------------------------
CLAIMS_VERSION = "claims-2026-11-02"
CLAIMS_CAPTURED_AT = "2026-11-02"

CLAIMS_REGISTER: list[dict[str, Any]] = [
    {
        "id": "ANGI-SHARED-5",
        "topic": "exclusividade",
        "title": "Pedido partilhado com até 5 profissionais",
        "our_position": "1 negócio por endereço/cidade; o lead não é revendido.",
        "competitor_position": "Cada pedido é combinado com no máximo 5 profissionais.",
        "competitor": "Angi",
        "source_title": "Opportunities and Leads: Frequently Asked Questions",
        "source_publisher": "Angi Help Center",
        "source_url": (
            "https://intercom.help/angi/en/articles/6221483-opportunities-and-"
            "leads-frequently-asked-questions"
        ),
        "source_date": "2026-04-20",
        "captured_at": CLAIMS_CAPTURED_AT,
        "status": "verified",
        "quote": (
            "Each time a homeowner submits a project request, we will match them "
            "with no more than five pros."
        ),
        "note": "FAQ oficial da Angi; consultada em 02/11/2026.",
    },
    {
        "id": "ANGI-PAY-NO-WIN",
        "topic": "cobrança",
        "title": "Paga o lead mesmo sem fechar o negócio",
        "our_position": "O passe semanal dá acesso; não há taxa por lead perdido.",
        "competitor_position": "O profissional paga o lead mesmo que não ganhe o trabalho.",
        "competitor": "Angi",
        "source_title": "Angi Pro Agreement — FAQ",
        "source_publisher": "Angi Pro (HomeAdvisor, Inc.)",
        "source_url": "https://angiads.pactsafe.io/versions/6ac568925ab7ef3fa4859c92.pdf",
        "source_date": "2026-10-06",
        "captured_at": CLAIMS_CAPTURED_AT,
        "status": "verified",
        "quote": (
            "Yes. You will pay for the leads you receive, even if you do not win "
            "the job. Leads are not guaranteed jobs."
        ),
        "note": "Contrato oficial atualizado em 06/10/2026.",
    },
    {
        "id": "ANGI-NOT-EXCLUSIVE",
        "topic": "exclusividade",
        "title": "Contrato não exclusivo",
        "our_position": "Exclusividade por endereço/cidade no nosso modelo de dados.",
        "competitor_position": "A Angi pode contratar e apresentar outros profissionais.",
        "competitor": "Angi",
        "source_title": "Angi Pro Agreement — Competition",
        "source_publisher": "Angi Pro (HomeAdvisor, Inc.)",
        "source_url": "https://angiads.pactsafe.io/versions/6ac568925ab7ef3fa4859c92.pdf",
        "source_date": "2026-10-06",
        "captured_at": CLAIMS_CAPTURED_AT,
        "status": "verified",
        "quote": (
            "Angi is free to contract with other Pros as this is not an "
            "exclusive contract."
        ),
        "note": "Cláusula de concorrência do contrato oficial.",
    },
    {
        "id": "ANGI-NO-GUARANTEE",
        "topic": "qualidade",
        "title": "Sem garantia de volume ou de fecho",
        "our_position": "Métricas de qualidade publicadas (Truth Score + Phone Truth).",
        "competitor_position": "Sem garantia de quantos leads ou trabalhos o profissional recebe.",
        "competitor": "Angi",
        "source_title": "Angi Pro Agreement — FAQ",
        "source_publisher": "Angi Pro (HomeAdvisor, Inc.)",
        "source_url": "https://angiads.pactsafe.io/versions/6ac568925ab7ef3fa4859c92.pdf",
        "source_date": "2026-10-06",
        "captured_at": CLAIMS_CAPTURED_AT,
        "status": "verified",
        "quote": (
            "No, we do not make any warranties about our services, including how "
            "many leads you will receive or how many jobs you will win."
        ),
        "note": "FAQ do contrato oficial.",
    },
    {
        "id": "ANGI-PRICE-VARIES",
        "topic": "preço",
        "title": "Preço por lead não publicado",
        "our_position": "Tabela pública: $120 por 7 dias.",
        "competitor_position": "A taxa por lead varia por tarefa, localização e demanda.",
        "competitor": "Angi",
        "source_title": "Opportunities and Leads: Frequently Asked Questions",
        "source_publisher": "Angi Help Center",
        "source_url": (
            "https://intercom.help/angi/en/articles/6221483-opportunities-and-"
            "leads-frequently-asked-questions"
        ),
        "source_date": "2026-04-20",
        "captured_at": CLAIMS_CAPTURED_AT,
        "status": "verified",
        "quote": (
            "Lead fees change based on task, homeowner location, and demand for "
            "the work."
        ),
        "note": "A Angi não publica tarifa única por lead.",
    },
    {
        "id": "ANGI-ETF",
        "topic": "contrato",
        "title": "Taxa de cancelamento antecipado",
        "our_position": "Passe de 7 dias, sem fidelização.",
        "competitor_position": "Pode existir ETF definida no contrato de onboarding.",
        "competitor": "Angi",
        "source_title": "Angi Pro Agreement — FAQ",
        "source_publisher": "Angi Pro (HomeAdvisor, Inc.)",
        "source_url": "https://angiads.pactsafe.io/versions/6ac568925ab7ef3fa4859c92.pdf",
        "source_date": "2026-10-06",
        "captured_at": CLAIMS_CAPTURED_AT,
        "status": "verified",
        "quote": (
            "An ETF is an Early Termination Fee, which, if applicable, will be "
            "set forth in the Contract you sign during your onboarding with Angi."
        ),
        "note": "A ETF depende do contrato específico de cada profissional.",
    },
    {
        "id": "FTC-LEADS-7.2M",
        "topic": "qualidade",
        "title": "FTC: ordem de $7,2M por marketing enganoso de leads",
        "our_position": "Publicamos limitações e erros cobrados em vez de prometer precisão.",
        "competitor_position": "HomeAdvisor/Angi foi ordenada a pagar até $7,2M por práticas enganosas.",
        "competitor": "Angi / HomeAdvisor",
        "source_title": (
            "FTC Order Requires HomeAdvisor to Pay Up To $7.2 Million and Stop "
            "Deceptively Marketing its Leads"
        ),
        "source_publisher": "Federal Trade Commission",
        "source_url": (
            "https://www.ftc.gov/news-events/news/press-releases/2023/01/"
            "ftc-order-requires-homeadvisor-pay-72-million-stop-deceptively-"
            "marketing-its-leads-home-improvement"
        ),
        "source_date": "2023-01-23",
        "captured_at": CLAIMS_CAPTURED_AT,
        "status": "verified",
        "quote": (
            "pay up to $7.2 million for using a wide range of deceptive and "
            "misleading tactics in selling home improvement project leads"
        ),
        "note": "A ordem final foi aprovada em abril de 2023.",
    },
    {
        "id": "FTC-MEMBERSHIP-FEE",
        "topic": "preço",
        "title": "Membresia anual + taxa por lead",
        "our_position": "Um único passe semanal, sem membresia anual.",
        "competitor_position": "Em 2023, a FTC registou membresia anual de $287,99 mais taxa por lead.",
        "competitor": "Angi / HomeAdvisor",
        "source_title": (
            "FTC Order Requires HomeAdvisor to Pay Up To $7.2 Million and Stop "
            "Deceptively Marketing its Leads"
        ),
        "source_publisher": "Federal Trade Commission",
        "source_url": (
            "https://www.ftc.gov/news-events/news/press-releases/2023/01/"
            "ftc-order-requires-homeadvisor-pay-72-million-stop-deceptively-"
            "marketing-its-leads-home-improvement"
        ),
        "source_date": "2023-01-23",
        "captured_at": CLAIMS_CAPTURED_AT,
        "status": "verified",
        "quote": (
            "annual membership fee of $287.99, in addition to a separate fee for "
            "each lead they receive"
        ),
        "note": "Valor histórico de 2023; a estrutura atual pode variar.",
    },
    {
        "id": "ANGI-ESTIMATE-15-85",
        "topic": "preço",
        "title": "Estimativa de terceiros: $15–$85 por lead",
        "our_position": "Preço publicado e previsível: $120/semana.",
        "competitor_position": "Estimativa de terceiros para o custo por lead da Angi.",
        "competitor": "Angi",
        "source_title": "Is Angi Worth It for Contractors? Angi Leads Cost and Terms (2026)",
        "source_publisher": "Sesklo (terceiro)",
        "source_url": "https://www.sesklo.com/for-service-providers/compare/angi",
        "source_date": "2026-10-05",
        "captured_at": CLAIMS_CAPTURED_AT,
        "status": "estimate",
        "quote": "Third-party estimate: $15–$85 a lead",
        "note": "Não é fonte oficial da Angi; apresentado apenas como faixa indicativa.",
    },
    {
        "id": "ANGI-SCALE-1.5M",
        "topic": "escala",
        "title": "Escala do marketplace",
        "our_position": "107.960 registos proprietários; 84.632 owners identificados.",
        "competitor_position": "Mais de 1,5M de oportunidades na Angi no último mês.",
        "competitor": "Angi",
        "source_title": "Angi Pro — Get Leads, Win Jobs",
        "source_publisher": "Angi",
        "source_url": "https://signup.angi.com/pro",
        "source_date": "consultado 2026-11-02",
        "captured_at": CLAIMS_CAPTURED_AT,
        "status": "verified",
        "quote": "Over 1.5M opportunities on Angi last month",
        "note": "Página oficial de aquisição de profissionais.",
    },
]

COMPETITIVE_MATRIX: list[dict[str, Any]] = [
    {
        "dimension": "Custo por lead",
        "magic": "Passe de $120/semana; sem taxa por lead",
        "angi": "Não publicado; varia por tarefa, localização e demanda",
        "edge": "magic",
        "source_ids": ["ANGI-PRICE-VARIES", "ANGI-ESTIMATE-15-85"],
    },
    {
        "dimension": "Exclusividade",
        "magic": "1 negócio por endereço/cidade",
        "angi": "Pedido partilhado com até 5 profissionais",
        "edge": "magic",
        "source_ids": ["ANGI-SHARED-5", "ANGI-NOT-EXCLUSIVE"],
    },
    {
        "dimension": "Cobrança sem fechar",
        "magic": "Sem taxa por lead perdido",
        "angi": "Paga o lead mesmo sem ganhar o trabalho",
        "edge": "magic",
        "source_ids": ["ANGI-PAY-NO-WIN"],
    },
    {
        "dimension": "Transparência de preço",
        "magic": "Tabela pública: $120 / 7 dias",
        "angi": "Preço por cotação; sem tarifa pública",
        "edge": "magic",
        "source_ids": ["ANGI-PRICE-VARIES"],
    },
    {
        "dimension": "Margem",
        "magic": "90%+ alvo com COGS variável controlado",
        "angi": "n/d; margem por lead não divulgada",
        "edge": "neutral",
        "source_ids": ["ANGI-PRICE-VARIES"],
    },
    {
        "dimension": "Fidelização",
        "magic": "Passe de 7 dias, sem fidelização",
        "angi": "Contrato com renovação; ETF conforme contrato",
        "edge": "magic",
        "source_ids": ["ANGI-ETF"],
    },
    {
        "dimension": "Propriedade do ativo",
        "magic": "Base e pipeline proprietários",
        "angi": "Marketplace de leads por pedido",
        "edge": "neutral",
        "source_ids": ["ANGI-SCALE-1.5M"],
    },
    {
        "dimension": "Qualidade / acurácia",
        "magic": "Truth Score e Phone Truth publicados",
        "angi": "Sem métrica pública; FTC exigiu cessar claims não substanciados",
        "edge": "magic",
        "source_ids": ["FTC-LEADS-7.2M", "ANGI-NO-GUARANTEE"],
    },
]

DEFAULT_ASSUMPTIONS: dict[str, Any] = {
    "version": VERSION,
    "approved_by": "Gate 0 — 2026-11-02",
    "approved_at": "2026-11-02T00:00:00+00:00",
    "ticket_price_weekly": PRICE_WEEKLY,
    "billing_interval_days": 7,
    "weeks_per_year": WEEKS_PER_YEAR,
    "monthlyization_factor": MONTHLY_FACTOR,
    "normalized_mrr_per_pass": MRR_PER_PASS,
    "arr_per_pass": ARR_PER_PASS,
    "monthly_churn": 0.08,
    "payment_fee_pct": 0.029,
    "payment_fee_fixed": 0.30,
    "searchbug_cost_per_success": 0.52,
    "reveals_per_contractor_month": 2,
    "infra_fixed_monthly": 150.0,
    "infra_per_mailbox": 10.0,
    "infra_per_city": 25.0,
    "opex_monthly": 0.0,
    "multiple_low": 2.0,
    "multiple_base": 3.5,
    "multiple_high": 8.0,
    "replacement_owner_low": 0.50,
    "replacement_owner_high": 1.50,
    "ip_months_low": 12,
    "ip_months_high": 18,
    "ip_rate_low": 8000.0,
    "ip_rate_high": 15000.0,
    "compliance_low": 10000.0,
    "compliance_high": 25000.0,
    "nda_version": NDA_VERSION,
    "code_inventory": {
        "python_lines": 60968,
        "typescript_lines": 21445,
        "pytest_tests": 1311,
        "vitest_tests": 109,
        "test_files": 121,
        "docs": 19,
        "coverage_backend_pct": 70.0,
        "coverage_measured_at": "2026-11-02",
        "coverage_command": "pytest tests --cov=backend --cov-report=json:coverage.json",
        "coverage_modules": {
            "models/schemas.py": 98.6,
            "outbound_templates.py": 93.9,
            "mailbox_guard.py": 94.0,
            "auto_ramp.py": 92.7,
            "inbox_sync.py": 50.0,
            "enrichment.py": 50.2,
            "control_tower.py": 51.6,
        },
        "ci": "GitHub Actions (pytest + tsc + next build)",
        "portability": (
            "Docker, SQLite WAL, variáveis de ambiente, Next.js/Vercel; "
            "adaptadores de fontes públicas sem dados licenciados."
        ),
        "known_debt": [
            "SQLite single-writer (mitigado por analytics.db/investor.db separados)",
            "db.py monolítico (~12,7k linhas) — modularização planeada",
            "notificações legacy sem msg_key (217)",
            "MAILBOX_SECRET_KEY/auth_ref a confirmar",
            "Resend/DKIM/DMARC pendente",
            "Searchbug: 24 erros cobrados em 30d — reconciliar",
        ],
    },
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at TEXT NOT NULL,
  version TEXT NOT NULL,
  checksum TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_at ON snapshots (captured_at);
CREATE TABLE IF NOT EXISTS assumptions (
  version TEXT PRIMARY KEY,
  approved_by TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  assumptions_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nda_acceptances (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  email TEXT,
  version TEXT NOT NULL,
  accepted_at TEXT DEFAULT CURRENT_TIMESTAMP,
  ip_hash TEXT,
  user_agent TEXT,
  UNIQUE(user_id, version)
);
CREATE TABLE IF NOT EXISTS access_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  email TEXT,
  action TEXT NOT NULL,
  resource TEXT,
  ip_hash TEXT,
  user_agent TEXT,
  at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reconciliation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at TEXT NOT NULL,
  access_passes INTEGER,
  pro_active INTEGER,
  verified_paid_passes INTEGER,
  cash_30d_usd REAL,
  cash_total_usd REAL,
  status TEXT,
  details_json TEXT
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

_LOCK = threading.Lock()
_INIT = {"path": None}
_CACHE: dict[str, tuple[float, dict]] = {}


def db_path() -> str:
    override = (os.getenv("INVESTOR_DB_PATH") or "").strip()
    if override:
        return override
    data_dir = (os.getenv("DATA_DIR") or "/data").strip()
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.getcwd(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "investor.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


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
            row = conn.execute(
                "SELECT version FROM assumptions WHERE version=?", (VERSION,)
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO assumptions (version, approved_by, assumptions_json) "
                    "VALUES (?, ?, ?)",
                    (VERSION, DEFAULT_ASSUMPTIONS["approved_by"],
                     json.dumps(DEFAULT_ASSUMPTIONS, ensure_ascii=False)),
                )
            conn.commit()
        finally:
            conn.close()
        _INIT["path"] = path


def assumptions() -> dict:
    init()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT assumptions_json FROM assumptions WHERE version=?",
            (VERSION,),
        ).fetchone()
        if row:
            data = json.loads(row["assumptions_json"])
            merged = dict(DEFAULT_ASSUMPTIONS)
            merged.update(data)
            return merged
    finally:
        conn.close()
    return dict(DEFAULT_ASSUMPTIONS)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hs(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return hashlib.sha256(text.encode()).hexdigest()[:24] if text else None


def _stripe_cash() -> dict:
    """Cash real via Stripe (read-only). Fail-soft: nunca derruba o snapshot."""
    key = (getattr(settings, "STRIPE_API_KEY", "") or "").strip()
    if not key:
        return {"status": "not_configured", "cash_30d": None, "cash_total": None}
    mode = "test" if key.startswith("sk_test_") else "live"
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(
                "https://api.stripe.com/v1/charges",
                params={"limit": 100},
                auth=(key, ""),
            )
        if resp.status_code != 200:
            return {
                "status": "error",
                "http_status": resp.status_code,
                "mode": mode,
                "cash_30d": None,
                "cash_total": None,
            }
        data = resp.json()
        charges = data.get("data") or []
        cutoff = (_utc_now() - timedelta(days=30)).timestamp()
        total = 0.0
        recent = 0.0
        count = 0
        for charge in charges:
            if not charge.get("paid") or charge.get("status") != "succeeded":
                continue
            if charge.get("refunded"):
                continue
            amount = float(charge.get("amount") or 0) / 100.0
            total += amount
            count += 1
            if float(charge.get("created") or 0) >= cutoff:
                recent += amount
        return {
            "status": "ok",
            "mode": mode,
            "cash_30d": round(recent, 2),
            "cash_total": round(total, 2),
            "charges": count,
            "has_more": bool(data.get("has_more")),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[INVESTOR] Stripe indisponível: %s", type(exc).__name__)
        return {
            "status": "unavailable",
            "mode": mode,
            "cash_30d": None,
            "cash_total": None,
        }


def _gather() -> dict:
    conn = get_connection()
    try:
        def one(sql: str, params: tuple = ()):
            return conn.execute(sql, params).fetchone()

        users = {
            "total": int(one("SELECT COUNT(*) FROM users")[0] or 0),
            "pro_active": int(one(
                "SELECT COUNT(*) FROM users WHERE plan='pro' AND subscription_status='active'"
            )[0] or 0),
            "access_active": int(one(
                "SELECT COUNT(*) FROM users WHERE plan='pro' AND subscription_status='active' "
                "AND plan_until IS NOT NULL AND datetime(plan_until) > datetime('now')"
            )[0] or 0),
            "trialing": int(one(
                "SELECT COUNT(*) FROM users WHERE subscription_status IN ('trial','trialing')"
            )[0] or 0),
        }
        checkout = {
            "completed": int(one(
                "SELECT COUNT(*) FROM checkout_sessions WHERE status='completed'"
            )[0] or 0),
            "expired": int(one(
                "SELECT COUNT(*) FROM checkout_sessions WHERE status='expired'"
            )[0] or 0),
            "completed_30d": int(one(
                "SELECT COUNT(*) FROM checkout_sessions WHERE status='completed' "
                "AND created_at >= datetime('now','-30 days')"
            )[0] or 0),
            "completed_cents": int(one(
                "SELECT COALESCE(SUM(amount_cents),0) FROM checkout_sessions WHERE status='completed'"
            )[0] or 0),
        }
        stripe_events = {
            "completed": int(one(
                "SELECT COUNT(*) FROM stripe_events WHERE event_type='checkout.session.completed'"
            )[0] or 0),
            "expired": int(one(
                "SELECT COUNT(*) FROM stripe_events WHERE event_type='checkout.session.expired'"
            )[0] or 0),
        }
        leads = dict(one(
            """
            SELECT COUNT(*) total,
              SUM(CASE WHEN COALESCE(TRIM(owner_name),'')<>'' THEN 1 ELSE 0 END) owners,
              SUM(CASE WHEN COALESCE(TRIM(address),'')<>'' THEN 1 ELSE 0 END) addresses,
              SUM(CASE WHEN COALESCE(TRIM(owner_phone),'')<>'' THEN 1 ELSE 0 END) phones,
              SUM(CASE WHEN COALESCE(TRIM(owner_email),'')<>'' THEN 1 ELSE 0 END) emails,
              SUM(CASE WHEN date_reported >= datetime('now','-7 days') THEN 1 ELSE 0 END) fresh7,
              SUM(CASE WHEN date_reported >= datetime('now','-30 days') THEN 1 ELSE 0 END) fresh30,
              SUM(CASE WHEN source_type IS NOT NULL AND external_id IS NOT NULL THEN 1 ELSE 0 END) provenance
            FROM leads
            """
        ))
        cities = [dict(r) for r in conn.execute(
            """
            SELECT UPPER(TRIM(city)) city, COUNT(*) total,
              SUM(CASE WHEN COALESCE(TRIM(owner_name),'')<>'' THEN 1 ELSE 0 END) owners,
              SUM(CASE WHEN date_reported >= datetime('now','-7 days') THEN 1 ELSE 0 END) fresh7
            FROM leads GROUP BY 1 ORDER BY total DESC
            """
        ).fetchall()]
        entities = {
            str(r["status"]): int(r["c"] or 0)
            for r in conn.execute(
                "SELECT status, COUNT(*) c FROM contractor_entities GROUP BY status"
            ).fetchall()
        }
        contacts = {
            str(r["email_status"]): int(r["c"] or 0)
            for r in conn.execute(
                "SELECT email_status, COUNT(*) c FROM outbound_contacts GROUP BY email_status"
            ).fetchall()
        }
        reveals = dict(one(
            "SELECT COUNT(*) total, "
            "SUM(CASE WHEN refunded=1 THEN 1 ELSE 0 END) refunded "
            "FROM lead_reveals WHERE revealed_date >= date('now','-30 days')"
        ))
        searchbug = {
            str(r["outcome"]): {
                "calls": int(r["calls"] or 0),
                "billed": int(r["billed"] or 0),
                "cost": round(float(r["cost"] or 0), 2),
            }
            for r in conn.execute(
                "SELECT outcome, COUNT(*) calls, "
                "SUM(CASE WHEN billed=1 THEN 1 ELSE 0 END) billed, "
                "COALESCE(SUM(cost_usd),0) cost "
                "FROM searchbug_calls WHERE called_at >= datetime('now','-30 days') "
                "GROUP BY outcome"
            ).fetchall()
        }
        outbound = {
            str(r["status"]): int(r["c"] or 0)
            for r in conn.execute(
                "SELECT status, COUNT(*) c FROM outbound_messages GROUP BY status"
            ).fetchall()
        }
        bounces = {
            str(r["kind"]): int(r["c"] or 0)
            for r in conn.execute(
                "SELECT kind, COUNT(*) c FROM mailbox_bounce_events GROUP BY kind"
            ).fetchall()
        }
        suppressions = int(one("SELECT COUNT(*) FROM suppressions")[0] or 0)
        replies = int(one(
            "SELECT COUNT(*) FROM outbound_contacts "
            "WHERE replied_at IS NOT NULL AND replied_at >= datetime('now','-30 days')"
        )[0] or 0)
        health = one(
            "SELECT overall_status, overall_score, captured_at FROM system_health_snapshots "
            "ORDER BY id DESC LIMIT 1"
        )
        return {
            "users": users,
            "checkout": checkout,
            "stripe_events": stripe_events,
            "leads": leads,
            "cities": cities,
            "entities": entities,
            "contacts": contacts,
            "reveals": reveals,
            "searchbug": searchbug,
            "outbound": outbound,
            "bounces": bounces,
            "suppressions": suppressions,
            "replies": replies,
            "health": dict(health) if health else {},
        }
    finally:
        conn.close()


def _price_bridge(metrics: dict, assumptions_: dict) -> dict:
    price = float(assumptions_["ticket_price_weekly"])
    mrr_per = float(assumptions_["normalized_mrr_per_pass"])
    arr_per = float(assumptions_["arr_per_pass"])
    access = int(metrics["users"]["access_active"])
    pro = int(metrics["users"]["pro_active"])
    return {
        "ticket_weekly": price,
        "monthly_factor": float(assumptions_["monthlyization_factor"]),
        "mrr_per_pass": round(mrr_per, 2),
        "arr_per_pass": round(arr_per, 2),
        "access_passes": access,
        "pro_active": pro,
        "weekly_run_rate_access": round(access * price, 2),
        "mrr_normalized_access": round(access * mrr_per, 2),
        "arr_normalized_access": round(access * arr_per, 2),
        "weekly_run_rate_pro": round(pro * price, 2),
        "mrr_normalized_pro": round(pro * mrr_per, 2),
        "arr_normalized_pro": round(pro * arr_per, 2),
    }


def _reconciliation(metrics: dict, cash: dict) -> dict:
    access = int(metrics["users"]["access_active"])
    pro = int(metrics["users"]["pro_active"])
    completed = int(metrics["checkout"]["completed"])
    stripe_completed = int(metrics["stripe_events"]["completed"])
    # Sem mapeamento Stripe↔utilizador, nenhum pass é "verificado" só por ter
    # acesso; grants/testes também têm plan_until.
    verified = 0
    if cash.get("status") == "ok" and cash.get("cash_total"):
        # Há dinheiro real, mas o mapeamento para passes exige reconciliação.
        status = "cash_without_mapping"
    elif stripe_completed and not completed:
        status = "stripe_events_without_checkout"
    elif access > 0:
        status = "access_without_verified_payment"
    elif pro > access:
        status = "pro_active_without_access"
    else:
        status = "ok"
    return {
        "access_passes": access,
        "pro_active": pro,
        "verified_paid_passes": verified,
        "completed_checkouts": completed,
        "stripe_completed_events": stripe_completed,
        "cash_30d": cash.get("cash_30d"),
        "cash_total": cash.get("cash_total"),
        "cash_status": cash.get("status"),
        "cash_mode": cash.get("mode"),
        "status": status,
        "details": (
            "Stripe é a fonte de cash e plan_until é a fonte de acesso. "
            "Passes com acesso mas sem cobrança mapeada ficam fora do MRR verificado."
        ),
    }


def _asset(metrics: dict, assumptions_: dict) -> dict:
    owners = int(metrics["leads"]["owners"] or 0)
    data_low = owners * float(assumptions_["replacement_owner_low"])
    data_high = owners * float(assumptions_["replacement_owner_high"])
    ip_low = float(assumptions_["ip_months_low"]) * float(assumptions_["ip_rate_low"])
    ip_high = float(assumptions_["ip_months_high"]) * float(assumptions_["ip_rate_high"])
    comp_low = float(assumptions_["compliance_low"])
    comp_high = float(assumptions_["compliance_high"])
    floor_low = data_low + ip_low + comp_low
    floor_high = data_high + ip_high + comp_high
    return {
        "owners": owners,
        "fresh7": int(metrics["leads"]["fresh7"] or 0),
        "data_low": round(data_low, 2),
        "data_high": round(data_high, 2),
        "ip_low": round(ip_low, 2),
        "ip_high": round(ip_high, 2),
        "compliance_low": round(comp_low, 2),
        "compliance_high": round(comp_high, 2),
        "floor_low": round(floor_low, 2),
        "floor_high": round(floor_high, 2),
        "basis": "custo de substituição/reconstrução; não é valor de mercado",
    }


def _going_concern(metrics: dict, assumptions_: dict) -> dict:
    mrr = float(assumptions_["normalized_mrr_per_pass"])
    arr = float(assumptions_["arr_per_pass"])
    access = int(metrics["users"]["access_active"])
    pro = int(metrics["users"]["pro_active"])
    low, base, high = (
        float(assumptions_["multiple_low"]),
        float(assumptions_["multiple_base"]),
        float(assumptions_["multiple_high"]),
    )
    return {
        "access_arr": round(access * arr, 2),
        "pro_arr": round(pro * arr, 2),
        "access_ev": {
            "low": round(access * arr * low, 2),
            "base": round(access * arr * base, 2),
            "high": round(access * arr * high, 2),
        },
        "pro_ev": {
            "low": round(pro * arr * low, 2),
            "base": round(pro * arr * base, 2),
            "high": round(pro * arr * high, 2),
        },
        "multiple_ranges": {"low": low, "base": base, "high": high},
        "mrr_per_pass": round(mrr, 2),
        "arr_per_pass": round(arr, 2),
    }


def _proof(metrics: dict, assumptions_: dict) -> dict:
    leads = metrics["leads"]
    total = int(leads["total"] or 0)
    owners = int(leads["owners"] or 0)
    addresses = int(leads["addresses"] or 0)
    fresh7 = int(leads["fresh7"] or 0)
    provenance = int(leads["provenance"] or 0)
    sb = metrics["searchbug"]
    calls = sum(v["calls"] for v in sb.values())
    success = int(sb.get("success", {}).get("calls", 0))
    error = int(sb.get("error", {}).get("calls", 0))
    no_results = int(sb.get("no_results", {}).get("calls", 0))
    mismatch = int(sb.get("name_mismatch", {}).get("calls", 0))
    transport = int(sb.get("transport_error", {}).get("calls", 0))
    error_billed = int(sb.get("error", {}).get("billed", 0))
    cost = round(sum(v["cost"] for v in sb.values()), 2)
    sent = int(metrics["outbound"].get("sent", 0))
    bounces = int(metrics["bounces"].get("bounce", 0))
    bounce_rate = (bounces / sent * 100.0) if sent else 0.0
    owner_pct = owners * 100.0 / total if total else 0.0
    address_pct = addresses * 100.0 / total if total else 0.0
    fresh_pct = fresh7 * 100.0 / total if total else 0.0
    success_pct = success * 100.0 / calls if calls else 0.0
    error_pct = error * 100.0 / calls if calls else 0.0
    provenance_pct = provenance * 100.0 / total if total else 0.0

    truth = (
        provenance_pct * 0.25
        + address_pct * 0.20
        + owner_pct * 0.20
        + success_pct * 0.20
        + fresh_pct * 0.10
        + 100.0 * 0.05
    )
    health = metrics.get("health") or {}
    return {
        "truth_score": round(truth, 1),
        "confidence": "baixa" if calls < 30 or sent < 30 else "média",
        "owner_coverage_pct": round(owner_pct, 1),
        "address_coverage_pct": round(address_pct, 1),
        "fresh7_pct": round(fresh_pct, 1),
        "fresh7": fresh7,
        "provenance_pct": round(provenance_pct, 1),
        "phone": {
            "status": "em remediação",
            "calls": calls,
            "success": success,
            "success_pct": round(success_pct, 1),
            "error": error,
            "error_billed": error_billed,
            "error_pct": round(error_pct, 1),
            "no_results": no_results,
            "name_mismatch": mismatch,
            "transport_error": transport,
            "cost_30d": cost,
            "cost_per_success": round(cost / success, 2) if success else None,
        },
        "email": {
            "sent": sent,
            "bounces": bounces,
            "bounce_rate_pct": round(bounce_rate, 1),
            "replies_30d": int(metrics["replies"] or 0),
            "suppressions": int(metrics["suppressions"] or 0),
            "status": "amostra baixa" if sent < 30 else "ok",
        },
        "operations": {
            "health_status": health.get("overall_status"),
            "health_score": health.get("health_score") or health.get("overall_score"),
            "captured_at": health.get("captured_at"),
            "ingestion": ">= 0.5k inseridos / 24h" if fresh7 else "sem factos frescos",
        },
        "cost_per_owner_cash": round(
            (cost + float(assumptions_["infra_fixed_monthly"])) / owners, 4
        ) if owners else None,
        "cost_per_owner_loaded": round(
            (cost + float(assumptions_["infra_fixed_monthly"])
             + 10000.0) / owners, 4
        ) if owners else None,
        "anti_angi": {
            "status": "claims register pendente de fonte/legal",
            "note": (
                "O painel não hardcodeia preços de concorrentes; cada claim "
                "tem URL, data e revisão."
            ),
        },
    }


def simulate(inputs: dict, assumptions_: dict, asset: dict) -> dict:
    def _num(name: str, default: float, lo: float = 0.0, hi: float = 1e9) -> float:
        try:
            value = float(inputs.get(name, default))
        except (TypeError, ValueError):
            value = default
        return max(lo, min(hi, value))

    n = _num("contractors", 10, 0, 1_000_000)
    price = float(assumptions_["ticket_price_weekly"])
    mrr_per = float(assumptions_["normalized_mrr_per_pass"])
    arr_per = float(assumptions_["arr_per_pass"])
    churn = _num("monthly_churn", float(assumptions_["monthly_churn"]), 0.001, 1)
    reveals = _num(
        "reveals_per_contractor_month",
        float(assumptions_["reveals_per_contractor_month"]),
        0,
        1000,
    )
    mailboxes = _num("mailboxes", 2, 1, 100)
    cities = _num("cities", 4, 1, 100)
    opex = _num("opex_monthly", float(assumptions_["opex_monthly"]), 0, 1e9)
    multiple = _num("multiple", float(assumptions_["multiple_base"]), 0, 100)
    fee_pct = float(assumptions_["payment_fee_pct"])
    fee_fixed = float(assumptions_["payment_fee_fixed"])
    charges_per_month = 52.0 / 12.0

    mrr = n * mrr_per
    arr = n * arr_per
    weekly = n * price
    searchbug = n * reveals * float(assumptions_["searchbug_cost_per_success"])
    fees = n * charges_per_month * (price * fee_pct + fee_fixed)
    infra = (
        float(assumptions_["infra_fixed_monthly"])
        + mailboxes * float(assumptions_["infra_per_mailbox"])
        + cities * float(assumptions_["infra_per_city"])
    )
    cogs = searchbug + fees + infra
    gross_margin = ((mrr - cogs) / mrr * 100.0) if mrr else 0.0
    net_margin = ((mrr - cogs - opex) / mrr * 100.0) if mrr else 0.0
    ltv = (mrr_per * (gross_margin / 100.0) / churn) if churn else None
    valuation = {
        "low": round(arr * float(assumptions_["multiple_low"]), 2),
        "base": round(arr * multiple, 2),
        "high": round(arr * float(assumptions_["multiple_high"]), 2),
    }
    return {
        "contractors": int(n),
        "weekly_revenue": round(weekly, 2),
        "mrr_normalized": round(mrr, 2),
        "arr_normalized": round(arr, 2),
        "searchbug_month": round(searchbug, 2),
        "payment_fees_month": round(fees, 2),
        "infra_month": round(infra, 2),
        "cogs_month": round(cogs, 2),
        "gross_margin_pct": round(gross_margin, 1),
        "net_margin_pct": round(net_margin, 1),
        "monthly_churn_pct": round(churn * 100, 1),
        "ltv": round(ltv, 2) if ltv is not None else None,
        "valuation": valuation,
        "asset_floor_low": asset["floor_low"],
        "asset_floor_high": asset["floor_high"],
        "ev_low": round(max(asset["floor_low"], valuation["low"]), 2),
        "ev_high": round(max(asset["floor_high"], valuation["high"]), 2),
        "notes": [
            "MRR = passes × 120 × 52/12 (não 4 semanas).",
            "Margem de contribuição ≠ margem líquida: opex fixo é input separado.",
            "Valuation é faixa; o piso patrimonial não é preço de mercado.",
        ],
    }


def _snapshot_payload(metrics: dict, cash: dict) -> dict:
    assumptions_ = assumptions()
    price = _price_bridge(metrics, assumptions_)
    reconciliation = _reconciliation(metrics, cash)
    asset = _asset(metrics, assumptions_)
    going = _going_concern(metrics, assumptions_)
    proof = _proof(metrics, assumptions_)
    analytics_summary = {}
    try:
        analytics_summary = analytics.get_summary("30d")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[INVESTOR] analytics indisponível: %s", exc)
    payload = {
        "generated_at": _utc_now().isoformat(),
        "version": VERSION,
        "assumptions": assumptions_,
        "price_bridge": price,
        "reconciliation": reconciliation,
        "asset": asset,
        "going_concern": going,
        "proof": proof,
        "metrics": {
            "users": metrics["users"],
            "checkout": metrics["checkout"],
            "stripe_events": metrics["stripe_events"],
            "leads": metrics["leads"],
            "cities": metrics["cities"],
            "entities": metrics["entities"],
            "contacts": metrics["contacts"],
            "reveals": metrics["reveals"],
            "outbound": metrics["outbound"],
        },
        "analytics": {
            "visits": (analytics_summary.get("cards") or {}).get("visits", {}).get("value", 0),
            "visitors": (analytics_summary.get("cards") or {}).get("visitors", {}).get("value", 0),
            "cta_clicks": (analytics_summary.get("cards") or {}).get("cta_clicks", {}).get("value", 0),
            "form_submits": (analytics_summary.get("cards") or {}).get("form_submits", {}).get("value", 0),
        },
        "code_inventory": assumptions_["code_inventory"],
        "nda_version": assumptions_["nda_version"],
        "claims_register": {
            "version": CLAIMS_VERSION,
            "captured_at": CLAIMS_CAPTURED_AT,
            "items": CLAIMS_REGISTER,
        },
        "competitive": COMPETITIVE_MATRIX,
    }
    return payload


def _checksum(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def build_snapshot(cash: Optional[dict] = None) -> dict:
    init()
    metrics = _gather()
    cash = cash if cash is not None else _stripe_cash()
    payload = _snapshot_payload(metrics, cash)
    payload["checksum"] = _checksum(payload)
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO snapshots (captured_at, version, checksum, payload_json) "
            "VALUES (?, ?, ?, ?)",
            (
                payload["generated_at"],
                payload["version"],
                payload["checksum"],
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.execute(
            "INSERT INTO reconciliation (captured_at, access_passes, pro_active, "
            "verified_paid_passes, cash_30d_usd, cash_total_usd, status, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                payload["generated_at"],
                payload["reconciliation"]["access_passes"],
                payload["reconciliation"]["pro_active"],
                payload["reconciliation"]["verified_paid_passes"],
                payload["reconciliation"]["cash_30d"],
                payload["reconciliation"]["cash_total"],
                payload["reconciliation"]["status"],
                json.dumps(payload["reconciliation"], ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    _CACHE["snapshot"] = (datetime.now(timezone.utc).timestamp(), payload)
    return payload


def latest() -> Optional[dict]:
    init()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT payload_json FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return json.loads(row["payload_json"]) if row else None
    finally:
        conn.close()


def get_snapshot() -> dict:
    cached = _CACHE.get("snapshot")
    if cached and datetime.now(timezone.utc).timestamp() - cached[0] < 60:
        return cached[1]
    snap = latest()
    if snap is None:
        snap = build_snapshot()
    _CACHE["snapshot"] = (datetime.now(timezone.utc).timestamp(), snap)
    return snap


def refresh(force: bool = False) -> dict:
    init()
    key = "last_refresh"
    conn = get_conn()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    finally:
        conn.close()
    if not force and row:
        try:
            last = datetime.fromisoformat(str(row["value"]))
            if (_utc_now() - last).total_seconds() < 60:
                return get_snapshot()
        except ValueError:
            pass
    snap = build_snapshot()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, snap["generated_at"]),
        )
        conn.commit()
    finally:
        conn.close()
    return snap


def refresh_if_due() -> dict:
    init()
    day = _utc_now().strftime("%Y-%m-%d")
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key='last_daily'"
        ).fetchone()
        if row and str(row["value"]) == day:
            return {"status": "skipped"}
    finally:
        conn.close()
    snap = refresh(force=True)
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('last_daily', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (day,),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "generated_at": snap["generated_at"]}


def has_nda(user_id: int, version: str = NDA_VERSION) -> bool:
    init()
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT 1 FROM nda_acceptances WHERE user_id=? AND version=?",
            (int(user_id), version),
        ).fetchone() is not None
    finally:
        conn.close()


def accept_nda(user_id: int, email: str, ip: str, user_agent: str) -> bool:
    init()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO nda_acceptances "
            "(user_id, email, version, ip_hash, user_agent) VALUES (?, ?, ?, ?, ?)",
            (int(user_id), email, NDA_VERSION, _hs(ip), str(user_agent)[:300]),
        )
        conn.execute(
            "INSERT INTO access_log (user_id, email, action, resource, ip_hash, user_agent) "
            "VALUES (?, ?, 'nda_accept', ?, ?, ?)",
            (int(user_id), email, NDA_VERSION, _hs(ip), str(user_agent)[:300]),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def log_access(user_id: int, email: str, action: str, resource: str, ip: str, ua: str) -> None:
    init()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO access_log (user_id, email, action, resource, ip_hash, user_agent) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (int(user_id), email, action, resource, _hs(ip), str(ua)[:300]),
        )
        conn.commit()
    finally:
        conn.close()


def export_csv(
    snapshot: dict, viewer_email: str, ip: str, ua: str, user_id: int = 0
) -> str:
    doc_id = f"IR-{_utc_now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
    exported = _utc_now().isoformat()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["section", "metric", "label", "value", "viewer_email", "exported_at", "doc_id"]
    )

    def row(section: str, metric: str, label: str, value) -> None:
        writer.writerow([section, metric, label, value, viewer_email, exported, doc_id])

    row("meta", "version", "", snapshot["version"])
    row("meta", "generated_at", "", snapshot["generated_at"])
    row("meta", "checksum", "", snapshot.get("checksum", ""))
    price = snapshot["price_bridge"]
    for key in (
        "ticket_weekly", "mrr_per_pass", "arr_per_pass", "access_passes",
        "pro_active", "weekly_run_rate_access", "mrr_normalized_access",
        "arr_normalized_access", "weekly_run_rate_pro", "mrr_normalized_pro",
        "arr_normalized_pro",
    ):
        row("price", key, "", price.get(key))
    rec = snapshot["reconciliation"]
    for key in (
        "verified_paid_passes", "cash_30d", "cash_total", "cash_status", "status",
    ):
        row("reconciliation", key, "", rec.get(key))
    asset = snapshot["asset"]
    for key in (
        "data_low", "data_high", "ip_low", "ip_high", "compliance_low",
        "compliance_high", "floor_low", "floor_high",
    ):
        row("asset", key, "", asset.get(key))
    going = snapshot["going_concern"]
    row("going_concern", "access_arr", "", going["access_arr"])
    row("going_concern", "pro_arr", "", going["pro_arr"])
    for scenario, values in (("access", going["access_ev"]), ("pro", going["pro_ev"])):
        for key, value in values.items():
            row("going_concern", f"{scenario}_{key}", "", value)
    proof = snapshot["proof"]
    row("proof", "truth_score", "", proof["truth_score"])
    row("proof", "owner_coverage_pct", "", proof["owner_coverage_pct"])
    row("proof", "fresh7_pct", "", proof["fresh7_pct"])
    phone = proof["phone"]
    for key, value in phone.items():
        row("phone", key, "", value)
    email = proof["email"]
    for key, value in email.items():
        row("email", key, "", value)
    ops = proof["operations"]
    for key, value in ops.items():
        row("operations", key, "", value)
    for key, value in snapshot["analytics"].items():
        row("analytics", key, "", value)
    for key, value in snapshot["assumptions"].items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            row("assumption", key, "", value)
    inventory = snapshot["code_inventory"]
    for key, value in inventory.items():
        if isinstance(value, list):
            continue
        row("code", key, "", value)
    claims = snapshot.get("claims_register") or {}
    for item in claims.get("items", []):
        claim_id = item.get("id", "")
        row("claim", claim_id, "topic", item.get("topic", ""))
        row("claim", claim_id, "status", item.get("status", ""))
        row("claim", claim_id, "source_url", item.get("source_url", ""))
        row("claim", claim_id, "source_date", item.get("source_date", ""))
        row("claim", claim_id, "captured_at", item.get("captured_at", ""))
    log_access(user_id, viewer_email, "export_csv", doc_id, ip, ua)
    return "\ufeff" + out.getvalue()
