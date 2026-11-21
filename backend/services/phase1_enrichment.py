"""Enriquecimento da Fase 1 (staging): dados reais, sem tocar na produção.

Fontes usadas (todas públicas, sem chave):

* chamados de habitação abertos (fila de pré-inspeção);
* violações de habitação com prazo legal;
* multas e audiências de aplicação (saldo em aberto);
* violações de construção de Chicago;
* valores de obra declarados em alvarás (NYC e Chicago);
* perfil do imóvel (PLUTO) por BBL.

Regras:
* Este módulo **não** corre no arranque nem no pipeline de produção. Só é
  chamado por `scripts/ingest_phase1_staging.py`, com guardas de ambiente.
* Nunca inventa valores: sem alvará, `job_value` fica nulo; sem multa real, os
  campos de multa ficam nulos. `value_source` diz sempre a base do valor.
* Nada do payload bruto é exposto ao cliente. `source_payload` continua interno.
* Deduplica por imóvel (`property_key`); o histórico de cada ocorrência vive em
  `history` e a ficha do imóvel em `property`.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from .db import get_connection
from .opportunity_workflow import make_property_key, opportunity_workflow
from .privacy import scrub
from .zip_lookup import resolve_chicago_zip

_USER_AGENT = "MagicLeadsPhase1/1.0 (staging enrichment)"
_TIMEOUT = 60

CHI_VIOLATIONS_WATERMARK = "chi_violations_open"


def _get_watermark(source: str) -> Optional[str]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT watermark FROM phase1_watermarks WHERE source = ?", (source,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    value = str(row["watermark"] or "").strip()
    return value or None


def _set_watermark(source: str, value: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO phase1_watermarks (source, watermark, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
              watermark = excluded.watermark,
              updated_at = excluded.updated_at
            """,
            (source, value, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

NYC = "data.cityofnewyork.us"
CHI = "data.cityofchicago.org"
DAL = "www.dallasopendata.com"
BOS = "data.boston.gov"

BOSTON_VIOLATIONS_RESOURCE = "800a2663-1d6a-46e7-9356-bedb70f5332c"
BOSTON_311_RESOURCE = "254adca6-64ab-4c5c-9fc0-a6da622be185"
BOSTON_PERMITS_RESOURCE = "6ddcd912-32a0-43df-9908-63574f8c7e77"
# Code Enforcement Violations: o unico dataset Boston com multa real (`value`).
BOSTON_CODE_ENFORCEMENT_RESOURCE = "90ed3816-5e70-443c-803d-9a71f44470be"

# Tipos de 311 de Dallas com ofício e imóvel privado identificáveis. Ficam
# de fora o balde genérico "Code Concern - CCS" (20k+, sem descrição/ofício) e
# as obras públicas (calçada, via, drenagem, água da cidade), que não são
# oportunidades de dono.
DALLAS_TRADE_LIKE = (
    "construction site complaint",
    "building permits violation",
    "historic district violation",
    "housing & neighborhood",
    "substandard",
    "high weeds",
    "junk vehicle",
    "rodent",
    "unsanitary",
    "sewer",
)

DATASETS = {
    "hpd_complaints": (NYC, "ygpa-z7cr"),
    "hpd_violations": (NYC, "wvxf-dwi5"),
    "ecb": (NYC, "6bgk-3dad"),
    "pluto": (NYC, "64uk-42ks"),
    "nyc_permits": (NYC, "rbx6-tga4"),
    "chi_violations": (CHI, "22u3-xenr"),
    "chi_permits": (CHI, "ydr8-5enu"),
    # 311 de Chicago: fonte de pre-inspecao (open_request), ja usada pelo
    # pipeline principal e agora tambem pela camada de oportunidades.
    "chi_311": (CHI, "v6vf-nfxy"),
    # Multas reais de Chicago: Ordinance Violations (`imposed_fine`) e
    # Vacant/Abandoned (`total_fines`/`current_amount_due`). O dataset
    # `22u3-xenr` (Building Violations) nao tem valor monetario.
    "chi_ordinance_fines": (CHI, "6br9-quuz"),
    "chi_vacant_fines": (CHI, "kc9i-wq85"),
    "dal_311": (DAL, "d7e7-envw"),
    "dal_permits": (DAL, "e7gq-4sah"),
}

# Palavra-chave -> categoria da plataforma. A ordem importa: as mais
# específicas entram primeiro para "heat/hot water" não cair em "water" e
# "elect eleva" cair em Elevator, não em Electrical.
_CATEGORY_RULES = [
    ("Heating", ("heat", "hot water", "boiler", "furnace", "steam", "radiator")),
    ("Elevator", ("elevator", "eleva", "lift")),
    ("Gas", ("gas leak", "gas piping", "gas")),
    (
        "Electrical",
        (
            "electric", "wiring", "wire", "smoke detector", "bell", "buzzer",
            "intercom", "power outage", "power failure", "light fixture",
            "lighting", "outlet", "circuit", "breaker panel",
        ),
    ),
    (
        "Roof",
        (
            "roof", "roofing", "waterproof", "chimney", "parapet", "skylight",
            "flashing", "gutter", "solar", "photovoltaic",
        ),
    ),
    (
        "Plumbing",
        (
            "plumb", "leak", "sewer", "drain", "pipe", "faucet", "toilet",
            "sink", "water",
        ),
    ),
    ("Mold", ("mold", "mould", "fungus", "moisture", "damp")),
    ("Lead", ("lead-based", "lead paint", "lead hazard", "lead")),
    ("Rodent", ("rodent", "rat", "roach", "mice", "mouse", "vermin", "pest")),
    ("Grass", ("grass", "weed", "weeds", "overgrown", "vegetation", "blight", "lawn")),
    ("Paint", ("paint", "plaster", "painting")),
    (
        "Structure",
        (
            "structur", "facade", "foundation", "sidewalk shed", "scaffold",
            "pedestrian protection", "construction", "new building",
            "demolition", "excavation", "retaining", "shoring", "underpinning",
            "beam", "column", "concrete", "masonry", "brick", "wall", "floor",
            "flooring", "ceiling", "stair", "porch", "fence", "fire escape",
            "balcony", "canopy", "shed", "hoist", "crane", "jobsite",
            "job site", "site safety", "netting", "curtain wall", "cornice",
            "sidewalk", "housing",
        ),
    ),
    ("Door_Window", ("window", "door", "frame", "glass")),
    ("Debris", ("debris", "garbage", "trash", "rubbish", "dumpster", "loose material", "junk", "dump")),
    ("Unsanitary", ("unsanitary", "dirty", "sanitation", "odor", "filth", "feces", "sewage")),
    (
        "Permit_Rejected",
        (
            "permit", "certificate of occupancy", "c of o", "resubmit",
            "follow plans", "approved plans", "stop work", "job filing",
            "certificate of correction", "historic",
        ),
    ),
]

# Termos curtos que exigem fronteira de palavra ("rat" não pode casar com
# "separate"; "gas" não pode casar com "gasket").
_WORD_BOUNDARY = {"rat", "gas", "mold", "mould", "lead", "pest", "weed", "lift"}

# Descrições administrativas/genéricas que não dão serviço a um prestador.
# Só são descartadas quando não há multa nem prazo associado.
_NON_ACTIONABLE = {
    "open",
    "closed",
    "n/a",
    "none",
    "arrange premise inspection",
    "owner or licensed contractor",
    "safe working conditions",
}


_SEVERITY_ORDER = {"routine": 0, "medium": 1, "high": 2, "critical": 3}

_BOROUGH_CODES = {
    "MANHATTAN": "1",
    "NEW YORK": "1",
    "BRONX": "2",
    "BROOKLYN": "3",
    "QUEENS": "4",
    "STATEN ISLAND": "5",
    "RICHMOND": "5",
}


def _get_json(url: str) -> list | dict:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "ignore"))


def socrata(name: str, params: dict) -> list:
    domain, dataset = DATASETS[name]
    url = f"https://{domain}/resource/{dataset}.json?" + urllib.parse.urlencode(params)
    data = _get_json(url)
    return data if isinstance(data, list) else []


def ckan_datastore(resource_id: str, params: dict) -> list:
    """Lê um recurso CKAN (Analyze Boston) com datastore ativo."""
    query = dict(params)
    query["resource_id"] = resource_id
    url = f"https://{BOS}/api/3/action/datastore_search?" + urllib.parse.urlencode(query)
    data = _get_json(url)
    if isinstance(data, dict):
        result = data.get("result") or {}
        return list(result.get("records") or [])
    return []


