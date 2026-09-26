import asyncio
import random
import re
from datetime import datetime, timedelta
from typing import List, Optional

import httpx

from ..config import settings
from ..models.schemas import IssueCategory, RawLead311, UrgencyLevel
from ..utils.logger import logger


class Socrata311Scraper:
    """
    Scrapa dados de 311 Service Requests via Socrata API.
    Suporta NYC, Chicago, Miami, etc.
    """

    # Retry configuration
    MAX_RETRIES = 3
    BASE_BACKOFF = 1.0  # seconds
    MAX_BACKOFF = 30.0  # seconds

    def __init__(self):
        self.keywords = settings.SCRAPER_KEYWORDS
        self.timeout = 30

    async def _fetch_soql(
        self, domain: str, dataset: str, select: str, where: str,
        limit: int = 50000, order: str = None, timeout: int = None
    ) -> list:
        """Consulta genérica via Socrata SoQL API (/resource/{id}.json), retorna lista de dicts.

        Inclui retry com backoff exponencial para falhas transitórias de rede.
        """
        t = timeout or self.timeout
        url = f"https://{domain}/resource/{dataset}.json"
        params = {
            "$select": select,
            "$limit": limit,
        }
        if where:
            params["$where"] = where
        if order:
            params["$order"] = order

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                headers = {}
                if settings.SOCRATA_APP_TOKEN:
                    headers["X-App-Token"] = settings.SOCRATA_APP_TOKEN
                async with httpx.AsyncClient(timeout=t) as client:
                    response = await client.get(url, params=params, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                    if isinstance(data, dict):  # erro retornado como dict
                        logger.error(f"Erro Socrata: {data}")
                        return []
                    return data or []
            except httpx.HTTPError as e:
                # Se não é a última tentativa, espera com backoff exponencial
                if attempt < self.MAX_RETRIES:
                    wait_time = min(self.BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.5), 30.0)
                    logger.warning(f"Erro Socrata {domain} (tentativa {attempt + 1}/{self.MAX_RETRIES + 1}): {e}. Retry em {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"Erro ao conectar {domain} após {self.MAX_RETRIES + 1} tentativas: {e}")
                return []
            except Exception as e:
                # Erros não-HTTP não fazem retry
                logger.error(f"Erro inesperado ao conectar {domain}: {e}")
                return []

    async def fetch_nyc_311(self) -> List[RawLead311]:
        """Fetch NYC 311 Service Requests (últimas 48h)"""
        select = (
            "unique_key, created_date, complaint_type, incident_address, "
            "street_name, incident_zip, city, latitude, longitude"
        )
        where_clause = self._build_where_clause(hours=48)

        rows = await self._fetch_soql(
            domain="data.cityofnewyork.us",
            dataset=self.NYC_DATASET,
            select=select,
            where=where_clause,
            order="created_date DESC",
        )

        leads = []
        for row in rows:
            try:
                lead = self._parse_nyc_row(row)
                if lead:
                    leads.append(lead)
            except Exception as e:
                logger.warning(f"Erro ao parsear NYC row: {e}")
                continue

        logger.info(f"NYC 311: Extraído {len(leads)} leads válidos")
        return leads

    async def fetch_chicago_311(self) -> List[RawLead311]:
        """Fetch Chicago 311 Service Requests"""
        since = (datetime.now() - timedelta(hours=48)).isoformat()
        keywords_or = " OR ".join([f"sr_type like '%{kw}%'" for kw in self.keywords])
        where_clause = f"created_date > '{since}' AND ({keywords_or})"

        rows = await self._fetch_soql(
            domain="data.cityofchicago.org",
            dataset=self.CHICAGO_DATASET,
            select="*",
            where=where_clause,
            order="created_date DESC",
        )

        leads = []
        for row in rows:
            try:
                lead = self._parse_chicago_row(row)
                if lead:
                    leads.append(lead)
            except Exception as e:
                logger.warning(f"Erro ao parsear Chicago row: {e}")
                continue

        logger.info(f"Chicago 311: Extraído {len(leads)} leads válidos")
        return leads

    def _build_where_clause(self, hours: int = 48) -> str:
        """Constrói cláusula WHERE para Socrata SoQL API"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        keywords_or = " OR ".join([f"complaint_type like '%{kw}%'" for kw in self.keywords])
        return f"created_date > '{since}' AND ({keywords_or})"

    def _parse_nyc_row(self, row: dict) -> RawLead311 | None:
        """Parse um dict de dados NYC (SoQL)"""
        try:
            street = row.get("incident_address") or row.get("street_name") or ""
            zip_code = row.get("incident_zip") or None
            address = f"{street}, NYC, NY" if street else "NYC, NY"
            if zip_code:
                address = f"{street}, NY {zip_code}" if street else f"NYC, NY {zip_code}"

            # created_date vem como ISO (ex: 2026-09-02T00:00:00.000)
            created = row.get("created_date")
            created_at = datetime.fromisoformat(str(created).replace("Z", "+00:00")) if created else datetime.now()

            return RawLead311(
                external_id=str(row.get("unique_key")),
                address=address,
                city="NYC",
                state="NY",
                zip_code=zip_code,
                issue_description=row.get("complaint_type") or "",
                created_at=created_at,
                lat=float(row["latitude"]) if row.get("latitude") is not None else None,
                lng=float(row["longitude"]) if row.get("longitude") is not None else None,
                issue_category=self._infer_category(row.get("complaint_type") or ""),
                case_title=row.get("complaint_type") or None,
                department=row.get("agency_name") or None,
                descriptor=row.get("descriptor") or None,
                case_status=row.get("status") or None,
                precinct=row.get("police_precinct") or None,
                neighborhood=row.get("borough") or None,
                ward=row.get("community_board") or row.get("council_district") or None,
                source=row.get("open_data_channel_type") or None,
            )
        except (KeyError, ValueError, TypeError):
            return None

    def _parse_chicago_row(self, row: dict) -> RawLead311 | None:
        """Parse um dict de dados Chicago (SoQL)"""
        try:
            created = row.get("created_date")
            created_at = datetime.fromisoformat(str(created).replace("Z", "+00:00")) if created else datetime.now()

            return RawLead311(
                external_id=str(row.get("sr_number")),
                address=f"{row.get('street_address') or ''}, Chicago, IL",
                city="Chicago",
                state="IL",
                zip_code=row.get("zip_code") or None,
                issue_description=row.get("sr_type") or "",
                created_at=created_at,
                lat=float(row["latitude"]) if row.get("latitude") is not None else None,
                lng=float(row["longitude"]) if row.get("longitude") is not None else None,
                issue_category=self._infer_category(row.get("sr_type") or ""),
                case_title=row.get("sr_type") or None,
                department=row.get("owner_department") or None,
                case_status=row.get("status") or None,
                ward=row.get("ward") or None,
                neighborhood=row.get("community_area") or None,
            )
        except (KeyError, ValueError, TypeError):
            return None

    # ---------- Framework nacional: scraper genérico multi-cidade ----------

    def _guess_columns(self, field_names: List[str]) -> dict:
        """Detecta heuristicamente as colunas relevantes em um dataset 311 de qualquer cidade."""
        fns = [f.lower() for f in (field_names or [])]
        _lower = " ".join(fns)

        def find(*cands):
            for f, fname in zip(fns, field_names or []):
                if f in cands:
                    return fname
            return None

        def find_prio(*ordered_cands):
            """Retorna o nome da coluna seguindo a ordem de preferência dos candidatos."""
            for cand in ordered_cands:
                for f, fname in zip(fns, field_names or []):
                    if f == cand:
                        return fname
            return None

        date_col = find(
            "created_date", "creation_date", "createdtime", "requested_datetime",
            "requested_date", "created", "date_entered", "open_date", "service_request_date",
            "inspection_date", "inspectiondate", "approved_date", "approveddate", "novissueddate",
        )
        desc_col = find(
            "complaint_type", "type_of_service_request", "service_request_type",
            "request_type", "issue_type", "category", "title", "type", "sr_type",
            "violation_type", "service_type", "novdescription", "nov_description", "description",
        )
        lat_col = find("latitude", "lat", "lat_address", "lat_location")
        lng_col = find("longitude", "lon", "lng", "long", "long_address")
        ext_col = find(
            "unique_key", "service_request_number", "service_request_id",
            "request_number", "case_number", "id", "sr_number", "violationid",
        )

        # endereço: várias cidades usam formatos diferentes
        addr_candidates = [
            "incident_address", "street_address", "address", "full_address",
            "street_name", "location_address", "open_data_channel", "housenumber",
        ]
        addr_col = None
        for f, fname in zip(fns, field_names or []):
            if f in addr_candidates:
                addr_col = fname
                break

        # cidade/estado (se existir) para montar o endereço
        city_col = find("city", "requested_zip_city", "municipality")
        zip_col = find("zip_code", "incident_zip", "zip", "postal_code")

        # Campos históricos (heurística genérica cobrindo NYC, Dallas, Chicago etc.)
        hist = {
            "case_title": find(
                "complaint_type", "service_request_type", "request_type",
                "case_title", "title", "issue_type", "category", "type_of_service_request",
            ),
            "subject": find("subject", "short_description", "subject_line"),
            "reason": find("reason", "request_reason", "problem"),
            "type": find("priority", "type", "subtype", "sub_type", "descriptor_2"),
            "queue": find("queue", "work_queue", "assignment_group"),
            "department": find_prio("agency_name", "owner_department", "department", "agency", "responsible_department"),
            "closure_reason": find("closure_reason", "close_reason", "resolution_note"),
            "case_status": find("status", "case_status", "service_request_status", "request_status"),
            "on_time": find("on_time", "on_finalize_ontime", "met_sla"),
            "sla_target_dt": find(
                "overall_service_request_due_date", "sla_target_dt", "due_date",
                "target_date", "est_resolution_date",
            ),
            "closed_dt": find("closed_date", "closed_dt", "close_date", "status_date"),
            "submitted_photo": find("submitted_photo", "photo_url", "before_photo"),
            "closed_photo": find("closed_photo", "after_photo", "closed_photo_url"),
            "source": find(
                "open_data_channel_type", "method_received_description", "source",
                "channel_type", "request_method",
            ),
            "neighborhood": find("borough", "neighborhood", "nbhd", "community", "community_area", "police_borough"),
            "ward": find("community_board", "city_council_district", "ward", "council_district", "district"),
            "precinct": find("police_precinct", "precinct", "police_district"),
            "descriptor": find("descriptor", "detail", "detailed_description", "subcategory", "sr_type", "service_request_type"),
            "resolution_description": find(
                "resolution_description", "outcome", "resolution", "final_description"
            ),
            "resolution_action_updated_date": find(
                "resolution_action_updated_date", "resolution_action", "resolution_date",
                "update_date",
            ),
        }

        return {
            "date": date_col,
            "desc": desc_col,
            "lat": lat_col,
            "lng": lng_col,
            "ext": ext_col,
            "addr": addr_col,
            "city": city_col,
            "zip": zip_col,
            "hist": hist,
            "_has_date": date_col is not None,
            "_has_desc": desc_col is not None,
        }

    async def fetch_from_dataset(
        self, domain: str, dataset_id: str, city: str, state: str,
        field_names: List[str], hours: int = 48, limit: int = 50000,
        keyword_filter: bool = True,
    ) -> List[RawLead311]:
        """Busca 311 genérico de qualquer cidade Socrata, detectando as colunas.

        keyword_filter=True  -> filtra por palavras-chave (scrape incremental).
        keyword_filter=False -> traz todos os registros da janela (usado no backfill).
        """
        cols = self._guess_columns(field_names)
        if not cols["_has_date"] or not cols["_has_desc"]:
            logger.warning(f"{city}: dataset sem colunas de data/descrição detectadas — pulando")
            return []

        # seleciona campos detectados (+ endereço + histórico)
        select_fields = [c for c in [cols["date"], cols["desc"], cols["lat"], cols["lng"], cols["ext"], cols["addr"], cols["zip"]] if c]
        for col in cols["hist"].values():
            if col and col not in select_fields:
                select_fields.append(col)
        if not select_fields:
            select_fields = ["*"]

        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d")

        # keyword filtering done in Python (post-fetch) to avoid SQL lower() issues
        where = f"{cols['date']} > '{since}'"

        rows = await self._fetch_soql(
            domain=domain,
            dataset=dataset_id,
            select=", ".join(select_fields),
            where=where,
            order=f"{cols['date']} DESC",
            limit=limit,
        )

        leads = []
        for row in rows:
            lead = self._parse_generic_row(row, cols, city, state)
            if not lead:
                continue
            if keyword_filter:
                # filtro de segurança client-side (caso o SQL não tenha pego tudo)
                desc = (lead.issue_description or "").lower()
                if not any(kw.lower() in desc for kw in self.keywords):
                    continue
            leads.append(lead)
        logger.info(f"{city} 311: {len(leads)} leads válidos")
        return leads

    def _infer_category(self, description: str, source_type: str = None) -> "IssueCategory":
        """Infere a categoria a partir das palavras-chave da descrição.

        Mapeia exclusivamente para as 16 categorias/ofícios da plataforma.
        Fallback: Obras & Permissões (Permit_Rejected) para fontes de obrigação
        legal (permit/violação/fiscalização); Structure para os demais."""
        desc = (description or "").lower()
        # Categorias específicas (devem vir ANTES das genéricas para não serem capturadas por palavras-chave amplas)
        if any(k in desc for k in ["heat", "hot water", "heating", "boiler", "no heat", "radiator", "no hot water"]):
            return IssueCategory.HEATING
        if any(k in desc for k in ["gas", "gas leak", "cooking gas", "gas odor", "gas smell"]):
            return IssueCategory.GAS
        if any(k in desc for k in ["electric", "electrical", "wiring", "outlet", "circuit", "panel", "short circuit"]):
            return IssueCategory.ELECTRICAL
        if any(k in desc for k in ["elevator", "lift"]):
            return IssueCategory.ELEVATOR
        if any(k in desc for k in ["rodent", "rat", "mice", "mouse", "vermin", "roach", "pest", "cockroach", "bed bug", "infestation", "pigeon"]):
            return IssueCategory.RODENT
        if any(k in desc for k in ["mold", "mildew", "fungus", "water damage"]):
            return IssueCategory.MOLD
        if any(k in desc for k in ["lead", "lead paint", "lead hazard"]):
            return IssueCategory.LEAD
        if any(k in desc for k in ["unsanitary", "sanitary", "filth", "sewage backup", "unsatisfactory living conditions", "hoarding", "sewage", "septic", "raw sewage", "bad odor", "foul odor", "squalid"]):
            return IssueCategory.UNSANITARY
        if any(k in desc for k in ["door", "window", "frame", "sash", "jamb", "broken window", "stuck window"]):
            return IssueCategory.DOOR_WINDOW
        if any(k in desc for k in ["debris", "garbage", "trash", "rubbish", "litter", "dumping", "junk", "dumpster", "bulk removal", "overflowing garbage"]):
            return IssueCategory.DEBRIS
        # Categorias genéricas (vêm depois)
        if any(k in desc for k in ["roof", "gutter", "shingle", "roof leak", "shed"]):
            return IssueCategory.ROOF
        if any(k in desc for k in ["plumb", "water", "leak", "pipe", "sewer", "drain", "backflow"]):
            return IssueCategory.PLUMBING
        if any(k in desc for k in ["paint", "plaster", "graffiti", "facade", "façade", "peeling"]):
            return IssueCategory.PAINT
        if any(k in desc for k in ["structur", "foundation", "wall", "collapse", "crack", "unsafe building", "sagging", "deterioration", "buckling", "leaning"]):
            return IssueCategory.STRUCTURE
        if any(k in desc for k in ["grass", "weed", "vegetation", "overgrown", "blight", "high weeds", "vacant lot", "tall grass", "brush", "excessive vegetation"]):
            return IssueCategory.GRASS
        if source_type in ("permit", "dob_violation", "tax_delinquency"):
            return IssueCategory.PERMIT_REJECTED  # Obras & Permissões
        return IssueCategory.STRUCTURE  # fallback conservador

    def _infer_urgency(self, description: str) -> UrgencyLevel:
        """Infere o nível de urgência a partir da descrição do chamado 311.

        HIGH: risco à habitabilidade/saúde/estrutura (sem aquecimento, elevador,
              gás, mofo, chumbo, esgoto, colapso estrutural, inundação/prevenção de incêndio).
        LOW:  manutenção rotineira (coleta perdida, lixo, iluminação pública, pichação).
        Padrão: MEDIUM.
        """
        desc = (description or "").lower()
        high_keywords = [
            "no heat", "heating", "boiler", "radiator",
            "elevator", "lift",
            "gas leak", "gas odor", "gas smell", "gas",
            "mold", "mildew",
            "lead", "lead paint", "lead hazard",
            "sewage", "sewer backup",
            "water main break", "water main leak", "burst pipe",
            "collapse", "collapsed", "unsafe building", "falling debris",
            "flood", "fire hazard", "electrical fire", "live wire",
        ]
        low_keywords = [
            "missed garbage", "missed trash", "missed recycling", "missed collection",
            "missed pickup", "bulk item", "leaf collection", "holiday tree",
            "graffiti", "street light", "pothole", "noise", "litter basket",
            "request for info", "information", "duplicate",
        ]
        if any(k in desc for k in high_keywords):
            return UrgencyLevel.HIGH
        if any(k in desc for k in low_keywords):
            return UrgencyLevel.LOW
        return UrgencyLevel.MEDIUM

    def _parse_generic_row(self, row: dict, cols: dict, city: str, state: str) -> RawLead311 | None:
        try:
            ext = str(row.get(cols["ext"]) or "") if cols["ext"] else ""
            if not ext:
                return None
            date_raw = row.get(cols["date"]) if cols["date"] else None
            if date_raw:
                try:
                    created_at = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00").replace("+00:00:00", "+00:00"))
                except ValueError:
                    created_at = datetime.now()
            else:
                created_at = datetime.now()

            addr = ""
            if cols["addr"]:
                addr = str(row.get(cols["addr"]) or "").strip()
            zipc = row.get(cols["zip"]) if cols["zip"] else None

            lat, lng = None, None
            if cols["lat"] and row.get(cols["lat"]) is not None:
                try:
                    lat_val = row[cols["lat"]]
                    if isinstance(lat_val, str) and lat_val.startswith("(") and "," in lat_val:
                        # Formato Dallas: "(lat,lon)"
                        parts = lat_val.strip("()").split(",")
                        lat = float(parts[0].strip())
                        lng = float(parts[1].strip())
                    else:
                        lat = float(lat_val)
                except (TypeError, ValueError):
                    lat = None
            if lng is None and cols["lng"] and row.get(cols["lng"]) is not None:
                try:
                    lng = float(row[cols["lng"]])
                except (TypeError, ValueError):
                    lng = None

            if not addr and lat and lng:
                addr = f"{lat},{lng}"

            full_addr = ""
            if addr:
                addr_up = addr.upper()
                if re.search(r"\b[A-Z]{2}\b[, ]*\d{5}", addr_up) or re.search(r",\s*[A-Z]{2}\s*$", addr_up):
                    full_addr = addr
                else:
                    full_addr = f"{addr}, {city}, {state}"
            else:
                full_addr = f"{city}, {state}"

            # Parse address components
            addr_components = self._parse_address_components(full_addr, city, state, str(zipc) if zipc else None)

            hist = cols.get("hist") or {}

            def _val(key, fallback_key=None):
                col = hist.get(key)
                if not col:
                    return None
                v = row.get(col)
                if v is None:
                    return None
                s = str(v).strip()
                return s or None

            # case_title: usa a coluna de descrição se não haver detecção própria
            case_title = _val("case_title") or (str(row.get(cols["desc"]) or "").strip() or None)

            return RawLead311(
                external_id=ext,
                address=full_addr,
                city=city,
                state=state,
                zip_code=str(zipc) if zipc else None,
                issue_description=str(row.get(cols["desc"]) or ""),
                created_at=created_at,
                lat=lat,
                lng=lng,
                issue_category=self._infer_category(str(row.get(cols["desc"]) or "")),
                case_title=case_title,
                subject=_val("subject"),
                reason=_val("reason"),
                type=_val("type"),
                queue=_val("queue"),
                department=_val("department"),
                closure_reason=_val("closure_reason") or _val("outcome"),
                case_status=_val("case_status"),
                on_time=_val("on_time"),
                sla_target_dt=_val("sla_target_dt"),
                closed_dt=_val("closed_dt"),
                submitted_photo=_val("submitted_photo"),
                closed_photo=_val("closed_photo"),
                source=_val("source"),
                neighborhood=_val("neighborhood"),
                ward=_val("ward"),
                precinct=_val("precinct"),
                descriptor=_val("descriptor"),
                resolution_description=_val("resolution_description") or _val("outcome"),
                resolution_action_updated_date=_val("resolution_action_updated_date") or _val("closed_dt"),
                # Address components
                address_street=addr_components.get("address_street"),
                address_city=addr_components.get("address_city"),
address_zip=addr_components.get("address_zip"),
            )
        except (KeyError, ValueError, TypeError):
            return None


    @staticmethod
    def _parse_address_components(full_address: str, city: str, state: str, zip_code: Optional[str] = None) -> dict:
        """
        Parse address string into components.
        Handles formats like:
        - "150 Washington St Dorchester MA 02121, Boston, MA"
        - "123 Main St, Boston, MA 02115"
        - "123 Main St, Boston, MA"
        """
        result = {
            "address_street": None,
            "address_city": None,
            "address_state": None,
            "address_zip": None,
        }

        if not full_address:
            return result

        # First, try to extract ZIP code if not provided
        zip_pattern = r'\b(\d{5}(?:-\d{4})?)\b'
        zip_match = re.search(zip_pattern, full_address)
        found_zip = zip_match.group(1) if zip_match else (zip_code or None)
        result["address_zip"] = found_zip

        # Remove ZIP from address for parsing
        addr_no_zip = re.sub(zip_pattern, '', full_address).strip()
        addr_upper = addr_no_zip.upper()

        # Try to find state abbreviation (2 letters) near the end
        state_pattern = r'\b([A-Z]{2})\b'
        state_matches = list(re.finditer(state_pattern, addr_upper))
        found_state = state.upper() if state else None

        if state_matches:
            # Take the last state-like match that's not the city abbreviation
            for match in reversed(state_matches):
                potential_state = match.group(1)
                # Skip if it's at the very beginning (likely part of street name)
                if match.start() > 5:
                    found_state = potential_state
                    break

        result["address_state"] = found_state

        # Try to parse street address
        # Remove state and zip from address for street parsing
        street_part = addr_no_zip
        if found_state:
            # Remove state abbreviation
            state_pattern_escaped = re.escape(found_state)
            street_part = re.sub(rf'\b{state_pattern_escaped}\b', '', street_part).strip()

        # Remove city from the end if present
        city_upper = city.upper() if city else None
        if city_upper and city_upper in street_part.upper():
            idx = street_part.upper().rfind(city_upper)
            street_part = street_part[:idx].strip()

        # Clean up trailing commas, spaces
        street_part = re.sub(r'[,\s]+$', '', street_part).strip()

        if street_part:
            result["address_street"] = street_part

        # Determine city - use provided city or try to extract
        if city:
            result["address_city"] = city
        elif street_part:
            # Try to extract city from remaining parts
            pass

        return result

# Instância global
socrata_scraper = Socrata311Scraper()
