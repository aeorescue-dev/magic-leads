"""Cache de áudio TTS para o modo `static`.

Pré-sintetiza o greeting via REST TTS da Telnyx e serve o MP3 por URL
pública. O call control usa `gather_using_audio` em vez de
`gather_using_speak`, eliminando a síntese no momento do atendimento.

O custo por caractere do REST TTS é o mesmo do TTS in-call. O ganho de
custo só existe quando o mesmo texto é reutilizado (modo `shared`, sem o
nome da empresa). No modo `dial` o texto é único por chamada; o ganho é
apenas de latência.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import httpx

from ..config import settings

API_BASE = "https://api.telnyx.com/v2"
VERSION = "2026-11-10.1"
HEX64 = re.compile(r"^[a-f0-9]{64}$")

_INIT: dict[str, Optional[str]] = {"path": None}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def enabled() -> bool:
    return bool(getattr(settings, "VOICE_TTS_CACHE_ENABLED", False))


def mode() -> str:
    value = str(getattr(settings, "VOICE_TTS_CACHE_MODE", "dial") or "dial")
    value = value.strip().lower()
    return value if value in {"dial", "shared"} else "dial"


def voice() -> str:
    return str(
        getattr(settings, "VOICE_TTS_VOICE", "")
        or getattr(settings, "TELNYX_ASSISTANT_VOICE", "")
        or ""
    ).strip()


def cache_dir() -> Path:
    configured = str(getattr(settings, "VOICE_TTS_CACHE_DIR", "") or "").strip()
    if configured:
        return Path(configured)
    data = Path("/data")
    if data.exists() and os.access(data, os.W_OK):
        return data / "voice_cache"
    return Path(__file__).resolve().parents[1] / "static" / "voice_cache"


def public_url(cache_hash: str) -> str:
    base = str(getattr(settings, "VOICE_TTS_CACHE_BASE_URL", "") or "").strip()
    if not base:
        base = str(getattr(settings, "PUBLIC_API_URL", "") or "").strip()
    if not base:
        base = "https://magic-leads-production.up.railway.app"
    return f"{base.rstrip('/')}/api/voice/tts/{cache_hash}.mp3"


def key(text: str, voice_id: Optional[str] = None) -> str:
    raw = f"{voice_id or voice()}\n{str(text or '').strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def path_for(cache_hash: str) -> Path:
    return cache_dir() / f"{cache_hash}.mp3"


def _conn():
    from . import b2b_voice

    b2b_voice.init()
    return b2b_voice.get_conn()


def init() -> None:
    path = str(cache_dir())
    if _INIT["path"] == path:
        return
    cache_dir().mkdir(parents=True, exist_ok=True)
    try:
        conn = _conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS voice_tts_cache (
                  hash TEXT PRIMARY KEY,
                  voice TEXT NOT NULL,
                  chars INTEGER NOT NULL,
                  bytes INTEGER NOT NULL,
                  path TEXT NOT NULL,
                  text TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  last_used_at TEXT NOT NULL,
                  hits INTEGER NOT NULL DEFAULT 0,
                  misses INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_voice_tts_cache_used
                  ON voice_tts_cache (last_used_at);
                """
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - cache de ficheiros continua a funcionar
        pass
    _INIT["path"] = path


def _row(cache_hash: str) -> Optional[dict]:
    try:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT * FROM voice_tts_cache WHERE hash=?", (cache_hash,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