def _normalize_text(value: Optional[str]) -> str:
    return " ".join(str(value or "").lower().split())


def _match_keyword(keyword: str, text: str) -> bool:
    if keyword in _WORD_BOUNDARY:
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def match_category(*parts: Optional[str]) -> Optional[str]:
    """Categoria dos 16 ofícios, ou None quando o texto é genérico."""
    text = _normalize_text(" ".join(str(part or "") for part in parts))
    for category, keywords in _CATEGORY_RULES:
        if any(_match_keyword(keyword, text) for keyword in keywords):
            return category
    return None


def map_category(*parts: Optional[str]) -> str:
    # Nunca devolver "Unclassified": o fallback é um ofício válido e traduzido.
    # Sinais realmente vazios são descartados na ingestão.
    return match_category(*parts) or "Structure"


def source_kind_for_signal(signal: Optional[str]) -> tuple[str, str]:
    """Classificação única: o tipo da oportunidade segue o sinal, não o pipeline.

    `legal_obligation` é reativo (violação), `authorized_work` é obra (alvará)
    e `open_request` é preventivo. Qualquer outro valor cai em preventivo.
    """
    value = str(signal or "").strip().lower()
    if value == "legal_obligation":
        return "reactive", "violation"
    if value == "authorized_work":
        return "permit", "permit"
    return "preventive", "pre_inspection"


def is_actionable(description: Optional[str], history: Optional[list] = None) -> bool:
    texts = [description] + [
        entry.get("label") for entry in (history or []) if isinstance(entry, dict)
    ]
    for value in texts:
        normalized = _normalize_text(value)
        if len(normalized) < 4:
            continue
        if normalized not in _NON_ACTIONABLE:
            return True
    return False


def map_hpd_severity(value: Optional[str]) -> str:
    key = str(value or "").strip().upper()
    if key == "C":
        return "class_c"
    if key == "B":
        return "class_b"
    if key == "A":
        return "class_a"
    return "medium"


def map_ecb_severity(value: Optional[str]) -> str:
    key = re.sub(r"\D", "", str(value or ""))
    if key.startswith("1"):
        return "class_1"
    if key.startswith("2"):
        return "class_2"
    if key.startswith("3"):
        return "class_3"
    return "medium"


def max_severity(*values: Optional[str]) -> str:
    best = "routine"
    for value in values:
        key = str(value or "").strip().lower()
        if _SEVERITY_ORDER.get(key, -1) > _SEVERITY_ORDER.get(best, -1):
            best = key
    return best


def to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def to_iso_date(value) -> Optional[str]:
    """Aceita ISO, YYYYMMDD e epoch; devolve YYYY-MM-DD."""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def normalize_address(*parts: Optional[str]) -> str:
    raw = " ".join(str(part or "").upper() for part in parts)
    return re.sub(r"[^A-Z0-9 ]+", " ", raw).strip()


def _parse_us_date(value) -> Optional[str]:
    """Datas dos portais em MM/DD/YY (Dallas) ou ISO (Boston)."""
    text = str(value or "").strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return to_iso_date(text)


def _split_dallas_address(raw) -> tuple[str, Optional[str]]:
    text = " ".join(str(raw or "").split())
    match = re.match(r"^(.*?),\s*DALLAS,\s*TX,?\s*(\d{5})", text, re.IGNORECASE)
    if match:
        return normalize_address(match.group(1)), match.group(2)
    zip_match = re.search(r"\b(\d{5})\b", text)
    zip_code = zip_match.group(1) if zip_match else None
    address = re.sub(r",\s*DALLAS.*$", "", text, flags=re.IGNORECASE)
    return normalize_address(address), zip_code


def _dallas_trade_where() -> str:
    likes = " OR ".join(
        f"lower(service_request_type) LIKE '%{pattern}%'"
        for pattern in DALLAS_TRADE_LIKE
    )
    return (
        "status NOT IN ('Closed','Completed','Cancelled') "
        f"AND ({likes})"
    )


def _dallas_category(value: Optional[str]) -> str:
    text = _normalize_text(value)
    if any(key in text for key in ("food", "restaurant", "smoking", "unsanitary", "pool")):
        return "Unsanitary"
    if any(key in text for key in ("weed", "grass")):
        return "Grass"
    if any(key in text for key in ("dump", "debris", "junk")):
        return "Debris"
    if any(key in text for key in ("rodent", "rat", "mosquito", "pest")):
        return "Rodent"
    return map_category(value)


def _severity_from_text(value: Optional[str]) -> str:
    text = _normalize_text(value)
    if any(key in text for key in ("unsafe", "dangerous", "emergency", "collapse", "fire")):
        return "critical"
    if any(key in text for key in ("failure", "permit", "violation", "structur", "unsafe")):
        return "high"
    return "medium"


def bbl_from_boro_block_lot(boro: Optional[str], block, lot) -> Optional[str]:
    raw_boro = str(boro or "").strip().upper()
    code = raw_boro if raw_boro in {"1", "2", "3", "4", "5"} else _BOROUGH_CODES.get(raw_boro)
    if not code:
        return None
    block_text = re.sub(r"\D", "", str(block or ""))
    lot_text = re.sub(r"\D", "", str(lot or ""))
    if not block_text or not lot_text or int(lot_text) == 0:
        return None
    return f"{code}{block_text.zfill(5)}{lot_text.zfill(4)}"[-10:]


def source_payload(source: str, row: dict) -> dict:
    """Payload bruto da fonte, para auditoria de campos ignorados.

    Remove apenas as regioes calculadas do Socrata (`:@computed_region_*`),
    que sao ruido e nao fazem parte do registo original.
    """
    return {
        "source": source,
        "row": {
            key: value
            for key, value in (row or {}).items()
            if not str(key).startswith(":@")
        },
    }


def _trim(text: Optional[str], limit: int = 220) -> Optional[str]:
    value = " ".join(str(text or "").split())
    if not value:
        return None
    return value[:limit]


def _clean(text: Optional[str], limit: int = 220) -> Optional[str]:
    """Texto de sinal para o cliente: sem marcas de fonte/arquitetura."""
    return scrub(_trim(text, limit))


def _history_entry(kind: str, label: str, when: Optional[str], status: Optional[str] = None, amount: Optional[float] = None, entry_id: Optional[str] = None) -> dict:
    entry = {"kind": kind, "label": label, "date": when, "status": status}
    if entry_id:
        entry["id"] = entry_id
    if amount is not None:
        entry["amount"] = round(float(amount), 2)
    return entry


