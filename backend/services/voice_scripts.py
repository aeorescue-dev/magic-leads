"""Registry de roteiros de voz (Fase 2B).

Roteiros em inglês, versionados, com status draft/approved e variáveis
Mustache. O texto é o `instructions` do Telnyx AI Assistant; o assistente é
iniciado na chamada quando o contacto atende.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from ..config import settings
from ..utils.logger import logger
from . import b2b_voice, showcase

DISCLOSURE = "Hi {{company}}, this is an automated assistant from Magic Leads."

TEMPLATE_VERSION = "2026-11-02.1"

DEFAULT_TEMPLATE = (
    "Opening & Pitch: Hi {{company}}, this is an automated assistant from "
    "Magic Leads. On our website right now, we have {{showcase_line}}. We're "
    "reaching out so you don't miss these exclusive opportunities. We deliver "
    "the client's name, address, and the specific job to perform before any "
    "competitor finds out. Can I send you our website link so you can check "
    "these opportunities?\n\n"
    "If Yes / Press 1: Great! What's the best email address to send the link "
    "right now?\n\n"
    "If No / Stop: No problem at all. I'll remove your number from our list. "
    "Have a great day!"
)

TRADES = (
    "remodeling",
    "roofing",
    "electrical",
    "painting",
    "hvac",
    "plumbing",
    "landscaping",
    "windows",
    "general_contractor",
    "remediation",
    "cleaning",
    "pest_control",
    "debris_removal",
    "elevator",
    "signage",
)

DEFAULT_SCRIPTS: dict[str, str] = {trade: DEFAULT_TEMPLATE for trade in TRADES}


def _apply_template(conn) -> None:
    """Atualiza os 15 seeds para o template oficial e volta a draft."""
    now = datetime.now(timezone.utc).isoformat()
    for trade, body in DEFAULT_SCRIPTS.items():
        existing = conn.execute(
            "SELECT version FROM voice_scripts WHERE trade_code=?", (trade,)
        ).fetchone()
        version = int(existing["version"] or 0) + 1 if existing else 1
        conn.execute(
            """
            INSERT INTO voice_scripts
              (trade_code, version, status, body, disclosure, updated_at)
            VALUES (?, ?, 'draft', ?, ?, ?)
            ON CONFLICT(trade_code) DO UPDATE SET
              version=excluded.version,
              status='draft',
              body=excluded.body,
              disclosure=excluded.disclosure,
              updated_at=excluded.updated_at
            """,
            (trade, version, body, DISCLOSURE, now),
        )
        conn.execute(
            "INSERT INTO voice_script_versions "
            "(trade_code, version, status, body, disclosure, created_at, created_by) "
            "VALUES (?, ?, 'draft', ?, ?, ?, 0)",
            (trade, version, body, DISCLOSURE, now),
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_scripts (
  trade_code TEXT PRIMARY KEY,
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft',
  body TEXT NOT NULL,
  disclosure TEXT,
  voice_id TEXT,
  assistant_id TEXT,
  approved_by INTEGER,
  approved_at TEXT,
  updated_by INTEGER,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_script_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_code TEXT NOT NULL,
  version INTEGER NOT NULL,
  status TEXT NOT NULL,
  body TEXT NOT NULL,
  disclosure TEXT,
  created_at TEXT NOT NULL,
  created_by INTEGER
);
CREATE INDEX IF NOT EXISTS idx_script_versions_trade
  ON voice_script_versions (trade_code, version DESC);

CREATE TABLE IF NOT EXISTS voice_script_overrides (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_code TEXT NOT NULL,
  scope_type TEXT NOT NULL DEFAULT 'state',
  scope_value TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft',
  body TEXT NOT NULL,
  disclosure TEXT,
  voice_id TEXT,
  assistant_id TEXT,
  approved_by INTEGER,
  approved_at TEXT,
  updated_by INTEGER,
  updated_at TEXT NOT NULL,
  UNIQUE(trade_code, scope_type, scope_value)
);
CREATE INDEX IF NOT EXISTS idx_script_overrides_scope
  ON voice_script_overrides (trade_code, scope_type, scope_value, status);
"""

_INIT: dict[str, Optional[str]] = {"path": None}


