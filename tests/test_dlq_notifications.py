"""Correção crítica: a DLQ de notificações in-app não pode crescer sem limite.

Antes: cada INSERT falhado escrevia um ficheiro que nunca era removido
(`reprocess_notification_dlq` estava morto) — disco infinito.
Agora: ring buffer que descarta os mais antigos por teto de ficheiros e por
idade (TTL), contabilizando os descartes num contador persistente.
"""

from backend.config import settings
from backend.services.db import db_service, get_connection


def _reset_dropped_counter() -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM dlq_counters")
        conn.commit()
    finally:
        conn.close()


def test_dlq_ring_buffer_drops_oldest_over_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "NOTIF_DLQ_MAX_FILES", 3)
    monkeypatch.setattr(settings, "NOTIF_DLQ_TTL_DAYS", 30)

    svc = db_service._service
    monkeypatch.setattr(svc, "_notification_dlq_dir", lambda: str(tmp_path))
    _reset_dropped_counter()

    for user_id in range(5):
        svc._save_notification_dlq(user_id, "new_lead", "t", "m", None, "boom")

    files = [f for f in tmp_path.iterdir() if f.suffix == ".json"]
    assert len(files) == 3, "deve manter apenas o teto de ficheiros"

    stats = svc.get_notification_dlq_stats()
    assert stats["pending"] == 3
    assert stats["dropped"] == 2, "os 2 mais antigos foram descartados"


def test_dlq_drops_files_older_than_ttl(tmp_path, monkeypatch):
    import os
    import time

    monkeypatch.setattr(settings, "NOTIF_DLQ_MAX_FILES", 500)
    monkeypatch.setattr(settings, "NOTIF_DLQ_TTL_DAYS", 7)

    svc = db_service._service
    monkeypatch.setattr(svc, "_notification_dlq_dir", lambda: str(tmp_path))
    _reset_dropped_counter()

    stale = tmp_path / "notif_stale.json"
    stale.write_text("{}", encoding="utf-8")
    old = time.time() - 8 * 86400
    os.utime(stale, (old, old))

    svc._save_notification_dlq(1, "new_lead", "t", "m", None, "boom")

    remaining = [f.name for f in tmp_path.iterdir() if f.suffix == ".json"]
    assert "notif_stale.json" not in remaining
    assert svc.get_notification_dlq_stats()["dropped"] == 1
