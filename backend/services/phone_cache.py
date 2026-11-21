"""Cache persistente de telefone (`phone_lookups`).

Regras (AGENTS #11):
  * hit valido -> 90 dias;
  * miss valido (`no_results`/`name_mismatch`) -> 7 dias, para nunca pagar
    duas vezes a mesma ausencia;
  * erro transitorio -> 1 hora, para nao transformar uma falha do provider
    numa ausencia permanente.

A chave inclui `lead_id`, nome do dono, morada e ZIP. Se o titular mudar, a
chave muda e o telefone do dono anterior deixa de ser servido.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from .db import get_connection

TTL_HIT_DAYS = 90
TTL_MISS_DAYS = 7
TTL_ERROR_HOURS = 1

_MISS_CODES = frozenset({"no_results", "name_mismatch", "guard_skipped"})


def _now_naive() -> datetime:
    return datetime.utcnow()


def normalize_key_part(value: Optional[str]) -> str:
    tokens = re.findall(r"[A-Z0-9]+", str(value or "").upper())
    return " ".join(tokens)


def owner_name_key(owner_name: Optional[str]) -> str:
    return normalize_key_part(owner_name)


def address_key(address: Optional[str], zip_code: Optional[str] = None) -> str:
    base = normalize_key_part(str(address or "").split(",")[0])
    zip_norm = re.sub(r"\D", "", str(zip_code or ""))[:5]
    return f"{base}|{zip_norm}"


def build_cache_key(
    lead_id: int,
    owner_name: Optional[str],
    address: Optional[str],
    zip_code: Optional[str] = None,
) -> str:
    material = "|".join(
        [
            str(int(lead_id)),
            owner_name_key(owner_name),
            address_key(address, zip_code),
        ]
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _expiry_for(result_code: str) -> datetime:
    code = (result_code or "").strip().lower()
    if code == "success":
        return _now_naive() + timedelta(days=TTL_HIT_DAYS)
    if code in _MISS_CODES:
        return _now_naive() + timedelta(days=TTL_MISS_DAYS)
    return _now_naive() + timedelta(hours=TTL_ERROR_HOURS)


def get(cache_key: str) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT * FROM phone_lookups
            WHERE cache_key = ?
              AND datetime(expires_at) > datetime('now')
            """,
            (cache_key,),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        # Cache e' optimizacao: uma falha aqui nunca pode derrubar o clique.
        return None
    finally:
        conn.close()


def put(
    *,
    cache_key: str,
    lead_id: int,
    owner_name: Optional[str],
    address: Optional[str],
    zip_code: Optional[str],
    state: Optional[str],
    phone: Optional[str],
    verified: bool,
    label: Optional[str],
    layer: Optional[str],
    provider: Optional[str],
    result_code: str,
) -> None:
    expires_at = _expiry_for(result_code).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO phone_lookups
              (cache_key, lead_id, owner_name_key, address_key, zip_code, state,
               phone, verified, label, layer, provider, result_code, expires_at,
               updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(cache_key) DO UPDATE SET
               phone = excluded.phone,
               verified = excluded.verified,
               label = excluded.label,
               layer = excluded.layer,
               provider = excluded.provider,
               result_code = excluded.result_code,
               expires_at = excluded.expires_at,
               updated_at = CURRENT_TIMESTAMP
            """,
            (
                cache_key,
                int(lead_id),
                owner_name_key(owner_name),
                address_key(address, zip_code),
                zip_code,
                state,
                phone,
                1 if verified else 0,
                label,
                layer,
                provider,
                result_code,
                expires_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def invalidate_lead(lead_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM phone_lookups WHERE lead_id = ?", (int(lead_id),))
        conn.commit()
    finally:
        conn.close()


def purge_expired() -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM phone_lookups WHERE datetime(expires_at) <= datetime('now')"
        )
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()
