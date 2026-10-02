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
    is_complete_delivery,
    is_incomplete_delivery,
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
    # Regra nova: sem sucesso total de dados nunca se cobra.
    assert charges_credit(sample) is False
    assert is_incomplete_delivery(sample) is True
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
        # Sucesso total (nome + telefone): unico perfil que debita.
        ({"owner_name": "JOHN", "owner_phone": "5551234"}, True),
        # everything else e entregue de graca.
        ({"owner_name": "ACME LLC", "mailing_address": "PO BOX 9"}, False),
        ({"owner_name": "65 MS LLC"}, False),
        ({"owner_phone": "5551234"}, False),
        ({"mailing_address": "PO BOX 9"}, False),
        ({}, False),
    ],
)
def test_charges_credit(overrides, expected):
    assert charges_credit(lead(**overrides)) is expected


def test_charges_credit_requires_total_success():
    """REGRA DE NEGOCIO: so se cobra com owner_name E owner_phone.

    Nao e a negacao de `is_corporate`: um lead incompleto nao e corporativo e
    mesmo assim nao pode ser cobrado, porque seria vendido um lead que o
    cliente nao pode contactar por telefone.
    """
    for overrides in ({}, {"owner_name": "A"}, {"owner_name": "A", "owner_phone": "1"}, {"owner_name": "A", "mailing_address": "B"}):
        sample = lead(**overrides)
        assert charges_credit(sample) is is_complete_delivery(sample)
        # corporate e incompleto nunca podem ser cobrados
        if is_corporate(sample) or is_incomplete_delivery(sample):
            assert charges_credit(sample) is False


def test_incomplete_delivery_is_always_free_and_corporate_is_always_free():
    for overrides in ({}, {"owner_name": "A"}, {"owner_name": "A", "owner_phone": "1"}, {"owner_name": "A", "mailing_address": "B"}):
        sample = lead(**overrides)
        if is_corporate(sample) or is_incomplete_delivery(sample):
            assert charges_credit(sample) is False, overrides


# ---------------------------------------------------------------------------
# classify: o veredito que o frontend consome
# ---------------------------------------------------------------------------
def test_classify_broken_lead():
    """Cenário real de produção: '2424, NYC, NY' sem qualquer contacto."""
    assert classify(lead(address="2424, NYC, NY")) == {
        "corporate": False,
        "address_resolvable": False,
        "unresolvable": True,
        "complete_delivery": False,
        "incomplete_delivery": True,
        "charged": False,
    }


def test_classify_corporate_lead():
    assert classify(lead(owner_name="ACME LLC", mailing_address="PO BOX 9")) == {
        "corporate": True,
        "address_resolvable": True,
        "unresolvable": False,
        "complete_delivery": False,
        "incomplete_delivery": False,
        "charged": False,
    }


def test_classify_is_consistent_with_the_predicates():
    for overrides in ({}, {"owner_name": "A"}, {"owner_name": "A", "owner_phone": "1"}, {"owner_name": "A", "mailing_address": "B"}):
        sample = lead(**overrides)
        verdict = classify(sample)
        assert verdict["corporate"] == is_corporate(sample)
        assert verdict["address_resolvable"] == address_is_resolvable(sample["address"])
        assert verdict["unresolvable"] == is_unresolvable(sample)
        assert verdict["complete_delivery"] == is_complete_delivery(sample)
        assert verdict["incomplete_delivery"] == is_incomplete_delivery(sample)
        assert verdict["charged"] == charges_credit(sample)
