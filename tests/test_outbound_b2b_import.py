"""Regressao da caixa preta: lote B2B enfileirava 0 e-mails.

Causas cobertas aqui (auditoria do Lote #28):
  1. `import_b2b_lead` violava NOT NULL (external_id/address/date_reported),
     rebentava e o except silencioso devolvia None -> nenhum lead entrava.
  2. O filtro de nicho (`issue_category IN (...)`) excluia os imports, cuja
     categoria e' "General Contractors".
  3. `ORDER BY date_reported DESC LIMIT 200` deixava imports (date_reported
     NULL) no fim da fila, fora do lote.
  4. O motor exigia `email_status='valid'` e ignorava imports com outro status.

A cidade usada (SEATTLE) nao e' servida nem tocada por outros testes.
"""

from __future__ import annotations

import json

import pytest

from backend.services import db as db_module
from backend.services import outbound_templates
from backend.services.db import get_connection
from backend.services.outbound_engine import (
    OutboundEngine,
    is_sendable_contact,
)

CITY = "SEATTLE"
NICHE = "general_contractors"


def _svc():
    return db_module.db_service._service


@pytest.fixture()
def clean_city():
    conn = get_connection()
    try:
        for table in (
            "outbound_messages",
            "outbound_batches",
            "outbound_contacts",
            "outbound_daily_counters",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM leads WHERE UPPER(TRIM(city)) = ?", (CITY,))
        conn.commit()
    finally:
        conn.close()
    yield
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE UPPER(TRIM(city)) = ?", (CITY,))
        conn.commit()
    finally:
        conn.close()


def _seed_permits(count: int, days: str = "2099-12") -> None:
    """Permissoes qualificadas e SEM e-mail, mais recentes que o import."""
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO leads (external_id, source_type, address, city, state, "
            "issue_category, date_reported, owner_name, case_status) "
            "VALUES (?, 'permit', ?, ?, 'WA', 'Roof', ?, 'Permit Owner', 'open')",
            [
                (f"SEA-{i}", f"{100 + i} Main Street", CITY, f"{days}-01")
                for i in range(count)
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _import(email: str = "pamela@pamela-clark.com") -> dict:
    contact = _svc().import_b2b_lead(
        email=email,
        company_name="Pamela Clark Builders",
        city=CITY,
        category="General Contractors",
    )
    assert contact is not None, "import_b2b_lead devolveu None (INSERT falhou)"
    return contact


def _batch(batch_size: int = 200) -> dict:
    svc = _svc()
    batch = svc.create_outbound_batch(
        city=CITY,
        name="b2b-audit",
        filters_json=json.dumps(
            {"city": CITY, "niche": NICHE, "batch_size": batch_size}
        ),
        kind="email",
    )
    svc.mark_outbound_batch_previewed(batch["id"], batch_size, 0.0)
    return svc.start_outbound_batch(batch["id"])


# ------------------------------------------------------------------ import


def test_import_persiste_lead_e_contacto(clean_city):
    _import()

    conn = get_connection()
    try:
        lead = conn.execute(
            "SELECT * FROM leads WHERE source_type='import_b2b'"
        ).fetchone()
        contact = conn.execute(
            "SELECT * FROM outbound_contacts WHERE email='pamela@pamela-clark.com'"
        ).fetchone()
    finally:
        conn.close()

    assert lead is not None
    assert lead["external_id"] and lead["date_reported"]
    assert lead["owner_email"] == "pamela@pamela-clark.com"
    assert contact is not None
    assert contact["email_status"] == "valid"
    assert contact["lead_id"] == lead["id"]


def test_import_e_idempotente(clean_city):
    _import()
    _import()
    conn = get_connection()
    try:
        leads = conn.execute(
            "SELECT COUNT(*) c FROM leads WHERE source_type='import_b2b'"
        ).fetchone()["c"]
        contacts = conn.execute("SELECT COUNT(*) c FROM outbound_contacts").fetchone()["c"]
    finally:
        conn.close()
    assert (leads, contacts) == (1, 1)


# --------------------------------------------------------------- selecao


def test_import_entra_no_lote_mesmo_atras_de_250_permissoes(clean_city):
    """O pior caso do Lote #28: import antigo, 250 permissoes mais recentes."""
    _import()
    _seed_permits(250)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE leads SET date_reported='2020-01-01' WHERE source_type='import_b2b'"
        )
        conn.commit()
    finally:
        conn.close()

    cats = outbound_templates.niche_categories(NICHE)
    leads = _svc().list_outbound_leads(CITY, cats, 200)

    assert len(leads) == 200
    assert leads[0]["owner_email"] == "pamela@pamela-clark.com"
    assert any(l["issue_category"] == "General Contractors" for l in leads)


def test_contagem_de_destinatarios_separa_inventario_de_emails(clean_city):
    _import()
    _seed_permits(250)
    assert _svc().count_outbound_recipients(CITY) == 1
    assert _svc().count_qualified_contractors_in_city(CITY, None) == 251


def test_diagnostico_mostra_onde_o_funil_para(clean_city):
    _import()
    _seed_permits(250)

    diag = _svc().outbound_diagnostics(CITY)

    assert diag["leads_total"] == 251
    assert diag["leads_with_email"] == 1
    assert diag["import_leads"] == 1
    assert diag["contacts_total"] == 1
    assert diag["contacts_by_status"] == {"valid": 1}
    assert diag["contacts_sendable"] == 1
    assert diag["recipients"] == 1


# --------------------------------------------------------------- enqueue


@pytest.mark.asyncio
async def test_enqueue_enfileira_import_b2b(clean_city):
    """O sintoma exato: queued=0/no_email=200 deve virar queued>=1."""
    _import()
    _seed_permits(250)

    result = await OutboundEngine().enqueue_batch(_batch())

    assert result["queued"] == 1, result
    assert result["no_email"] == 199, result
    assert _svc().count_outbound_messages(status="queued") == 1


@pytest.mark.asyncio
async def test_enqueue_aceita_status_verified_e_import_sem_status(clean_city):
    lead_id = _import("peter@peter-ross.com")["lead_id"]
    svc = _svc()
    svc.upsert_outbound_contact(
        lead_id=lead_id,
        email="peter@peter-ross.com",
        city=CITY,
        email_source="emaillistverify",
        email_status="verified",
    )
    # Import antigo: contacto com e-mail mas status NULL.
    svc.upsert_outbound_contact(
        lead_id=lead_id,
        email="legacy@peter-ross.com",
        city=CITY,
        email_source="import",
        email_status=None,
    )

    result = await OutboundEngine().enqueue_batch(_batch(batch_size=1))
    assert result["queued"] == 1, result


def test_is_sendable_contact_regras():
    assert is_sendable_contact({"email": "a@b.com", "email_status": "valid"})
    assert is_sendable_contact({"email": "a@b.com", "email_status": "verified"})
    assert is_sendable_contact({"email": "a@b.com", "email_source": "import"})
    assert is_sendable_contact(
        {"email": "a@b.com", "email_status": None, "email_source": "import"}
    )
    assert not is_sendable_contact({"email": "a@b.com", "email_status": "unknown"})
    assert not is_sendable_contact(
        {"email": "a@b.com", "email_status": "valid", "unsubscribed": 1}
    )
    assert not is_sendable_contact({"email": "   ", "email_status": "valid"})
    assert not is_sendable_contact(None)
