"""Regressão P0 (auditoria 01/11/2026): moradas de Boston corrompidas.

O 311 de Boston devolve `location` já com bairro/estado/ZIP. O pipeline antigo
acrescentava `, Boston, MA` e guardava `"2 Columbus Ave  Boston  MA  02116,
Boston, MA"`, o que quebrava o casamento com o dataset de proprietários
(10.095/10.097 leads afectados; owner de Boston em 0,2%).
"""
from __future__ import annotations

import pytest

from backend.services.boston_address import (
    clean_boston_location,
    parcel_filters,
    parcel_has_unit,
    parcel_match_key,
)
from backend.services.enrichment import _number_overlap, normalize_street, parse_address


@pytest.mark.parametrize(
    "raw, fallback, street, zip5",
    [
        ("2 Columbus Ave  Boston  MA  02116", None, "2 Columbus Ave", "02116"),
        (
            "970 American Legion Hwy  Hyde Park  MA  02136",
            None,
            "970 American Legion Hwy",
            "02136",
        ),
        (
            "62 William C Kelly Sq  East Boston  MA  02128",
            None,
            "62 William C Kelly Sq",
            "02128",
        ),
        # Linhas já corrompidas pelo pipeline antigo (backfill tem de as limpar).
        (
            "2 Columbus Ave  Boston  MA  02116, Boston, MA",
            None,
            "2 Columbus Ave",
            "02116",
        ),
        (
            "18 Phillips St  Boston  MA  02114, Boston, MA",
            None,
            "18 Phillips St",
            "02114",
        ),
        ("18 Phillips St, Boston, MA 02114", None, "18 Phillips St", "02114"),
        ("123 Main St", "02125", "123 Main St", "02125"),
        ("Vassar St", None, "Vassar St", None),
        ("", "02125", "", "02125"),
        (None, "02125-1234", "", "02125"),
    ],
)
def test_clean_boston_location(raw, fallback, street, zip5):
    got_street, got_zip = clean_boston_location(raw, fallback)
    assert got_street == street
    assert got_zip == zip5


def test_ingest_address_never_duplicates_city():
    street, zip5 = clean_boston_location(
        "2 Columbus Ave  Boston  MA  02116", "02116"
    )
    assert "Boston" not in street
    assert street.count(",") == 0
    assert zip5 == "02116"


def test_parcel_dataset_abbreviation_matches_311_address():
    """`full_address` do parcel dataset usa "AV"; o 311 usa "Ave"."""
    lead = parse_address("199 Savin Hill Ave")
    parcel = parse_address("199   SAVIN HILL AV ")
    assert lead and parcel
    assert (lead[0], normalize_street(lead[1])) == (
        parcel[0],
        normalize_street(parcel[1]),
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("199   SAVIN HILL AV ", ("199", "SAVIN HILL AV")),
        ("526   COLUMBUS AV 2", ("526", "COLUMBUS AV")),
        ("604 608 COLUMBUS AV ", ("604", "COLUMBUS AV")),
        ("107 -109 SAVIN HILL AV 1", ("107-109", "SAVIN HILL AV")),
        ("9   JEFFRIES ST", ("9", "JEFFRIES ST")),
        ("2 Columbus Ave", ("2", "COLUMBUS AVE")),
        ("INTERSECTION of W Broadway &amp; D St", None),
        ("", None),
    ],
)
def test_parcel_match_key_ignores_unit_and_range(raw, expected):
    assert parcel_match_key(raw) == expected


def test_parcel_key_matches_311_after_normalization():
    lead = parcel_match_key("526 Columbus Ave")
    parcel = parcel_match_key("526   COLUMBUS AV 2")
    assert lead and parcel
    assert (lead[0], normalize_street(lead[1])) == (
        parcel[0],
        normalize_street(parcel[1]),
    )


def test_parcel_filters_strip_suffix_and_keep_directional():
    assert parcel_filters("357", "MASSACHUSETTS AVE") == {
        "ST_NUM": "357",
        "ST_NAME": "MASSACHUSETTS",
    }
    assert parcel_filters("81", "CHARLES ST") == {
        "ST_NUM": "81",
        "ST_NAME": "CHARLES",
    }
    assert parcel_filters("374", "W BROADWAY") == {
        "ST_NUM": "374",
        "ST_NAME": "W BROADWAY",
    }
    assert parcel_filters("", "CHARLES ST") is None
    assert parcel_filters("81", "") is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("526   COLUMBUS AV 2", True),
        ("526   COLUMBUS AV ", False),
        ("980 970 AMERICAN LEGION HW ", False),
        ("INTERSECTION of X", False),
    ],
)
def test_parcel_has_unit(raw, expected):
    assert parcel_has_unit(raw) is expected


@pytest.mark.parametrize(
    "num, row_num, expected",
    [
        ("970", "980 970", True),
        ("81-83", "81 83", True),
        ("132", "132A", True),
        ("132", "1320", False),
        ("132", "1132", False),
        ("132", None, False),
        (None, "132", False),
    ],
)
def test_number_overlap(num, row_num, expected):
    assert _number_overlap(num, row_num) is expected
