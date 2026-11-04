"""Registry de roteiros de voz (Fase 2B).

Roteiros em inglês, versionados, com status draft/approved e variáveis
Mustache. O texto é o `instructions` do Telnyx AI Assistant; o assistente é
iniciado na chamada quando o contacto atende.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx

from ..config import settings
from ..utils.logger import logger
from . import b2b_voice, showcase

DISCLOSURE = "Hi {{company | Contractor}}, this is an automated assistant from Magic Leads."

TEMPLATE_VERSION = "2026-11-04.3"

# Guardrails do voice: nunca prometer uma vitrine com contagem fraca/zero
# nem usar inventário antigo. O valor pode ser afinado por ambiente.
VOICE_MIN_SHOWCASE_ITEMS = 5
VOICE_SHOWCASE_MAX_AGE_HOURS = 72.0

DEFAULT_TEMPLATE = (
    "Hi {{company | Contractor}}, this is an automated assistant from Magic "
    "Leads. We have {{showcase_line}} on MagicLeads.app right now. Stop wasting "
    "money competing with 5 to 8 other contractors on traditional platforms "
    "that only bleed your pocket. With us, you get exclusive opportunities up "
    "to 7 days before anyone else, with the client's name, address, and job "
    "details. Go to MagicLeads.app on your phone's browser to close your first "
    "deal today. To remove your number from our list, press 2 now. Have a "
    "great day!"
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

FALLBACK_SCRIPT = (
    "You can visit MagicLeads.app to see this week's active opportunities. "
    "Have a great day!"
)

TOOL_GUIDANCE = (
    "## Operational rules\n"
    "You are on a live outbound phone call. Follow the approved script above "
    "exactly; do not add claims, prices, or promises that are not in it.\n"
    "- The script asks the caller to visit MagicLeads.app and to press 2 to be "
    "removed from the list.\n"
    "- Pressing 2 is an opt-out. The backend handles the suppression and the "
    "confirmation; do not call any tool for DTMF input.\n"
    "- Call remove_from_list only when the caller verbally asks to be removed "
    "or to stop calling (for example: \"remove me\", \"stop calling\", \"do "
    "not call\", \"take me off your list\").\n"
    "- Do not ask for an email address. Do not promise email or SMS delivery. "
    "The only conversion path is the website.\n"
    "- If the caller asks for the website, repeat \"MagicLeads dot app\".\n"
    "- If the caller says no or is not interested, end the call politely. Do "
    "not pressure them.\n"
)


def build_instructions(body: str) -> str:
    """Script aprovado + regras operacionais (website-only, sem email/SMS)."""
    return f"{str(body or '').strip()}\n\n{TOOL_GUIDANCE}"


def opening_for_greeting(body: str) -> str:
    """Primeira fala, sem o label 'Opening & Pitch:'."""
    first = str(body or "").split("\n\nIf Yes", 1)[0].strip()
    if first.lower().startswith("opening & pitch:"):
        first = first.split(":", 1)[1].strip()
    return first



def _apply_template(conn) -> None:
    """Aplica o template global aprovado (V3) aos 15 seeds.

    A versão é bumpada e o script fica `approved` porque a V3 foi aprovada
    explicitamente pelo operador antes do deploy. Overrides por cidade/estado
    continuam a ter precedência e não são tocados.
    """
    now = datetime.now(timezone.utc).isoformat()
    for trade, body in DEFAULT_SCRIPTS.items():
        existing = conn.execute(
            "SELECT version FROM voice_scripts WHERE trade_code=?", (trade,)
        ).fetchone()
        version = int(existing["version"] or 0) + 1 if existing else 1
        conn.execute(
            """
            INSERT INTO voice_scripts
              (trade_code, version, status, body, disclosure, approved_by,
               approved_at, updated_at)
            VALUES (?, ?, 'approved', ?, ?, 0, ?, ?)
            ON CONFLICT(trade_code) DO UPDATE SET
              version=excluded.version,
              status='approved',
              body=excluded.body,
              disclosure=excluded.disclosure,
              approved_by=0,
              approved_at=excluded.approved_at,
              updated_at=excluded.updated_at
            """,
            (trade, version, body, DISCLOSURE, now, now),
        )
        conn.execute(
            "INSERT INTO voice_script_versions "
            "(trade_code, version, status, body, disclosure, created_at, created_by) "
            "VALUES (?, ?, 'approved', ?, ?, ?, 0)",
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
                # Override por cidade/estado herda assistant/voz do global
                # quando não define os seus próprios.
                result["assistant_id"] = (
                    result.get("assistant_id")
                    or global_script.get("assistant_id")
                    or ""
                )
                result["voice_id"] = (
                    result.get("voice_id") or global_script.get("voice_id") or ""
                )
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
    shared_id = str(
        getattr(settings, "TELNYX_SHARED_ASSISTANT_ID", "") or ""
    ).strip()
    if shared_id and scripts:
        # Plano Telnyx limita TeXML Applications: um assistant serve os 15
        # roteiros; as instructions sao renderizadas por chamada.
        try:
            sync_to_telnyx(scripts[0]["trade_code"])
        except ValueError as exc:
            return {
                "ok": False,
                "status": "partial",
                "synced": 0,
                "total": len(scripts),
                "shared": True,
                "assistant_id": shared_id,
                "errors": [
                    {
                        "trade_code": scripts[0]["trade_code"],
                        "error": str(exc)[:300],
                    }
                ],
            }
        conn = b2b_voice.get_conn()
        try:
            conn.execute(
                "UPDATE voice_scripts SET assistant_id=? WHERE status='approved'",
                (shared_id,),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "ok": True,
            "status": "ok",
            "synced": len(scripts),
            "total": len(scripts),
            "shared": True,
            "assistant_id": shared_id,
            "errors": [],
        }
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


_VAR_RE = re.compile(
    r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\|\s*([^}]*?))?\s*\}\}"
)

_BAD_COMPANY = {
    "UNAVAILABLE OWNER",
    "UNKNOWN",
    "OWNER",
    "N A",
    "NA",
    "NONE",
    "TAXPAYER OF",
    "SAME AS OWNER",
    "SELF",
    "PRIVATE",
}


def _clean_company(value: object) -> str:
    """Nome apresentável para o TTS; vazio se for placeholder ou lixo."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    normalized = re.sub(r"[^A-Z0-9 ]+", " ", text.upper())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if len(normalized) < 3 or normalized in _BAD_COMPANY:
        return ""
    return text


