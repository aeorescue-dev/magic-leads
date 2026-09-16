"""
Enriquecimento de proprietário a partir de registros públicos (custo $0).

Estratégia multicaminho para máxima consistência:
  A) Match exato (número + rua)
  B) Normalização de sufixo de rua (STREET->ST, AVENUE->AVE, etc.)
  C) Prefixo do número (fallback)
  D) Busca apenas por rua (fallback final)

Por cidade, usa o dataset Socrata/CKAN que contém owner + endereço no mesmo registro.
"""
import re
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

from ..config import settings
from ..utils.logger import logger

CITY_DATASETS: Dict[str, Dict] = {
    "NYC": {
        # PLUTO (Primary Land Use Tax Lot Output) — dono de todos os lotes, mais completo que BuildCom
        "domain": "data.cityofnewyork.us",
        "dataset": "64uk-42ks",
        "owner_col": "ownername",
        "num_col": None,  # address é endereço completo ("323 EAST 12 STREET")
        "street_col": None,
        "address_col": "address",
        "zip_col": None,  # não usado (sem coluna separada confiável)
        "mailing_addr_col": None,
        "mailing_city_col": None,
        "mailing_zip_col": None,
        "type": "socrata",
        "number_as_string": True,
    },
    "DALLAS": {
        "domain": "www.dallasopendata.com",
        "dataset": "jk5c-7csb",
        "owner_col": "owner1",
        "num_col": "siteaddrnum",
        "street_col": "sitestreetname",
        "zip_col": None,  # not in dataset
        "mailing_addr_col": "ownaddr2",
        "mailing_city_col": "ownercity",
        "mailing_zip_col": "ownerzip",
        "type": "socrata",
        "number_as_string": True,
    },
    "NORFOLK": {
        "domain": "data.norfolk.gov",
        "dataset": "qva7-tzrf",  # Property Assessment FY27
        "owner_col": "owner",
        "num_col": "property_street_number",
        "street_col": "property_street_name",
        "zip_col": "property_zip",
        "mailing_addr_col": None,
        "mailing_city_col": None,
        "mailing_zip_col": None,
        "type": "socrata",
        "number_as_string": True,
    },
    "BOSTON": {
        "domain": "data.boston.gov",
        "dataset": "bdb17c2b-e9ab-44e4-a070-bf804a0e1a7f",  # Property Assessment 2015
        "owner_col": "OWNER",
        "num_col": None,  # use full_address parsing
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
        "dataset": "3723-97qp",  # Cook County Assessor - Parcel Addresses (owner + mailing)
        "owner_col": "owner_address_name",
        "num_col": None,  # endereço completo em um só campo (prop_address_full)
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
    "STREET": "ST", "AVENUE": "AVE", "PLACE": "PL", "ROAD": "RD",
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


class OwnerEnrichment:
    """Consultas de nome do proprietário + mailing address por endereço (com cache)."""

    def __init__(self):
        self._cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._budget_date: Optional[date] = None
        self._budget_used: int = 0

    def _budget_available(self) -> bool:
        """Reseta o contador diário quando vira o dia e checa a cota."""
        today = date.today()
        if self._budget_date != today:
            self._budget_date = today
            self._budget_used = 0
        return self._budget_used < settings.ENRICHMENT_DAILY_BUDGET

    def _consume_budget(self) -> None:
        self._budget_used += 1

    def budget_remaining(self) -> int:
        self._budget_available()
        return max(0, settings.ENRICHMENT_DAILY_BUDGET - self._budget_used)

    def _headers(self) -> Dict[str, str]:
        headers = {}
        if settings.SOCRATA_APP_TOKEN:
            headers["X-App-Token"] = settings.SOCRATA_APP_TOKEN
        return headers

    def _config_for(self, city: str) -> Optional[Dict]:
        key = None
        city_upper = city.upper()
        for k in CITY_DATASETS:
            if city_upper.startswith(k) or k in city_upper:
                key = k
                break
        return CITY_DATASETS.get(key)

    async def enrich(self, address: str, city: str) -> Optional[Dict[str, Any]]:
        cfg = self._config_for(city)
        if not cfg:
            return None
        cache_key = f"{city}:{address}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        if not self._budget_available():
            logger.info(f"Enriquecimento: cota diária esgotada ({settings.ENRICHMENT_DAILY_BUDGET}/dia) — pulando {address}")
            self._cache[cache_key] = None
            return None
        self._consume_budget()
        result = await self._lookup(address, cfg)
        self._cache[cache_key] = result
        return result

    async def _lookup(self, address: str, cfg: Dict) -> Optional[Dict[str, Any]]:
        parsed = parse_address(address)
        if not parsed:
            return None
        num, street = parsed
        # Keep original street for query (dataset uses full names like ROAD, AVENUE)
        # Also create normalized version for client-side comparison if needed

        if cfg["type"] == "socrata":
            return await self._lookup_socrata(address, num, street, cfg)
        elif cfg["type"] == "ckan":
            return await self._lookup_ckan(address, num, street, cfg)
        return None

    async def _lookup_socrata(self, original_address: str, num: str, street_norm: str, cfg: Dict) -> Optional[Dict[str, Any]]:
        domain = cfg["domain"]
        dset = cfg["dataset"]

        # Build select columns
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

        # Use original street name for query (dataset has full names like ROAD, AVENUE)
        # Also create normalized version for client-side comparison
        street_for_query = street_norm  # Keep original (not abbreviated)
        # Collaps multi-spaces (ex.: "323 EAST   12 STREET" -> "323 EAST 12 STREET")
        street_for_query = re.sub(r"\s+", " ", street_for_query).strip()
        # Don't abbreviate suffixes in query - dataset uses full names

        # Build queries in order of preference
        queries = []

        if address_col:
            # Full-address dataset (e.g. Cook County): "153 W NORTH AVE" em um campo só
            full_address = f"{num} {street_for_query}"
            # Escape single quotes for Socrata
            full_address_esc = full_address.replace("'", "''")
            city_part = ""
            if city_filter_col and city_filter_value:
                city_esc = city_filter_value.replace("'", "''")
                city_part = f" AND {city_filter_col} = '{city_esc}'"
            # Prefix-exact (endereço começa com número+rua): usa índice, mais rápido que %...%
            queries.append(f"{address_col} like '{full_address_esc}%'{city_part}")

        if num_col and street_col:
            # Prefix-exact primeiro (usa índice, ~1s) e broad como fallback
            if cfg.get("number_as_string", True):
                # Number as string in Socrata - use single quotes
                queries.append(f"{street_col} like '{street_for_query}%' AND {num_col} = '{num}'")
                queries.append(f"{street_col} like '%{street_for_query}%' AND {num_col} = '{num}'")
            else:
                queries.append(f"{street_col} like '{street_for_query}%' AND {num_col} = {num}")
                queries.append(f"{street_col} like '%{street_for_query}%' AND {num_col} = {num}")

        # Prefix fallback
        if num_col and street_col and len(num) > 1:
            prefix = num[:max(1, len(num) - 1)]
            if cfg.get("number_as_string", True):
                queries.append(f"{street_col} like '%{street_for_query}%' AND {num_col} like '{prefix}%'")
            else:
                queries.append(f"{street_col} like '%{street_for_query}%' AND {num_col} like {prefix}%")

        # Street only (broad match, filter client-side)
        if street_col:
            queries.append(f"{street_col} like '%{street_for_query}%'")

        async with httpx.AsyncClient(timeout=90) as client:
            for where in queries:
                try:
                    params = {
                        "$select": sel,
                        "$limit": "5",  # Get a few to filter client-side
                        "$where": where,
                    }
                    if cfg.get("order_col"):
                        order = cfg["order_col"]
                        if cfg.get("order_dir"):
                            order = f"{order} {cfg['order_dir']}"
                        params["$order"] = order
                    resp = await client.get(base, params=params, headers=self._headers())
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                except httpx.HTTPError as e:
                    logger.debug(f"Erro enrichment {domain}: {e}")
                    continue

                if isinstance(data, list) and data:
                    if num_col:
                        # Filter client-side for exact number match if we have num_col
                        for row in data:
                            row_num = str(row.get(num_col) or "").strip()
                            if row_num == num:
                                return self._build_result(row, cfg, original_address)
                        # If no exact number match, return first (street match)
                        return self._build_result(data[0], cfg, original_address)
                    else:
                        # Full-address dataset: prefer exact full-address match
                        # Cook County tem várias linhas por imóvel (um por ano)
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
                        if data:
                            return self._build_result(data[0], cfg, original_address)
        return None

    async def _lookup_ckan(self, original_address: str, num: str, street_norm: str, cfg: Dict) -> Optional[Dict[str, Any]]:
        domain = cfg["domain"]
        dset = cfg["dataset"]
        base = f"https://{domain}/api/3/action/datastore_search"

        # CKAN uses different query format - we'll search by full_address
        # Build field list
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

        # Search by street name in full_address
        street_search = street_norm.split()[0] if street_norm else ""
        if not street_search:
            return None

        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.get(base, params={
                    "resource_id": dset,
                    "limit": "10",
                    "fields": ",".join(fields),
                    "q": street_search,  # Full-text search
                }, headers=self._headers())
                if resp.status_code != 200:
                    return None
                result = resp.json()
        except httpx.HTTPError as e:
            logger.debug(f"Erro enrichment CKAN {domain}: {e}")
            return None

        if not result.get("success"):
            return None

        records = result["result"].get("records", [])
        if not records:
            return None

        # Filter client-side for best match
        for row in records:
            full_addr = str(row.get(cfg["street_col"]) or "").upper()
            if street_norm in full_addr:
                # Try to match number
                if num:
                    addr_part = full_addr.split(",")[0].strip()
                    addr_num = addr_part.split(" ")[0] if " " in addr_part else addr_part
                    if addr_num == num:
                        return self._build_result(row, cfg, original_address)
                # Return first street match
                return self._build_result(row, cfg, original_address)

        # Fallback: return first record
        return self._build_result(records[0], cfg, original_address)

    def _build_result(self, row: Dict, cfg: Dict, original_address: str) -> Dict[str, Any]:
        owner = str(row.get(cfg["owner_col"]) or "").strip()
        if not owner or owner.upper().startswith("N/A"):
            return None

        result = {
            "owner_name": owner,
            "source_dataset": f"{cfg['domain']}/{cfg['dataset']}",
            "matched_address": original_address,
        }

        # Add mailing address if available
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
        """Enriquece uma lista de (address, city), retornando dict address->result."""
        out = {}
        seen = set()
        for address, city in address_city_pairs:
            key = f"{city}:{address}"
            if key in seen:
                continue
            seen.add(key)
            out[key] = await self.enrich(address, city)
        return out


owner_enrichment = OwnerEnrichment()
