"""Upgrade de e-mail generico -> nominal (OSINT) com guardas."""
from __future__ import annotations

from backend.services.db import db_service, get_connection


def _clean():
    conn = get_connection()
    try:
        conn.execute("DELETE FROM outbound_messages WHERE to_email LIKE '%@upgrade-test.com'")
        conn.execute("DELETE FROM outbound_contacts WHERE email LIKE '%@upgrade-test.com'")
        conn.execute("DELETE FROM leads WHERE owner_email LIKE '%@upgrade-test.com'")
        conn.execute("DELETE FROM contractor_entities WHERE city='UPG'")
        conn.commit()
    finally:
        conn.close()


def _seed(lead_email: str, entity_email: str, source: str = "smtp_pattern"):
    svc = db_service._service
    row = svc.upsert_contractor_entity(
        "UPGRADE TEST CO", "UPG", state="NY", role="contractor",
        source="test", external_id="upg-1", phone="2125550100",
    )
    entity_id = int(row["id"])
    svc.mark_contractor_domain_attempt(entity_id, "upgradetest.com", 0.9, 2)
    svc.mark_contractor_email_attempt(entity_id, entity_email, "valid", 2, source)
    contact = svc.import_b2b_lead(
        email=entity_email, company_name="UPGRADE TEST CO", city="UPG",
        state="NY", domain="upgradetest.com", email_source=source,
    )
    svc.mark_contractor_bridged(entity_id, int(contact["id"]), contact.get("lead_id"))
    return entity_id, contact


def test_upgrade_troca_contacto_lead_e_entidade():
    _clean()
    entity_id, contact = _seed("info@upgrade-test.com", "info@upgrade-test.com")
    result = db_service._service.upgrade_contact_email(
        entity_id, "owner@upgrade-test.com"
    )
    assert result["status"] == "updated"
    conn = get_connection()
    try:
        c = conn.execute(
            "SELECT email, email_source FROM outbound_contacts WHERE id=?",
            (contact["id"],),
        ).fetchone()
        e = conn.execute(
            "SELECT email, email_source FROM contractor_entities WHERE id=?",
            (entity_id,),
        ).fetchone()
        lead = conn.execute(
            "SELECT owner_email FROM leads WHERE id=?", (contact["lead_id"],)
        ).fetchone()
    finally:
        conn.close()
    assert c["email"] == "owner@upgrade-test.com"
    assert c["email_source"] == "owner_osint"
    assert e["email"] == "owner@upgrade-test.com"
    assert e["email_source"] == "owner_osint"
    assert lead["owner_email"] == "owner@upgrade-test.com"
    _clean()


def test_upgrade_recusa_com_mensagem_ativa():
    _clean()
    entity_id, contact = _seed("info@upgrade-test.com", "info@upgrade-test.com")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO outbound_messages (contact_id, city, to_email, subject, "
            "body_hash, status) VALUES (?, 'UPG', 'info@upgrade-test.com', 's', 'h', 'queued')",
            (contact["id"],),
        )
        conn.commit()
    finally:
        conn.close()
    result = db_service._service.upgrade_contact_email(
        entity_id, "owner@upgrade-test.com"
    )
    assert result["status"] == "has_active_message"
    _clean()


def test_upgrade_recusa_email_em_uso():
    _clean()
    entity_id, _ = _seed("info@upgrade-test.com", "info@upgrade-test.com")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO outbound_contacts (email, city, email_status) "
            "VALUES ('taken@upgrade-test.com', 'UPG', 'valid')"
        )
        conn.commit()
    finally:
        conn.close()
    result = db_service._service.upgrade_contact_email(
        entity_id, "taken@upgrade-test.com"
    )
    assert result["status"] == "email_in_use"
    _clean()
