"""
Enriquecimento de proprietário a partir de registros públicos (custo $0).

Estratégia multicaminho para máxima consistência:
  A) Match exato (número + rua)
  B) Normalização de sufixo de rua (STREET->ST, AVENUE->AVE, etc.)
  C) Prefixo do número (fallback)
  D) Busca apenas por rua (fallback final)

Por cidade, usa o dataset Socrata/CKAN que contém owner + endereço no mesmo registro.
"""
import asyncio
import json
import random
import re
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

from ..config import settings
from ..utils.logger import logger
from .boston_address import parcel_filters, parcel_has_unit, parcel_match_key

# Retry configuration for enrichment
ENRICHMENT_MAX_RETRIES = 3
ENRICHMENT_BASE_BACKOFF = 1.0  # seconds
ENRICHMENT_MAX_BACKOFF = 30.0  # seconds

# Aliases de cidade -> chave em CITY_DATASETS. As 311 guardam a cidade como
# "NYC", mas varias fontes e Reports usam o nome por extenso ou o borough.
CITY_ALIASES: Dict[str, str] = {
    "NEW YORK": "NYC",
    "NYC": "NYC",
    "MANHATTAN": "NYC",
    "BROOKLYN": "NYC",
    "QUEENS": "NYC",
    "BRONX": "NYC",
    "STATEN ISLAND": "NYC",
    "CHICAGO": "CHICAGO",
    "DALLAS": "DALLAS",
    "BOSTON": "BOSTON",
    # NORFOLK removido de proposito: data.norfolk.gov/qva7-tzrf e um cadastro
    # fiscal de predios (parcel tax roll), sem categoria de obra nem estado de
    # chamado. Nao passa _qualified_where (endereco + 16 oficios + gatilho), e
    # forca-lo a passar mostraria donos sem defeito verificado como lead de obra.
}


CITY_DATASETS: Dict[str, Dict] = {
    "NYC": {
        "domain": "data.cityofnewyork.us",
        "dataset": "64uk-42ks",
        "owner_col": "ownername",
        "num_col": None,
        "street_col": None,
        "address_col": "address",
        "zip_col": None,
        "mailing_addr_col": None,
        "mailing_city_col": None,
        "mailing_zip_col": None,
        "type": "socrata",
        "number_as_string": True,
        # BBL (borough-block-lot) e o identificador canonico de imovel em NYC.
        # Quando presente, o casamento e exacto e nao depende de parsing de morada.
        "bbl_col": "bbl",
    },
    "DALLAS": {
        "domain": "www.dallasopendata.com",
        "dataset": "jk5c-7csb",
        "owner_col": "owner1",
        "num_col": "siteaddrnum",
        "street_col": "sitestreetname",
        "zip_col": None,
        "mailing_addr_col": "ownaddr2",
        "mailing_city_col": "ownercity",
        "mailing_zip_col": "ownerzip",
        "type": "socrata",
        "number_as_string": True,
    },
    "BOSTON": {
        "domain": "data.boston.gov",
        "dataset": "bdb17c2b-e9ab-44e4-a070-bf804a0e1a7f",
        "owner_col": "OWNER",
        "num_col": None,
        "street_col": "full_address",
        "zip_col": "ZIPCODE",
        "mailing_addr_col": "OWNER_MAIL_ADDRESS",
        "mailing_city_col": "OWNER_MAIL_CS",
        "mailing_zip_col": "OWNER_MAIL_ZIPCODE",
        "type": "ckan",
        "number_as_string": True,
    },
    "CHICAGO": {
        "domain": "datacatalog.cookcountyil.gov",
        "dataset": "3723-97qp",
        "owner_col": "owner_address_name",
        "num_col": None,
        "street_col": None,
        "address_col": "prop_address_full",
        "city_filter_col": "prop_address_city_name",
        "city_filter_value": "CHICAGO",
        "order_col": "year",
        "order_dir": "DESC",
        "year_col": "year",
        "zip_col": None,
        "mailing_addr_col": "mail_address_full",
        "mailing_city_col": "mail_address_city_name",
        "mailing_zip_col": "mail_address_zipcode_1",
        "type": "socrata",
        "number_as_string": True,
    },
}


_SUFFIX = {
    "STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "PLACE": "PL", "ROAD": "RD",
    "BOULEVARD": "BLVD", "LANE": "LN", "DRIVE": "DR", "TERRACE": "TER",
    "PARKWAY": "PKWY", "COURT": "CT", "SQUARE": "SQ", "HIGHWAY": "HWY",
    "CIRCLE": "CIR", "WAY": "WAY", "DR": "DR", "LN": "LN",
}