def init() -> None:
    b2b_voice.init()
    path = b2b_voice.db_path()
    if _INIT["path"] == path:
        return
    conn = b2b_voice.get_conn()
    try:
        conn.executescript(_SCHEMA)
        row = conn.execute(
            "SELECT value FROM voice_meta WHERE key='scripts_template_version'"
        ).fetchone()
        current = str(row["value"]) if row else ""
        if current != TEMPLATE_VERSION:
            _apply_template(conn)
            conn.execute(
                "INSERT INTO voice_meta (key, value) "
                "VALUES ('scripts_template_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (TEMPLATE_VERSION,),
            )
        conn.commit()
    finally:
        conn.close()
    _INIT["path"] = path


def list_scripts() -> list[dict]:
    init()
    conn = b2b_voice.get_conn()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT trade_code, version, status, body, disclosure, "
                "voice_id, assistant_id, approved_by, approved_at, updated_at "
                "FROM voice_scripts ORDER BY trade_code"
            ).fetchall()
        ]
    finally:
        conn.close()


def get_script(trade_code: str) -> Optional[dict]:
    init()
    code = showcase.normalize_trade(trade_code) or str(trade_code or "").strip()
    conn = b2b_voice.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM voice_scripts WHERE trade_code=?", (code,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_effective_script(
    trade_code: str, city: str = "", state: str = ""
) -> Optional[dict]:
    """Resolve override aprovado (cidade > estado) ou o default global."""
    global_script = get_script(trade_code)
    if not global_script:
        return None
    code = global_script["trade_code"]
    candidates: list[tuple[str, str]] = []
    if city.strip():
        candidates.append(("city", city.strip()))
    if state.strip():
        candidates.append(("state", state.strip().upper()))
    conn = b2b_voice.get_conn()
    try:
        for scope_type, scope_value in candidates:
            row = conn.execute(
                "SELECT * FROM voice_script_overrides "
                "WHERE trade_code=? AND scope_type=? "
                "AND UPPER(scope_value)=UPPER(?) AND status='approved'",
                (code, scope_type, scope_value),
            ).fetchone()
            if row:
                result = dict(row)
                result["scope"] = scope_type
                result["scope_value"] = scope_value
                return result
    finally:
        conn.close()
    result = dict(global_script)
    result["scope"] = "global"
    result["scope_value"] = ""
    return result


def save_draft(
    trade_code: str,
    body: str,
    disclosure: str = "",
    assistant_id: str = "",
    voice_id: str = "",
    user_id: int = 0,
) -> dict:
    init()
    code = showcase.normalize_trade(trade_code) or str(trade_code or "").strip()
    if not code or not body.strip():
        raise ValueError("trade_code e body são obrigatórios")
    now = datetime.now(timezone.utc).isoformat()
    conn = b2b_voice.get_conn()
    try:
        current = conn.execute(
            "SELECT version FROM voice_scripts WHERE trade_code=?", (code,)
        ).fetchone()
        version = int(current["version"] or 0) + 1 if current else 1
        conn.execute(
            """
            INSERT INTO voice_scripts
              (trade_code, version, status, body, disclosure, voice_id,
               assistant_id, updated_by, updated_at)
            VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_code) DO UPDATE SET
              version=excluded.version,
              status='draft',
              body=excluded.body,
              disclosure=excluded.disclosure,
              voice_id=COALESCE(NULLIF(excluded.voice_id,''), voice_scripts.voice_id),
              assistant_id=COALESCE(NULLIF(excluded.assistant_id,''), voice_scripts.assistant_id),
              updated_by=excluded.updated_by,
              updated_at=excluded.updated_at
            """,
            (
                code,
                version,
                body,
                disclosure or DISCLOSURE,
                voice_id or "",
                assistant_id or "",
                int(user_id or 0),
                now,
            ),
        )
        conn.execute(
            "INSERT INTO voice_script_versions "
            "(trade_code, version, status, body, disclosure, created_at, created_by) "
            "VALUES (?, ?, 'draft', ?, ?, ?, ?)",
            (code, version, body, disclosure or DISCLOSURE, now, int(user_id or 0)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM voice_scripts WHERE trade_code=?", (code,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def approve(trade_code: str, user_id: int = 0) -> dict:
    init()
    code = showcase.normalize_trade(trade_code) or str(trade_code or "").strip()
    now = datetime.now(timezone.utc).isoformat()
    conn = b2b_voice.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM voice_scripts WHERE trade_code=?", (code,)
        ).fetchone()
        if not row:
            raise ValueError("roteiro não encontrado")
        conn.execute(
            "UPDATE voice_scripts SET status='approved', approved_by=?, "
            "approved_at=? WHERE trade_code=?",
            (int(user_id or 0), now, code),
        )
        conn.execute(
            "INSERT INTO voice_script_versions "
            "(trade_code, version, status, body, disclosure, created_at, created_by) "
            "VALUES (?, ?, 'approved', ?, ?, ?, ?)",
            (
                code,
                int(row["version"]),
                row["body"],
                row["disclosure"],
                now,
                int(user_id or 0),
            ),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM voice_scripts WHERE trade_code=?", (code,)
        ).fetchone()
        return dict(updated)
    finally:
        conn.close()


def approve_all(user_id: int = 0) -> dict:
    """Aprova todos os roteiros globais que ainda estão em draft."""
    init()
    now = datetime.now(timezone.utc).isoformat()
    conn = b2b_voice.get_conn()
    approved = 0
    trades: list[str] = []
    try:
        rows = conn.execute(
            "SELECT * FROM voice_scripts ORDER BY trade_code"
        ).fetchall()
        for row in rows:
            if row["status"] == "approved":
                continue
            conn.execute(
                "UPDATE voice_scripts SET status='approved', approved_by=?, "
                "approved_at=? WHERE trade_code=?",
                (int(user_id or 0), now, row["trade_code"]),
            )
            conn.execute(
                "INSERT INTO voice_script_versions "
                "(trade_code, version, status, body, disclosure, created_at, created_by) "
                "VALUES (?, ?, 'approved', ?, ?, ?, ?)",
                (
                    row["trade_code"],
                    int(row["version"]),
                    row["body"],
                    row["disclosure"],
                    now,
                    int(user_id or 0),
                ),
            )
            approved += 1
            trades.append(row["trade_code"])
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "approved": approved,
        "total": len(rows),
        "trades": trades,
    }


