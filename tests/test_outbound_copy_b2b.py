"""Copy de outbound para leads B2B importados.

Os leads `import_b2b` nao tem endereco real: `import_b2b_lead` grava um
placeholder unico ("B2B contact - <email>") para satisfazer UNIQUE(address, city).
Se esse valor chegar ao template, o e-mail sai com
"...near B2B contact - info@empresa.com" — parece spam quebrado e expoe o
tratamento interno dos dados.
"""
from __future__ import annotations

from backend.services import outbound_templates as templates

B2B_LEAD = {
    "id": 1,
    "address": "B2B contact - info@skender.com",
    "city": "CHICAGO",
    "state": "IL",
    "issue_category": "General Contractors",
    "owner_name": "Skender",
}


def _render(lead, contact=None):
    ctx = templates.build_context(
        lead, "CHICAGO", "general_contractors", 10, contact=contact
    )
    return templates.render_email("general_contractors", ctx)["body"]


def test_b2b_placeholder_address_never_reaches_copy():
    body = _render(B2B_LEAD, contact={"company_name": "Skender"})
    assert "B2B contact" not in body
    assert "info@skender.com" not in body
    # sem endereco nao ha clausula de endereco (evita "in Chicago ... across Chicago")
    assert "across Chicago" not in body
    assert "10 active project opportunities in Chicago." in body


def test_real_address_still_included():
    lead = {
        "id": 2,
        "address": "4400 KILBOURN",
        "city": "CHICAGO",
        "state": "IL",
        "issue_category": "Paint",
        "owner_name": None,
    }
    body = _render(lead)
    assert "near 4400 KILBOURN" in body
