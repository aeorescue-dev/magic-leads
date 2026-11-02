"""Vitrine pública por cidade/nicho — Fase 2A.

Fonte de inventário: `leads.db` (oportunidades abertas dos últimos N dias).
Estado público (páginas, itens mascarados, tokens, visitas e checkouts) vive
em `showcase.db`.

Nunca expõe owner_name, owner_phone, owner_email, morada exata ou ID externo
no payload público. Apenas bairro/ZIP parcial, categoria, data e faixa de valor
(quando existir).
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from ..config import settings
from ..utils.logger import logger
from .db import get_connection
from .unsubscribe import unsubscribe_url

VERSION = "2026-11-02.1"
TOKEN_TTL_DAYS = 30

CITY_CANON = {
    "BOSTON": "Boston",
    "CHICAGO": "Chicago",
    "DALLAS": "Dallas",
    "NYC": "New York",
    "NEW YORK": "New York",
    "BROOKLYN": "Brooklyn",
}

TRADE_MAP = {
    "Roof": "roofing",
    "Paint": "painting",
    "Lead": "painting",
    "Plumbing": "plumbing",
    "Electrical": "electrical",
    "Heating": "hvac",
    "Gas": "hvac",
    "Structure": "remodeling",
    "Door_Window": "windows",
    "Grass": "landscaping",
    "Debris": "debris_removal",
    "Rodent": "pest_control",
    "Mold": "remediation",
    "Unsanitary": "cleaning",
    "Elevator": "elevator",
}

TRADE_LABELS = {
    "roofing": "Roofing",
    "painting": "Painting",
    "plumbing": "Plumbing",
    "electrical": "Electrical",
    "hvac": "HVAC",
    "remodeling": "Remodeling",
    "windows": "Windows & Doors",
    "landscaping": "Landscaping",
    "debris_removal": "Debris Removal",
    "pest_control": "Pest Control",
    "remediation": "Remediation",
    "cleaning": "Cleaning",
    "elevator": "Elevator",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_inventory (
  city_slug TEXT NOT NULL,
  trade_slug TEXT NOT NULL,
  city TEXT NOT NULL,
  state TEXT NOT NULL,
  trade_code TEXT NOT NULL,
  item_count INTEGER NOT NULL DEFAULT 0,
  last_observed_at TEXT,
  built_at TEXT NOT NULL,
  PRIMARY KEY (city_slug, trade_slug)
);

CREATE TABLE IF NOT EXISTS showcase_pages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  city_slug TEXT NOT NULL,
  trade_slug TEXT NOT NULL,
  city TEXT NOT NULL,
  state TEXT NOT NULL,
  trade_code TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  subtitle TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  inventory_count INTEGER NOT NULL DEFAULT 0,
  signal_label TEXT NOT NULL DEFAULT 'opportunity',
  last_built_at TEXT NOT NULL,
  version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_showcase_pages_status
  ON showcase_pages (status, city_slug, trade_slug);

CREATE TABLE IF NOT EXISTS showcase_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id INTEGER NOT NULL REFERENCES showcase_pages(id) ON DELETE CASCADE,
  lead_id INTEGER NOT NULL,
  trade_code TEXT NOT NULL,
  neighborhood TEXT,
  zip_prefix TEXT,
  observed_at TEXT,
  value_band TEXT,
  signal_type TEXT,
  masked_title TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_showcase_items_page
  ON showcase_items (page_id, sort_order);

CREATE TABLE IF NOT EXISTS showcase_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_hash TEXT NOT NULL UNIQUE,
  voice_call_id INTEGER,
  company_id INTEGER,
  email TEXT,
  company_name TEXT,
  city_slug TEXT NOT NULL,
  trade_slug TEXT NOT NULL,
  city TEXT NOT NULL,
  trade_code TEXT NOT NULL,
  campaign_id TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  clicked_at TEXT,
  visit_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_showcase_links_company
  ON showcase_links (company_id, created_at DESC);

CREATE TABLE IF NOT EXISTS showcase_visits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  link_id INTEGER NOT NULL REFERENCES showcase_links(id) ON DELETE CASCADE,
  path TEXT,
  referrer TEXT,
  ip_hash TEXT,
  user_agent TEXT,
  visited_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS showcase_checkouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  link_id INTEGER,
  session_id TEXT NOT NULL UNIQUE,
  user_id INTEGER,
  email TEXT,
  amount_cents INTEGER DEFAULT 0,
  status TEXT DEFAULT 'open',
  created_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_showcase_checkouts_link
  ON showcase_checkouts (link_id);
"""

