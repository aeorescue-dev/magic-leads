"""Regra A e resolucao de endereco: backend/services/lead_rules.py.

Estes testes existem porque a UI consome estes flags em vez de recalcular a
regra, o que torna impossivel divergir do que a reserva cobra.
"""

import pytest

from backend.services.lead_rules import (
    address_is_resolvable,
    charges_credit,
    classify,
    is_corporate,
    is_unresolvable,
    missing_critical_fields,
)


def lead(**overrides):
    base = {
        "id": 1,
        "address": "123 MAIN ST",
        "owner_name": None,
        "owner_phone": None,
        "mailing_address": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# is_corporate: owner_name + mailing_address, sem owner_phone
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"owner_name": "ACME LLC", "mailing_address": "PO BOX 9, NY"}, True),
        # telefone presente deixa de ser corporativo: passa a ser lead padrão
        ({"owner_name": "ACME LLC", "owner_phone": "5551234", "mailing_address": "PO BOX 9"}, False),
        # owner_name é obrigatório por definição, mesmo com morada
        ({"mailing_address": "PO BOX 9"}, False),
        # morada obrigatória
        ({"owner_name": "ACME LLC"}, False),
        ({}, False),
        # strings vazias não contam como presentes
        ({"owner_name": "", "mailing_address": ""}, False),
        # apenas espaços
        ({"owner_name": "  ", "mailing_address": "  "}, False),
    ],
)
def test_is_corporate(overrides, expected):
    assert is_corporate(lead(**overrides)) is expected


def test_owner_name_alone_is_not_corporate():
    """Sem morada o lead e padrão, mesmo sem telefone: não deve ser promovido."""
    assert is_corporate(lead(owner_name="JOHN DOE")) is False


def test_whitespace_lead_is_never_corporate_and_never_charges():
    """owner_name='  ' e truthy em Python. Sem normalizar, esse lead seria vendido
    como corporativo (0 creditos) sem ter nada para revelar."""
    sample = lead(owner_name="  ", mailing_address="  ")
    assert is_corporate(sample) is False
    # e nao pode cair no outro extremo: cobrar por um lead sem nada
    assert charges_credit(sample) is True
    assert missing_critical_fields(sample) == ["owner_name", "owner_phone_or_mailing_address"]


# ---------------------------------------------------------------------------
# address_is_resolvable
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "address,expected",
    [
        ("123 MAIN ST", True),
        ("123 MAIN ST, BROOKLYN, NY", True),
        ("473, NYC, NY", False),
        ("2424, NYC, NY", False),
        ("9630", False),
        ("", False),
        (None, False),
    ],
)
def test_address_is_resolvable(address, expected):
    assert address_is_resolvable(address) is expected


def test_house_number_only_is_unresolvable_but_reversible():
    """Um endereço sem rua nunca resolve; com rua passa a resolver."""
    assert address_is_resolvable("2424, NYC, NY") is False
    assert address_is_resolvable("2424 PARK AVE, NYC, NY") is True


# ---------------------------------------------------------------------------
# is_unresolvable: sem contacto E endereço irresolvível
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"address": "2424, NYC, NY"}, True),
        ({"address": "2424 PARK AVE, NYC, NY"}, False),
        # tem dados de contacto: nada a revelar mas não é um beco sem saída
        ({"address": "2424, NYC, NY", "owner_name": "ACME"}, False),
    ],
)
def test_is_unresolvable(overrides, expected):
    assert is_unresolvable(lead(**overrides)) is expected


def test_unresolvable_never_passes_as_corporate():
    """Um beco sem saída nunca pode ser vendido como corporativo."""
    broken = lead(address="2424, NYC, NY")
    assert is_unresolvable(broken) is True
    assert is_corporate(broken) is False


# ---------------------------------------------------------------------------
# Regra A: missing_critical_fields
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"owner_name": "JOHN", "owner_phone": "5551234"}, []),
        ({"owner_name": "ACME", "mailing_address": "PO BOX 9"}, []),
        ({}, ["owner_name", "owner_phone_or_mailing_address"]),
        ({"owner_name": "JOHN"}, ["owner_phone_or_mailing_address"]),
        ({"owner_phone": "5551234"}, ["owner_name"]),
        ({"mailing_address": "PO BOX 9"}, ["owner_name"]),
    ],
)
def test_missing_critical_fields(overrides, expected):
    assert missing_critical_fields(lead(**overrides)) == expected


def test_corporate_lead_always_passes_regra_a():
    """Contrato interno: se is_corporate então nada falta. A UI promete 0 créditos,
    portanto a Regra A nunca pode devolver 422 nesse caso."""
    for overrides in (
        {"owner_name": "ACME LLC", "mailing_address": "PO BOX 9, NY"},
        {"owner_name": "ACME LLC", "mailing_address": "PO BOX 9, NY", "address": "2424, NY"},
    ):
        sample = lead(**overrides)
        assert is_corporate(sample) is True
        assert missing_critical_fields(sample) == []


# ---------------------------------------------------------------------------
# charges_credit: único ponto de decisão sobre débito
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"owner_name": "ACME LLC", "mailing_address": "PO BOX 9"}, False),
        ({"owner_name": "JOHN", "owner_phone": "5551234"}, True),
        ({}, True),
    ],
)
def test_charges_credit(overrides, expected):
    assert charges_credit(lead(**overrides)) is expected


def test_charges_credit_is_always_inverse_of_corporate():
    for overrides in ({}, {"owner_name": "A"}, {"owner_name": "A", "owner_phone": "1"}, {"owner_name": "A", "mailing_address": "B"}):
        sample = lead(**overrides)
        assert charges_credit(sample) is not is_corporate(sample)


# ---------------------------------------------------------------------------
# classify: o veredito que o frontend consome
# ---------------------------------------------------------------------------
def test_classify_broken_lead():
    """Cenário real de produção: '2424, NYC, NY' sem qualquer contacto."""
    assert classify(lead(address="2424, NYC, NY")) == {
        "corporate": False,
        "address_resolvable": False,
        "unresolvable": True,
    }


def test_classify_corporate_lead():
    assert classify(lead(owner_name="ACME LLC", mailing_address="PO BOX 9")) == {
        "corporate": True,
        "address_resolvable": True,
        "unresolvable": False,
    }


def test_classify_is_consistent_with_the_predicates():
    for overrides in ({}, {"owner_name": "A"}, {"owner_name": "A", "owner_phone": "1"}, {"owner_name": "A", "mailing_address": "B"}):
        sample = lead(**overrides)
        verdict = classify(sample)
        assert verdict["corporate"] == is_corporate(sample)
        assert verdict["address_resolvable"] == address_is_resolvable(sample["address"])
        assert verdict["unresolvable"] == is_unresolvable(sample)
