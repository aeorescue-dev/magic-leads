"""A rota de migracao tem de ser segura por omissao.

O que estes testes travam:
* sem `X-Admin-Secret` nao faz nada (401);
* com secret errado nao faz nada (401);
* sem `ADMIN_SECRET` configurado e fail-closed (503), como as outras rotas admin;
* `merge_duplicates` sem `apply` e recusado (400) em vez de apagar coisas;
* o default e dry-run: uma chamada so de leitura nao escreve nada.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts import normalize_addresses as mig  # noqa: E402

URL = "/api/admin/normalize-addresses"


@pytest.fixture
def client(monkeypatch, tmp_path):
    from backend import config, main as main_mod

    db = tmp_path / "leads.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE leads (
            id INTEGER, external_id TEXT, source_type TEXT, address TEXT, city TEXT,
            state TEXT, zip_code TEXT, owner_name TEXT, owner_phone TEXT,
            owner_email TEXT, owner_status TEXT, mailing_address TEXT, lat REAL,
            lng REAL, bbl TEXT, address_unit TEXT, image_url TEXT, source_url TEXT,
            county TEXT, date_reported TEXT, lead_status TEXT, reserved_by TEXT,
            reserved_until TEXT, contact_count INTEGER, converted_by TEXT,
            converted_at TEXT, revealed_at TEXT
        );
        INSERT INTO leads VALUES
            (1,'e1','s','441 BROOKLYN AVENUE, NYC, NY 11225','NYC','NY','11225',
             'OWNER LLC',NULL,NULL,NULL,NULL,40.6,-73.9,'b',NULL,NULL,NULL,NULL,
             '2026-09-23','available',NULL,NULL,0,NULL,NULL,NULL),
            (2,'e2','s','441 BROOKLYN AVENUE, NYC, NY','NYC','NY',NULL,
             NULL,'5551234',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,
             '2026-10-01','available',NULL,NULL,0,NULL,NULL,NULL);
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("LEADS_DB_PATH", str(db))
    monkeypatch.setattr(config.settings, "ADMIN_SECRET", "segredo-de-teste", raising=False)
    monkeypatch.setattr(main_mod.settings, "ADMIN_SECRET", "segredo-de-teste", raising=False)
    return TestClient(main_mod.app), db


def _count(db):
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    conn.close()
    return n


def test_sem_secret_nao_faz_nada(client):
    tc, db = client
    before = _count(db)
    r = tc.post(URL)
    assert r.status_code == 401, r.text
    assert _count(db) == before


def test_secret_errado_nao_faz_nada(client):
    tc, db = client
    before = _count(db)
    r = tc.post(URL, headers={"X-Admin-Secret": "chute"})
    assert r.status_code == 401, r.text
    assert _count(db) == before


def test_sem_admin_secret_configurado_e_fail_closed(client, monkeypatch):
    from backend import config, main as main_mod

    tc, db = client
    before = _count(db)
    monkeypatch.setattr(config.settings, "ADMIN_SECRET", "", raising=False)
    monkeypatch.setattr(main_mod.settings, "ADMIN_SECRET", "", raising=False)
    r = tc.post(URL, headers={"X-Admin-Secret": "qualquer"})
    assert r.status_code == 503, r.text
    assert _count(db) == before


def test_default_e_dry_run_nao_escreve(client):
    tc, db = client
    before = _count(db)
    r = tc.post(URL, headers={"X-Admin-Secret": "segredo-de-teste"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is False
    assert body["normalised"] == 0 and body["merged"] == 0
    # As duas linhas da fixture sao o MESMO predio em dois formatos, logo o
    # trabalho pendente e a fusao, nao a normalizacao avulsa.
    assert body["to_merge"] == 1
    assert body["leads"] == 2
    assert _count(db) == before, "o dry-run nao pode apagar nem escrever"


def test_merge_sem_apply_e_recusado(client):
    tc, db = client
    before = _count(db)
    r = tc.post(
        URL + "?merge_duplicates=true", headers={"X-Admin-Secret": "segredo-de-teste"}
    )
    assert r.status_code == 400, r.text
    assert "requires_apply" in r.json()["detail"]
    assert _count(db) == before


def test_apply_normaliza_e_funde(client):
    tc, db = client
    before = _count(db)
    r = tc.post(
        URL + "?apply=true&merge_duplicates=true",
        headers={"X-Admin-Secret": "segredo-de-teste"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is True
    assert body["merged"] == 1
    assert body["leads_after"] == before - 1
    assert _count(db) == before - 1

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    left = conn.execute("SELECT * FROM leads").fetchall()
    assert len(left) == 1
    assert left[0]["address"] == "441 BROOKLYN AVENUE"
    assert left[0]["owner_name"] == "OWNER LLC"
    assert left[0]["owner_phone"] == "5551234", "o telefone tinha de ser herdado"
    conn.close()


def test_run_e_idempotente_quando_chamada_duas_vezes(client):
    tc, db = client
    h = {"X-Admin-Secret": "segredo-de-teste"}
    tc.post(URL + "?apply=true&merge_duplicates=true", headers=h)
    after_first = _count(db)
    r = tc.post(URL + "?apply=true&merge_duplicates=true", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["merged"] == 0
    assert _count(db) == after_first


def test_db_path_inexistente_nao_escreve_nada(client, monkeypatch):
    tc, _db = client
    monkeypatch.setenv("LEADS_DB_PATH", "/caminho/que/nao/existe/leads.db")
    r = tc.post(URL, headers={"X-Admin-Secret": "segredo-de-teste"})
    assert r.status_code == 400
    assert r.json()["detail"] == "db_not_found"


def test_script_run_aceita_db_path_explicito(tmp_path):
    """O CLI e a rota podem apontar a bases diferentes sem mexer no ambiente."""
    db = tmp_path / "outro.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE leads (id INTEGER, address TEXT)")
    conn.commit()
    conn.close()
    result = mig.run(db_path=str(db), log=lambda *a, **k: None)
    assert result["ok"] is True
    assert result["db_path"] == str(db)
    assert result["leads"] == 0