_LOCK = threading.Lock()
_INIT: dict[str, Optional[str]] = {"path": None}
_CACHE: dict[str, tuple[float, Any]] = {}


def db_path() -> str:
    override = (os.getenv("SHOWCASE_DB_PATH") or "").strip()
    if override:
        return override
    data_dir = (os.getenv("DATA_DIR") or "/data").strip()
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.getcwd(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "showcase.db")


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
            conn.commit()
        finally:
            conn.close()
        _INIT["path"] = path


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _utc_now()).isoformat()


def slugify(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return text.strip("-")


def _city_label(raw: Any) -> str:
    text = str(raw or "").strip()
    return CITY_CANON.get(text.upper(), text.title()) if text else ""


def _trade_code(raw: Any) -> Optional[str]:
    return TRADE_MAP.get(str(raw or "").strip())


def _trade_label(code: str) -> str:
    return TRADE_LABELS.get(code, code.replace("_", " ").title())


def normalize_trade(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in TRADE_LABELS:
        return text
    for code, label in TRADE_LABELS.items():
        if text == label.lower():
            return code
    for raw, code in TRADE_MAP.items():
        if text == raw.lower():
            return code
    return None


def _public_base() -> str:
    return (
        getattr(settings, "SHOWCASE_BASE_URL", "")
        or getattr(settings, "PUBLIC_API_URL", "")
        or "https://magic-leads-production.up.railway.app"
    ).rstrip("/")


def _frontend_base() -> str:
    return (getattr(settings, "FRONTEND_URL", "") or "https://www.magicleads.app").rstrip("/")


def _signal_types() -> list[str]:
    raw = getattr(settings, "SHOWCASE_SIGNAL_TYPES", "open_request,authorized_work")
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _window_days() -> int:
    return max(1, int(getattr(settings, "SHOWCASE_WINDOW_DAYS", 30)))


def _min_items() -> int:
    return max(1, int(getattr(settings, "SHOWCASE_MIN_ITEMS", 3)))


def _collect_inventory(days: Optional[int] = None) -> dict[tuple[str, str, str], dict]:
    """Agrega oportunidades abertas do leads.db por (city_slug, trade_slug)."""
    days = days or _window_days()
    signals = _signal_types()
    placeholders = ",".join("?" for _ in signals)
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT id, city, state, zip_code, neighborhood, issue_category,
                   signal_type, date_reported
            FROM leads
            WHERE signal_status='open'
              AND datetime(date_reported) >= datetime('now', ?)
              AND signal_type IN ({placeholders})
              AND COALESCE(is_junk, 0) = 0
            """,
            (f"-{days} days", *signals),
        ).fetchall()
    finally:
        conn.close()

    grouped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        city = _city_label(row["city"])
        state = str(row["state"] or "").strip().upper()
        trade = _trade_code(row["issue_category"])
        if not city or not state or not trade:
            continue
        city_slug = slugify(city)
        key = (city_slug, trade, state)
        bucket = grouped.setdefault(
            key,
            {
                "city": city,
                "state": state,
                "city_slug": city_slug,
                "trade_code": trade,
                "items": [],
            },
        )
        zip_prefix = str(row["zip_code"] or "").strip()[:3] or None
        neighborhood = str(row["neighborhood"] or "").strip() or (
            f"ZIP {zip_prefix}" if zip_prefix else "Local area"
        )
        bucket["items"].append(
            {
                "lead_id": int(row["id"]),
                "trade_code": trade,
                "neighborhood": neighborhood,
                "zip_prefix": zip_prefix,
                "observed_at": row["date_reported"],
                "value_band": None,
                "signal_type": row["signal_type"],
                "masked_title": f"{_trade_label(trade)} · {neighborhood}",
            }
        )

    for bucket in grouped.values():
        bucket["items"].sort(
            key=lambda item: str(item.get("observed_at") or ""), reverse=True
        )
        bucket["count"] = len(bucket["items"])
        bucket["last_observed_at"] = (
            bucket["items"][0]["observed_at"] if bucket["items"] else None
        )
        bucket["signal_label"] = (
            "approved work"
            if any(i["signal_type"] == "authorized_work" for i in bucket["items"])
            else "property opportunity"
        )
    return grouped


def _page_title(city: str, trade_label: Optional[str], count: int) -> str:
    if trade_label:
        noun = "opportunity" if count == 1 else "opportunities"
        return f"{count} {trade_label} {noun} in {city}"
    noun = "opportunity" if count == 1 else "opportunities"
    return f"{count} active property {noun} in {city}"


def _page_subtitle() -> str:
    return (
        "Public records, refreshed continuously. Masked samples; exact addresses "
        "and owner details unlock with a weekly pass."
    )


def build_pages(days: Optional[int] = None) -> dict:
    """Recalcula páginas publicadas a partir do inventário real."""
    init()
    now = _iso()
    inventory = _collect_inventory(days)
    min_items = _min_items()
    published = 0
    combos = len(inventory)
    conn = get_conn()
    try:
        conn.execute("UPDATE showcase_pages SET status='draft'")
        for (city_slug, trade, state), bucket in inventory.items():
            count = int(bucket["count"])
            conn.execute(
                """
                INSERT INTO market_inventory
                  (city_slug, trade_slug, city, state, trade_code, item_count,
                   last_observed_at, built_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(city_slug, trade_slug) DO UPDATE SET
                  city=excluded.city,
                  state=excluded.state,
                  trade_code=excluded.trade_code,
                  item_count=excluded.item_count,
                  last_observed_at=excluded.last_observed_at,
                  built_at=excluded.built_at
                """,
                (
                    city_slug,
                    trade,
                    bucket["city"],
                    state,
                    trade,
                    count,
                    bucket["last_observed_at"],
                    now,
                ),
            )
            if count < min_items:
                continue
            title = _page_title(bucket["city"], _trade_label(trade), count)
            slug = f"{city_slug}-{trade}"
            conn.execute(
                """
                INSERT INTO showcase_pages
                  (city_slug, trade_slug, city, state, trade_code, slug, title,
                   subtitle, status, inventory_count, signal_label,
                   last_built_at, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                  title=excluded.title,
                  subtitle=excluded.subtitle,
                  status='published',
                  inventory_count=excluded.inventory_count,
                  signal_label=excluded.signal_label,
                  last_built_at=excluded.last_built_at,
                  version=excluded.version
                """,
                (
                    city_slug,
                    trade,
                    bucket["city"],
                    state,
                    trade,
                    slug,
                    title,
                    _page_subtitle(),
                    count,
                    bucket["signal_label"],
                    now,
                    VERSION,
                ),
            )
            page = conn.execute(
                "SELECT id FROM showcase_pages WHERE slug=?", (slug,)
            ).fetchone()
            page_id = int(page["id"])
            conn.execute("DELETE FROM showcase_items WHERE page_id=?", (page_id,))
            for index, item in enumerate(bucket["items"][:12]):
                conn.execute(
                    """
                    INSERT INTO showcase_items
                      (page_id, lead_id, trade_code, neighborhood, zip_prefix,
                       observed_at, value_band, signal_type, masked_title,
                       sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        page_id,
                        item["lead_id"],
                        item["trade_code"],
                        item["neighborhood"],
                        item["zip_prefix"],
                        item["observed_at"],
                        item["value_band"],
                        item["signal_type"],
                        item["masked_title"],
                        index,
                    ),
                )
            published += 1
        conn.execute(
            "DELETE FROM showcase_items WHERE page_id IN "
            "(SELECT id FROM showcase_pages WHERE status='draft')"
        )
        conn.commit()
    finally:
        conn.close()
    _CACHE.clear()
    return {
        "ok": True,
        "published": published,
        "combos": combos,
        "min_items": min_items,
        "window_days": days or _window_days(),
        "built_at": now,
    }


def _page_payload(
    page: dict,
    items: list[dict],
    *,
    fallback: Optional[str] = None,
    fallback_label: Optional[str] = None,
) -> dict:
    return {
        "page": {
            "city": page["city"],
            "state": page["state"],
            "city_slug": page["city_slug"],
            "trade_code": page["trade_code"],
            "trade_label": _trade_label(page["trade_code"]),
            "title": page["title"],
            "subtitle": page["subtitle"],
            "count": int(page.get("inventory_count") or len(items)),
            "signal_label": page.get("signal_label") or "property opportunity",
            "last_built_at": page.get("last_built_at"),
            "fallback": fallback,
            "fallback_label": fallback_label,
        },
        "items": [
            {
                "masked_title": item["masked_title"],
                "neighborhood": item["neighborhood"],
                "zip_prefix": item["zip_prefix"],
                "observed_at": item["observed_at"],
                "value_band": item["value_band"],
                "signal_type": item["signal_type"],
            }
            for item in items
        ],
        "cta": {
            "price_usd": float(getattr(settings, "PLAN_AMOUNT_USD", 120.0)),
            "period": "week",
            "checkout_enabled": bool(
                getattr(settings, "STRIPE_API_KEY", "")
                and getattr(settings, "STRIPE_PRICE_ID_PRO", "")
                and getattr(settings, "STRIPE_PRICE_ID_PRO", "") != "price_..."
            ),
        },
    }


def _load_page(conn: sqlite3.Connection, city_slug: str, trade_slug: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM showcase_pages WHERE city_slug=? AND trade_slug=? "
        "AND status='published'",
        (city_slug, trade_slug),
    ).fetchone()
    if row is None:
        return None
    items = [
        dict(item)
        for item in conn.execute(
            "SELECT * FROM showcase_items WHERE page_id=? ORDER BY sort_order",
            (row["id"],),
        ).fetchall()
    ]
    return _page_payload(dict(row), items)


def _fallback_page(city_slug: str, trade_slug: str) -> Optional[dict]:
    """Fallback: cidade inteira ou trade noutras cidades."""
    inventory = _collect_inventory()
    min_items = _min_items()

    city_buckets = [
        bucket
        for (cs, _trade, _state), bucket in inventory.items()
        if cs == city_slug and int(bucket["count"]) >= min_items
    ]
    if city_buckets:
        items: list[dict] = []
        for bucket in city_buckets:
            items.extend(bucket["items"][:6])
        items.sort(key=lambda item: str(item.get("observed_at") or ""), reverse=True)
        city = city_buckets[0]["city"]
        state = city_buckets[0]["state"]
        total_count = sum(int(bucket["count"]) for bucket in city_buckets)
        page = {
            "city": city,
            "state": state,
            "city_slug": city_slug,
            "trade_code": trade_slug,
            "title": _page_title(city, None, total_count),
            "subtitle": _page_subtitle(),
            "inventory_count": total_count,
            "signal_label": "property opportunity",
            "last_built_at": _iso(),
        }
        return _page_payload(
            page,
            items[:12],
            fallback="city",
            fallback_label=f"Showing all active trades in {city}",
        )

    trade_buckets = [
        bucket
        for (_cs, trade, _state), bucket in inventory.items()
        if trade == trade_slug and int(bucket["count"]) >= min_items
    ]
    if trade_buckets:
        trade_buckets.sort(key=lambda b: int(b["count"]), reverse=True)
        bucket = trade_buckets[0]
        page = {
            "city": bucket["city"],
            "state": bucket["state"],
            "city_slug": bucket["city_slug"],
            "trade_code": trade_slug,
            "title": _page_title(bucket["city"], _trade_label(trade_slug), bucket["count"]),
            "subtitle": _page_subtitle(),
            "inventory_count": int(bucket["count"]),
            "signal_label": bucket["signal_label"],
            "last_built_at": _iso(),
        }
        return _page_payload(
            page,
            bucket["items"][:12],
            fallback="trade",
            fallback_label=(
                f"No { _trade_label(trade_slug) } inventory in this city yet; "
                f"showing {bucket['city']}"
            ),
        )
    return None


def ensure_built() -> None:
    """Constrói páginas na primeira utilização se ainda não existirem."""
    init()
    conn = get_conn()
    try:
        rows = int(
            conn.execute("SELECT COUNT(*) FROM market_inventory").fetchone()[0] or 0
        )
    finally:
        conn.close()
    if rows == 0:
        build_pages()


def get_page(city_slug: str, trade_slug: str) -> Optional[dict]:
    init()
    ensure_built()
    city_slug = slugify(city_slug)
    trade_slug = slugify(trade_slug)
    conn = get_conn()
    try:
        page = _load_page(conn, city_slug, trade_slug)
        if page is not None:
            return page
    finally:
        conn.close()
    return _fallback_page(city_slug, trade_slug)


def available(city_slug: str, trade_slug: str) -> dict:
    """Consulta rápida para o guião de voz antes de prometer uma vitrine."""
    init()
    ensure_built()
    city_slug = slugify(city_slug)
    trade_slug = slugify(trade_slug)
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT item_count, city, state FROM market_inventory "
            "WHERE city_slug=? AND trade_slug=?",
            (city_slug, trade_slug),
        ).fetchone()
        exact = int(row["item_count"]) if row else 0
        city_total = int(
            conn.execute(
                "SELECT COALESCE(SUM(item_count),0) FROM market_inventory "
                "WHERE city_slug=?",
                (city_slug,),
            ).fetchone()[0]
            or 0
        )
        return {
            "available": exact >= _min_items(),
            "exact_count": exact,
            "city_total": city_total,
            "min_items": _min_items(),
            "page_path": f"/en/{city_slug}/{trade_slug}",
        }
    finally:
        conn.close()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_link(
    *,
    company_id: int,
    email: str,
    city: str,
    trade_code: str,
    company_name: str = "",
    voice_call_id: Optional[int] = None,
    campaign_id: str = "",
) -> dict:
    init()
    city_slug = slugify(city)
    trade_slug = slugify(trade_code)
    token = secrets.token_urlsafe(24)
    now = _utc_now()
    expires = now + timedelta(days=TOKEN_TTL_DAYS)
    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO showcase_links
              (token_hash, voice_call_id, company_id, email, company_name,
               city_slug, trade_slug, city, trade_code, campaign_id,
               created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _hash_token(token),
                int(voice_call_id) if voice_call_id else None,
                int(company_id),
                (email or "").strip().lower() or None,
                company_name,
                city_slug,
                trade_slug,
                _city_label(city),
                trade_code,
                campaign_id,
                _iso(now),
                _iso(expires),
            ),
        )
        conn.commit()
        link_id = int(cur.lastrowid)
    finally:
        conn.close()
    return {
        "ok": True,
        "link_id": link_id,
        "token": token,
        "url": f"{_public_base()}/r/{token}",
        "expires_at": _iso(expires),
        "city_slug": city_slug,
        "trade_slug": trade_slug,
    }


def resolve_link(token: str) -> Optional[dict]:
    init()
    if not token:
        return None
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM showcase_links WHERE token_hash=?",
            (_hash_token(token),),
        ).fetchone()
        if row is None:
            return None
        link = dict(row)
        expires = link.get("expires_at")
        if expires:
            try:
                parsed = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed <= _utc_now():
                    return None
            except ValueError:
                return None
        link["token"] = token
        return link
    finally:
        conn.close()


