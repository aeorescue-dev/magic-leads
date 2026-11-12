"""Web Analytics first-party, cookieless (Fase 29).

Banco separado (`analytics.db`) para não competir com `leads.db`. Nenhum IP,
e-mail ou nome é persistido: o visitante único é um HMAC com salt diário.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from ..utils.logger import logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_key TEXT NOT NULL UNIQUE,
  visitor_hash TEXT,
  started_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  country TEXT,
  region TEXT,
  city TEXT,
  device TEXT,
  browser TEXT,
  os TEXT,
  locale TEXT,
  landing_path TEXT,
  referrer_host TEXT,
  source TEXT,
  medium TEXT,
  campaign TEXT,
  content TEXT,
  term TEXT,
  pageviews INTEGER DEFAULT 1,
  engagement_ms INTEGER DEFAULT 0,
  scroll_pct INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions (started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_visitor ON sessions (visitor_hash, started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions (source, medium, started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_geo ON sessions (country, city, started_at);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_uid TEXT NOT NULL UNIQUE,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  ts TEXT NOT NULL,
  name TEXT NOT NULL,
  path TEXT,
  label TEXT,
  value REAL,
  props_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);
CREATE INDEX IF NOT EXISTS idx_events_name_ts ON events (name, ts);
CREATE INDEX IF NOT EXISTS idx_events_session ON events (session_id);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

_ALLOWED_EVENTS = {
    "pageview",
    "cta_click",
    "form_start",
    "form_submit",
    "checkout_started",
    "scroll",
    "outbound_click",
    "language_switch",
    "pricing_view",
}
_BOT_RE = re.compile(
    r"(bot|crawler|spider|slurp|bingpreview|headless|phantom|"
    r"python-requests|curl/|wget/|go-http-client|vercel|preview|"
    r"facebookexternalhit|whatsapp|telegrambot|lighthouse)",
    re.IGNORECASE,
)
_INTERNAL_HOSTS = {
    "magicleads.app",
    "www.magicleads.app",
    "localhost",
    "127.0.0.1",
}
# Hosts públicos legítimos. Qualquer outro *.vercel.app é preview de QA e
# não entra no analytics de mercado.
_PUBLIC_HOSTS = {
    "magicleads.app",
    "www.magicleads.app",
    "magic-leads-frontend-final.vercel.app",
    "magicleads-oficial.vercel.app",
}
# Cidades de datacenter/cloud que aparecem quando o IP pertence a um proxy,
# runner de QA ou scanner. Podem ser estendidas por env.
_DEFAULT_INFRA_GEO = {
    ("kearny", "NJ"),
    ("moses lake", "WA"),
    ("council bluffs", "IA"),
    ("ashburn", "VA"),
    ("beauharnois", "QC"),
    ("falkenstein", "SN"),
    ("prineville", "OR"),
}
_ORGANIC_HOSTS = (
    "google.",
    "bing.com",
    "duckduckgo.com",
    "yahoo.com",
    "yandex.",
    "ecosia.org",
    "brave.com",
)
_SOCIAL_HOSTS = (
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "t.co",
    "reddit.com",
    "youtube.com",
)
_EMAIL_HOSTS = (
    "mail.google.com",
    "outlook.live.com",
    "outlook.office.com",
    "mail.yahoo.com",
    "yahoo.com",
    "proton.me",
    "protonmail.com",
)

_LOCK = threading.Lock()
_INITIALIZED = False
_INITIALIZED_PATH: Optional[str] = None
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 60.0
_RATE: dict[str, list[float]] = {}


def db_path() -> str:
    override = (os.getenv("ANALYTICS_DB_PATH") or "").strip()
    if override:
        return override
    data_dir = (os.getenv("DATA_DIR") or "/data").strip()
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.getcwd(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "analytics.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    global _INITIALIZED, _INITIALIZED_PATH
    path = db_path()
    if _INITIALIZED and _INITIALIZED_PATH == path:
        return
    with _LOCK:
        if _INITIALIZED and _INITIALIZED_PATH == path:
            return
        conn = get_connection()
        try:
            conn.executescript(_SCHEMA)
            _purge_internal_sessions(conn)
            conn.commit()
        finally:
            conn.close()
        _INITIALIZED = True
        _INITIALIZED_PATH = path


# ------------------------------------------------------------- classifiers
def is_bot(user_agent: Optional[str]) -> bool:
    return bool(user_agent and _BOT_RE.search(user_agent))


def parse_user_agent(user_agent: Optional[str]) -> dict:
    ua = str(user_agent or "")
    low = ua.lower()
    if "ipad" in low or "tablet" in low:
        device = "tablet"
    elif "mobile" in low or "iphone" in low or "android" in low:
        device = "mobile"
    else:
        device = "desktop"

    if "edg/" in low:
        browser = "Edge"
    elif "opr/" in low or "opera" in low:
        browser = "Opera"
    elif "chrome/" in low and "chromium" not in low:
        browser = "Chrome"
    elif "firefox/" in low:
        browser = "Firefox"
    elif "safari/" in low:
        browser = "Safari"
    else:
        browser = "Other"

    if "iphone" in low or "ipad" in low or "ios" in low:
        os_name = "iOS"
    elif "android" in low:
        os_name = "Android"
    elif "windows" in low:
        os_name = "Windows"
    elif "mac os" in low or "macintosh" in low:
        os_name = "macOS"
    elif "linux" in low:
        os_name = "Linux"
    else:
        os_name = "Other"
    return {"device": device, "browser": browser, "os": os_name}


def classify_source(referrer: Optional[str], utm: Optional[dict]) -> dict:
    utm = utm or {}
    source = str(utm.get("source") or "").strip().lower()
    medium = str(utm.get("medium") or "").strip().lower()
    campaign = str(utm.get("campaign") or "").strip().lower()
    content = str(utm.get("content") or "").strip().lower()
    term = str(utm.get("term") or "").strip().lower()

    host = ""
    if referrer:
        try:
            host = (urlparse(str(referrer)).hostname or "").lower()
        except ValueError:
            host = ""

    if source:
        if medium in ("email", "outreach") or source in ("magicleads", "email"):
            source = "email"
            medium = medium or "outreach"
    elif host and host not in _INTERNAL_HOSTS:
        if any(h in host for h in _ORGANIC_HOSTS):
            source, medium = "organic", "organic"
        elif any(h in host for h in _SOCIAL_HOSTS):
            source, medium = "social", "social"
        elif any(h in host for h in _EMAIL_HOSTS):
            source, medium = "email", "email"
        else:
            source, medium = "referral", "referral"
    else:
        source, medium = "direct", "(none)"
    return {
        "source": source or "direct",
        "medium": medium or "(none)",
        "campaign": campaign,
        "content": content,
        "term": term,
        "referrer_host": host,
    }


# --------------------------------------------------------------- privacy
def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _daily_salt(conn: sqlite3.Connection) -> str:
    day = _utc_day()
    key = f"salt:{day}"
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    if row and row["value"]:
        return str(row["value"])
    salt = secrets.token_hex(16)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, salt),
    )
    conn.execute("DELETE FROM meta WHERE key LIKE 'salt:%' AND key<>?", (key,))
    conn.commit()
    return salt


def visitor_hash(conn: sqlite3.Connection, ip: str, user_agent: str) -> Optional[str]:
    if not ip:
        return None
    salt = _daily_salt(conn)
    digest = hmac.new(
        salt.encode("utf-8"),
        f"{ip}|{user_agent}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:32]


# ------------------------------------------------------------- ingest
def allow_ingest(ip: str, limit: int = 120, window_s: int = 60) -> bool:
    """Rate-limit em memória por IP (uma instância uvicorn)."""
    key = hashlib.sha256(str(ip or "unknown").encode()).hexdigest()[:24]
    now = time.monotonic()
    bucket = [t for t in _RATE.get(key, []) if now - t < window_s]
    if len(bucket) >= limit:
        _RATE[key] = bucket
        return False
    bucket.append(now)
    _RATE[key] = bucket
    return True


def _iso(
    value: Optional[str],
    now: datetime,
    max_past_s: int = 12 * 3600,
    max_future_s: int = 300,
) -> str:
    if value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
            delta = (now - dt).total_seconds()
            if -max_future_s <= delta <= max_past_s:
                return dt.isoformat(timespec="seconds")
        except ValueError:
            pass
    return now.isoformat(timespec="seconds")


def _clean_path(value: Optional[str]) -> str:
    text = str(value or "")[:300]
    return text.split("?", 1)[0]


def _infra_geo_pairs() -> set[tuple[str, str]]:
    pairs = set(_DEFAULT_INFRA_GEO)
    raw = str(os.getenv("ANALYTICS_INFRA_GEO") or "").strip()
    for part in raw.split(","):
        city, sep, region = part.partition("|")
        if sep and city.strip():
            pairs.add((city.strip().lower(), region.strip().upper()))
    return pairs


def _ip_internal(ip: str) -> bool:
    value = str(ip or "").strip()
    if not value:
        return False
    exact = {
        item.strip()
        for item in str(os.getenv("ANALYTICS_INTERNAL_IPS") or "").split(",")
        if item.strip()
    }
    if value in exact:
        return True
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    for part in str(os.getenv("ANALYTICS_INTERNAL_CIDRS") or "").split(","):
        cidr = part.strip()
        if not cidr:
            continue
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _internal_reason(context: dict, session: dict, client_ip: str) -> str:
    if bool(session.get("internal")):
        return "qa_flag"
    host = str(context.get("host") or "").strip().lower()
    if host:
        host = host.split(",")[0].split(":")[0].strip(".")
        if host in {"localhost", "127.0.0.1"} or host.endswith(".local"):
            return "internal_host"
        if host.endswith(".vercel.app") and host not in _PUBLIC_HOSTS:
            return "internal_host"
    if _ip_internal(client_ip):
        return "internal_ip"
    city = str(context.get("city") or "").strip().lower()
    region = str(context.get("region") or "").strip().upper()
    if city and (city, region) in _infra_geo_pairs():
        return "infra_geo"
    return ""


def _purge_internal_sessions(conn: sqlite3.Connection) -> int:
    """Remove QA/infra já gravado (sem IP histórico, usa cidade/região)."""
    pairs = _infra_geo_pairs()
    if not pairs:
        return 0
    rows = conn.execute(
        "SELECT id, LOWER(TRIM(city)) AS city, UPPER(TRIM(region)) AS region "
        "FROM sessions WHERE city IS NOT NULL AND TRIM(city) != '' "
        "AND started_at >= datetime('now', '-190 days')"
    ).fetchall()
    ids = [
        int(row["id"])
        for row in rows
        if (str(row["city"]), str(row["region"])) in pairs
    ]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    conn.execute(f"DELETE FROM events WHERE session_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM sessions WHERE id IN ({placeholders})", ids)
    logger.info("[ANALYTICS] %s sessões QA/infra removidas", len(ids))
    return len(ids)


def ingest(payload: dict, client_ip: str = "") -> dict:
    init_db()
    session = (payload or {}).get("session") or {}
    events = (payload or {}).get("events") or []
    context = (payload or {}).get("context") or {}
    if not isinstance(session, dict) or not isinstance(events, list):
        return {"status": "invalid", "inserted": 0}

    user_agent = str(context.get("ua") or "")
    if is_bot(user_agent):
        return {"status": "ignored", "reason": "bot", "inserted": 0}
    internal_reason = _internal_reason(context, session, client_ip)
    if internal_reason:
        return {
            "status": "ignored",
            "reason": internal_reason,
            "inserted": 0,
        }

    now = datetime.now(timezone.utc)
    session_key = str(session.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", session_key):
        session_key = uuid.uuid4().hex

    utm = session.get("utm") or {}
    source = classify_source(
        context.get("referrer") or session.get("referrer"), utm
    )
    ua = parse_user_agent(user_agent)
    started = _iso(session.get("started_at"), now)
    last_seen = _iso(session.get("last_seen_at"), now)
    try:
        engagement_ms = max(0, min(int(session.get("engagement_ms") or 0), 6 * 3600 * 1000))
    except (TypeError, ValueError):
        engagement_ms = 0
    try:
        scroll_pct = max(0, min(int(session.get("scroll_pct") or 0), 100))
    except (TypeError, ValueError):
        scroll_pct = 0
    try:
        pageviews = max(1, min(int(session.get("pageviews") or 1), 1000))
    except (TypeError, ValueError):
        pageviews = 1

    inserted = 0
    conn = get_connection()
    try:
        vhash = visitor_hash(conn, client_ip, user_agent)
        conn.execute(
            """
            INSERT INTO sessions (
              session_key, visitor_hash, started_at, last_seen_at,
              country, region, city, device, browser, os, locale,
              landing_path, referrer_host, source, medium, campaign,
              content, term, pageviews, engagement_ms, scroll_pct
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_key) DO UPDATE SET
              last_seen_at=excluded.last_seen_at,
              pageviews=MAX(sessions.pageviews, excluded.pageviews),
              engagement_ms=MAX(sessions.engagement_ms, excluded.engagement_ms),
              scroll_pct=MAX(sessions.scroll_pct, excluded.scroll_pct)
            """,
            (
                session_key,
                vhash,
                started,
                last_seen,
                str(context.get("country") or "")[:8],
                str(context.get("region") or "")[:40],
                str(context.get("city") or "")[:80],
                ua["device"],
                ua["browser"],
                ua["os"],
                str(session.get("locale") or "")[:8],
                _clean_path(session.get("landing_path") or session.get("path")),
                source["referrer_host"][:120],
                source["source"][:40],
                source["medium"][:40],
                source["campaign"][:80],
                source["content"][:80],
                source["term"][:80],
                pageviews,
                engagement_ms,
                scroll_pct,
            ),
        )
        row = conn.execute(
            "SELECT id FROM sessions WHERE session_key=?", (session_key,)
        ).fetchone()
        session_id = int(row["id"]) if row else 0

        for event in events[:20]:
            if not isinstance(event, dict):
                continue
            name = str(event.get("name") or "").strip()
            if name not in _ALLOWED_EVENTS:
                continue
            uid = str(event.get("uid") or "").strip()[:64] or uuid.uuid4().hex
            props = event.get("props")
            try:
                props_json = json.dumps(props, ensure_ascii=False)[:2000] if props else None
            except (TypeError, ValueError):
                props_json = None
            value = event.get("value")
            try:
                value = float(value) if value is not None else None
            except (TypeError, ValueError):
                value = None
            cur = conn.execute(
                "INSERT OR IGNORE INTO events "
                "(event_uid, session_id, ts, name, path, label, value, props_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    uid,
                    session_id,
                    _iso(event.get("ts"), now),
                    name,
                    _clean_path(event.get("path")),
                    str(event.get("label") or "")[:80] or None,
                    value,
                    props_json,
                ),
            )
            inserted += int(cur.rowcount or 0)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ANALYTICS] ingest falhou: %s", exc)
        return {"status": "error", "inserted": 0}
    finally:
        conn.close()
    return {"status": "ok", "inserted": inserted, "session": session_key}


# -------------------------------------------------------------- summary
def _parse_day(value: str) -> datetime:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        raise ValueError("data inválida (use YYYY-MM-DD)")


def _range_bounds(
    range_key: str,
    now: datetime,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[datetime, datetime, datetime, str, str]:
    """(início, fim exclusivo, início do período anterior, bucket, label)."""
    if start_date or end_date:
        if not (start_date and end_date):
            raise ValueError("indique 'start' e 'end' em conjunto")
        start = _parse_day(start_date)
        end = _parse_day(end_date) + timedelta(days=1)
        if end <= start:
            raise ValueError("'end' tem de ser >= 'start'")
        if end > now + timedelta(days=1):
            raise ValueError("'end' no futuro")
        span = end - start
        if span > timedelta(days=366):
            raise ValueError("intervalo máximo de 366 dias")
        mode = "hour" if span <= timedelta(days=2) else "day"
        return start, end, start - span, mode, "custom"

    key = (range_key or "7d").lower()
    if key == "24h":
        start = now - timedelta(hours=24)
        return start, now + timedelta(seconds=1), start - timedelta(hours=24), "hour", "24h"
    if key == "30d":
        start = now - timedelta(days=30)
        return start, now + timedelta(seconds=1), start - timedelta(days=30), "day", "30d"
    start = now - timedelta(days=7)
    return start, now + timedelta(seconds=1), start - timedelta(days=7), "day", "7d"


def _bucket(value: str, mode: str) -> str:
    if mode == "hour":
        return value[:13] + ":00:00"
    return value[:10]


def _delta_pct(current: float, previous: float) -> Optional[float]:
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _score_ratio(current: float, previous: float) -> int:
    if not current and not previous:
        return 0
    if not previous:
        return 100
    return max(0, min(100, int(round(50 + 50 * (current - previous) / previous))))


def _grouped(
    conn: sqlite3.Connection,
    cols: list[str],
    start_s: str,
    now_s: str,
    limit: int,
    extra_where: str = "",
) -> list[dict]:
    """Agrupa sessões + eventos (cliques/formulários) sem duplicar visitas."""
    col_sql = ", ".join(
        f"COALESCE(NULLIF(TRIM(s.{col}),''),'(none)') AS {col}" for col in cols
    )
    group_sql = ", ".join(str(i + 1) for i in range(len(cols)))
    where = f"AND {extra_where}" if extra_where else ""
    sessions = conn.execute(
        f"""
        SELECT {col_sql}, COUNT(*) visits,
               COUNT(DISTINCT COALESCE(s.visitor_hash, s.session_key)) visitors,
               SUM(s.pageviews) pageviews
        FROM sessions s
        WHERE s.started_at>=? AND s.started_at<? {where}
        GROUP BY {group_sql}
        """,
        (start_s, now_s),
    ).fetchall()
    events = conn.execute(
        f"""
        SELECT {col_sql},
               SUM(CASE WHEN e.name='cta_click' THEN 1 ELSE 0 END) cta_clicks,
               SUM(CASE WHEN e.name='form_submit' THEN 1 ELSE 0 END) form_submits,
               COUNT(DISTINCT CASE WHEN e.name='cta_click' THEN e.session_id END)
                 cta_sessions,
               COUNT(DISTINCT CASE WHEN e.name='form_submit' THEN e.session_id END)
                 form_sessions
        FROM events e JOIN sessions s ON s.id=e.session_id
        WHERE e.ts>=? AND e.ts<? {where}
        GROUP BY {group_sql}
        """,
        (start_s, now_s),
    ).fetchall()
    by_key = {
        tuple(row[col] for col in cols): {
            **{col: row[col] for col in cols},
            "visits": int(row["visits"] or 0),
            "visitors": int(row["visitors"] or 0),
            "pageviews": int(row["pageviews"] or 0),
            "cta_clicks": 0,
            "form_submits": 0,
            "cta_sessions": 0,
            "form_sessions": 0,
        }
        for row in sessions
    }
    for row in events:
        key = tuple(row[col] for col in cols)
        item = by_key.setdefault(
            key,
            {
                **{col: row[col] for col in cols},
                "visits": 0, "visitors": 0, "pageviews": 0,
                "cta_clicks": 0, "form_submits": 0,
                "cta_sessions": 0, "form_sessions": 0,
            },
        )
        item["cta_clicks"] = int(row["cta_clicks"] or 0)
        item["form_submits"] = int(row["form_submits"] or 0)
        item["cta_sessions"] = int(row["cta_sessions"] or 0)
        item["form_sessions"] = int(row["form_sessions"] or 0)
    rows = sorted(by_key.values(), key=lambda r: (r["visits"], r["cta_clicks"]), reverse=True)
    for row in rows:
        visits = row["visits"]
        row["form_rate"] = round(row["form_sessions"] * 100 / visits, 1) if visits else 0.0
        row["cta_rate"] = round(row["cta_sessions"] * 100 / visits, 1) if visits else 0.0
    return rows[: max(1, int(limit))]


def summary(
    range_key: str = "7d",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    init_db()
    now = datetime.now(timezone.utc)
    start, end, prev_start, mode, label = _range_bounds(
        range_key, now, start_date, end_date
    )
    start_s = start.isoformat(timespec="seconds")
    prev_s = prev_start.isoformat(timespec="seconds")
    now_s = end.isoformat(timespec="seconds")
    conn = get_connection()
    try:
        def scalar(sql: str, params: tuple = ()) -> Any:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None

        visits = int(scalar(
            "SELECT COUNT(*) FROM sessions WHERE started_at>=? AND started_at<?",
            (start_s, now_s),
        ) or 0)
        prev_visits = int(scalar(
            "SELECT COUNT(*) FROM sessions WHERE started_at>=? AND started_at<?",
            (prev_s, start_s),
        ) or 0)
        visitors = int(scalar(
            "SELECT COUNT(DISTINCT COALESCE(visitor_hash, session_key)) FROM sessions "
            "WHERE started_at>=? AND started_at<?",
            (start_s, now_s),
        ) or 0)
        prev_visitors = int(scalar(
            "SELECT COUNT(DISTINCT COALESCE(visitor_hash, session_key)) FROM sessions "
            "WHERE started_at>=? AND started_at<?",
            (prev_s, start_s),
        ) or 0)
        pageviews = int(scalar(
            "SELECT COUNT(*) FROM events WHERE name='pageview' AND ts>=? AND ts<?",
            (start_s, now_s),
        ) or 0)
        cta = int(scalar(
            "SELECT COUNT(*) FROM events WHERE name='cta_click' AND ts>=? AND ts<?",
            (start_s, now_s),
        ) or 0)
        forms = int(scalar(
            "SELECT COUNT(*) FROM events WHERE name='form_submit' AND ts>=? AND ts<?",
            (start_s, now_s),
        ) or 0)
        prev_pageviews = int(scalar(
            "SELECT COUNT(*) FROM events WHERE name='pageview' AND ts>=? AND ts<?",
            (prev_s, start_s),
        ) or 0)
        prev_cta = int(scalar(
            "SELECT COUNT(*) FROM events WHERE name='cta_click' AND ts>=? AND ts<?",
            (prev_s, start_s),
        ) or 0)
        prev_forms = int(scalar(
            "SELECT COUNT(*) FROM events WHERE name='form_submit' AND ts>=? AND ts<?",
            (prev_s, start_s),
        ) or 0)
        avg_eng = float(scalar(
            "SELECT COALESCE(AVG(engagement_ms),0) FROM sessions "
            "WHERE started_at>=? AND started_at<?",
            (start_s, now_s),
        ) or 0) / 1000.0
        prev_avg_eng = float(scalar(
            "SELECT COALESCE(AVG(engagement_ms),0) FROM sessions "
            "WHERE started_at>=? AND started_at<?",
            (prev_s, start_s),
        ) or 0) / 1000.0
        avg_scroll = float(scalar(
            "SELECT COALESCE(AVG(scroll_pct),0) FROM sessions "
            "WHERE started_at>=? AND started_at<?",
            (start_s, now_s),
        ) or 0)
        engaged = int(scalar(
            "SELECT COUNT(*) FROM sessions s WHERE s.started_at>=? AND s.started_at<? "
            "AND (s.scroll_pct>=50 OR EXISTS ("
            "  SELECT 1 FROM events e WHERE e.session_id=s.id "
            "  AND e.name IN ('cta_click','form_submit')))",
            (start_s, now_s),
        ) or 0)
        prev_engaged = int(scalar(
            "SELECT COUNT(*) FROM sessions s WHERE s.started_at>=? AND s.started_at<? "
            "AND (s.scroll_pct>=50 OR EXISTS ("
            "  SELECT 1 FROM events e WHERE e.session_id=s.id "
            "  AND e.name IN ('cta_click','form_submit')))",
            (prev_s, start_s),
        ) or 0)
        bounce_rate = round((1 - engaged / visits) * 100, 1) if visits else 0.0
        prev_bounce = (
            round((1 - prev_engaged / prev_visits) * 100, 1) if prev_visits else 0.0
        )

        # Série temporal
        rows = conn.execute(
            "SELECT started_at, visitor_hash, session_key FROM sessions "
            "WHERE started_at>=? AND started_at<?",
            (start_s, now_s),
        ).fetchall()
        buckets: dict[str, dict] = {}
        for row in rows:
            key = _bucket(str(row["started_at"]), mode)
            bucket = buckets.setdefault(
                key,
                {"t": key, "visits": 0, "visitors": 0, "pageviews": 0,
                 "cta": 0, "forms": 0},
            )
            bucket["visits"] += 1
            bucket.setdefault("_visitors", set()).add(
                row["visitor_hash"] or row["session_key"]
            )
        ev_rows = conn.execute(
            "SELECT ts, name, COUNT(*) c FROM events "
            "WHERE ts>=? AND ts<? AND name IN ('pageview','cta_click','form_submit') "
            "GROUP BY 1,2",
            (start_s, now_s),
        ).fetchall()
        for row in ev_rows:
            key = _bucket(str(row["ts"]), mode)
            buckets.setdefault(
                key,
                {"t": key, "visits": 0, "visitors": 0, "pageviews": 0,
                 "cta": 0, "forms": 0},
            )
            if row["name"] == "pageview":
                buckets[key]["pageviews"] += int(row["c"])
            elif row["name"] == "cta_click":
                buckets[key]["cta"] += int(row["c"])
            elif row["name"] == "form_submit":
                buckets[key]["forms"] += int(row["c"])
        for bucket in buckets.values():
            bucket["visitors"] = len(bucket.pop("_visitors", set()))
        series = [buckets[k] for k in sorted(buckets)]

        sources = _grouped(conn, ["source", "medium"], start_s, now_s, 12)
        geo = _grouped(conn, ["country", "region", "city"], start_s, now_s, 15)
        campaigns = _grouped(
            conn, ["source", "medium", "campaign", "content"], start_s, now_s, 15
        )
        attribution_rows = _grouped(
            conn,
            ["campaign", "content", "city"],
            start_s,
            now_s,
            15,
            extra_where="s.source='email'",
        )
        email_visits = sum(int(r["visits"] or 0) for r in attribution_rows)
        email_cta = sum(int(r["cta_clicks"] or 0) for r in attribution_rows)
        email_forms = sum(int(r["form_sessions"] or 0) for r in attribution_rows)
        email_attribution = {
            "visits": email_visits,
            "cta_clicks": email_cta,
            "form_submits": email_forms,
            "form_rate": round(email_forms * 100 / email_visits, 1)
            if email_visits
            else 0.0,
            "rows": attribution_rows,
        }

        devices = [
            dict(r) for r in conn.execute(
                "SELECT device, COUNT(*) visits FROM sessions "
                "WHERE started_at>=? AND started_at<? GROUP BY device ORDER BY visits DESC",
                (start_s, now_s),
            ).fetchall()
        ]
        locales = [
            dict(r) for r in conn.execute(
                "SELECT COALESCE(NULLIF(locale,''),'(unknown)') locale, COUNT(*) visits "
                "FROM sessions WHERE started_at>=? AND started_at<? "
                "GROUP BY locale ORDER BY visits DESC",
                (start_s, now_s),
            ).fetchall()
        ]
        events = [
            dict(r) for r in conn.execute(
                "SELECT name, COUNT(*) count, COUNT(DISTINCT session_id) sessions "
                "FROM events WHERE ts>=? AND ts<? GROUP BY name ORDER BY count DESC",
                (start_s, now_s),
            ).fetchall()
        ]
        recent = [
            dict(r) for r in conn.execute(
                """
                SELECT e.ts, e.name, e.path, e.label,
                       s.source, s.medium, s.campaign, s.content, s.city
                FROM events e JOIN sessions s ON s.id=e.session_id
                WHERE e.ts>=? AND e.ts<?
                ORDER BY e.ts DESC LIMIT 15
                """,
                (start_s, now_s),
            ).fetchall()
        ]
        cta_sessions = int(scalar(
            "SELECT COUNT(DISTINCT session_id) FROM events "
            "WHERE name='cta_click' AND ts>=? AND ts<?",
            (start_s, now_s),
        ) or 0)
        form_start_sessions = int(scalar(
            "SELECT COUNT(DISTINCT session_id) FROM events "
            "WHERE name='form_start' AND ts>=? AND ts<?",
            (start_s, now_s),
        ) or 0)
        form_sessions = int(scalar(
            "SELECT COUNT(DISTINCT session_id) FROM events "
            "WHERE name='form_submit' AND ts>=? AND ts<?",
            (start_s, now_s),
        ) or 0)
        scroll_sessions = int(scalar(
            "SELECT COUNT(*) FROM sessions s WHERE s.started_at>=? AND s.started_at<? "
            "AND (s.scroll_pct>=50 OR EXISTS ("
            "  SELECT 1 FROM events e WHERE e.session_id=s.id "
            "  AND e.name='scroll' AND e.value>=50))",
            (start_s, now_s),
        ) or 0)

        cta_rate = (cta_sessions / visits) if visits else 0.0
        form_rate = (form_sessions / visits) if visits else 0.0
        volume_score = _score_ratio(visits, prev_visits)
        engagement_score = (
            max(0, min(100, int(round((min(avg_eng, 60) / 60) * 60 + (avg_scroll / 100) * 40))))
            if visits else 0
        )
        conversion_score = (
            max(0, min(100, int(round((min(cta_rate, 0.05) / 0.05) * 60
                                      + (min(form_rate, 0.02) / 0.02) * 40))))
            if visits else 0
        )
        overall = int(round(
            volume_score * 0.4 + engagement_score * 0.3 + conversion_score * 0.3
        ))
        status = "ok" if overall >= 80 else ("warn" if overall >= 50 else "fail")
        reasons: list[str] = []
        if not visits:
            reasons.append("sem tráfego no período")
        else:
            if volume_score < 50:
                reasons.append("volume abaixo do período anterior")
            if engagement_score < 50:
                reasons.append("engagement baixo")
            if conversion_score < 50:
                reasons.append("poucos cliques/formulários")
        funnel = [
            {"step": "Visitas", "count": visits, "rate": 100.0 if visits else 0.0},
            {"step": "Scroll 50%", "count": scroll_sessions,
             "rate": round(scroll_sessions * 100 / visits, 1) if visits else 0.0},
            {"step": "CTA click", "count": cta_sessions,
             "rate": round(cta_sessions * 100 / visits, 1) if visits else 0.0},
            {"step": "Form start", "count": form_start_sessions,
             "rate": round(form_start_sessions * 100 / visits, 1) if visits else 0.0},
            {"step": "Form submit", "count": form_sessions,
             "rate": round(form_sessions * 100 / visits, 1) if visits else 0.0},
        ]
        return {
            "generated_at": now_s,
            "range": label,
            "start": start.date().isoformat(),
            "end": (end - timedelta(seconds=1)).date().isoformat(),
            "window_start": start_s,
            "window_end": now_s,
            "overall": {
                "score": overall,
                "status": status,
                "status_label": {"ok": "Saudável", "warn": "Atenção", "fail": "Crítico"}[status],
                "reasons": reasons,
                "volume": volume_score,
                "engagement": engagement_score,
                "conversion": conversion_score,
            },
            "cards": {
                "visits": {"value": visits, "delta_pct": _delta_pct(visits, prev_visits),
                           "spark": [b["visits"] for b in series]},
                "visitors": {"value": visitors, "delta_pct": _delta_pct(visitors, prev_visitors),
                             "spark": [b["visits"] for b in series]},
                "pageviews": {"value": pageviews,
                              "delta_pct": _delta_pct(pageviews, prev_pageviews),
                              "spark": [b["pageviews"] for b in series]},
                "cta_clicks": {"value": cta,
                               "delta_pct": _delta_pct(cta, prev_cta),
                               "spark": [b["cta"] for b in series]},
                "form_submits": {"value": forms,
                                 "delta_pct": _delta_pct(forms, prev_forms),
                                 "spark": [b["forms"] for b in series]},
                "avg_engagement_s": {"value": round(avg_eng, 1),
                                     "delta_pct": _delta_pct(avg_eng, prev_avg_eng),
                                     "spark": []},
                "bounce_rate": {"value": bounce_rate,
                                "delta_pct": _delta_pct(bounce_rate, prev_bounce),
                                "spark": []},
            },
            "series": series,
            "sources": sources,
            "campaigns": campaigns,
            "email_attribution": email_attribution,
            "geo": geo,
            "internal_filter": True,
            "funnel": funnel,
            "events": events,
            "devices": devices,
            "locales": locales,
            "recent": recent,
        }
    finally:
        conn.close()


def get_summary(
    range_key: str = "7d",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    key = (range_key or "7d").lower()
    cache_key = f"{db_path()}:{key}:{start_date or ''}:{end_date or ''}"
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    data = summary(key, start_date, end_date)
    _CACHE[cache_key] = (now, data)
    return data


def clear_cache() -> None:
    _CACHE.clear()


def maintenance(days_events: int = 90, days_sessions: int = 180) -> dict:
    init_db()
    conn = get_connection()
    try:
        ev = conn.execute(
            "DELETE FROM events WHERE datetime(ts) < datetime('now', ?)",
            (f"-{max(1, int(days_events))} days",),
        ).rowcount
        sess = conn.execute(
            "DELETE FROM sessions WHERE datetime(last_seen_at) < datetime('now', ?)",
            (f"-{max(1, int(days_sessions))} days",),
        ).rowcount
        salts = conn.execute(
            "DELETE FROM meta WHERE key LIKE 'salt:%' AND key<>?",
            (f"salt:{_utc_day()}",),
        ).rowcount
        conn.commit()
        return {"events": int(ev or 0), "sessions": int(sess or 0), "salts": int(salts or 0)}
    finally:
        conn.close()


def maintenance_if_due() -> dict:
    """Purge diário de retenção (chamado pela Control Tower)."""
    init_db()
    today = _utc_day()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key='maintenance_day'"
        ).fetchone()
        if row and str(row["value"]) == today:
            return {"status": "skipped"}
    finally:
        conn.close()
    result = maintenance(90, 180)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('maintenance_day', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (today,),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("[ANALYTICS] manutenção: %s", result)
    return {"status": "ok", **result}