def normalize_street(s: str) -> str:
    s = (s or "").upper()
    words = s.split()
    out = []
    for w in words:
        cleaned = re.sub(r"\.$", "", w)
        if cleaned in _SUFFIX:
            cleaned = _SUFFIX[cleaned]
        out.append(cleaned)
    return " ".join(out)


def normalize_number(num: str) -> str:
    return num.strip()


def parse_address(address: str) -> Optional[tuple]:
    """Extrai (numero, rua) de endereços tipo '1415 EAST 86 STREET, NY 11236'."""
    if not address:
        return None
    part = address.split(",")[0].strip()
    p = part.split(" ", 1)
    if len(p) < 2:
        return None
    return p[0].strip(), p[1].strip()


# Numero de casa aceite: digitos, com sufixo de letra (1684A), hifen (31-67)
# ou ponto (100.5). Fracoes ("1/2") e palavras nao sao numeros de imovel.
_HOUSE_NUMBER_RE = re.compile(r"^\d+[A-Za-z]?(-\d+[A-Za-z]?)*(\.\d+)?$")


def is_house_number(num: str) -> bool:
    """True se `num` parece mesmo um numero de imovel.

    Enderecos como "INTERSECTION of Vassar St" ou "S Barry Ave" fazem
    `parse_address` devolver "INTERSECTION" / "S" como numero. Sem esta
    verificacao o casamento por nome de rua atribui o proprietario de um
    imovel que nao e o do chamado.
    """
    candidate = re.sub(r"[^0-9A-Za-z./-]", "", (num or "").strip())
    return bool(candidate) and bool(_HOUSE_NUMBER_RE.match(candidate))


# Retry configuration for enrichment
ENRICHMENT_MAX_RETRIES = 3
ENRICHMENT_BASE_BACKOFF = 1.0  # seconds
ENRICHMENT_MAX_BACKOFF = 30.0  # seconds


def _number_overlap(num: Optional[str], row_num: Optional[str]) -> bool:
    """True se os numeros/intervalos se sobrepoem (970 vs 980 970)."""

    def _ints(value: Optional[str]) -> list[int]:
        return [int(x) for x in re.findall(r"\d+", str(value or ""))]

    a = _ints(num)
    b = _ints(row_num)
    if not a or not b:
        return False
    return min(a) <= max(b) and min(b) <= max(a)