class Phase1EnrichmentService:
    """Junta as fontes por imóvel e grava no `opportunity_workflow`."""

    def __init__(self, today: Optional[date] = None):
        self.today = today or datetime.now(timezone.utc).date()

    # ------------------------------------------------------------------ fonte
    def fetch_hpd_complaints(self, limit: int = 20) -> list:
        if limit <= 0:
            return []
        since = (self.today - timedelta(days=30)).isoformat()
        rows = socrata(
            "hpd_complaints",
            {
                "$limit": max(1, int(limit)),
                "$order": "received_date DESC",
                "$where": f"problem_status = 'OPEN' AND received_date >= '{since}T00:00:00'",
            },
        )
        grouped: dict = {}
        for row in rows:
            key = make_property_key(bbl=row.get("bbl"), bin_value=row.get("bin"))
            if not key.startswith(("bbl:", "bin:")):
                key = make_property_key(address=f"{row.get('house_number')} {row.get('street_name')}", city="NYC", zip_code=row.get("post_code"))
            item = grouped.setdefault(
                key,
                {
                    "property_key": key,
                    "bin": str(row.get("bin") or "") or None,
                    "bbl": str(row.get("bbl") or "") or None,
                    "address": normalize_address(row.get("house_number"), row.get("street_name")) or "—",
                    "city": "NYC",
                    "state": "NY",
                    "zip_code": str(row.get("post_code") or "")[:5] or None,
                    "signal_type": "open_request",
                    "severity": "high" if str(row.get("type") or "").upper() == "EMERGENCY" else "medium",
                    "category": map_category(row.get("type"), row.get("major_category"), row.get("minor_category")),
                    "description": _clean(f"{row.get('major_category') or ''} — {row.get('minor_category') or ''}"),
                    "received_at": row.get("received_date"),
                    "history": [],
                    "tags": ["inspection_possible"],
                    "source_record_id": f"phase1-hpd-complaint-{key}",
                },
            )
            item.setdefault("source_payload", []).append(
                source_payload("hpd_complaints", row)
            )
            item["history"].append(
                _history_entry(
                    "complaint",
                    _clean(f"{row.get('major_category') or 'Complaint'} — {row.get('minor_category') or ''}", 120) or "Complaint",
                    to_iso_date(row.get("received_date")),
                    row.get("problem_status"),
                    None,
                    f"hpd-complaint-{row.get('problem_id')}",
                )
            )
        return list(grouped.values())

    def fetch_hpd_deadlines(self, limit: int = 20) -> list:
        if limit <= 0:
            return []
        rows = socrata(
            "hpd_violations",
            {
                "$limit": max(1, int(limit)),
                "$order": "newcorrectbydate ASC",
                "$where": (
                    "violationstatus = 'Open' AND newcorrectbydate IS NOT NULL "
                    f"AND newcorrectbydate >= '{self.today.isoformat()}T00:00:00'"
                ),
            },
        )
        grouped: dict = {}
        for row in rows:
            key = make_property_key(bbl=row.get("bbl"), bin_value=row.get("bin"))
            deadline = to_iso_date(row.get("newcorrectbydate") or row.get("originalcorrectbydate"))
            item = grouped.setdefault(
                key,
                {
                    "property_key": key,
                    "bin": str(row.get("bin") or "") or None,
                    "bbl": str(row.get("bbl") or "") or None,
                    "address": normalize_address(row.get("housenumber"), row.get("streetname")) or "—",
                    "city": "NYC",
                    "state": "NY",
                    "zip_code": str(row.get("zip") or "")[:5] or None,
                    "signal_type": "legal_obligation",
                    "severity": map_hpd_severity(row.get("class")),
                    "category": map_category(row.get("novdescription")),
                    "description": _clean(row.get("novdescription")),
                    "compliance_deadline": deadline,
                    "history": [],
                    "tags": ["inspection_possible"],
                    "source_record_id": f"phase1-hpd-violation-{key}",
                },
            )
            if deadline and (not item.get("compliance_deadline") or deadline < item["compliance_deadline"]):
                item["compliance_deadline"] = deadline
            item.setdefault("source_payload", []).append(
                source_payload("hpd_violations", row)
            )
            item["severity"] = max_severity(item.get("severity"), map_hpd_severity(row.get("class")))
            item["history"].append(
                _history_entry(
                    "violation",
                    _clean(row.get("novdescription"), 140) or f"Violation class {row.get('class') or '—'}",
                    to_iso_date(row.get("inspectiondate")),
                    row.get("currentstatus"),
                    None,
                    f"hpd-violation-{row.get('violationid')}",
                )
            )
        return list(grouped.values())

    def fetch_ecb(self, limit: int = 40) -> list:
        if limit <= 0:
            return []
        rows = socrata(
            "ecb",
            {
                "$limit": max(1, int(limit)),
                "$order": "issue_date DESC",
                "$where": "balance_due > 0",
            },
        )
        grouped: dict = {}
        for row in rows:
            bin_value = str(row.get("bin") or "").strip()
            bbl = bbl_from_boro_block_lot(row.get("boro"), row.get("block"), row.get("lot"))
            key = make_property_key(bbl=bbl, bin_value=bin_value)
            if not key.startswith(("bbl:", "bin:")):
                continue
            balance = to_float(row.get("balance_due")) or 0.0
            imposed = to_float(row.get("penality_imposed")) or 0.0
            paid = to_float(row.get("amount_paid")) or 0.0
            hearing = to_iso_date(row.get("hearing_date"))
            item = grouped.setdefault(
                key,
                {
                    "property_key": key,
                    "bin": bin_value or None,
                    "bbl": bbl,
                    "city": "NYC",
                    "state": "NY",
                    "signal_type": "legal_obligation",
                    "category": map_category(row.get("violation_description"), row.get("violation_type")),
                    "description": _clean(row.get("violation_description")),
                    "fine_balance": 0.0,
                    "fine_imposed": 0.0,
                    "fine_paid": 0.0,
                    "hearing_date": None,
                    "hearing_status": None,
                    "severity": map_ecb_severity(row.get("severity")),
                    "history": [],
                    "tags": ["fine_active"],
                    "source_record_id": f"phase1-ecb-{key}",
                },
            )
            item["fine_balance"] += balance
            item["fine_imposed"] += imposed
            item["fine_paid"] += paid
            item["severity"] = max_severity(item.get("severity"), map_ecb_severity(row.get("severity")))
            if hearing and (not item.get("hearing_date") or hearing < item["hearing_date"]):
                item["hearing_date"] = hearing
            item["hearing_status"] = row.get("hearing_status") or item.get("hearing_status")
            item.setdefault("source_payload", []).append(
                source_payload("ecb", row)
            )
            item["history"].append(
                _history_entry(
                    "fine",
                    _clean(row.get("violation_description"), 160) or "Fine issued",
                    to_iso_date(row.get("issue_date")),
                    row.get("hearing_status"),
                    balance,
                    f"ecb-{row.get('ecb_violation_number')}",
                )
            )
        return list(grouped.values())

    def fetch_pluto(self, bbls: Iterable[Optional[str]]) -> dict:
        clean = sorted({re.sub(r"\D", "", str(bbl or "")) for bbl in bbls if bbl})
        clean = [bbl for bbl in clean if len(bbl) >= 9][:40]
        if not clean:
            return {}
        quoted = ",".join(f"'{bbl[-10:]}'" for bbl in clean)
        rows = socrata(
            "pluto",
            {
                "$limit": len(clean),
                "$where": f"bbl IN ({quoted})",
            },
        )
        out = {}
        for row in rows:
            raw_bbl = str(row.get("bbl") or "")
            try:
                digits = str(int(float(raw_bbl)))
            except (TypeError, ValueError):
                digits = re.sub(r"\D", "", raw_bbl)
            if not digits:
                continue
            out[f"bbl:{digits[-10:]}"] = {
                "address": _trim(row.get("address"), 120),
                "zip_code": str(row.get("zipcode") or "")[:5] or None,
                "owner_name": _trim(row.get("ownername"), 120),
                "owner_type": _trim(row.get("ownertype"), 60),
                "building_class": _trim(row.get("bldgclass"), 20),
                "units_residential": row.get("unitsres"),
                "units_total": row.get("unitstotal"),
                "year_built": row.get("yearbuilt"),
                "floors": row.get("numfloors"),
                "lot_area": row.get("lotarea"),
                "building_area": row.get("bldgarea"),
                "assessed_total": row.get("assesstot"),
                "assessed_land": row.get("assessland"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
            }
        return out

    def fetch_nyc_permit_values(self, bins: Iterable[Optional[str]], limit: int = 40) -> dict:
        clean = sorted({str(bin_value) for bin_value in bins if bin_value})[:40]
        if not clean:
            return {}
        quoted = ",".join(f"'{bin_value}'" for bin_value in clean)
        rows = socrata(
            "nyc_permits",
            {
                "$limit": max(1, int(limit)),
                "$order": "issued_date DESC",
                "$where": (
                    f"bin IN ({quoted}) AND estimated_job_costs IS NOT NULL "
                    "AND estimated_job_costs != '0' "
                    f"AND issued_date >= '{(self.today - timedelta(days=3 * 365)).isoformat()}T00:00:00'"
                ),
            },
        )
        out: dict = {}
        for row in rows:
            bin_value = str(row.get("bin") or "").strip()
            value = to_float(row.get("estimated_job_costs"))
            if not bin_value or not value or value <= 0:
                continue
            current = out.get(bin_value)
            if current is None or value > (current.get("job_value") or 0):
                out[bin_value] = {
                    "job_value": value,
                    "value_source": "permit",
                    "owner_name": _trim(row.get("owner_name") or row.get("owner_business_name"), 120),
                    "history": _history_entry(
                        "permit",
                        _clean(row.get("job_description"), 160) or "Approved work",
                        to_iso_date(row.get("issued_date")),
                        row.get("permit_status"),
                        value,
                        f"nyc-permit-{row.get('job_filing_number')}-{row.get('work_permit')}",
                    ),
                }
        return out

    def fetch_chicago_violations(self, limit: int = 20) -> list:
        if limit <= 0:
            return []
        budget = max(1, int(limit))
        watermark = _get_watermark(CHI_VIOLATIONS_WATERMARK)
        if not watermark:
            watermark = (self.today - timedelta(days=90)).isoformat()
        page_size = min(1000, budget)
        grouped: dict = {}
        offset = 0
        max_seen = watermark
        for _ in range(20):
            rows = socrata(
                "chi_violations",
                {
                    "$limit": min(page_size, max(1, budget - len(grouped))),
                    "$offset": offset,
                    "$order": "coalesce(violation_last_modified_date, violation_date) ASC",
                    "$where": (
                        "violation_status = 'OPEN' "
                        "AND coalesce(violation_last_modified_date, violation_date) "
                        f"> '{watermark}'"
                    ),
                },
            )
            if not rows:
                break
            for row in rows:
                address = normalize_address(row.get("address"))
                if not address:
                    continue
                zip_code, zip_source = resolve_chicago_zip(
                    address=address,
                    lat=row.get("latitude"),
                    lng=row.get("longitude"),
                )
                key = make_property_key(address=address, city="Chicago", zip_code=None)
                item = grouped.setdefault(
                    key,
                    {
                        "property_key": key,
                        "address": address,
                        "city": "Chicago",
                        "state": "IL",
                        "zip_code": zip_code,
                        "zip_source": zip_source,
                        "signal_type": "legal_obligation",
                        "severity": "critical"
                        if str(row.get("inspection_status") or "").upper() == "FAILED"
                        else "high",
                        "category": map_category(
                            row.get("violation_description"), row.get("violation_code")
                        ),
                        "description": _clean(row.get("violation_description")),
                        "received_at": row.get("violation_date"),
                        "history": [],
                        "tags": ["inspection_possible"],
                        "source_record_id": "phase1-chi-violation-"
                        + hashlib.sha1(address.encode("utf-8")).hexdigest()[:16],
                    },
                )
                if zip_code and not item.get("zip_code"):
                    item["zip_code"] = zip_code
                    item["zip_source"] = zip_source
                item.setdefault("source_payload", []).append(
                    source_payload("chi_violations", row)
                )
                item["history"].append(
                    _history_entry(
                        "violation",
                        _clean(row.get("violation_description"), 140) or "Violation",
                        to_iso_date(row.get("violation_date")),
                        row.get("violation_status"),
                        None,
                        f"chi-violation-{row.get('id')}",
                    )
                )
                seen = str(
                    row.get("violation_last_modified_date")
                    or row.get("violation_date")
                    or ""
                ).strip()
                if seen and seen > max_seen:
                    max_seen = seen
            offset += len(rows)
            if len(rows) < min(page_size, budget):
                break
            if len(grouped) >= budget:
                break
        if max_seen > watermark:
            _set_watermark(CHI_VIOLATIONS_WATERMARK, max_seen)
        return list(grouped.values())

    def fetch_chicago_permits(self, limit: int = 0, days: int = 30) -> list:
        """Alvarás de Chicago como oportunidades de obra autorizada."""
        if limit <= 0:
            return []
        rows = socrata(
            "chi_permits",
            {"$limit": max(1, int(limit)), "$order": ":id DESC"},
        )
        cutoff = (self.today - timedelta(days=max(1, int(days)))).isoformat()
        grouped: dict = {}
        for row in rows:
            issued = to_iso_date(row.get("issue_date"))
            if not issued or issued < cutoff:
                continue
            street = " ".join(
                part
                for part in (
                    str(row.get("street_number") or "").strip(),
                    str(row.get("street_direction") or "").strip(),
                    str(row.get("street_name") or "").strip(),
                )
                if part
            )
            address = normalize_address(street)
            if not address:
                continue
            permit_type = _clean(row.get("permit_type"))
            description = _clean(row.get("work_description")) or permit_type or "Approved work"
            zip_code, zip_source = resolve_chicago_zip(
                address=address,
                lat=row.get("latitude"),
                lng=row.get("longitude"),
                contact_zip=row.get("contact_1_zipcode"),
            )
            key = make_property_key(address=address, city="Chicago", zip_code=None)
            item = grouped.get(key)
            if item is None:
                item = {
                    "property_key": key,
                    "address": address,
                    "city": "Chicago",
                    "state": "IL",
                    "zip_code": zip_code,
                    "zip_source": zip_source,
                    "signal_type": "authorized_work",
                    "severity": "medium",
                    "category": match_category(description)
                    or match_category(permit_type)
                    or "Structure",
                    "description": description,
                    "received_at": issued,
                    "job_value": to_float(row.get("reported_cost")),
                    "value_source": "permit",
                    "history": [],
                    "tags": ["inspection_possible"],
                    "source_record_id": "phase1-chi-permit-"
                    + hashlib.sha1(
                        str(row.get("id") or row.get("permit_") or address).encode("utf-8")
                    ).hexdigest()[:16],
                }
                grouped[key] = item
            elif zip_code and not item.get("zip_code"):
                item["zip_code"] = zip_code
                item["zip_source"] = zip_source
            item.setdefault("source_payload", []).append(
                source_payload("chi_permits", row)
            )
            value = to_float(row.get("reported_cost"))
            if value and (not item.get("job_value") or value > item["job_value"]):
                item["job_value"] = value
            item["history"].append(
                _history_entry(
                    "permit",
                    description,
                    issued,
                    row.get("permit_status") or "Issued",
                    value,
                    f"chi-permit-{row.get('id')}",
                )
            )
        return list(grouped.values())

    def fetch_chicago_permit_values(self, limit: int = 500) -> dict:
        if limit <= 0:
            return {}
        rows = socrata(
            "chi_permits",
            {
                "$limit": max(1, int(limit)),
                "$order": "issue_date DESC",
                "$where": "reported_cost > 0",
            },
        )
        out: dict = {}
        for row in rows:
            address = normalize_address(
                row.get("street_number"),
                row.get("street_direction"),
                row.get("street_name"),
                row.get("street_type"),
            )
            value = to_float(row.get("reported_cost"))
            if not address or not value or value <= 0:
                continue
            key = make_property_key(address=address, city="Chicago", zip_code=None)
            current = out.get(key)
            if current is None or value > (current.get("job_value") or 0):
                out[key] = {
                    "job_value": value,
                    "value_source": "permit",
                    "owner_name": _trim(row.get("contact_1_name"), 120),
                    "history": _history_entry(
                        "permit",
                        _clean(row.get("work_description"), 160) or "Approved work",
                        to_iso_date(row.get("issue_date")),
                        row.get("permit_status"),
                        value,
                        f"chi-permit-{row.get('id')}",
                    ),
                }
        return out

    def fetch_chicago_311(self, limit: int = 0) -> list:
        """311 aberto de Chicago (`v6vf-nfxy`) como pre-inspecao real."""
        if limit <= 0:
            return []
        since = (self.today - timedelta(days=30)).isoformat()
        rows = socrata(
            "chi_311",
            {
                "$limit": max(1, int(limit)),
                "$order": "created_date DESC",
                "$where": (
                    "status = 'Open' "
                    f"AND created_date >= '{since}T00:00:00'"
                ),
            },
        )
        grouped: dict = {}
        for row in rows:
            address = normalize_address(row.get("street_address"))
            if len(address) < 8:
                continue
            category = match_category(row.get("sr_type"))
            if not category:
                continue
            zip_code = str(row.get("zip_code") or "").strip()[:5] or None
            key = make_property_key(address=address, city="Chicago", zip_code=zip_code)
            when = row.get("created_date")
            item = grouped.get(key)
            if item is None:
                item = {
                    "property_key": key,
                    "address": address,
                    "city": "Chicago",
                    "state": "IL",
                    "zip_code": zip_code,
                    "zip_source": "311",
                    "signal_type": "open_request",
                    "severity": _severity_from_text(row.get("sr_type")),
                    "category": category,
                    "description": _clean(row.get("sr_type")) or "311 request",
                    "received_at": when,
                    "compliance_deadline": None,
                    "history": [],
                    "tags": ["inspection_possible"],
                    "source_record_id": "phase1-chi-311-"
                    + hashlib.sha1(
                        f"{address}|{row.get('sr_number')}".encode("utf-8")
                    ).hexdigest()[:16],
                    "source_payload": [],
                }
                grouped[key] = item
            item["source_payload"].append(source_payload("chi_311", row))
            item["history"].append(
                _history_entry(
                    "complaint",
                    _clean(row.get("sr_type"), 140) or "311",
                    to_iso_date(when),
                    row.get("status"),
                    None,
                    f"chi-311-{row.get('sr_number')}",
                )
            )
        return list(grouped.values())

    def fetch_chicago_fines(self, limit: int = 0) -> list:
        """Multas reais de Chicago: Ordinance Violations + Vacant/Abandoned.

        `hearing_date` e' uma audiencia, nao um prazo de correcao: fica no
        campo `hearing_date` e `compliance_deadline` permanece None.
        """
        if limit <= 0:
            return []
        grouped: dict = {}
        # P1.1: a mesma notificacao (`nov_number`/`violation_number`) pode
        # aparecer em varias linhas (varios codigos) ou nos dois datasets.
        # Conta-se uma vez por imovel; sem chave, mantem-se a linha unica.
        seen_fine_keys: set[tuple[str, str]] = set()
        ord_limit = max(1, int(limit) // 2)
        vac_limit = max(1, int(limit) - ord_limit)

        def merge_fine_item(
            row: dict,
            source: str,
            address: str,
            when,
            fine_imposed,
            fine_paid,
            fine_balance,
            hearing,
            description,
            category,
            dedupe_key=None,
        ):
            if not address or len(address) < 8:
                return
            key = make_property_key(address=address, city="Chicago", zip_code=None)
            normalized_key = str(dedupe_key or "").strip().upper()
            if normalized_key:
                token = (key, normalized_key)
                if token in seen_fine_keys:
                    return
                seen_fine_keys.add(token)
            item = grouped.get(key)
            if item is None:
                zip_code, zip_source = resolve_chicago_zip(
                    address=address,
                    lat=row.get("latitude"),
                    lng=row.get("longitude"),
                )
                item = {
                    "property_key": key,
                    "address": address,
                    "city": "Chicago",
                    "state": "IL",
                    "zip_code": zip_code,
                    "zip_source": zip_source,
                    "signal_type": "legal_obligation",
                    "severity": "high",
                    "category": category,
                    "description": description,
                    "received_at": when,
                    "compliance_deadline": None,
                    "hearing_date": hearing,
                    "fine_imposed": 0.0,
                    "fine_paid": 0.0,
                    "fine_balance": 0.0,
                    "history": [],
                    "tags": ["fine_active", "inspection_possible"],
                    "source_record_id": "phase1-chi-fines-"
                    + hashlib.sha1(address.encode("utf-8")).hexdigest()[:16],
                    "source_payload": [],
                }
                grouped[key] = item
            item["fine_imposed"] += float(fine_imposed or 0)
            item["fine_paid"] += float(fine_paid or 0)
            item["fine_balance"] += max(0.0, float(fine_balance or 0))
            if hearing and (
                not item.get("hearing_date") or hearing < item["hearing_date"]
            ):
                item["hearing_date"] = hearing
            item["source_payload"].append(source_payload(source, row))
            item["history"].append(
                _history_entry(
                    "violation",
                    _clean(description, 140) or "Fine",
                    to_iso_date(when),
                    "Open",
                    fine_imposed,
                    f"{source}-{row.get('id') or row.get('violation_number') or row.get('nov_number')}",
                )
            )

        for row in socrata(
            "chi_ordinance_fines",
            {
                "$limit": ord_limit,
                "$order": "last_modified_date DESC",
                "$where": "imposed_fine > 0",
            },
        ):
            merge_fine_item(
                row=row,
                source="chi_ordinance_fines",
                address=normalize_address(row.get("address")),
                when=to_iso_date(row.get("violation_date")),
                fine_imposed=to_float(row.get("imposed_fine")),
                fine_paid=0.0,
                fine_balance=to_float(row.get("imposed_fine")),
                hearing=to_iso_date(row.get("hearing_date")),
                description=_clean(row.get("violation_description")),
                category=map_category(row.get("violation_description")),
                dedupe_key=row.get("nov_number") or row.get("id"),
            )

        for row in socrata(
            "chi_vacant_fines",
            {
                "$limit": vac_limit,
                "$order": "last_hearing_date DESC",
                "$where": "total_fines > 0 OR current_amount_due > 0",
            },
        ):
            total = to_float(row.get("total_fines")) or 0.0
            due = to_float(row.get("current_amount_due")) or 0.0
            paid = to_float(row.get("total_paid")) or 0.0
            if total <= 0 and due <= 0:
                continue
            merge_fine_item(
                row=row,
                source="chi_vacant_fines",
                address=normalize_address(row.get("property_address")),
                when=to_iso_date(row.get("issued_date") or row.get("last_hearing_date")),
                fine_imposed=total,
                fine_paid=paid,
                fine_balance=max(0.0, due),
                hearing=to_iso_date(row.get("last_hearing_date")),
                description=_clean(row.get("violation_type")),
                category=map_category(row.get("violation_type")),
                dedupe_key=(
                    row.get("violation_number")
                    or row.get("docket_number")
                    or row.get("id")
                ),
            )
        return list(grouped.values())

    def fetch_boston_code_enforcement(self, limit: int = 0) -> list:
        """Code Enforcement Violations de Boston: `value` e' a multa real."""
        if limit <= 0:
            return []
        rows = ckan_datastore(
            BOSTON_CODE_ENFORCEMENT_RESOURCE,
            {
                "limit": max(1, int(limit)),
                "sort": "status_dttm DESC",
                "filters": json.dumps({"status": "Open"}),
            },
        )
        grouped: dict = {}
        seen_cases: set[tuple[str, str]] = set()
        for row in rows:
            address = normalize_address(
                row.get("violation_stno"),
                row.get("violation_street"),
                row.get("violation_suffix"),
            )
            value = to_float(row.get("value"))
            if len(address) < 8 or not value or value <= 0:
                continue
            zip_code = str(row.get("violation_zip") or "").strip()[:5] or None
            key = make_property_key(address=address, city="Boston", zip_code=zip_code)
            case_key = str(
                row.get("case_no") or row.get("ticket_no") or ""
            ).strip().upper()
            if case_key:
                token = (key, case_key)
                if token in seen_cases:
                    continue
                seen_cases.add(token)
            when = to_iso_date(row.get("status_dttm"))
            item = grouped.get(key)
            if item is None:
                item = {
                    "property_key": key,
                    "address": address,
                    "city": "Boston",
                    "state": "MA",
                    "zip_code": zip_code,
                    "signal_type": "legal_obligation",
                    "severity": _severity_from_text(row.get("description")),
                    "category": map_category(row.get("description"), row.get("code")),
                    "description": _clean(row.get("description")) or "Code enforcement",
                    "received_at": when,
                    "compliance_deadline": None,
                    "hearing_date": None,
                    "fine_imposed": 0.0,
                    "fine_paid": 0.0,
                    "fine_balance": 0.0,
                    "history": [],
                    "tags": ["fine_active", "inspection_possible"],
                    "source_record_id": "phase1-bos-cev-"
                    + hashlib.sha1(address.encode("utf-8")).hexdigest()[:16],
                    "source_payload": [],
                }
                grouped[key] = item
            item["fine_imposed"] += value
            item["fine_balance"] += value
            item["source_payload"].append(source_payload("bos_code_enforcement", row))
            item["history"].append(
                _history_entry(
                    "violation",
                    _clean(row.get("description"), 140) or "Code enforcement",
                    when,
                    row.get("status"),
                    value,
                    f"bos-cev-{row.get('case_no')}",
                )
            )
        return list(grouped.values())

    # ------------------------------------------------------------- composição
    # ------------------------------------------------- Boston / Dallas
    def fetch_boston_violations(self, limit: int = 200) -> list:
        """ISD Building & Property Violations (Analyze Boston CKAN)."""
        if limit <= 0:
            return []
        rows = ckan_datastore(
            BOSTON_VIOLATIONS_RESOURCE,
            {
                "limit": max(1, int(limit)),
                "sort": "status_dttm DESC",
                "filters": json.dumps({"status": "Open"}),
            },
        )
        grouped: dict = {}
        for row in rows:
            address = normalize_address(
                row.get("violation_stno"),
                row.get("violation_street"),
                row.get("violation_suffix"),
            )
            if len(address) < 8:
                continue
            zip_code = str(row.get("violation_zip") or "").strip()[:5] or None
            key = make_property_key(address=address, city="Boston", zip_code=zip_code)
            description = _clean(row.get("description")) or "Building violation"
            status = row.get("status")
            when = to_iso_date(row.get("status_dttm"))
            item = grouped.setdefault(
                key,
                {
                    "property_key": key,
                    "address": address,
                    "city": "Boston",
                    "state": "MA",
                    "zip_code": zip_code,
                    "signal_type": "open_request",
                    "severity": _severity_from_text(description),
                    "category": map_category(description, row.get("code")),
                    "description": description,
                    "received_at": when,
                    "compliance_deadline": None,
                    "history": [],
                    "tags": ["inspection_possible"],
                    "source_record_id": "phase1-bos-violation-"
                    + hashlib.sha1(address.encode("utf-8")).hexdigest()[:16],
                },
            )
            item.setdefault("source_payload", []).append(
                source_payload("bos_violations", row)
            )
            item["history"].append(
                _history_entry(
                    "violation",
                    description,
                    when,
                    status,
                    None,
                    f"bos-violation-{row.get('case_no')}",
                )
            )
        return list(grouped.values())

    def fetch_boston_311(self, limit: int = 200) -> list:
        """311 Service Requests - NEW SYSTEM (Analyze Boston CKAN)."""
        if limit <= 0:
            return []
        rows = ckan_datastore(
            BOSTON_311_RESOURCE,
            {"limit": max(1, int(limit)), "sort": "open_date DESC"},
        )
        closed = {"closed", "resolved", "completed", "cancelled", "canceled"}
        grouped: dict = {}
        for row in rows:
            status = str(row.get("case_status") or "")
            if status.strip().lower() in closed:
                continue
            description = _clean(row.get("case_topic") or row.get("service_name"))
            if not description:
                continue
            category = match_category(description)
            if not category:
                continue
            raw_address = str(row.get("full_address") or "")
            street = raw_address.split(",")[0]
            address = normalize_address(street)
            if len(address) < 8:
                continue
            raw_zip = str(row.get("zip_code") or "").strip()
            zip_code = raw_zip.zfill(5) if raw_zip.isdigit() else None
            key = make_property_key(address=address, city="Boston", zip_code=zip_code)
            when = to_iso_date(row.get("open_date"))
            deadline = to_iso_date(row.get("target_close_date"))
            item = grouped.setdefault(
                key,
                {
                    "property_key": key,
                    "address": address,
                    "city": "Boston",
                    "state": "MA",
                    "zip_code": zip_code,
                    "signal_type": "open_request",
                    "severity": _severity_from_text(description),
                    "category": category,
                    "description": description,
                    "received_at": when,
                    "compliance_deadline": deadline,
                    "history": [],
                    "tags": ["inspection_possible"],
                    "source_record_id": "phase1-bos-311-"
                    + hashlib.sha1(address.encode("utf-8")).hexdigest()[:16],
                },
            )
            item.setdefault("source_payload", []).append(
                source_payload("bos_311", row)
            )
            item["history"].append(
                _history_entry(
                    "complaint",
                    description,
                    when,
                    status,
                    None,
                    f"bos-311-{row.get('case_id')}",
                )
            )
        return list(grouped.values())

    def fetch_boston_permits(self, limit: int = 300, days: int = 30) -> list:
        """Approved Building Permits dos últimos N dias (Analyze Boston CKAN)."""
        if limit <= 0:
            return []
        rows = ckan_datastore(
            BOSTON_PERMITS_RESOURCE,
            {"limit": max(1, int(limit)), "sort": "issued_date DESC"},
        )
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=max(1, int(days)))).isoformat()
        grouped: dict = {}
        for row in rows:
            issued = to_iso_date(row.get("issued_date"))
            if not issued or issued < cutoff:
                continue
            address = normalize_address(row.get("address"))
            if len(address) < 8:
                continue
            zip_code = str(row.get("zip") or "").strip()[:5] or None
            key = make_property_key(address=address, city="Boston", zip_code=zip_code)
            description = _clean(
                row.get("description") or row.get("permittypedescr") or row.get("worktype")
            ) or "Approved work"
            value = to_float(row.get("declared_valuation"))
            item = grouped.setdefault(
                key,
                {
                    "property_key": key,
                    "address": address,
                    "city": "Boston",
                    "state": "MA",
                    "zip_code": zip_code,
                    "signal_type": "authorized_work",
                    "severity": "medium",
                    "category": match_category(description)
                    or match_category(row.get("worktype"), row.get("permittypedescr"))
                    or "Structure",
                    "description": description,
                    "received_at": issued,
                    "job_value": value,
                    "value_source": "permit" if value else None,
                    "history": [],
                    "tags": ["inspection_possible"],
                    "source_record_id": "phase1-bos-permit-"
                    + hashlib.sha1(address.encode("utf-8")).hexdigest()[:16],
                },
            )
            item.setdefault("source_payload", []).append(
                source_payload("bos_permits", row)
            )
            if value and (not item.get("job_value") or value > item["job_value"]):
                item["job_value"] = value
                item["value_source"] = "permit"
            item["history"].append(
                _history_entry(
                    "permit",
                    description,
                    issued,
                    row.get("status"),
                    value,
                    f"bos-permit-{row.get('permitnumber')}",
                )
            )
        return list(grouped.values())

    def fetch_dallas_code(self, limit: int = 300) -> list:
        """Code Compliance aberto (Dallas 311, Socrata d7e7-envw)."""
        if limit <= 0:
            return []
        rows = socrata(
            "dal_311",
            {
                "$limit": max(1, int(limit)),
                "$order": "created_date DESC",
                "$where": "department = 'Code Compliance' AND "
                + _dallas_trade_where(),
            },
        )
        return self._dallas_items(rows, require_trade=True)

    def fetch_dallas_311(self, limit: int = 200) -> list:
        """311 aberto com ofício identificável (Dallas, Socrata d7e7-envw)."""
        if limit <= 0:
            return []
        rows = socrata(
            "dal_311",
            {
                "$limit": max(1, int(limit)),
                "$order": "created_date DESC",
                "$where": _dallas_trade_where(),
            },
        )
        return self._dallas_items(rows, require_trade=True)

    def _dallas_items(self, rows: Iterable[dict], require_trade: bool = False) -> list:
        grouped: dict = {}
        for row in rows:
            address, zip_code = _split_dallas_address(row.get("address"))
            if len(address) < 8:
                continue
            raw_type = str(row.get("service_request_type") or "").strip()
            if require_trade and match_category(raw_type) is None:
                continue
            description = _clean(raw_type.replace(" - CCS", "")) or "Code concern"
            key = make_property_key(address=address, city="Dallas", zip_code=zip_code)
            when = to_iso_date(row.get("created_date"))
            deadline = to_iso_date(row.get("overall_service_request_due_date"))
            status = row.get("status")
            item = grouped.setdefault(
                key,
                {
                    "property_key": key,
                    "address": address,
                    "city": "Dallas",
                    "state": "TX",
                    "zip_code": zip_code,
                    "signal_type": "open_request",
                    "severity": _severity_from_text(description),
                    "category": _dallas_category(raw_type),
                    "description": description,
                    "received_at": when,
                    "compliance_deadline": deadline,
                    "history": [],
                    "tags": ["inspection_possible"],
                    "source_record_id": "phase1-dal-311-"
                    + hashlib.sha1(address.encode("utf-8")).hexdigest()[:16],
                },
            )
            item.setdefault("source_payload", []).append(
                source_payload("dal_311", row)
            )
            item["history"].append(
                _history_entry(
                    "complaint",
                    description,
                    when,
                    status,
                    None,
                    f"dal-311-{row.get('service_request_number')}",
                )
            )
        return list(grouped.values())

    def fetch_dallas_permits(self, limit: int = 300, days: int = 30) -> list:
        """Building Permits dos últimos N dias (Dallas, Socrata e7gq-4sah)."""
        if limit <= 0:
            return []
        rows = socrata(
            "dal_permits",
            {"$limit": max(1, int(limit)), "$order": ":id DESC"},
        )
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=max(1, int(days)))).isoformat()
        grouped: dict = {}
        for row in rows:
            issued = _parse_us_date(row.get("issued_date"))
            if not issued or issued < cutoff:
                continue
            address = normalize_address(row.get("street_address"))
            if len(address) < 8:
                continue
            zip_code = str(row.get("zip_code") or "").strip()[:5] or None
            key = make_property_key(address=address, city="Dallas", zip_code=zip_code)
            description = _clean(row.get("work_description") or row.get("permit_type")) or "Approved work"
            value = to_float(row.get("value"))
            item = grouped.setdefault(
                key,
                {
                    "property_key": key,
                    "address": address,
                    "city": "Dallas",
                    "state": "TX",
                    "zip_code": zip_code,
                    "signal_type": "authorized_work",
                    "severity": "medium",
                    "category": match_category(description)
                    or match_category(row.get("permit_type"))
                    or "Structure",
                    "description": description,
                    "received_at": issued,
                    "job_value": value,
                    "value_source": "permit" if value else None,
                    "history": [],
                    "tags": ["inspection_possible"],
                    "source_record_id": "phase1-dal-permit-"
                    + hashlib.sha1(address.encode("utf-8")).hexdigest()[:16],
                },
            )
            item.setdefault("source_payload", []).append(
                source_payload("dal_permits", row)
            )
            if value and (not item.get("job_value") or value > item["job_value"]):
                item["job_value"] = value
                item["value_source"] = "permit"
            item["history"].append(
                _history_entry(
                    "permit",
                    description,
                    issued,
                    row.get("permit_type"),
                    value,
                    f"dal-permit-{row.get('permit_number')}",
                )
            )
        return list(grouped.values())

    def build_candidates(
        self,
        *,
        hpd_complaints: int = 20,
        hpd_deadlines: int = 20,
        ecb: int = 40,
        chi_violations: int = 20,
        chi_permits: int = 0,
        chi_311: int = 0,
        chi_fines: int = 0,
        permit_rows: int = 400,
        bos_violations: int = 0,
        bos_311: int = 0,
        bos_code: int = 0,
        bos_permits: int = 0,
        dal_code: int = 0,
        dal_311: int = 0,
        dal_permits: int = 0,
        permit_window_days: int = 30,
    ) -> list:
        """Constrói a lista final por imóvel, já com multas, prazos e valores."""
        merged: dict = {}

        def merge(item: dict) -> None:
            key = item["property_key"]
            target = merged.get(key)
            if target is None:
                target = dict(item)
                target.setdefault("history", [])
                target.setdefault("tags", [])
                merged[key] = target
                return
            for field, value in item.items():
                if field in ("history", "tags"):
                    continue
                if field == "source_payload":
                    # Auditoria: guarda todas as linhas-fonte que alimentaram
                    # este imovel, nao apenas a primeira.
                    incoming = value if isinstance(value, list) else [value]
                    existing = target.get("source_payload")
                    if not existing:
                        target["source_payload"] = incoming
                    elif isinstance(existing, list):
                        target["source_payload"] = existing + incoming
                    else:
                        target["source_payload"] = [existing] + incoming
                    continue
                if field == "compliance_deadline" and value:
                    current = target.get("compliance_deadline")
                    if not current or value < current:
                        target[field] = value
                    continue
                if field == "severity":
                    target[field] = max_severity(target.get(field), value)
                elif target.get(field) in (None, "", 0, 0.0):
                    target[field] = value
            target["history"] = (target.get("history") or []) + (item.get("history") or [])
            for tag in item.get("tags") or []:
                if tag not in target["tags"]:
                    target["tags"].append(tag)

        def merge_fine(item: dict) -> None:
            """Soma multas no imovel, sem tocar em prazo/hearing."""
            key = item["property_key"]
            target = merged.get(key)
            if target is None:
                target = dict(item)
                target.setdefault("history", [])
                target.setdefault("tags", [])
                merged[key] = target
                return
            for field in ("fine_balance", "fine_imposed", "fine_paid"):
                target[field] = (target.get(field) or 0) + (item.get(field) or 0)
            target["severity"] = max_severity(
                target.get("severity"), item.get("severity")
            )
            if item.get("hearing_date") and (
                not target.get("hearing_date")
                or item["hearing_date"] < target["hearing_date"]
            ):
                target["hearing_date"] = item["hearing_date"]
            if item.get("compliance_deadline") and (
                not target.get("compliance_deadline")
                or item["compliance_deadline"] < target["compliance_deadline"]
            ):
                target["compliance_deadline"] = item["compliance_deadline"]
            incoming = item.get("source_payload") or []
            if not isinstance(incoming, list):
                incoming = [incoming]
            existing = target.get("source_payload")
            if not existing:
                target["source_payload"] = incoming
            elif isinstance(existing, list):
                target["source_payload"] = existing + incoming
            else:
                target["source_payload"] = [existing] + incoming
            target["history"] = (target.get("history") or []) + (
                item.get("history") or []
            )
            for tag in item.get("tags") or []:
                if tag not in target["tags"]:
                    target["tags"].append(tag)
            for field in ("description", "category", "zip_code"):
                if not target.get(field) and item.get(field):
                    target[field] = item[field]

        for item in self.fetch_hpd_complaints(hpd_complaints):
            merge(item)
        for item in self.fetch_hpd_deadlines(hpd_deadlines):
            merge(item)
        for item in self.fetch_ecb(ecb):
            target = next(
                (
                    candidate
                    for candidate in merged.values()
                    if (item.get("bin") and candidate.get("bin") == item.get("bin"))
                    or (item.get("bbl") and candidate.get("bbl") == item.get("bbl"))
                ),
                None,
            )
            if target is None:
                # Multa real sem ocorrência conhecida: cria já um candidato
                # próprio (a ficha PLUTO preenche a morada a seguir).
                target = dict(item)
                merged[target["property_key"]] = target
            target["fine_balance"] = (target.get("fine_balance") or 0) + (item.get("fine_balance") or 0)
            target["fine_imposed"] = (target.get("fine_imposed") or 0) + (item.get("fine_imposed") or 0)
            target["fine_paid"] = (target.get("fine_paid") or 0) + (item.get("fine_paid") or 0)
            target["severity"] = max_severity(target.get("severity"), item.get("severity"))
            if item.get("hearing_date") and (
                not target.get("hearing_date") or item["hearing_date"] < target["hearing_date"]
            ):
                target["hearing_date"] = item["hearing_date"]
            target["hearing_status"] = item.get("hearing_status") or target.get("hearing_status")
            payloads = item.get("source_payload") or []
            if payloads:
                target.setdefault("source_payload", [])
                target["source_payload"].extend(
                    payloads if isinstance(payloads, list) else [payloads]
                )
            target["history"] = (target.get("history") or []) + (item.get("history") or [])
        for item in self.fetch_chicago_violations(chi_violations):
            merge(item)
        for item in self.fetch_chicago_311(chi_311):
            merge(item)
        for item in self.fetch_chicago_fines(chi_fines):
            merge_fine(item)
        if chi_permits > 0:
            for item in self.fetch_chicago_permits(
                chi_permits, days=permit_window_days
            ):
                merge(item)
        for item in self.fetch_boston_violations(bos_violations):
            merge(item)
        for item in self.fetch_boston_311(bos_311):
            merge(item)
        for item in self.fetch_boston_code_enforcement(bos_code):
            merge_fine(item)
        for item in self.fetch_dallas_code(dal_code):
            merge(item)
        for item in self.fetch_dallas_311(dal_311):
            merge(item)
        if bos_permits > 0:
            for item in self.fetch_boston_permits(
                bos_permits, days=permit_window_days
            ):
                merge(item)
        if dal_permits > 0:
            for item in self.fetch_dallas_permits(
                dal_permits, days=permit_window_days
            ):
                merge(item)

        # Valores de obra: alvarás NYC casados por BIN; Chicago por morada.
        if permit_rows > 0:
            nyc_values = self.fetch_nyc_permit_values(
                (item.get("bin") for item in merged.values() if item.get("city") == "NYC"),
                limit=max(permit_rows // 2, 20),
            )
            chi_values = self.fetch_chicago_permit_values(limit=permit_rows)
            for key, target in merged.items():
                permit = (
                    nyc_values.get(str(target.get("bin") or ""))
                    if target.get("city") == "NYC"
                    else chi_values.get(key)
                )
                if not permit:
                    continue
                target["job_value"] = permit["job_value"]
                target["value_source"] = permit["value_source"]
                target["owner_name"] = target.get("owner_name") or permit.get("owner_name")
                target["history"] = (target.get("history") or []) + [permit["history"]]

        # Ficha do imóvel (PLUTO) só para quem tem BBL.
        profiles = self.fetch_pluto(item.get("bbl") for item in merged.values())
        for key, target in merged.items():
            profile = profiles.get(key)
            if profile:
                target["property"] = profile
                target["address"] = target.get("address") or profile.get("address")
                target["zip_code"] = target.get("zip_code") or profile.get("zip_code")
                target["owner_name"] = target.get("owner_name") or profile.get("owner_name")
                target["owner_type"] = target.get("owner_type") or (
                    "institutional" if str(profile.get("owner_type") or "").upper() in ("C", "M", "O") else "company"
                )

        candidates = []
        for target in merged.values():
            if not target.get("address"):
                continue
            if (
                not is_actionable(target.get("description"), target.get("history"))
                and not target.get("fine_balance")
                and not target.get("compliance_deadline")
            ):
                continue
            # A classificacao tem de seguir o sinal, nao o pipeline. Antes
            # tudo era "preventive", pelo que as abas Reativos/Obras nao
            # tinham dados e as multas/prazos de NYC ficavam no balde errado.
            target["source_kind"], target["source_type"] = source_kind_for_signal(
                target.get("signal_type")
            )
            target["inspection_status"] = "possible"
            fine_balance = float(target.get("fine_balance") or 0)
            tags = list(target.get("tags") or [])
            if fine_balance > 0:
                if "fine_active" not in tags:
                    tags.append("fine_active")
            elif "no_fine" not in tags:
                tags.append("no_fine")
            if target.get("owner_name") and "owner_identified" not in tags:
                tags.append("owner_identified")
            target["tags"] = tags
            target["severity"] = target.get("severity") or "medium"
            target["category"] = target.get("category") or "Unclassified"
            target["timeline"] = self._timeline(target)
            candidates.append(target)
        return candidates

    def _timeline(self, item: dict) -> list:
        received = str(item.get("received_at") or "")[:10] or None
        deadline = item.get("compliance_deadline")
        fine = float(item.get("fine_balance") or 0) > 0
        return [
            {"key": "complaint", "state": "done", "date": received},
            {"key": "inspection", "state": "current"},
            {"key": "violation", "state": "done" if deadline or fine else "future"},
        ]

    # ---------------------------------------------------------------- escrita
    @staticmethod
    def _existing() -> dict:
        from .db import get_connection

        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM opportunity_workflow ORDER BY id ASC"
            ).fetchall()
        finally:
            conn.close()
        out = {}
        for row in rows:
            key = row["property_key"]
            if key and key not in out:
                out[key] = opportunity_workflow._public(dict(row))
        return out

    def reclassify_existing(self, dry_run: bool = False) -> dict:
        """Limpa a fila: reclassifica 'Unclassified' e descarta genéricos.

        Só mexe em linhas sem classificação; categorias já válidas (incluindo
        as do seed) ficam intactas.
        """
        from .db import get_connection

        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, category, description, history_json, fine_balance, "
                "compliance_deadline FROM opportunity_workflow "
                "WHERE source_kind = 'preventive'"
            ).fetchall()
            updates: list = []
            drops: list = []
            by_category: dict = {}
            for row in rows:
                current = str(row["category"] or "").strip()
                if current not in ("", "Unclassified", "None"):
                    continue
                try:
                    history = json.loads(row["history_json"] or "[]")
                except (TypeError, ValueError):
                    history = []
                if (
                    not is_actionable(row["description"], history)
                    and not row["fine_balance"]
                    and not row["compliance_deadline"]
                ):
                    drops.append((row["id"],))
                    continue
                labels = " ".join(
                    str(entry.get("label") or "")
                    for entry in history
                    if isinstance(entry, dict)
                )
                category = map_category(row["description"], labels)
                updates.append((category, row["id"]))
                by_category[category] = by_category.get(category, 0) + 1
            if not dry_run:
                if updates:
                    conn.executemany(
                        "UPDATE opportunity_workflow SET category = ?, "
                        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        updates,
                    )
                if drops:
                    conn.executemany(
                        "DELETE FROM opportunity_workflow WHERE id = ?", drops
                    )
                conn.commit()
            return {
                "scanned": len(rows),
                "reclassified": len(updates),
                "dropped": len(drops),
                "by_category": by_category,
                "dry_run": dry_run,
            }
        finally:
            conn.close()

    def ingest(self, candidates: Optional[list] = None, **kwargs) -> dict:
        candidates = candidates if candidates is not None else self.build_candidates(**kwargs)
        existing = self._existing()
        stats = {
            "candidates": len(candidates),
            "created": 0,
            "enriched": 0,
            "skipped": 0,
            "fines": 0,
            "deadlines": 0,
            "values": 0,
            "ids": [],
        }
        for candidate in candidates:
            key = candidate["property_key"]
            current = existing.get(key)
            if current:
                fields = self._enrichment_fields(current, candidate)
                if not fields:
                    stats["skipped"] += 1
                    continue
                opportunity_workflow.update_enrichment(current["id"], **fields)
                stats["enriched"] += 1
                stats["ids"].append(current["id"])
            else:
                payload = dict(candidate)
                payload.pop("property_key", None)
                payload["bin_value"] = payload.pop("bin", None)
                row = opportunity_workflow.create_opportunity(**payload)
                existing[key] = row
                stats["created"] += 1
                stats["ids"].append(row["id"])
            if candidate.get("fine_balance"):
                stats["fines"] += 1
            if candidate.get("compliance_deadline"):
                stats["deadlines"] += 1
            if candidate.get("job_value"):
                stats["values"] += 1
        return stats

    @staticmethod
    def _enrichment_fields(current: dict, candidate: dict) -> dict:
        fields: dict = {}
        deadline = candidate.get("compliance_deadline")
        if deadline and (not current.get("compliance_deadline") or deadline < current["compliance_deadline"]):
            fields["compliance_deadline"] = deadline
        if candidate.get("description"):
            fields["description"] = candidate["description"]
        if candidate.get("zip_code") and not current.get("zip_code"):
            fields["zip_code"] = candidate["zip_code"]
            fields["zip_source"] = candidate.get("zip_source")
        if candidate.get("job_value"):
            fields["job_value"] = candidate["job_value"]
            fields["value_source"] = candidate.get("value_source")
        if candidate.get("fine_balance"):
            # A janela atual é a fonte da verdade: mantém saldo e histórico
            # coerentes entre si em vez de somar execuções antigas.
            for field in ("fine_balance", "fine_imposed", "fine_paid"):
                fields[field] = candidate.get(field) or 0
        if candidate.get("hearing_date") and not current.get("hearing_date"):
            fields["hearing_date"] = candidate["hearing_date"]
        for field in ("hearing_status", "owner_name", "owner_type"):
            if candidate.get(field) and not current.get(field):
                fields[field] = candidate[field]
        if candidate.get("property") and not current.get("property"):
            fields["property"] = candidate["property"]
        if candidate.get("history"):
            # A janela de ingestão é a fonte da verdade do histórico desta
            # execução: substituir evita duplicar ocorrências entre runs.
            fields["history"] = Phase1EnrichmentService._merge_history(
                [], candidate["history"]
            )
        if candidate.get("tags"):
            merged_tags = list(dict.fromkeys((current.get("tags") or []) + candidate["tags"]))
            if merged_tags != (current.get("tags") or []):
                fields["tags"] = merged_tags
        if candidate.get("source_payload"):
            # P1: guarda o payload bruto da fonte para auditoria futura.
            fields["source_payload"] = candidate["source_payload"]
        return fields

    @staticmethod
    def _merge_history(current: list, incoming: list) -> list:
        merged: list = []
        seen: set = set()
        for entry in list(current) + list(incoming):
            signature = entry.get("id") or (
                str(entry.get("kind")),
                str(entry.get("date")),
                str(entry.get("label")),
            )
            if signature in seen:
                continue
            seen.add(signature)
            merged.append(dict(entry))
        merged.sort(key=lambda entry: str(entry.get("date") or ""), reverse=True)
        return merged[:20]


phase1_enrichment = Phase1EnrichmentService()