def record_visit(
    token: str, path: str = "", referrer: str = "", ip: str = "", user_agent: str = ""
) -> Optional[dict]:
    link = resolve_link(token)
    if link is None:
        return None
    now = _iso()
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE showcase_links SET clicked_at=COALESCE(clicked_at, ?), "
            "visit_count=visit_count+1 WHERE id=?",
            (now, link["id"]),
        )
        conn.execute(
            "INSERT INTO showcase_visits "
            "(link_id, path, referrer, ip_hash, user_agent, visited_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                link["id"],
                str(path)[:500],
                str(referrer)[:500],
                hashlib.sha256(str(ip or "").encode()).hexdigest()[:24],
                str(user_agent)[:300],
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return link


def redirect_url(link: dict, token: str) -> str:
    return (
        f"{_frontend_base()}/en/{link['city_slug']}/{link['trade_slug']}"
        f"?vt={quote(token)}"
    )


def record_checkout(
    *,
    link_id: Optional[int],
    session_id: str,
    user_id: Optional[int],
    email: str,
    amount_cents: int = 0,
) -> None:
    init()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO showcase_checkouts "
            "(link_id, session_id, user_id, email, amount_cents, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'open', ?) "
            "ON CONFLICT(session_id) DO NOTHING",
            (
                int(link_id) if link_id else None,
                session_id,
                int(user_id) if user_id else None,
                (email or "").strip().lower() or None,
                int(amount_cents or 0),
                _iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mark_checkout_completed(session_id: str) -> None:
    init()
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE showcase_checkouts SET status='completed', completed_at=? "
            "WHERE session_id=?",
            (_iso(), session_id),
        )
        conn.commit()
    finally:
        conn.close()


def attribution_stats() -> dict:
    init()
    conn = get_conn()
    try:
        pages = int(
            conn.execute(
                "SELECT COUNT(*) FROM showcase_pages WHERE status='published'"
            ).fetchone()[0]
            or 0
        )
        links = int(conn.execute("SELECT COUNT(*) FROM showcase_links").fetchone()[0] or 0)
        visits = int(conn.execute("SELECT COUNT(*) FROM showcase_visits").fetchone()[0] or 0)
        checkouts = int(
            conn.execute("SELECT COUNT(*) FROM showcase_checkouts").fetchone()[0] or 0
        )
        completed = int(
            conn.execute(
                "SELECT COUNT(*) FROM showcase_checkouts WHERE status='completed'"
            ).fetchone()[0]
            or 0
        )
        revenue = int(
            conn.execute(
                "SELECT COALESCE(SUM(amount_cents),0) FROM showcase_checkouts "
                "WHERE status='completed'"
            ).fetchone()[0]
            or 0
        )
        return {
            "pages": pages,
            "links": links,
            "visits": visits,
            "checkouts": checkouts,
            "completed": completed,
            "revenue_cents": revenue,
        }
    finally:
        conn.close()


def send_showcase_email(
    *,
    to_email: str,
    company_name: str,
    city: str,
    trade_code: str,
    count: int,
    link_url: str,
) -> dict:
    """Envia o link da vitrine via Resend. Fail-soft em dev/teste."""
    email = (to_email or "").strip().lower()
    if not email or "@" not in email:
        return {"sent": False, "reason": "no_email", "link_url": link_url}
    if not getattr(settings, "EMAIL_API_KEY", "") or not getattr(
        settings, "EMAIL_FROM", ""
    ):
        logger.info("[SHOWCASE] Email em modo logs (sem EMAIL_API_KEY): %s", link_url)
        return {"sent": False, "dry_run": True, "link_url": link_url}

    trade_label = _trade_label(trade_code)
    noun = "opportunity" if count == 1 else "opportunities"
    subject = f"{count} {trade_label} {noun} in {city} this week"
    body = (
        f"Hi {company_name or 'there'},\n\n"
        f"We found {count} active {trade_label.lower()} {noun} in {city} "
        "from public records this week.\n\n"
        f"See the masked list here: {link_url}\n\n"
        "Magic Leads gives contractors a weekly pass: one business per address, "
        "with owner details when you subscribe. $120 for 7 days.\n\n"
        f"Unsubscribe: {unsubscribe_url(email)}\n\n"
        "— Magic Leads\n"
        "Boston, MA\n"
    )
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.EMAIL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.EMAIL_FROM,
                "to": [email],
                "subject": subject,
                "text": body,
            },
            timeout=15,
        )
        if resp.status_code in (200, 202):
            logger.info("[SHOWCASE] Vitrine enviada para %s", email)
            return {"sent": True, "link_url": link_url}
        logger.warning(
            "[SHOWCASE] Resend recusou (HTTP %s) para %s", resp.status_code, email
        )
        return {
            "sent": False,
            "reason": f"http_{resp.status_code}",
            "link_url": link_url,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SHOWCASE] Falha ao enviar email: %s", type(exc).__name__)
        return {"sent": False, "reason": "exception", "link_url": link_url}
