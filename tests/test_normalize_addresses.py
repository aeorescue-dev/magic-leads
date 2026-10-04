"""Testes da normalização de `leads.address`.

O ponto crítico é NÃO perder parte do endereço: "EAST NEW YORK AVENUE" tem de
sobreviver quando a cidade é "NYC"/"New York", e um número de apartamento não
pode ser confundido com um ZIP.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts.normalize_addresses import strip_city_state  # noqa: E402


def test_strips_city_state_and_zip():
    assert (
        strip_city_state("403 EAST 87 STREET, NYC, NY 10128", "NYC", "NY", "10128")
        == "403 EAST 87 STREET"
    )


def test_strips_city_and_state_without_zip():
    assert strip_city_state("854 EAST NEW YORK AVENUE, NYC, NY", "NYC", "NY", "") == (
        "854 EAST NEW YORK AVENUE"
    )


def test_keeps_street_named_after_city():
    # Regressão: a cidade é NYC, mas "NEW YORK" faz parte do nome da rua.
    assert strip_city_state("1267 NEW YORK AVENUE, NYC, NY", "NYC", "NY", "") == (
        "1267 NEW YORK AVENUE"
    )


def test_keeps_apartment_unit():
    addr = "1410 NEW YORK AVENUE, APT 1E, NYC, NY 11210"
    assert strip_city_state(addr, "NYC", "NY", "11210") == "1410 NEW YORK AVENUE, APT 1E"


def test_strips_zip_even_when_zip_column_is_null():
    # Regressão: Dallas tem zip_code NULL mas o address traz ", TX, 75218".
    assert strip_city_state("847 BROOKHURST DR, DALLAS, TX, 75218", "Dallas", "TX", None) == (
        "847 BROOKHURST DR"
    )


def test_strips_combined_state_zip_segment():
    assert strip_city_state("2009 W 22ND PL, Chicago, IL 60608", "Chicago", "IL", "60608") == (
        "2009 W 22ND PL"
    )


def test_appends_city_when_absent_from_address():
    # Address já canónico (só a rua): não há nada para remover.
    assert strip_city_state("3312 N NEWLAND AVE", "Chicago", "IL", "60623") == "3312 N NEWLAND AVE"


def test_handles_empty_and_missing_city():
    assert strip_city_state("", "NYC", "NY", "") == ""
    assert strip_city_state("1", "", "", "") == "1"


def test_does_not_strip_numeric_looking_apartment():
    # "APT 5B" não é ZIP. E um número de rua não é ZIP.
    assert strip_city_state("200 MAIN STREET, APT 5B, NYC", "NYC", "NY", "") == (
        "200 MAIN STREET, APT 5B"
    )


def test_state_full_name_matches_abbreviation():
    # state="Texas" mas o address traz a sigla "TX".
    assert strip_city_state("2688 LACLEDE ST, DALLAS, TX, 75204", "Dallas", "Texas", None) == (
        "2688 LACLEDE ST"
    )