def sync_all() -> dict:
    """Sincroniza todos os roteiros aprovados com a Telnyx, se configurada."""
    init()
    if not getattr(settings, "TELNYX_API_KEY", ""):
        return {
            "ok": False,
            "status": "telnyx_not_configured",
            "synced": 0,
            "errors": [],
        }
    scripts = [item for item in list_scripts() if item["status"] == "approved"]
    synced = 0
    errors: list[dict] = []
    for script in scripts:
        try:
            result = sync_to_telnyx(script["trade_code"])
            if result.get("ok"):
                synced += 1
        except ValueError as exc:
            errors.append(
                {"trade_code": script["trade_code"], "error": str(exc)[:200]}
            )
    return {
        "ok": not errors,
        "status": "ok" if not errors else "partial",
        "synced": synced,
        "total": len(scripts),
        "errors": errors,
    }


def save_override(
    trade_code: str,
    scope_type: str,
    scope_value: str,
    body: str,
    disclosure: str = "",
    assistant_id: str = "",
    voice_id: str = "",
    user_id: int = 0,
) -> dict:
    """Cria/atualiza override por estado ou cidade; começa em draft."""
    init()
    code = showcase.normalize_trade(trade_code) or str(trade_code or "").strip()
    if scope_type not in ("state", "city"):
        raise ValueError("scope_type deve ser state ou city")
    if not code or not scope_value.strip() or not body.strip():
        raise ValueError("trade, scope_value e body são obrigatórios")
    now = datetime.now(timezone.utc).isoformat()
    conn = b2b_voice.get_conn()
    try:
        conn.execute(
            """
            INSERT INTO voice_script_overrides
              (trade_code, scope_type, scope_value, version, status, body,
               disclosure, voice_id, assistant_id, updated_by, updated_at)
            VALUES (?, ?, ?, 1, 'draft', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_code, scope_type, scope_value) DO UPDATE SET
              version=voice_script_overrides.version + 1,
              status='draft',
              body=excluded.body,
              disclosure=excluded.disclosure,
              voice_id=COALESCE(NULLIF(excluded.voice_id,''), voice_script_overrides.voice_id),
              assistant_id=COALESCE(NULLIF(excluded.assistant_id,''), voice_script_overrides.assistant_id),
              updated_by=excluded.updated_by,
              updated_at=excluded.updated_at
            """,
            (
                code,
                scope_type,
                scope_value.strip(),
                body,
                disclosure or DISCLOSURE,
                voice_id or "",
                assistant_id or "",
                int(user_id or 0),
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM voice_script_overrides WHERE trade_code=? "
            "AND scope_type=? AND scope_value=?",
            (code, scope_type, scope_value.strip()),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def approve_override(override_id: int, user_id: int = 0) -> dict:
    init()
    now = datetime.now(timezone.utc).isoformat()
    conn = b2b_voice.get_conn()
    try:
        conn.execute(
            "UPDATE voice_script_overrides SET status='approved', "
            "approved_by=?, approved_at=? WHERE id=?",
            (int(user_id or 0), now, int(override_id)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM voice_script_overrides WHERE id=?", (int(override_id),)
        ).fetchone()
        if not row:
            raise ValueError("override não encontrado")
        return dict(row)
    finally:
        conn.close()


def render(
    trade_code: str,
    company: str = "",
    city: str = "",
    permit_count: int = 0,
    state: str = "",
) -> dict:
    script = get_effective_script(trade_code, city, state)
    if not script:
        raise ValueError("roteiro não encontrado")
    code = showcase.normalize_trade(trade_code) or trade_code
    city_label = city.strip() or "your city"
    trade_label = showcase.trade_label(code)
    available = showcase.available(city_label, code)
    if available["available"]:
        showcase_line = (
            f"{available['exact_count']} active {trade_label.lower()} "
            f"opportunities in {city_label} this week"
        )
    elif available["city_total"]:
        showcase_line = (
            f"{available['city_total']} active property opportunities "
            f"in {city_label} this week"
        )
    else:
        showcase_line = (
            f"new property opportunities in {city_label} this week"
        )
    replacements = {
        "{{company}}": company or "your company",
        "{{city}}": city_label,
        "{{trade}}": trade_label,
        "{{permit_count}}": str(int(permit_count or 0)),
        "{{showcase_line}}": showcase_line,
        "{{price_weekly}}": "$120",
        "{{price_monthly}}": "$520",
    }
    body = script["body"]
    for key, value in replacements.items():
        body = body.replace(key, value)
    disclosure = (script.get("disclosure") or DISCLOSURE)
    for key, value in replacements.items():
        disclosure = disclosure.replace(key, value)
    return {
        "trade_code": code,
        "version": script["version"],
        "status": script["status"],
        "assistant_id": script.get("assistant_id") or "",
        "body": body,
        "disclosure": disclosure,
        "variables": replacements,
    }


def approved_for_trade(
    trade_code: str, city: str = "", state: str = ""
) -> Optional[dict]:
    script = get_effective_script(trade_code, city, state)
    if script and script.get("status") == "approved":
        return script
    return None


def sync_to_telnyx(trade_code: str) -> dict:
    script = get_script(trade_code)
    if not script:
        raise ValueError("roteiro não encontrado")
    if script.get("status") != "approved":
        raise ValueError("aprova o roteiro antes de sincronizar")
    key = getattr(settings, "TELNYX_API_KEY", "")
    if not key:
        raise ValueError("TELNYX_API_KEY não configurada")
    assistant_id = (script.get("assistant_id") or "").strip()
    body = {
        "name": f"Magic Leads — {showcase.trade_label(script['trade_code'])}",
        "instructions": script["body"],
    }
    voice = getattr(settings, "TELNYX_ASSISTANT_VOICE", "")
    if voice and not assistant_id:
        body["voice"] = voice
    try:
        if assistant_id:
            response = httpx.post(
                f"https://api.telnyx.com/v2/ai/assistants/{assistant_id}",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=30,
            )
            mode = "updated"
        else:
            model = getattr(settings, "TELNYX_ASSISTANT_MODEL", "")
            if not model:
                raise ValueError(
                    "define TELNYX_ASSISTANT_MODEL ou cola um assistant_id"
                )
            body["model"] = model
            response = httpx.post(
                "https://api.telnyx.com/v2/ai/assistants",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=30,
            )
            mode = "created"
        if response.status_code >= 300:
            raise ValueError(f"Telnyx HTTP {response.status_code}")
        data = response.json() if response.content else {}
        payload = data.get("data") if isinstance(data, dict) else {}
        new_id = (payload or {}).get("id") or assistant_id
        if new_id:
            conn = b2b_voice.get_conn()
            try:
                conn.execute(
                    "UPDATE voice_scripts SET assistant_id=? WHERE trade_code=?",
                    (new_id, script["trade_code"]),
                )
                conn.commit()
            finally:
                conn.close()
        return {"ok": True, "mode": mode, "assistant_id": new_id}
    except httpx.HTTPError as exc:
        logger.warning("[VOICE-SCRIPTS] Telnyx sync falhou: %s", type(exc).__name__)
        raise ValueError("falha de rede ao sincronizar com Telnyx")
