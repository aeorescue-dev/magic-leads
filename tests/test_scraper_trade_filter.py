"""Movimento #1 — filtro por oficio e fontes de permisos.

Contexto (medido em producao): o filtro anterior usava a lista
`SCRAPER_KEYWORDS` sobre a DESCRICAO. Essa lista nao cobre a redacao real
das fontes, por isso descartava oficios REAIS: 156 PLUMBING + 16 GRASS +
14 RODENT por ciclo em Dallas, 113 PLUMBING em NYC. Ao mesmo tempo, o
catalogo Socrata tem dezenas de datasets "por categoria" (CUNY, Chicago
historicos) que sao ARQUIVOS MORTOS (ultimo registo entre 2012 e 2022) —
liga-los nao produziria zero leads novos.

Invariantes fixados aqui:
  1. `_infer_category_ex` distingue "oficio real" de "fallback generico".
  2. O filtro do scraper mantem o oficio e descarta o ruido.
  3. Uma fonte de obrigacao legal (permit/violation) mantem-se sempre.
  4. A heuristica de colunas reconhece datasets de permisos (data, descricao,
     endereco, id) — antes abortava a fonte com "no such column".
"""
from __future__ import annotations

import pytest

from backend.models.schemas import IssueCategory
from backend.scrapers.socrata_311 import socrata_scraper


# ------------------------------------------------------- 1. inferencia de oficio


def test_infer_category_ex_flags_real_trades():
    """Descricoes que nomeiam um oficio devolvem (categoria, True)."""
    cases = [
        ("SEWER - Complaint", IssueCategory.PLUMBING),
        ("Water leak in basement", IssueCategory.PLUMBING),
        ("PAINT/PLASTER VIOLATION", IssueCategory.PAINT),
        ("Rodent Baiting/Rat Complaint", IssueCategory.RODENT),
        ("Heat - Hot Water", IssueCategory.HEATING),
        ("Exposed Wire - Electrical", IssueCategory.ELECTRICAL),
        ("Re-roof with Class A roof covering", IssueCategory.ROOF),
        ("Broken Window - Sash", IssueCategory.DOOR_WINDOW),
        ("Tree Debris - Branch Down", IssueCategory.DEBRIS),
    ]
    for desc, expected in cases:
        cat, matched = socrata_scraper._infer_category_ex(desc)
        assert matched is True, f"{desc!r} devia contar como oficio real"
        assert cat == expected, f"{desc!r} -> {cat} (esperado {expected})"


def test_infer_category_ex_flags_generic_fallback():
    """Ruido de 311 (recolha, candeeiros, informacao) cai no fallback."""
    for desc in (
        "Missed Collection",
        "Street Lights Out",
        "Request for Information",
        "Homeless Encampment - EMCR",
        "Industrial Waste Complaints",
    ):
        cat, matched = socrata_scraper._infer_category_ex(desc)
        assert matched is False, f"{desc!r} devia ser ruido (fallback)"
        assert cat == IssueCategory.STRUCTURE


def test_infer_category_ex_known_false_positive_indoor():
    """Limitacao CONHECIDA: "indoor" contem "door" -> classifica como porta.

    Match por substring, nao por palavra. Medido: 23 registos por ciclo no
    311 de NYC (~1,5% da fonte). O impacto e' pequeno demais para justificar
    mexer no classificador nuclear neste momento — fica documentado.
    """
    cat, matched = socrata_scraper._infer_category_ex("Indoor Air Quality")
    assert matched is True
    assert cat == IssueCategory.DOOR_WINDOW


def test_infer_category_ex_legal_source_is_always_a_trade():
    """Fontes de obrigacao legal (permit/violacao) sao oficio, mesmo sem texto."""
    for stype in ("permit", "dob_violation", "hpd_violation", "tax_delinquency"):
        cat, matched = socrata_scraper._infer_category_ex("X", stype)
        assert matched is True, stype
        assert cat == IssueCategory.PERMIT_REJECTED


def test_infer_category_backwards_compatible():
    """`_infer_category` continua a devolver so' a categoria."""
    assert socrata_scraper._infer_category("SEWER - Complaint") == IssueCategory.PLUMBING
    assert socrata_scraper._infer_category("Missed Collection") == IssueCategory.STRUCTURE


# ------------------------------------------------------- 2. filtro do scraper


class _FakeScraper:
    """Reimplementa o filtro do scraper sobre um fetch ja' feito."""

    def __init__(self, descriptions, source_type=None):
        self.descriptions = descriptions
        self.source_type = source_type

    def keep(self, description):
        _cat, matched = socrata_scraper._infer_category_ex(
            description, self.source_type
        )
        return matched


def test_trade_filter_keeps_trades_and_drops_noise():
    fake = _FakeScraper([])
    assert fake.keep("SEWER - Complaint") is True
    assert fake.keep("Missed Collection") is False
    assert fake.keep("Heat - Hot Water") is True
    assert fake.keep("Street Lights Out") is False
    # "Garbage" e' uma das 16 categorias (entulho) -> conta como oficio.
    assert fake.keep("Sanitation Missed Garbage - SAN") is True


def test_trade_filter_keeps_legal_source_without_keywords():
    fake = _FakeScraper([], source_type="permit")
    assert fake.keep("CL2 - Exempt") is True


