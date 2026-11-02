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

DISCLOSURE = (
    "Hi, this is an automated assistant from Magic Leads. This call may be "
    "recorded for quality. You can say stop at any time and we will not call "
    "you again."
)

_RULES = (
    "RULES: Speak US English only. Keep the call under 60 seconds. Never "
    "promise jobs, revenue or a specific close rate. Use only the facts in "
    "{{showcase_line}} and {{permit_count}}. If asked whether you are an AI, "
    "say yes. If the person says stop, not interested, or do not call, confirm "
    "once and end the call. Do not mention homeowner names or exact addresses."
)


def _script(trade: str, value_line: str, objection_line: str) -> str:
    return (
        "ROLE: You are a courteous, executive US English B2B voice assistant "
        "for Magic Leads. You call contractors, not homeowners.\n\n"
        f"DISCLOSURE: \"{DISCLOSURE}\"\n\n"
        "OPENING: \"Hi, I'm calling {{company}} because you're an active "
        "{{trade}} contractor in {{city}}. Do you have thirty seconds?\"\n\n"
        f"VALUE: \"{value_line} {objection_line}\"\n\n"
        "QUALIFY: \"{{showcase_line}} Would it help if I sent you the masked "
        "list by email so you can see the projects?\"\n\n"
        "PRICE: \"Access is a seven-day pass for {{price_weekly}}, which is "
        "{{price_monthly}} per month normalized. No annual contract and no "
        "per-lead fee.\"\n\n"
        "OBJECTIONS:\n"
        "- Too expensive: \"It is a weekly pass, not a per-lead charge. You "
        "can test one week and cancel.\"\n"
        "- I already buy leads: \"Most shared-lead programs send the same "
        "request to several contractors. We keep one business per address.\"\n"
        "- Send information: \"I can send the masked city list and the "
        "checkout link right now.\"\n"
        "- Not interested: \"No problem. I will mark you as do-not-call and "
        "we will not call again.\"\n\n"
        "CLOSE: \"If you want the list, say yes or press one. If not, say "
        "stop.\"\n\n" + _RULES
    )


DEFAULT_SCRIPTS: dict[str, str] = {
    "remodeling": _script(
        "remodeling",
        "We track active remodeling and structure opportunities from public "
        "records in {{city}}, including permit and property signals.",
        "Unlike shared-lead marketplaces, we do not resell the same address "
        "to a group of contractors.",
    ),
    "roofing": _script(
        "roofing",
        "We track active roofing and exterior opportunities from public "
        "records in {{city}}.",
        "One contractor per address means you are not bidding against four "
        "other roofers for the same homeowner.",
    ),
    "electrical": _script(
        "electrical",
        "We track electrical and building-service opportunities from public "
        "records in {{city}}.",
        "You get a focused weekly list instead of paying separately for every "
        "shared lead.",
    ),
    "painting": _script(
        "painting",
        "We track painting and property-condition opportunities from public "
        "records in {{city}}.",
        "The weekly pass is designed for contractors who want a predictable "
        "local pipeline.",
    ),
    "hvac": _script(
        "hvac",
        "We track heating, cooling and building-service opportunities from "
        "public records in {{city}}.",
        "You see the opportunity before it is resold across a large "
        "marketplace.",
    ),
    "plumbing": _script(
        "plumbing",
        "We track plumbing and water-related opportunities from public "
        "records in {{city}}.",
        "The pass gives you a local list without a per-lead auction.",
    ),
    "landscaping": _script(
        "landscaping",
        "We track landscaping, vegetation and exterior opportunities from "
        "public records in {{city}}.",
        "You can focus on the addresses that match your crew and service area.",
    ),
    "windows": _script(
        "windows",
        "We track window, door and exterior-envelope opportunities from "
        "public records in {{city}}.",
        "One business per address keeps your estimate pipeline cleaner.",
    ),
    "general_contractor": _script(
        "general_contractor",
        "We track construction, remodeling and property opportunities from "
        "public records in {{city}}.",
        "The weekly pass is built for contractors who want local projects "
        "without a shared-lead race.",
    ),
    "remediation": _script(
        "remediation",
        "We track remediation, restoration and property-condition "
        "opportunities from public records in {{city}}.",
        "You get a focused list and a clear weekly price.",
    ),
    "cleaning": _script(
        "cleaning",
        "We track cleaning and property-condition opportunities from public "
        "records in {{city}}.",
        "The pass is weekly, so you can test your market without a long "
        "contract.",
    ),
    "pest_control": _script(
        "pest_control",
        "We track pest-control and property-condition opportunities from "
        "public records in {{city}}.",
        "You see local signals without paying a separate fee for every shared "
        "lead.",
    ),
    "debris_removal": _script(
        "debris_removal",
        "We track debris, cleanup and property-maintenance opportunities from "
        "public records in {{city}}.",
        "The weekly pass keeps the cost predictable while you test the route.",
    ),
    "elevator": _script(
        "elevator",
        "We track elevator and building-service opportunities from public "
        "records in {{city}}.",
        "The pass is designed for specialist contractors with a focused "
        "service area.",
    ),
    "signage": _script(
        "signage",
        "We track signage, permit and business-location opportunities from "
        "public records in {{city}}.",
        "You get a local list without a shared-lead marketplace taking a cut "
        "of every job.",
    ),
}

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
        count = int(conn.execute("SELECT COUNT(*) FROM voice_scripts").fetchone()[0] or 0)
        if count == 0:
            now = datetime.now(timezone.utc).isoformat()
            for trade, body in DEFAULT_SCRIPTS.items():
                conn.execute(
                    "INSERT INTO voice_scripts "
                    "(trade_code, version, status, body, disclosure, "
                    "updated_at) VALUES (?, 1, 'draft', ?, ?, ?)",
                    (trade, body, DISCLOSURE, now),
                )
                conn.execute(
                    "INSERT INTO voice_script_versions "
                    "(trade_code, version, status, body, disclosure, "
                    "created_at) VALUES (?, 1, 'draft', ?, ?, ?)",
                    (trade, body, DISCLOSURE, now),
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


def render(
    trade_code: str,
    company: str = "",
    city: str = "",
    permit_count: int = 0,
) -> dict:
    script = get_script(trade_code)
    if not script:
        raise ValueError("roteiro não encontrado")
    code = showcase.normalize_trade(trade_code) or trade_code
    city_label = city.strip() or "your city"
    trade_label = showcase.trade_label(code)
    available = showcase.available(city_label, code)
    if available["available"]:
        showcase_line = (
            f"We have {available['exact_count']} active {trade_label.lower()} "
            f"opportunities in {city_label} this week."
        )
    elif available["city_total"]:
        showcase_line = (
            f"We have {available['city_total']} active property opportunities "
            f"in {city_label} this week."
        )
    else:
        showcase_line = (
            f"We have new property opportunities in {city_label} this week."
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


def approved_for_trade(trade_code: str) -> Optional[dict]:
    script = get_script(trade_code)
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
