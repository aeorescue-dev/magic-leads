"""Testes da regra que impede o sufixo de cidade/estado de voltar a colar-se.

Regressão de produção: o dataset de Boston traz `full_address` como
"257-259 Cambridge St  Allston  MA  02134, Boston, MA". A `normalize_street`
antiga só colapsava espaços, por isso o ", Boston, MA" ficava dentro de
`address` e o frontend voltava a juntar a coluna `city`, dando
"... BOSTON, MA, BOSTON, MA" ao utilizador.

O mesmo mecanismo está em `normalize_addresses.strip_city_state`; a migração e a
ingestão têm de limpar igual, senão a migração limpa o que o scraper volta a
sujar no dia seguinte.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.lead_rules import (  # noqa: E402
    normalize_street,
    strip_city_state,
)


def test_strips_boston_suffix_when_city_and_state_known():
    # A assinatura real que o dataset de Boston devolve. `normalize_street`
    # upper-casa sempre (comportamento anterior, mantido).
    assert (
        normalize_street(
            "257-259 Cambridge St  Allston  MA  02134, Boston, MA",
            city="Boston",
            state="MA",
            zip_code="02134",
        )
        == "257-259 CAMBRIDGE ST ALLSTON MA 02134"
    )


def test_strips_suffix_with_state_full_name():
    # O dataset traz a sigla no address mas a coluna pode trazer o nome inteiro.
    assert (
        normalize_street("84 Beacon St, Boston, MA", city="Boston", state="Massachusetts")
        == "84 BEACON ST"
    )


def test_keeps_street_named_after_city():
    # "NEW YORK AVENUE" é nome de rua legítimo na cidade de New York.
    assert (
        normalize_street("1267 NEW YORK AVENUE, New York, NY", city="New York", state="NY")
        == "1267 NEW YORK AVENUE"
    )


def test_no_suffix_when_city_unknown():
    # Sem city/state não há como saber o que é sufixo: não se inventa.
    assert normalize_street("84 Beacon St, Boston, MA") == "84 BEACON ST, BOSTON, MA"


def test_empty_address_stays_empty():
    assert normalize_street(None) == ""
    assert normalize_street("", city="Boston", state="MA") == ""


def test_whitespace_and_commas_still_collapsed():
    assert (
        normalize_street("  22  FRONT  stagg  street, , ", city="NYC", state="NY")
        == "22 FRONT STAGG STREET"
    )


def test_migration_and_ingestion_agree():
    """A regra que limpa a base e a que limpa os dados novos não divergem.

    Comparados em caixa e espaçamento normalizados, porque divergem lá de
    propósito: `normalize_street` upper-casa e colapsa espaços (é o que o
    `ON CONFLICT` espera), a migração preserva o texto que já está na base.
    O que não pode diferir é o CONTEÚDO — sobretudo nunca sobrar a cidade.
    """
    addr = "257-259 Cambridge St  Allston  MA  02134, Boston, MA"
    squeeze = lambda s: " ".join(str(s).upper().split())
    assert squeeze(strip_city_state(addr, "Boston", "MA", "02134")) == squeeze(
        normalize_street(addr, city="Boston", state="MA", zip_code="02134")
    )


def test_strip_city_state_still_keeps_apartment_unit():
    # Regressão: um apartamento não pode ser comido como se fosse ZIP.
    assert (
        strip_city_state("1410 NEW YORK AVENUE, APT 1E, NYC, NY 11210", "NYC", "NY", "11210")
        == "1410 NEW YORK AVENUE, APT 1E"
    )