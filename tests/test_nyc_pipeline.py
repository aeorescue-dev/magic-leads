"""
Testes de regressao para o pipeline de NYC.

Causam cobertas por estes testes:

1. `incident_address or street_name` descartava a rua no 311 de NYC e
   gravava 93,4% do inventario sem nome de rua.
2. `NYC_DATASET` era referenciado mas nunca definido.
3. Selects Socrata com colunas inexistentes quebravam a query com HTTP 400
   (DOB Permits: `job_type`; HPD: `violation_id`).
4. Datasets que nao sao 311 (HPD violations) ficavam com `source_type = '311'`
   e desapareciam do filtro de obrigacao legal.
5. O fallback por substring devolvia o dono do imovel vizinho quando nao
   havia casamento exacto.
6. Sem `bbl` nao havia forma de casar o proprietario de forma exacta.
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.scrapers.socrata_311 import socrata_scraper
from backend.services.enrichment import (
    CITY_ALIASES,
    CITY_DATASETS,
    OwnerEnrichment,
    is_house_number,
)


# ---------------------------------------------------------------- enderecos
class TestComposeAddressParts:
    def test_numero_mais_rua(self):
        assert socrata_scraper._compose_address_parts("1684A", "EAST 87 STREET") == "1684A EAST 87 STREET"

    def test_numero_com_guiao(self):
        assert socrata_scraper._compose_address_parts("31-67", "49 STREET") == "31-67 49 STREET"

    def test_nao_duplica_rua_ja_presente(self):
        # incident_address as vezes ja traz o endereco completo
        got = socrata_scraper._compose_address_parts("31-67 49 STREET", "49 STREET")
        assert got == "31-67 49 STREET"

    def test_so_rua(self):
        assert socrata_scraper._compose_address_parts(None, "MAIN STREET") == "MAIN STREET"

    def test_so_numero(self):
        assert socrata_scraper._compose_address_parts("1200", None) == "1200"

    def test_so_intersecao(self):
        got = socrata_scraper._compose_address_parts(None, None, "5TH AVE AND 34TH ST")
        assert got == "5TH AVE AND 34TH ST"

    def test_tudo_vazio(self):
        assert socrata_scraper._compose_address_parts(None, None, None) == ""

    def test_todos_os_campos_ausentes_nao_parte_nada(self):
        assert socrata_scraper._compose_address_parts("", "", "") == ""


# ---------------------------------------------------------------------- BBL
class TestCleanBbl:
    @pytest.mark.parametrize("raw,expected", [
        ("1002360026", "1002360026"),
        (1002360026, "1002360026"),
        ("1002360026.0", "1002360026"),
        (None, None),
        ("", None),
        ("ABC", None),
        ("12", None),
        ("1" * 11, None),
    ])
    def test_normaliza(self, raw, expected):
        assert socrata_scraper._clean_bbl(raw) == expected

    def test_bbl_sujo_nunca_vira_chave_de_casamento(self):
        assert socrata_scraper._clean_bbl("N/A") is None
        assert socrata_scraper._clean_bbl("12; DROP TABLE leads") is None


# --------------------------------------------------------- deteccao de colunas
class TestGuessColumns:
    NYC_311_FIELDS = [
        "unique_key", "created_date", "complaint_type", "incident_address",
        "street_name", "intersection_street_1", "incident_zip", "latitude",
        "longitude", "status", "agency_name", "borough", "bbl",
    ]
    HPD_FIELDS = [
        "violationid", "buildingid", "inspectiondate", "housenumber",
        "lowhousenumber", "highhousenumber", "streetname", "boro", "zip",
        "bbl", "novdescription", "currentstatus",
    ]

    def test_detecta_par_numero_rua_do_311(self):
        cols = socrata_scraper._guess_columns(self.NYC_311_FIELDS)
        assert cols["addr_num"] == "incident_address"
        assert cols["addr_street"] == "street_name"
        assert cols["date"] == "created_date"
        assert cols["ext"] == "unique_key"

    def test_detecta_par_numero_rua_do_hpd(self):
        cols = socrata_scraper._guess_columns(self.HPD_FIELDS)
        assert cols["addr_num"] == "housenumber"
        assert cols["addr_street"] == "streetname"
        assert cols["ext"] == "violationid"
        assert cols["date"] == "inspectiondate"

    def test_detecta_coluna_bbl(self):
        for fields in (self.NYC_311_FIELDS, self.HPD_FIELDS):
            assert socrata_scraper._guess_columns(fields)["bbl"] == "bbl"

    def test_sem_bbl_quando_a_fonte_nao_tem(self):
        fields = ["unique_key", "created_date", "complaint_type", "incident_address"]
        assert socrata_scraper._guess_columns(fields)["bbl"] is None


# --------------------------------------------------------------- parse de row
class TestParseGenericRow:
    HPD_FIELDS = [
        "violationid", "buildingid", "inspectiondate", "housenumber",
        "streetname", "boro", "zip", "bbl", "novdescription", "currentstatus",
    ]

    def _row(self, **over):
        row = {
            "violationid": "19250069",
            "inspectiondate": "2026-09-01T00:00:00.000",
            "housenumber": "1730",
            "streetname": "ANDREWS AVENUE SOUTH",
            "boro": "3",
            "zip": "10453",
            "bbl": "2028780178",
            "novdescription": "Wall paint peeling",
            "currentstatus": "OPEN",
        }
        row.update(over)
        return row

    def test_endereco_tem_rua_e_bbl(self):
        cols = socrata_scraper._guess_columns(self.HPD_FIELDS)
        lead = socrata_scraper._parse_generic_row(
            self._row(), cols, "NYC", "NY", source_type="hpd_violation")
        assert lead is not None
        assert "ANDREWS AVENUE SOUTH" in lead.address
        assert lead.address.startswith("1730 ")
        assert lead.bbl == "2028780178"
        assert lead.source_type == "hpd_violation"

    def test_source_type_por_omissao_continua_311(self):
        cols = socrata_scraper._guess_columns(self.HPD_FIELDS)
        lead = socrata_scraper._parse_generic_row(self._row(), cols, "NYC", "NY")
        assert lead.source_type is None

    def test_bbl_invalido_vira_none(self):
        cols = socrata_scraper._guess_columns(self.HPD_FIELDS)
        lead = socrata_scraper._parse_generic_row(
            self._row(bbl="XYZ"), cols, "NYC", "NY")
        assert lead.bbl is None

    def test_endereco_so_com_numero_nao_e_aceito_como_completo(self):
        # Regressao do bug original: sem streetname o address ficava "1730".
        cols = socrata_scraper._guess_columns(["violationid", "inspectiondate", "housenumber"])
        lead = socrata_scraper._parse_generic_row(
            {"violationid": "1", "inspectiondate": "2026-09-01T00:00:00", "housenumber": "140"},
            cols, "NYC", "NY")
        assert lead is not None
        # pelo menos tem de indicar a ausencia de rua de forma visivel
        assert "140" in lead.address


# ------------------------------------------------------------------- aliases
class TestCityAliases:
    def test_nyc_aceita_nome_por_extenso_e_boroughs(self):
        oe = OwnerEnrichment()
        for city in ["NYC", "New York", "New York City", "MANHATTAN",
                     "Brooklyn", "Queens", "Bronx", "Staten Island"]:
            cfg = oe._config_for(city)
            assert cfg is not None, f"cidade {city!r} nao resolve"
            assert cfg["dataset"] == CITY_DATASETS["NYC"]["dataset"]

    def test_cidades_existentes_continuam_a_resolver(self):
        oe = OwnerEnrichment()
        for key in ("CHICAGO", "DALLAS", "BOSTON", "NORFOLK"):
            cfg = oe._config_for(key)
            assert cfg is not None, f"cidade {key!r} regrediu"
            assert cfg["dataset"] == CITY_DATASETS[key]["dataset"]

    def test_todo_alias_aponta_para_uma_cidade_existente(self):
        for alias, target in CITY_ALIASES.items():
            assert target in CITY_DATASETS, f"alias {alias!r} aponta para {target!r} inexistente"

    def test_cidade_vazia_nao_parte_nada(self):
        assert OwnerEnrichment()._config_for("") is None
        assert OwnerEnrichment()._config_for(None) is None


# ------------------------------------------------------------- config do BBL
class TestNycBblConfig:
    def test_nyc_tem_bbl_col(self):
        assert CITY_DATASETS["NYC"].get("bbl_col") == "bbl"

    def test_apenas_nyc_usa_bbl(self):
        for key, cfg in CITY_DATASETS.items():
            if key != "NYC":
                assert "bbl_col" not in cfg, f"{key} nao deveria ter bbl_col"


# ------------------------------------------------------- fonte de reduzido risco
class TestFailClosed:
    """O fallback por substring devolvia o proprietario do imovel vizinho.

    `_lookup_socrata` recebe o `$where` ja filtrado por numero, por isso se
    nao houver linha com esse numero a resposta segura e None.
    """

    @pytest.mark.asyncio
    async def test_sem_match_exato_devolve_none(self, monkeypatch):
        import httpx

        oe = OwnerEnrichment()
        cfg = dict(CITY_DATASETS["DALLAS"])  # usa num_col, o ramo removido

        class FakeResponse:
            status_code = 200

            def json(self):
                # o servidor devolve um imóvel vizinho, nao o pedido
                return [{"siteaddrnum": "999", "owner1": "IMOVEL VIZINHO",
                         "sitestreetname": "MAIN ST"}]

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())
        result = await oe._lookup_socrata("123 MAIN ST", "123", "MAIN ST", cfg)
        assert result is None, "devolveu o dono de outro imóvel"

    @pytest.mark.asyncio
    async def test_numero_certo_devolve_o_dono(self, monkeypatch):
        import httpx

        oe = OwnerEnrichment()
        cfg = dict(CITY_DATASETS["DALLAS"])

        class FakeResponse:
            status_code = 200

            def json(self):
                return [{"siteaddrnum": "123", "owner1": "DONO CERTO",
                         "sitestreetname": "MAIN ST"}]

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())
        result = await oe._lookup_socrata("123 MAIN ST", "123", "MAIN ST", cfg)
        assert result is not None
        assert result["owner_name"] == "DONO CERTO"

    @pytest.mark.asyncio
    async def test_bbl_invalido_e_ignorado(self, monkeypatch):
        import httpx

        oe = OwnerEnrichment()
        cfg = dict(CITY_DATASETS["NYC"])
        called = []

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                called.append(kw)
                raise AssertionError("nao devia consultar a API com BBL invalido")

        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())
        assert await oe._lookup_by_bbl("nao-e-bbl", cfg) is None
        assert called == []

    @pytest.mark.asyncio
    async def test_bbl_valido_consulta_exatamente_por_bbl(self, monkeypatch):
        import httpx

        oe = OwnerEnrichment()
        cfg = dict(CITY_DATASETS["NYC"])
        seen = {}

        class FakeResponse:
            status_code = 200

            def json(self):
                return [{"bbl": "1002360026", "ownername": "DONO LLC",
                         "address": "139 MULBERRY STREET"}]

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, params=None, headers=None):
                seen["where"] = (params or {}).get("$where")
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())
        result = await oe._lookup_by_bbl("1002360026", cfg)
        assert result is not None
        assert result["owner_name"] == "DONO LLC"
        assert "bbl = 1002360026" in seen["where"]

    @pytest.mark.asyncio
    async def test_bbl_sem_resultado_devolve_none(self, monkeypatch):
        import httpx

        oe = OwnerEnrichment()
        cfg = dict(CITY_DATASETS["NYC"])

        class FakeResponse:
            status_code = 200

            def json(self):
                return []

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: FakeClient())
        assert await oe._lookup_by_bbl("1002360026", cfg) is None


class TestHouseNumberGuard:
    """Sem numero de imovel nao se atribui um proprietario.

    `parse_address` devolve a primeira palavra como numero, por isso
    "INTERSECTION of Vassar St" produzia num="INTERSECTION" e o casamento por
    nome de rua devolvia o dono de um imovel que nao e o do chamado.
    """

    @pytest.mark.parametrize("num,ok", [
        ("210", True),
        ("1684A", True),
        ("31-67", True),
        ("100-01", True),
        ("100.5", True),
        ("1/2", False),
        ("INTERSECTION", False),
        ("S", False),
        ("N", False),
        ("", False),
    ])
    def test_reconhece_numero_de_casa(self, num, ok):
        assert is_house_number(num) is ok

    @pytest.mark.asyncio
    async def test_cruzamento_nao_atribui_dono(self):
        oe = OwnerEnrichment()
        cfg = oe._config_for("Boston")
        assert cfg is not None

        called = []

        async def spy(*a, **kw):
            called.append(a)
            return {"owner_name": "DONO DE UM IMOVEL QUALQUER"}

        oe._lookup_ckan = spy
        result = await oe._lookup(
            "INTERSECTION of Vassar St & Harvard Ave  Cambridge  MA  02139", cfg)
        assert result is None
        assert called == [], "a consulta por nome de rua nem devia ter sido tentada"

    @pytest.mark.asyncio
    async def test_via_sem_numero_nao_atribui_dono(self):
        oe = OwnerEnrichment()
        assert await oe._lookup("S BARRY AVE & EAST GRAND AVE, DALLAS, TX, 75220",
                                oe._config_for("Dallas")) is None


# --------------------------------------------------------- cache com bbl
class TestEnrichCache:
    @pytest.mark.asyncio
    async def test_cache_distingue_mesmo_endereco_com_bbl_diferente(self, monkeypatch):
        oe = OwnerEnrichment()
        monkeypatch.setattr(oe, "_budget_available", lambda: True)
        monkeypatch.setattr(oe, "_consume_budget", lambda: None)

        seen = []

        async def fake_lookup(address, cfg, bbl=None):
            seen.append(bbl)
            return {"owner_name": f"DONO {bbl}"} if bbl else None

        monkeypatch.setattr(oe, "_lookup", fake_lookup)

        await oe.enrich("139 MULBERRY STREET, NYC, NY", "NYC", bbl="1002360026")
        await oe.enrich("139 MULBERRY STREET, NYC, NY", "NYC", bbl="2002360026")
        assert seen == ["1002360026", "2002360026"], "cache colou dois imoveis diferentes"
