"""Scraper Socrata: o endereco tem de sobreviver a viagem ate a base de dados.

Regressao do defeito que deixou 93 de 100 leads do inventario como
"2424, NYC, NY": o SELECT do SoQL nao pedia `addr_num`/`addr_street`, logo o
`streetname` do HPD nunca chegava ao mapper, e o fallback posterior voltava a
gravar o numero isolado. As fixtures abaixo usam valores reais do dataset
wvxf-dwi5 (HPD Housing Maintenance Code Violations).
"""

import pytest

from backend.scrapers.socrata_311 import socrata_scraper
from backend.services.enrichment import parse_address
from backend.services.lead_rules import address_is_resolvable, normalize_street

# Campos tal como estão declarados em main.py para o dataset HPD.
HPD_FIELDS = [
    "violationid", "buildingid", "inspectiondate", "approveddate", "housenumber",
    "lowhousenumber", "highhousenumber", "streetname", "boro", "zip", "apartment",
    "latitude", "longitude", "novtype", "novdescription", "violationstatus",
    "currentstatus", "novissueddate", "communityboard", "councildistrict", "bbl",
    "block", "lot",
]


def hpd_row(**overrides):
    row = {
        "violationid": "1234567",
        "inspectiondate": "2026-09-30T00:00:00",
        "housenumber": "22 FRONT",
        "streetname": "STAGG STREET",
        "zip": "11206",
        "boro": "BROOKLYN",
        "novdescription": "Heat - Lack of heat",
        "latitude": 40.7,
        "longitude": -73.9,
        "bbl": "3012345678",
    }
    row.update(overrides)
    return row


def cols_for(fields, dataset="wvxf-dwi5"):
    return socrata_scraper._guess_columns(fields)


def parse(row, cols=None, city="NYC", state="NY", source_type="hpd_violation"):
    return socrata_scraper._parse_generic_row(
        row, cols or cols_for(HPD_FIELDS), city, state, source_type=source_type
    )


# ---------------------------------------------------------------------------
# O numero tem de ser acompanhado da rua
# ---------------------------------------------------------------------------
def test_hpd_street_is_not_lost():
    """housenumber + streetname têm de virar um endereço completo."""
    lead = parse(hpd_row())
    assert lead is not None, "lead descartado apesar de ter numero, rua e zip"
    assert lead.address.startswith("22 FRONT STAGG STREET")
    assert address_is_resolvable(lead.address), f"endereco insoluvel: {lead.address!r}"


def test_hpd_address_yields_number_and_street():
    """O que o enrichment vai receber tem de dar parse_address com rua real."""
    lead = parse(hpd_row())
    parsed = parse_address(lead.address)
    assert parsed is not None, "parse_address falhou: nao ha dono possivel"
    number, street = parsed
    assert number == "22"
    assert street == "FRONT STAGG STREET"


def test_hpd_zip_is_carried_through():
    lead = parse(hpd_row())
    assert lead.zip_code == "11206"


def test_hpd_bbl_is_carried_through():
    """BBL torna o enriquecimento exacto; detetado mas nunca seleccionado era
    a mesma classe de defeito do streetname."""
    lead = parse(hpd_row())
    assert lead.bbl == "3012345678"


def test_house_number_alone_is_discarded_not_saved_bare():
    """Sem rua o lead não tem dono possível. Antes regressava como número isolado
    ("2424, NYC, NY") e ficava clicável até falhar na reserva."""
    lead = parse(hpd_row(housenumber="2424", streetname=None))
    assert lead is None, "lead sem rua foi gravado em vez de descartado"


def test_streetname_missing_does_not_fall_back_to_bare_number():
    """Regressão directa: o fallback `if not addr` anulava a rejeição."""
    row = hpd_row(streetname=None, housenumber="473")
    assert parse(row) is None


# ---------------------------------------------------------------------------
# O SELECT tem de incluir o par numero+rua e o bbl
# ---------------------------------------------------------------------------
def test_guess_columns_detects_hpd_pair():
    cols = cols_for(HPD_FIELDS)
    assert cols["addr_num"] == "housenumber"
    assert cols["addr_street"] == "streetname"
    assert cols["zip"] == "zip"
    assert cols["bbl"] == "bbl"


