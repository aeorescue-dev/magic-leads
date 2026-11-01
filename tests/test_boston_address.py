"""Regressão P0 (auditoria 01/11/2026): moradas de Boston corrompidas.

O 311 de Boston devolve `location` já com bairro/estado/ZIP. O pipeline antigo
acrescentava `, Boston, MA` e guardava `"2 Columbus Ave  Boston  MA  02116,
Boston, MA"`, o que quebrava o casamento com o dataset de proprietários
(10.095/10.097 leads afectados; owner de Boston em 0,2%).
"""
from __future__ import annotations

import pytest

from backend.services.boston_address import clean_boston_location
from backend.services.enrichment import normalize_street, parse_address


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