def _record(
    cache_hash: str,
    text: str,
    chars: int,
    size: int,
    path: Path,
    hit: bool,
) -> None:
    now = _now_iso()
    try:
        conn = _conn()
        try:
            if hit:
                conn.execute(
                    "UPDATE voice_tts_cache SET last_used_at=?, hits=hits+1 "
                    "WHERE hash=?",
                    (now, cache_hash),
                )
            else:
                conn.execute(
                    "INSERT INTO voice_tts_cache "
                    "(hash, voice, chars, bytes, path, text, created_at, "
                    " last_used_at, hits, misses) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1) "
                    "ON CONFLICT(hash) DO UPDATE SET "
                    "voice=excluded.voice, chars=excluded.chars, "
                    "bytes=excluded.bytes, path=excluded.path, "
                    "text=excluded.text, last_used_at=excluded.last_used_at, "
                    "misses=voice_tts_cache.misses+1",
                    (
                        cache_hash,
                        voice(),
                        chars,
                        size,
                        str(path),
                        text[:4000],
                        now,
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def _synthesize(text: str) -> dict:
    token = str(getattr(settings, "TELNYX_API_KEY", "") or "")
    voice_id = voice()
    if not token:
        return {"ok": False, "reason": "telnyx_not_configured"}
    if not voice_id:
        return {"ok": False, "reason": "voice_not_configured"}
    max_chars = int(getattr(settings, "VOICE_TTS_MAX_CHARS", 3000) or 3000)
    if len(text) > max_chars:
        return {"ok": False, "reason": "text_too_long"}
    timeout = float(getattr(settings, "VOICE_TTS_TIMEOUT_SECONDS", 20) or 20)
    try:
        resp = httpx.post(
            f"{API_BASE}/text-to-speech/speech",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"text": text, "voice": voice_id},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"network:{type(exc).__name__}"}
    if resp.status_code >= 300:
        return {
            "ok": False,
            "reason": f"http_{resp.status_code}",
            "detail": resp.text[:200],
        }
    content_type = str(resp.headers.get("content-type") or "").lower()
    audio = b""
    if "application/json" in content_type:
        try:
            payload = resp.json()
            encoded = (
                payload.get("audio")
                or (payload.get("data") or {}).get("audio")
                or (payload.get("data") or {}).get("base64")
            )
            if encoded:
                audio = base64.b64decode(str(encoded))
        except Exception:  # noqa: BLE001
            audio = b""
    else:
        audio = resp.content
    if not audio or len(audio) < 100:
        return {"ok": False, "reason": "empty_audio"}
    return {"ok": True, "audio": audio, "content_type": content_type}


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def get_or_create(text: str) -> dict:
    """Devolve o áudio em cache ou sintetiza-o. Nunca levanta exceção."""
    if not enabled():
        return {"ok": False, "reason": "disabled"}
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "reason": "empty_text"}
    try:
        init()
        cache_hash = key(text)
        path = path_for(cache_hash)
        if path.exists() and path.stat().st_size > 0:
            size = path.stat().st_size
            _record(cache_hash, text, len(text), size, path, hit=True)
            return {
                "ok": True,
                "hash": cache_hash,
                "url": public_url(cache_hash),
                "path": str(path),
                "chars": len(text),
                "bytes": size,
                "hit": True,
            }
        result = _synthesize(text)
        if not result.get("ok"):
            return result
        audio = result["audio"]
        _write_atomic(path, audio)
        _record(cache_hash, text, len(text), len(audio), path, hit=False)
        return {
            "ok": True,
            "hash": cache_hash,
            "url": public_url(cache_hash),
            "path": str(path),
            "chars": len(text),
            "bytes": len(audio),
            "hit": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"error:{type(exc).__name__}"}


def prewarm(texts: Iterable[str]) -> dict:
    created = 0
    hits = 0
    errors: list[dict] = []
    for text in texts:
        result = get_or_create(text)
        if not result.get("ok"):
            errors.append({"reason": result.get("reason"), "chars": len(text or "")})
            continue
        if result.get("hit"):
            hits += 1
        else:
            created += 1
    return {"ok": True, "created": created, "hits": hits, "errors": errors}


def stats() -> dict:
    init()
    try:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(bytes),0) bytes, "
                "COALESCE(SUM(hits),0) hits, COALESCE(SUM(misses),0) misses, "
                "COALESCE(SUM(chars),0) chars FROM voice_tts_cache"
            ).fetchone()
            return dict(row)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return {"n": 0, "bytes": 0, "hits": 0, "misses": 0, "chars": 0}


def cleanup(days: Optional[int] = None) -> dict:
    init()
    ttl = int(
        days
        if days is not None
        else (getattr(settings, "VOICE_TTS_CACHE_TTL_DAYS", 30) or 30)
    )
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(0, ttl))).isoformat()
    removed = 0
    try:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT hash, path FROM voice_tts_cache WHERE last_used_at < ?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                try:
                    Path(row["path"]).unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass
                conn.execute(
                    "DELETE FROM voice_tts_cache WHERE hash=?", (row["hash"],)
                )
                removed += 1
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "removed": removed, "ttl_days": ttl}


def clear() -> dict:
    """Remove todos os ficheiros e registos. Usado em testes/admin."""
    removed = 0
    try:
        init()
        for item in cache_dir().glob("*.mp3"):
            try:
                item.unlink()
                removed += 1
            except Exception:  # noqa: BLE001
                pass
        conn = _conn()
        try:
            conn.execute("DELETE FROM voice_tts_cache")
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "removed": removed}