# ------------------------------------------------------- 3. colunas de permisos


CHI_PERMIT_COLUMNS = [
    "id", "issue_date", "work_description", "permit_type", "permit_status",
    "street_number", "street_name", "latitude", "longitude", "community_area",
    "ward", "application_start_date",
]

LA_PERMIT_COLUMNS = [
    "permit_nbr", "zip_code", "issue_date", "submitted_date", "work_desc",
    "use_desc", "permit_type", "permit_sub_type", "primary_address",
    "latitude", "lon", "status_desc",
]

NYC_ECB_COLUMNS = [
    "hearing_date", "boro", "bin", "ecb_violation_number", "violation_type",
    "respondent_street", "respondent_house_number", "respondent_zip",
    "issue_date", "block", "lot",
]


def test_guess_columns_detects_chicago_permits():
    """Chicago Building Permits: data, descricao de trabalho, endereco e id."""
    g = socrata_scraper._guess_columns(CHI_PERMIT_COLUMNS)
    assert g["date"] == "issue_date"
    assert g["desc"] == "work_description"
    assert g["addr_num"] == "street_number"
    assert g["addr_street"] == "street_name"
    assert g["ext"] == "id"
    assert g["_has_date"] and g["_has_desc"]
    assert g["lat"] == "latitude" and g["lng"] == "longitude"


def test_guess_columns_detects_la_permits():
    """LA Building Permits: endereco num campo unico e id = permit_nbr."""
    g = socrata_scraper._guess_columns(LA_PERMIT_COLUMNS)
    assert g["date"] == "issue_date"
    assert g["desc"] == "work_desc"
    assert g["addr"] == "primary_address"
    assert g["ext"] == "permit_nbr"
    assert g["_has_date"] and g["_has_desc"]


def test_guess_columns_detects_nyc_ecb_violations():
    """DOB ECB: par numero+rua (respondent_house_number/respondent_street)."""
    g = socrata_scraper._guess_columns(NYC_ECB_COLUMNS)
    assert g["date"] == "hearing_date"
    assert g["desc"] == "violation_type"
    assert g["addr_num"] == "respondent_house_number"
    assert g["addr_street"] == "respondent_street"
    assert g["ext"] == "ecb_violation_number"


def test_guess_columns_prefers_trade_bearing_description_over_flags():
    """`use_desc`/`work_desc` ganham a campos sem descricao (construction)."""
    g = socrata_scraper._guess_columns(
        ["permit_nbr", "issue_date", "construction", "use_desc", "work_desc",
         "primary_address", "latitude", "lon"]
    )
    assert g["desc"] in ("use_desc", "work_desc")


def test_guess_columns_keeps_existing_311_sources_unchanged():
    """As fontes 311 que ja' funcionavam nao podem regredir."""
    nyc = socrata_scraper._guess_columns(
        ["unique_key", "created_date", "closed_date", "due_date", "complaint_type",
         "descriptor", "incident_address", "street_name", "incident_zip",
         "latitude", "longitude", "status", "bbl", "borough"]
    )
    assert nyc["date"] == "created_date"
    assert nyc["desc"] == "complaint_type"
    assert nyc["addr"] == "incident_address"
    assert nyc["ext"] == "unique_key"
    assert nyc["bbl"] == "bbl"

    chi = socrata_scraper._guess_columns(
        ["sr_number", "created_date", "sr_type", "street_address", "zip_code",
         "latitude", "longitude", "status"]
    )
    assert chi["date"] == "created_date"
    assert chi["desc"] == "sr_type"
    assert chi["ext"] == "sr_number"

    dal = socrata_scraper._guess_columns(
        ["service_request_number", "created_date", "service_request_type",
         "address", "lat_location", "status"]
    )
    assert dal["date"] == "created_date"
    assert dal["desc"] == "service_request_type"
    assert dal["addr"] == "address"
    assert dal["ext"] == "service_request_number"
    # Dallas traz as coordenadas num campo unico "(lat,lon)".
    assert dal["lat"] == "lat_location"


def test_guess_columns_hpd_keeps_a_description_column():
    """HPD: a descricao continua a ser detectada (violation_status nao conta)."""
    g = socrata_scraper._guess_columns(
        ["violationid", "inspectiondate", "approveddate", "housenumber",
         "streetname", "latitude", "longitude", "novtype", "novdescription",
         "violationstatus", "currentstatus", "novissueddate", "bbl"]
    )
    assert g["date"] in ("inspectiondate", "approveddate", "novissueddate")
    assert g["desc"] in ("novtype", "novdescription")
    assert g["addr_num"] == "housenumber"
    assert g["addr_street"] == "streetname"
    assert g["bbl"] == "bbl"


# ------------------------------------------------------- 4. config do scraper


def test_scrape_worker_config_includes_chicago_permits():
    """A fonte nova tem de estar na configuracao do worker."""
    import re

    from pathlib import Path

    main_py = Path(__file__).resolve().parents[1] / "backend" / "main.py"
    src = main_py.read_text(encoding="utf-8")
    assert re.search(r'"dataset":\s*"ydr8-5enu"', src), (
        "a fonte de Building Permits de Chicago nao esta' em base_cities"
    )
    assert '"chi_permits": "permit"' in src, (
        "o source_type da nova fonte nao esta' mapeado"
    )
