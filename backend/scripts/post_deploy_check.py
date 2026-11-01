"""Verificacao pos-deploy: espaco em disco + integridade do SQLite.

O volume do Railway e' pequeno (434 MB; a caminho de 2 GB). Um WAL grande ja'
encheu /data e deixou a base em "disk I/O error". Este script corre no arranque
do contentor, antes do uvicorn, e deixa o resultado em `system_kv` para o Admin
e para os logs. Nunca bloqueia o arranque: sem base ou com erro, apenas avisa.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone

DB_PATH = os.getenv("LEADS_DB_PATH") or os.getenv("DATA_DIR", "/data") + "/leads.db"
MIN_FREE_MB = 200
CRITICAL_FREE_MB = 80


def _mb(value: int) -> int:
    return int(value // (1024 * 1024))


def check() -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out: dict = {"checked_at": now, "db_path": DB_PATH, "status": "ok"}
    db_dir = os.path.dirname(DB_PATH) or "."
    try:
        free_mb = _mb(shutil.disk_usage(db_dir).free)
    except OSError:
        free_mb = -1
    out["free_mb"] = free_mb
    if free_mb < 0:
        out["status"] = "unknown"
    elif free_mb < CRITICAL_FREE_MB:
        out["status"] = "critical"
    elif free_mb < MIN_FREE_MB:
        out["status"] = "warn"

    for suffix, key in (("-wal", "wal_mb"), ("-shm", "shm_mb")):
        path = DB_PATH + suffix
        out[key] = _mb(os.path.getsize(path)) if os.path.exists(path) else 0

    if not os.path.exists(DB_PATH):
        out["db"] = "missing"
        return out
    try:
        conn = sqlite3.connect(DB_PATH, timeout=15.0)
        try:
            out["db_mb"] = _mb(os.path.getsize(DB_PATH))
            out["integrity"] = conn.execute("PRAGMA quick_check").fetchone()[0]
            out["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
            pages = conn.execute("PRAGMA page_count").fetchone()[0]
            size = conn.execute("PRAGMA page_size").fetchone()[0]
            out["pages"] = int(pages)
            out["sqlite_mb"] = _mb(pages * size)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        out["db"] = f"error: {type(exc).__name__}: {exc}"
        out["status"] = "critical"
        return out

    if out.get("integrity") != "ok":
        out["status"] = "critical"

    # Escrita real (o disco pode estar cheio sem o free o mostrar).
    try:
        with tempfile.NamedTemporaryFile(dir=db_dir, delete=True) as fh:
            fh.write(b"ok")
        out["writable"] = True
    except OSError as exc:
        out["writable"] = False
        out["write_error"] = str(exc)[:120]
        out["status"] = "critical"
    return out


def persist(result: dict) -> None:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        try:
            conn.execute(
                "INSERT INTO system_kv (key, value, updated_at) "
                "VALUES ('post_deploy_check', ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=CURRENT_TIMESTAMP",
                (json.dumps(result),),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    result = check()
    print("[POST-DEPLOY] " + json.dumps(result), flush=True)
    if result.get("status") == "critical":
        print(
            "[POST-DEPLOY] CRITICAL: disco/integridade exigem atencao. "
            "A aplicacao arranca, mas a ingestao fica protegida pelo guarda de espaco.",
            flush=True,
        )
    persist(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