def _render_template(text: str, values: dict[str, str]) -> str:
    """Substitui {{var}} e {{var | fallback}} sem deixar braces no áudio."""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        fallback = (match.group(2) or "").strip()
        value = values.get(key)
        if value is None or not str(value).strip():
            return fallback
        return str(value)

    return _VAR_RE.sub(repl, str(text or ""))


def _spoken_count(value: object) -> str:
    """Números grandes arredondados para não arrastar o TTS."""
    try:
        count = max(0, int(value))
    except (TypeError, ValueError):
        return "0"
    if count >= 1000:
        rounded = (count // 100) * 100
        return f"over {rounded:,}"
    return str(count)


def _voice_min_items() -> int:
    return max(
        1,
        int(
            getattr(
                settings,
                "VOICE_MIN_SHOWCASE_ITEMS",
                VOICE_MIN_SHOWCASE_ITEMS,
            )
            or VOICE_MIN_SHOWCASE_ITEMS
        ),
    )


def _voice_max_age_hours() -> float:
    try:
        return max(
            0.0,
            float(
                getattr(
                    settings,
                    "VOICE_SHOWCASE_MAX_AGE_HOURS",
                    VOICE_SHOWCASE_MAX_AGE_HOURS,
                )
                or VOICE_SHOWCASE_MAX_AGE_HOURS
            ),
        )
    except (TypeError, ValueError):
        return VOICE_SHOWCASE_MAX_AGE_HOURS


def showcase_guard(trade_code: str, city: str = "") -> dict:
    """Fonte única da linha falada e do gate de disparo.

    Nunca devolve uma linha com 0. Se a contagem exata ou city-wide estiver
    abaixo do mínimo, ou se o inventário estiver velho, `ready=False` e a
    chamada real é bloqueada por `telnyx_voice.create_call`.
    """
    code = showcase.normalize_trade(trade_code) or str(trade_code or "").strip()
    city_label = str(city or "").strip() or "your city"
    threshold = _voice_min_items()
    info = showcase.available(
        city_label,
        code,
        min_items=threshold,
        max_age_hours=_voice_max_age_hours(),
    )
    exact = int(info.get("exact_count") or 0)
    city_total = int(info.get("city_total") or 0)
    # Voz é estrita: o número tem de ser do nicho exato. Um total city-wide
    # ("863 property opportunities") não serve para um HVAC/roofing e seria
    # exatamente o tipo de número estranho que queremos evitar.
    problems: list[str] = []
    if info.get("fresh") is False:
        problems.append("stale_inventory")
    if exact < threshold:
        problems.append("insufficient_trade_inventory")
    if problems:
        return {
            "ready": False,
            "reason": ",".join(problems),
            "line": "",
            "scope": "none",
            "count": exact,
            "exact_count": exact,
            "city_total": city_total,
            "threshold": threshold,
            "built_at": info.get("built_at"),
            "age_hours": info.get("age_hours"),
        }
    line = (
        f"{_spoken_count(exact)} active {showcase.trade_label(code).lower()} "
        f"opportunities in {city_label} this week"
    )
    return {
        "ready": True,
        "reason": "",
        "line": line,
        "scope": "trade",
        "count": exact,
        "exact_count": exact,
        "city_total": city_total,
        "threshold": threshold,
        "built_at": info.get("built_at"),
        "age_hours": info.get("age_hours"),
    }


def render(
    trade_code: str,
    company: str = "",
    city: str = "",
    permit_count: int = 0,
    state: str = "",
    email: str = "",
) -> dict:
    script = get_effective_script(trade_code, city, state)
    if not script:
        raise ValueError("roteiro não encontrado")
    code = showcase.normalize_trade(trade_code) or trade_code
    city_label = city.strip() or "your city"
    guard = showcase_guard(code, city_label)
    if not guard["ready"]:
        raise ValueError(f"showcase_unavailable: {guard['reason']}")
    values = {
        "company": _clean_company(company) or "Contractor",
        "city": city_label,
        "trade": showcase.trade_label(code),
        "permit_count": str(int(permit_count or 0)),
        "showcase_line": guard["line"],
        "price_weekly": "$120",
        "price_monthly": "$520",
    }
    body = _render_template(script["body"], values)
    disclosure = _render_template(script.get("disclosure") or DISCLOSURE, values)
    greeting = opening_for_greeting(body)
    return {
        "trade_code": code,
        "version": script["version"],
        "status": script["status"],
        "assistant_id": script.get("assistant_id") or "",
        "voice_id": _assistant_voice(script),
        "body": body,
        "instructions": build_instructions(body),
        "greeting": greeting,
        "disclosure": disclosure,
        "showcase": guard,
        "variables": {f"{{{{{key}}}}}": value for key, value in values.items()},
    }


def approved_for_trade(
    trade_code: str, city: str = "", state: str = ""
) -> Optional[dict]:
    script = get_effective_script(trade_code, city, state)
    if script and script.get("status") == "approved":
        return script
    return None


def _assistant_voice(script: dict) -> str:
    return (
        (script.get("voice_id") or "").strip()
        or str(getattr(settings, "TELNYX_ASSISTANT_VOICE", "") or "").strip()
    )


def _tools_base_url() -> str:
    base = str(getattr(settings, "TELNYX_TOOLS_URL", "") or "").strip()
    if not base:
        public = str(getattr(settings, "PUBLIC_API_URL", "") or "").rstrip("/")
        base = f"{public}/api/voice/telnyx/tools"
    return base.rstrip("/")


def _assistant_tools() -> list[dict]:
    """Tools webhook que ligam a conversa ao backend (link e opt-out)."""
    base = _tools_base_url()
    secret = str(getattr(settings, "TELNYX_WEBHOOK_SECRET", "") or "")

    def tool(name: str, description: str, properties: dict, required: list[str]):
        url = f"{base}/{name}"
        if secret:
            url = f"{url}?secret={quote(secret)}"
        return {
            "type": "webhook",
            "webhook": {
                "name": name,
                "description": description,
                "url": url,
                "method": "POST",
                "body_parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    return [
        tool(
            "remove_from_list",
            (
                "Register that the caller asked to stop. Use it only when the "
                "caller verbally asks to be removed or to stop calling. DTMF 2 "
                "is handled by the backend."
            ),
            {},
            [],
        ),
    ]


def _voice_settings(script: dict) -> dict:
    voice = _assistant_voice(script)
    if not voice:
        return {}
    settings_payload: dict = {"voice": voice}
    if bool(getattr(settings, "TELNYX_ASSISTANT_EXPRESSIVE_MODE", False)):
        if voice.startswith("Telnyx.Ultra."):
            settings_payload["expressive_mode"] = True
    return settings_payload


def sync_to_telnyx(trade_code: str) -> dict:
    script = get_script(trade_code)
    if not script:
        raise ValueError("roteiro não encontrado")
    if script.get("status") != "approved":
        raise ValueError("aprova o roteiro antes de sincronizar")
    key = getattr(settings, "TELNYX_API_KEY", "")
    if not key:
        raise ValueError("TELNYX_API_KEY não configurada")
    shared_id = str(
        getattr(settings, "TELNYX_SHARED_ASSISTANT_ID", "") or ""
    ).strip()
    assistant_id = shared_id or (script.get("assistant_id") or "").strip()
    body = {
        "name": (
            "Magic Leads — Voice"
            if shared_id
            else f"Magic Leads — {showcase.trade_label(script['trade_code'])}"
        ),
        "instructions": build_instructions(script["body"]),
        "tools": _assistant_tools(),
        "telephony_settings": {
            # O assistant nao deve receber DTMF: 1/2 sao tratados pelo backend
            # (1 envia o link, 2 para o assistant e toca o MP3). Assim o LLM
            # nao comeca uma resposta que seria cortada pelo stop.
            "disable_dtmf": True,
            "voicemail_detection": {
                "on_voicemail_detected": {"action": "stop_assistant"}
            },
            "recording_settings": {"enabled": False},
        },
    }
    transcription_model = str(
        getattr(settings, "TELNYX_ASSISTANT_TRANSCRIPTION_MODEL", "") or ""
    ).strip()
    if transcription_model:
        transcription: dict = {"model": transcription_model, "language": "en"}
        keyterms = str(
            getattr(settings, "TELNYX_ASSISTANT_KEYTERMS", "") or ""
        ).strip()
        if keyterms:
            transcription["settings"] = {"keyterm": keyterms}
        body["transcription"] = transcription
    noise_suppression = str(
        getattr(settings, "TELNYX_ASSISTANT_NOISE_SUPPRESSION", "") or ""
    ).strip()
    if noise_suppression:
        body["telephony_settings"]["noise_suppression"] = noise_suppression
    voice_settings = _voice_settings(script)
    if voice_settings:
        body["voice_settings"] = voice_settings
    try:
        if assistant_id:
            response = httpx.post(
                f"https://api.telnyx.com/v2/ai/assistants/{assistant_id}",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=30,
            )
            mode = "shared" if shared_id else "updated"
        else:
            model = str(getattr(settings, "TELNYX_ASSISTANT_MODEL", "") or "").strip()
            if model:
                body["model"] = model
            response = httpx.post(
                "https://api.telnyx.com/v2/ai/assistants",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
                timeout=30,
            )
            mode = "created"
        if response.status_code >= 300:
            detail = ""
            try:
                detail = json.dumps(response.json(), ensure_ascii=False)[:300]
            except Exception:  # noqa: BLE001
                detail = response.text[:300]
            raise ValueError(f"Telnyx HTTP {response.status_code}: {detail}")
        data = response.json() if response.content else {}
        nested = data.get("data") if isinstance(data, dict) else None
        payload = nested if isinstance(nested, dict) else data
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
