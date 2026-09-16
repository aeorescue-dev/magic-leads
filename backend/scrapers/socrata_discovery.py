"""
Framework nacional de descoberta de datasets públicos via Socrata Discovery API.

A API de catálogo do Socrata (https://api.us.socrata.com/api/catalog/v1) lista
datasets públicos de MILHARES de cidades/condados/estados dos EUA — tudo gratuito.
Isso permite cobrir o país inteiro sem cadastrar cada município manualmente.
"""
from typing import Dict, List

import httpx

from ..config import settings
from ..utils.logger import logger

SOCRATA_CATALOG = "https://api.us.socrata.com/api/catalog/v1"
TIMEOUT = 30

# Buscas-tema que mapeiam as frentes de captura do produto
DISCOVERY_QUERIES: Dict[str, List[str]] = {
    "311": ["311 service requests", "311 requests", "311 complaints", "open 311"],
    "permits": [
        "building permits", "building permit", "construction permits",
        "code enforcement", "code violations", "building violations",
    ],
    "tax": [
        "tax delinquency", "property tax", "tax liens", "delinquent property",
        "foreclosure", "abandoned property",
    ],
}


class SocrataDiscovery:
    """Descobre datasets públicos por tema, nacionalmente, via Discovery API."""

    def __init__(self):
        self.timeout = TIMEOUT

    async def _search(self, query: str, limit: int = 100) -> List[dict]:
        """Consulta o catálogo nacional por uma busca e retorna metadados úteis."""
        params = {
            "q": query,
            "only": "datasets",
            "limit": limit,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                headers = {}
                if settings.SOCRATA_APP_TOKEN:
                    headers["X-App-Token"] = settings.SOCRATA_APP_TOKEN
                resp = await client.get(SOCRATA_CATALOG, params=params, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
            except httpx.HTTPError as e:
                logger.error(f"Discovery API erro ({query}): {e}")
                return []

        results = []
        for item in payload.get("results", []):
            res = item.get("resource", {})
            meta = item.get("metadata", {})
            domain = meta.get("domain", "")
            dataset_id = res.get("id", "")
            name = res.get("name", "")
            if not (domain and dataset_id):
                continue
            results.append(
                {
                    "domain": domain,
                    "id": dataset_id,
                    "name": name,
                    "columns": res.get("columns_field_name", []),
                    "column_names": res.get("columns_name", []),
                }
            )
        return results

    async def discover(self, theme: str, per_query: int = 100) -> List[dict]:
        """Descobre datasets de um tema ('311' | 'permits' | 'tax')."""
        seen = set()
        out = []
        for query in DISCOVERY_QUERIES.get(theme, []):
            for ds in await self._search(query, limit=per_query):
                key = (ds["domain"], ds["id"])
                if key in seen:
                    continue
                seen.add(key)
                out.append(ds)
        logger.info(f"Discovery '{theme}': {len(out)} datasets únicos")
        return out

    async def discover_all(self) -> dict:
        """Descobre todos os temas. Retorna {311: [...], permits: [...], tax: [...]}."""
        result = {}
        for theme in DISCOVERY_QUERIES:
            result[theme] = await self.discover(theme)
        return result


socrata_discovery = SocrataDiscovery()