class OwnerEnrichment:
    """Consultas de nome do proprietário + mailing address por endereço (com cache)."""

    def __init__(self):
        self._cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._budget_date: Optional[date] = None
        self._budget_used: int = 0

    def _budget_available(self) -> bool:
        """True se a cota diária ainda não foi usada OU cota = 0 (ilimitada)."""
        if settings.ENRICHMENT_DAILY_BUDGET <= 0:
            return True
        today = date.today()
        if self._budget_date != today:
            self._budget_date = today
            self._budget_used = 0
        return self._budget_used < settings.ENRICHMENT_DAILY_BUDGET

    def _consume_budget(self) -> None:
        if settings.ENRICHMENT_DAILY_BUDGET > 0:
            self._budget_used += 1

    def budget_remaining(self) -> int:
        if settings.ENRICHMENT_DAILY_BUDGET <= 0:
            return 1_000_000
        self._budget_available()
        return max(0, settings.ENRICHMENT_DAILY_BUDGET - self._budget_used)

    def _headers(self) -> Dict[str, str]:
        headers = {}
        if settings.SOCRATA_APP_TOKEN:
            headers["X-App-Token"] = settings.SOCRATA_APP_TOKEN
        return headers

    def _config_for(self, city: str) -> Optional[Dict]:
        if not city:
            return None
        key = None
        city_upper = city.upper().strip()
        for alias, target in CITY_ALIASES.items():
            if alias in city_upper:
                key = target
                break
        if key is None:
            for k in CITY_DATASETS:
                if city_upper.startswith(k) or k in city_upper:
                    key = k
                    break
        return CITY_DATASETS.get(key)

    async def enrich(
        self, address: str, city: str, bbl: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        cfg = self._config_for(city)
        if not cfg:
            return None
        bbl_key = str(bbl).strip() if bbl else ""
        cache_key = f"{city}:{address}" + (f":bbl={bbl_key}" if bbl_key else "")
        if cache_key in self._cache:
            return self._cache[cache_key]
        if not self._budget_available():
            logger.info(f"Enriquecimento: cota diária esgotada ({settings.ENRICHMENT_DAILY_BUDGET}/dia) — pulando {address}")
            return None
        self._consume_budget()
        result = await self._lookup(address, cfg, bbl_key or None)
        if result is not None:
            self._cache[cache_key] = result
        return result

    async def _lookup(
        self, address: str, cfg: Dict, bbl: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        # BBL primeiro: e o identificador canonico de imovel em NYC e da um
        # casamento exacto, sem parsing de morada e sem risco de atribuir o
        # proprietario do imovel vizinho.
        if bbl and cfg.get("bbl_col"):
            bbl_result = await self._lookup_by_bbl(bbl, cfg)
            if bbl_result is not None:
                return bbl_result

        parsed = parse_address(address)
        if not parsed:
            return None
        num, street = parsed

        # Sem numero de imovel nao ha como provar a que propriedade o dono
        # pertence. Enderecos de cruzamento ("INTERSECTION of A & B") e vias sem
        # numero ("S Barry Ave") caem aqui e devolvem None de proposito.
        if not is_house_number(num):
            logger.debug(f"Sem numero de imovel em {address!r} — owner nao atribuido")
            return None

        # Comparacoes e filtros (ST_NAME, LIKE) sao em maiusculas: as fontes
        # devolvem moradas em caixa alta e o 311 de Boston em caixa mista.
        street_norm = normalize_street(street)

        if cfg["type"] == "socrata":
            return await self._lookup_socrata(address, num, street_norm, cfg)
        elif cfg["type"] == "ckan":
            return await self._lookup_ckan(address, num, street_norm, cfg)
        return None

    async def _lookup_by_bbl(self, bbl: str, cfg: Dict) -> Optional[Dict[str, Any]]:
        """Casamento exacto de imovel via BBL (borough-block-lot) de NYC."""
        bbl_col = cfg.get("bbl_col")
        if not bbl_col:
            return None
        if not re.fullmatch(r"\d{9,10}", bbl):
            logger.debug(f"BBL invalido, ignorado: {bbl!r}")
            return None

        domain, dset = cfg["domain"], cfg["dataset"]
        select_cols = [cfg["owner_col"]]
        for opt in ("address_col", "zip_col", "mailing_addr_col", "mailing_city_col", "mailing_zip_col"):
            if cfg.get(opt):
                select_cols.append(cfg[opt])
        select_cols = list(dict.fromkeys(select_cols))

        url = f"https://{domain}/resource/{dset}.json"
        params = {
            "$select": ",".join(select_cols),
            "$where": f"{bbl_col} = {bbl}",
            "$limit": "1",
        }
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.get(url, params=params, headers=self._headers())
        except httpx.HTTPError as e:
            logger.warning(f"Erro lookup BBL {bbl}: {e}")
            return None
        if resp.status_code != 200:
            logger.warning(f"Lookup BBL {bbl} retornou {resp.status_code}")
            return None
        try:
            data = resp.json()
        except Exception:
            return None
        if not isinstance(data, list) or not data:
            logger.warning(f"BBL {bbl} sem proprietario em {dset}")
            return None
        return self._build_result(data[0], cfg, f"BBL {bbl}")

    async def _lookup_socrata(self, original_address: str, num: str, street_norm: str, cfg: Dict) -> Optional[Dict[str, Any]]:
        domain = cfg["domain"]
        dset = cfg["dataset"]

        select_cols = [cfg["owner_col"]]
        if cfg.get("mailing_addr_col"):
            select_cols.append(cfg["mailing_addr_col"])
        if cfg.get("mailing_city_col"):
            select_cols.append(cfg["mailing_city_col"])
        if cfg.get("mailing_zip_col"):
            select_cols.append(cfg["mailing_zip_col"])
        if cfg.get("num_col"):
            select_cols.append(cfg["num_col"])
        if cfg.get("street_col"):
            select_cols.append(cfg["street_col"])
        if cfg.get("address_col"):
            select_cols.append(cfg["address_col"])
        if cfg.get("city_filter_col"):
            select_cols.append(cfg["city_filter_col"])
        if cfg.get("year_col"):
            select_cols.append(cfg["year_col"])
        if cfg.get("zip_col"):
            select_cols.append(cfg["zip_col"])

        sel = ",".join(select_cols)
        base = f"https://{domain}/resource/{dset}.json"
        num_col = cfg.get("num_col")
        street_col = cfg.get("street_col")
        address_col = cfg.get("address_col")
        city_filter_col = cfg.get("city_filter_col")
        city_filter_value = cfg.get("city_filter_value")

        street_for_query = street_norm
        street_for_query = re.sub(r"\s+", " ", street_for_query).strip()

        queries = []

        if address_col:
            full_address = f"{num} {street_for_query}"
            full_address_esc = full_address.replace("'", "''")
            city_part = ""
            if city_filter_col and city_filter_value:
                city_esc = city_filter_value.replace("'", "''")
                city_part = f" AND {city_filter_col} = '{city_esc}'"
            queries.append(f"{address_col} like '{full_address_esc}%'{city_part}")
            # For address_col-only cities (e.g., Chicago), also try number + street pattern
            # to handle directional prefixes/suffixes in dataset (e.g., "7025 S CALUMET AVE")
            num_esc = num.replace("'", "''")
            queries.append(f"{address_col} like '%{num_esc}% {street_for_query}%'{city_part}")

        if num_col and street_col:
            if cfg.get("number_as_string", True):
                queries.append(f"{street_col} like '{street_for_query}%' AND {num_col} = '{num}'")
                queries.append(f"{street_col} like '%{street_for_query}%' AND {num_col} = '{num}'")
            else:
                queries.append(f"{street_col} like '{street_for_query}%' AND {num_col} = {num}")
                queries.append(f"{street_col} like '%{street_for_query}%' AND {num_col} = {num}")

        if num_col and street_col and len(num) > 1:
            prefix = num[:max(1, len(num) - 1)]
            if cfg.get("number_as_string", True):
                queries.append(f"{street_col} like '%{street_for_query}%' AND {num_col} like '{prefix}%'")
            else:
                queries.append(f"{street_col} like '%{street_for_query}%' AND {num_col} like {prefix}%")

        if street_col:
            queries.append(f"{street_col} like '%{street_for_query}%'")
        elif address_col:
            # Fallback para cidades sem street_col separado (ex: NYC): busca por rua no address_col
            queries.append(f"{address_col} like '%{street_for_query}%'")

        async with httpx.AsyncClient(timeout=90) as client:
            for where in queries:
                for attempt in range(ENRICHMENT_MAX_RETRIES + 1):
                    try:
                        params = {
                            "$select": sel,
                            "$limit": "5",
                            "$where": where,
                        }
                        if cfg.get("order_col"):
                            order = cfg["order_col"]
                            if cfg.get("order_dir"):
                                order = f"{order} {cfg['order_dir']}"
                            params["$order"] = order
                        resp = await client.get(base, params=params, headers=self._headers())
                        if resp.status_code != 200:
                            if attempt < ENRICHMENT_MAX_RETRIES:
                                wait_time = min(ENRICHMENT_BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.5), 30.0)
                                logger.warning(f"Enrichment {domain} status {resp.status_code} (tentativa {attempt + 1}/{ENRICHMENT_MAX_RETRIES + 1}). Retry em {wait_time:.1f}s")
                                await asyncio.sleep(wait_time)
                                continue
                            continue
                        data = resp.json()
                        break
                    except httpx.HTTPError as e:
                        if attempt < ENRICHMENT_MAX_RETRIES:
                            wait_time = min(ENRICHMENT_BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.5), 30.0)
                            logger.warning(f"Erro enrichment {domain} (tentativa {attempt + 1}/{ENRICHMENT_MAX_RETRIES + 1}): {e}. Retry em {wait_time:.1f}s")
                            await asyncio.sleep(wait_time)
                            continue
                        logger.warning(f"Erro enrichment {domain}: {e}")
                        break
                    except Exception as e:
                        logger.warning(f"Erro inesperado enrichment {domain}: {e}")
                        break

                if 'data' not in locals() or not data:
                    continue

                if isinstance(data, list) and data:
                    if num_col:
                        for row in data:
                            row_num = str(row.get(num_col) or "").strip()
                            if row_num == num:
                                return self._build_result(row, cfg, original_address)
                        # O $where ja filtrou pelo numero: se nao ha casamento exato,
                        # a unica resposta segura e NAO ter proprietario.
                        logger.debug(f"Sem match exato para numero {num!r} em {cfg.get('dataset')}")
                        return None
                    else:
                        best = None
                        best_year = -1
                        for row in data:
                            row_addr = str(row.get(address_col) or "").upper()
                            if row_addr == full_address.upper():
                                year = -1
                                if cfg.get("year_col"):
                                    y = str(row.get(cfg["year_col"]) or "").strip()
                                    if y.replace(".", "").isdigit():
                                        year = int(float(y))
                                if year > best_year:
                                    best_year = year
                                    best = row
                        if best is not None:
                            return self._build_result(best, cfg, original_address)
                        # Fallback seguro: so aceitar uma linha cujo numero de
                        # imovel normalizado coincida com o pedido. Devolver
                        # data[0] sem verificacao atribui o proprietario do
                        # imóvel vizinho.
                        for row in data:
                            row_addr = str(row.get(address_col) or "")
                            parsed = parse_address(row_addr)
                            if parsed and normalize_number(parsed[0]) == normalize_number(num):
                                return self._build_result(row, cfg, original_address)
                        logger.debug(
                            f"Sem match verificado para {original_address!r} em {cfg.get('dataset')}"
                        )
                        return None
        return None

    async def _ckan_fetch(self, base: str, params: dict) -> Optional[list]:
        """GET ao CKAN com retry; devolve records ou None (nunca rebenta)."""
        for attempt in range(ENRICHMENT_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=90) as client:
                    resp = await client.get(
                        base, params=params, headers=self._headers()
                    )
                    if resp.status_code != 200:
                        if attempt < ENRICHMENT_MAX_RETRIES:
                            wait_time = min(
                                ENRICHMENT_BASE_BACKOFF * (2 ** attempt)
                                + random.uniform(0, 0.5),
                                30.0,
                            )
                            logger.warning(
                                "CKAN %s status %s (tentativa %s/%s). Retry em %.1fs",
                                params.get("resource_id"),
                                resp.status_code,
                                attempt + 1,
                                ENRICHMENT_MAX_RETRIES + 1,
                                wait_time,
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        return None
                    payload = resp.json()
                    if not payload.get("success"):
                        return None
                    return list(payload["result"].get("records") or [])
            except httpx.HTTPError as e:
                if attempt < ENRICHMENT_MAX_RETRIES:
                    wait_time = min(
                        ENRICHMENT_BASE_BACKOFF * (2 ** attempt)
                        + random.uniform(0, 0.5),
                        30.0,
                    )
                    logger.warning(
                        "Erro enrichment CKAN (tentativa %s/%s): %s. Retry em %.1fs",
                        attempt + 1,
                        ENRICHMENT_MAX_RETRIES + 1,
                        e,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                logger.warning("Erro enrichment CKAN: %s", e)
                return None
            except Exception:  # noqa: BLE001
                logger.warning("Erro inesperado enrichment CKAN")
                return None
        return None

    def _match_ckan(
        self, records: list, cfg: Dict, num: str, street_norm: str,
        original_address: str,
    ) -> Optional[Dict[str, Any]]:
        """Escolhe o registo certo; nunca devolve o vizinho por engano."""
        street_col = cfg["street_col"]
        exact = []
        for row in records:
            full_addr = str(row.get(street_col) or "").upper()
            row_key = parcel_match_key(full_addr)
            if not row_key or not num:
                continue
            row_num, row_street = row_key
            if (
                row_num == str(num).strip()
                and normalize_street(row_street) == street_norm
            ):
                exact.append(row)
        if exact:
            # Condominios: preferir a linha sem unidade (dono do edificio).
            for row in exact:
                if not parcel_has_unit(row.get(street_col)):
                    return self._build_result(row, cfg, original_address)
            return self._build_result(exact[0], cfg, original_address)

        # Intervalos ("980 970 AMERICAN LEGION HW", "81-83 CHARLES ST") e
        # números com letra não passam no filtro exacto ST_NUM. Casar por
        # sobreposição numérica na mesma rua.
        if num:
            for row in records:
                full_addr = str(row.get(street_col) or "").upper()
                row_key = parcel_match_key(full_addr)
                if not row_key:
                    continue
                _, row_street = row_key
                if normalize_street(row_street) != street_norm:
                    continue
                if _number_overlap(num, row.get("ST_NUM") or row_key[0]):
                    return self._build_result(row, cfg, original_address)

        for row in records:
            full_addr = str(row.get(street_col) or "").upper()
            if street_norm and street_norm in full_addr:
                if num:
                    addr_part = full_addr.split(",")[0].strip()
                    addr_num = (
                        addr_part.split(" ")[0] if " " in addr_part else addr_part
                    )
                    if (
                        addr_num == num
                        or addr_num.startswith(num)
                        or num.startswith(addr_num)
                    ):
                        return self._build_result(row, cfg, original_address)
                else:
                    return self._build_result(row, cfg, original_address)

        orig_norm = normalize_street(original_address.split(",")[0].strip().upper())
        for row in records:
            full_addr = str(row.get(street_col) or "").upper()
            row_norm = normalize_street(full_addr.split(",")[0].strip())
            if orig_norm == row_norm:
                return self._build_result(row, cfg, original_address)

        # Sem correspondencia: so aceitar quando existe um unico candidato.
        if len(records) == 1:
            logger.warning(
                "CKAN %s: a unica resposta para %r nao casou com a rua; "
                "atribuido por unico candidato",
                cfg["dataset"],
                original_address,
            )
            return self._build_result(records[0], cfg, original_address)
        return None

    async def _lookup_ckan(
        self, original_address: str, num: str, street_norm: str, cfg: Dict
    ) -> Optional[Dict[str, Any]]:
        domain = cfg["domain"]
        dset = cfg["dataset"]
        base = f"https://{domain}/api/3/action/datastore_search"

        fields = [cfg["owner_col"]]
        if cfg.get("mailing_addr_col"):
            fields.append(cfg["mailing_addr_col"])
        if cfg.get("mailing_city_col"):
            fields.append(cfg["mailing_city_col"])
        if cfg.get("mailing_zip_col"):
            fields.append(cfg["mailing_zip_col"])
        if cfg.get("street_col"):
            fields.append(cfg["street_col"])
        if cfg.get("zip_col"):
            fields.append(cfg["zip_col"])
        # ST_NUM permite casar intervalos ("980 970 AMERICAN LEGION HW").
        fields.append("ST_NUM")

        street_search = street_norm.split()[0] if street_norm else ""
        if not street_search:
            return None
        common = {
            "resource_id": dset,
            "limit": "50",
            "fields": ",".join(fields),
        }
        # 1) filtros exactos ST_NUM/ST_NAME (o `q` do CKAN e' OR e falha em
        # ruas compridas); 2) fallback de texto para ranges/unidades.
        tries: list[dict] = []
        filters = parcel_filters(num, street_norm)
        if filters:
            tries.append({**common, "filters": json.dumps(filters)})
            # Rua sem número: apanha intervalos e unidades. Ordenar por
            # ST_NUM e trazer 500 porque o intervalo pode estar no meio.
            tries.append(
                {
                    **common,
                    "limit": "500",
                    "sort": "ST_NUM asc",
                    "filters": json.dumps({"ST_NAME": filters["ST_NAME"]}),
                }
            )
        query = f"{num} {street_search}".strip() if num else street_search
        tries.append({**common, "q": query})

        for params in tries:
            records = await self._ckan_fetch(base, params)
            if not records:
                continue
            match = self._match_ckan(
                records, cfg, num, street_norm, original_address
            )
            if match:
                return match

        logger.warning(
            "CKAN %s: nenhuma resposta casou com %r", dset, original_address
        )
        return None

    def _build_result(self, row: Dict, cfg: Dict, original_address: str) -> Dict[str, Any]:
        owner = str(row.get(cfg["owner_col"]) or "").strip()
        if not owner or owner.upper().startswith("N/A"):
            return None

        result = {
            "owner_name": owner,
            "source_dataset": f"{cfg['domain']}/{cfg['dataset']}",
            "matched_address": original_address,
        }

        mailing_parts = []
        if cfg.get("mailing_addr_col"):
            addr = str(row.get(cfg["mailing_addr_col"]) or "").strip()
            if addr:
                mailing_parts.append(addr)
        if cfg.get("mailing_city_col"):
            city = str(row.get(cfg["mailing_city_col"]) or "").strip()
            if city:
                mailing_parts.append(city)
        if cfg.get("mailing_zip_col"):
            zipc = str(row.get(cfg["mailing_zip_col"]) or "").strip()
            if zipc:
                mailing_parts.append(zipc)

        if mailing_parts:
            result["mailing_address"] = ", ".join(mailing_parts)

        return result

    async def enrich_batch(self, address_city_pairs: List[tuple]) -> Dict[str, Optional[Dict[str, Any]]]:
        out = {}
        seen = set()
        for item in address_city_pairs:
            if len(item) == 3:
                address, city, bbl = item
                bbl = bbl if bbl else None
            else:
                address, city = item[0], item[1] if len(item) > 1 else ""
                bbl = None
            key = f"{city}:{address}"
            if key in seen:
                continue
            seen.add(key)
            out[key] = await self.enrich(address, city, bbl=bbl)
        return out


owner_enrichment = OwnerEnrichment()