def test_select_includes_addr_pair_and_bbl():
    """O select é montado dentro de fetch_from_dataset; aqui reproduz-se a mesma
    lista para travar a intenção, já que o método faz I/O."""
    cols = cols_for(HPD_FIELDS)
    select_fields = [
        c for c in [
            cols["date"], cols["desc"], cols["lat"], cols["lng"], cols["ext"],
            cols["addr"], cols.get("addr_num"), cols.get("addr_street"),
            cols["zip"], cols.get("bbl"),
        ] if c
    ]
    assert "streetname" in select_fields, "a rua nao era pedida: causa raiz"
    assert "housenumber" in select_fields
    assert "zip" in select_fields
    assert "bbl" in select_fields


def test_zipcode_spelling_is_accepted():
    """Alguns datasets usam `zipcode` em vez de `zip`."""
    cols = cols_for(["incident_address", "street_name", "zipcode"])
    assert cols["zip"] == "zipcode"


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  22  FRONT stagg  street, ", "22 FRONT STAGG STREET"),
        ("2424   CRUGER AVENUE", "2424 CRUGER AVENUE"),
        ("7-11 UNION SQ", "7-11 UNION SQ"),
        (", , 319 WEST 88 STREET ,", "319 WEST 88 STREET"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_street(raw, expected):
    assert normalize_street(raw) == expected


def test_normalize_keeps_address_resolvable_intact():
    assert address_is_resolvable(normalize_street("  2424   CRUGER   AVENUE "))


def test_address_holds_only_the_street():
    """Contrato canonico: `address` guarda SO a rua.

    A cidade, o estado e o zip vivem em colunas proprias. Embebidos no address
    davam "X ST, NYC, NY" e, como o frontend juntava outra vez a coluna city,
    o utilizador via "X ST, NYC, NY, NYC". A garantia de "nao duplicar" e agora
    trivial: a cidade nao entra no address.
    """
    lead = parse(hpd_row())
    assert lead.address == "22 FRONT STAGG STREET"
    assert lead.city == "NYC"
    assert lead.state == "NY"


def test_city_and_state_not_duplicated():
    """Regressao: o scraper nao pode acrescentar cidade/estado ao address.

    Nota: "BROOKLYN" vem da propria coluna `streetname` da fonte e tem de
    permanecer -- o nome da rua e dado. O que nao pode acontecer e o scraper
    juntar a sua propria cidade/estado a um address que ja os menciona, o que
    daria "X ST BROOKLYN, BROOKLYN, NY, NYC, NY".
    """
    lead = parse(hpd_row(housenumber="22", streetname="STAGG STREET BROOKLYN"))
    assert lead.address.count("BROOKLYN") == 1, lead.address
    assert "NYC" not in lead.address.upper(), lead.address
    assert "NY, NY" not in lead.address, lead.address
    assert lead.address == "22 STAGG STREET BROOKLYN", lead.address


def test_city_and_state_come_from_their_own_columns():
    """Onde quer que a rua ja traga a cidade, as colunas continuam a ser a
    fonte da verdade (sao elas que a pesquisa e a migracao usam)."""
    lead = parse(hpd_row(housenumber="22", streetname="STAGG STREET BROOKLYN"))
    assert lead.city == "NYC"
    assert lead.state == "NY"
    assert lead.zip_code == "11206"


def test_address_keeps_first_comma_segment_as_the_street():
    """parse_address e address_is_resolvable cortam na primeira vírgula: o que
    está antes dela tem de ser numero + rua."""
    lead = parse(hpd_row())
    first = lead.address.split(",")[0].strip()
    assert len(first.split()) >= 2, f"primeiro segmento incompativel: {first!r}"
    assert parse_address(lead.address) is not None


# ---------------------------------------------------------------------------
# Regressão: o bug real de produção
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("number", ["2424", "473", "198", "1472"])
def test_real_production_lead_shape_is_no_longer_produced(number):
    """Nenhum lead pode sair com o formato "N, NYC, NY"."""
    cols = cols_for(HPD_FIELDS)
    row = hpd_row(housenumber=number, streetname="CRUGER AVENUE", zip="10469")
    lead = parse(row, cols)
    assert lead is not None
    assert lead.address != f"{number}, NYC, NY"
    assert address_is_resolvable(lead.address)
    assert parse_address(lead.address)[0] == number
