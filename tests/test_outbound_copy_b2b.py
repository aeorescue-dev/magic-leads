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
    assert "across Chicago" not in body
    # Value-First: a primeira linha abre com o numero e o nicho.
    assert "10 active construction projects in Chicago this week" in body


def test_real_address_is_not_injected_in_value_first_copy():
    """A estrutura Value-First abre com o numero; nao interpola enderecos.

    O endereco de um lead 311 identificaria a origem municipal do dado, que a
    politica de copy proibe. `address_tail` continua no contexto para usos
    futuros, mas nao faz parte do corpo.
    """
    lead = {
        "id": 2,
        "address": "4400 KILBOURN",
        "city": "CHICAGO",
        "state": "IL",
        "issue_category": "Paint",
        "owner_name": None,
    }
    body = _render(lead)
    assert "4400 KILBOURN" not in body
