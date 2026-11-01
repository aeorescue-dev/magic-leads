"""TDLR, OSINT do dono e check pos-deploy."""
from __future__ import annotations

import sqlite3

from backend.scripts import post_deploy_check
from backend.services.licensing_sources import extract_tdlr_licenses
from backend.services.owner_email import (
    extract_owner_names,
    find_owner_email,
    owner_patterns,
)


def test_tdlr_filtra_metro_de_dallas_e_normaliza():
    rows = [
        {"BUSINESS NAME": "TORRES ELECTRICAL SERVICE", "LICENSE NUMBER": "17000",
         "BUSINESS CITY, STATE ZIP": "DALLAS TX 75211",
         "BUSINESS PHONE": "2145550100"},
        {"BUSINESS NAME": "HOUSTON ELECTRIC LLC", "LICENSE NUMBER": "17001",
         "BUSINESS CITY, STATE ZIP": "HOUSTON TX 77031",
         "BUSINESS PHONE": "7135550101"},
        {"BUSINESS NAME": "TORRES ELECTRICAL SERVICE", "LICENSE NUMBER": "17002",
         "BUSINESS CITY, STATE ZIP": "DALLAS TX 75211",
         "BUSINESS PHONE": "2145550100"},
        {"BUSINESS NAME": "PLANO AIR LLC", "LICENSE NUMBER": "17003",
         "BUSINESS CITY, STATE ZIP": "PLANO TX 75023",
         "BUSINESS PHONE": "(972) 555-0102"},
    ]
    out = extract_tdlr_licenses(rows)
    assert [r["legal_name"] for r in out] == [
        "TORRES ELECTRICAL SERVICE", "PLANO AIR LLC",
    ]
    assert all(r["city"] == "DALLAS" and r["state"] == "TX" for r in out)
    assert all(r["source"] == "tdlr_tx" for r in out)
    assert out[1]["phone"] == "9725550102"


def test_owner_names_extrai_nome_junto_ao_cargo():
    html = b"""
    <html><body>
    <h1>About Us</h1>
    <p>John Smith, Owner</p>
    <p>President: Maria Gonzalez</p>
    <p>Our team</p>
    </body></html>
    """
    names = extract_owner_names(html)
    assert ("john", "smith") in names
    assert ("maria", "gonzalez") in names
    assert len(names) == 2


def test_owner_patterns_ordem_e_sem_duplicados():
    patterns = owner_patterns("acme.com", "john", "smith")
    assert patterns[0] == "john@acme.com"
    assert "john.smith@acme.com" in patterns
    assert "jsmith@acme.com" in patterns
    assert len(patterns) == len(set(patterns))


def _page(html: str):
    return {"status": 200, "url": "", "html": html.encode("utf-8")}


class _Prober:
    def __init__(self, catch_all: bool, accepted: set[str]):
        self.catch_all = catch_all
        self.accepted = accepted

    def probe(self, domain, recipients):
        codes = {}
        for r in recipients:
            if r.startswith("zz"):
                codes[r] = "accepted" if self.catch_all else "rejected"
            else:
                codes[r] = "accepted" if r in self.accepted else "rejected"
        return {"error": None, "codes": codes}


def test_find_owner_email_aceita_apenas_comprovado():
    html = b"<html><title>Acme</title><body>John Smith, Owner</body></html>"
    prober = _Prober(False, {"john@acme.com"})
    found = find_owner_email(
        "acme.com", "Acme", fetch=lambda url, timeout: _page(html.decode()), prober=prober
    )
    assert found == "john@acme.com"


def test_find_owner_email_nunca_aceita_catch_all():
    html = b"<html><body>John Smith, Owner</body></html>"
    prober = _Prober(True, {"john@acme.com"})
    assert find_owner_email(
        "acme.com", "Acme", fetch=lambda url, timeout: _page(html.decode()), prober=prober
    ) is None


def test_post_deploy_check_verifica_integridade(tmp_path, monkeypatch):
    db = tmp_path / "leads.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(post_deploy_check, "DB_PATH", str(db))
    result = post_deploy_check.check()
    assert result["integrity"] == "ok"
    assert result["writable"] is True
    assert result["sqlite_mb"] >= 0
    assert result["status"] in ("ok", "warn")  # warn se o runner tiver pouco disco
