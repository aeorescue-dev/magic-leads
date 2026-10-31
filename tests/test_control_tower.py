"""Testes da Control Tower (saude, digest, limiares).

Nao tocam na rede: cobrem as verificacoes puras (worker, fila, backup) e a
composicao do digest. O caminho de backup/restauro e' validado no ambiente
real (VPS), nao aqui.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.services import control_tower as ct


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- worker

def test_worker_sem_heartbeat_e_warn(monkeypatch):
    monkeypatch.setattr(ct, "kv_get", lambda key: None)
    r = ct._check_worker()
    assert r["status"] == "warn"
    assert "sem heartbeat" in r["detail"]


def test_worker_recente_e_ok(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(ct, "kv_get", lambda key: _iso(now - timedelta(minutes=1)))
    assert ct._check_worker()["status"] == "ok"


def test_worker_atrasado_e_fail(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(ct, "kv_get", lambda key: _iso(now - timedelta(minutes=40)))
    r = ct._check_worker()
    assert r["status"] == "fail"
    assert "sem tick" in r["detail"]


# ----------------------------------------------------------------- backup

def test_backup_nunca_correu_e_fail(monkeypatch):
    monkeypatch.setattr(ct, "kv_get", lambda key: None)
    checks = {c["name"]: c for c in ct._check_backup()}
    assert checks["backup"]["status"] == "fail"
    assert checks["backup_verify"]["status"] == "warn"


def test_backup_recente_e_ok(monkeypatch):
    now = datetime.now(timezone.utc)
    values = {
        ct.KV_LAST_BACKUP: _iso(now - timedelta(hours=2)),
        ct.KV_LAST_BACKUP_BYTES: "22000000",
        ct.KV_LAST_VERIFY: _iso(now - timedelta(hours=2)),
    }
    monkeypatch.setattr(ct, "kv_get", lambda key: values.get(key))
    checks = {c["name"]: c for c in ct._check_backup()}
    assert checks["backup"]["status"] == "ok"
    assert checks["backup_verify"]["status"] == "ok"


def test_backup_antigo_e_fail(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        ct, "kv_get",
        lambda key: _iso(now - timedelta(hours=60)) if key == ct.KV_LAST_BACKUP else None,
    )
    checks = {c["name"]: c for c in ct._check_backup()}
    assert checks["backup"]["status"] == "fail"


# ------------------------------------------------------------------ digest

def test_digest_tem_os_blocos_esperados(monkeypatch):
    monkeypatch.setattr(ct, "latest_health", lambda: [
        {"check_name": "worker", "status": "ok", "detail": "tick ha 1 min"},
        {"check_name": "backup", "status": "ok", "detail": "ha 2h"},
    ])
    out = ct.build_digest()
    for bloco in ("CONTROL TOWER", "estado geral: VERDE", "MOTOR", "INGESTAO", "BACKUP"):
        assert bloco in out
    assert "ALERTAS    nenhum" in out
    assert "https://www.magicleads.app/" in out


def test_digest_mostra_o_motivo_da_ingestao_parada(monkeypatch):
    monkeypatch.setattr(ct, "latest_health", lambda: [
        {"check_name": "worker", "status": "ok", "detail": "tick ha 1 min"},
        {
            "check_name": "ingestion",
            "status": "fail",
            "detail": "último run success há 20.0h · 0 inseridos · 0 lead(s) em 24h",
        },
    ])
    out = ct.build_digest()
    assert "INGESTAO" in out
    assert "há 20.0h" in out


def test_digest_marca_estado_vermelho_quando_ha_fail(monkeypatch):
    monkeypatch.setattr(ct, "latest_health", lambda: [
        {"check_name": "gmail_tokens", "status": "fail", "detail": "HTTP 400"},
    ])
    out = ct.build_digest()
    assert "estado geral: VERMELHO" in out
    assert "gmail_tokens: HTTP 400" in out


def test_parse_aceita_formatos_do_sqlite_e_iso():
    assert ct._parse("2026-10-28 21:37:26") is not None
    assert ct._parse("2026-10-28T21:37:26Z") is not None
    assert ct._parse("2026-10-28") is not None
    assert ct._parse("lixo") is None
    assert ct._parse(None) is None


def test_parse_aceita_microssegundos_do_utcnow_isoformat():
    """Regressão do falso 'sem data de conclusão' (31/10)."""
    parsed = ct._parse("2026-10-30T22:50:53.145799")
    assert parsed is not None
    assert parsed.year == 2026 and parsed.minute == 50
