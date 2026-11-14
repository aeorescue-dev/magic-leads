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

from .opportunity_workflow import make_property_key, opportunity_workflow
from .privacy import scrub

_USER_AGENT = "MagicLeadsPhase1/1.0 (staging enrichment)"
_TIMEOUT = 60

NYC = "data.cityofnewyork.us"
CHI = "data.cityofchicago.org"

DATASETS = {
    "hpd_complaints": (NYC, "ygpa-z7cr"),
    "hpd_violations": (NYC, "wvxf-dwi5"),
    "ecb": (NYC, "6bgk-3dad"),
    "pluto": (NYC, "64uk-42ks"),
    "nyc_permits": (NYC, "rbx6-tga4"),
    "chi_violations": (CHI, "22u3-xenr"),
    "chi_permits": (CHI, "ydr8-5enu"),
}

# Palavra-chave -> categoria da plataforma. A ordem importa: as mais
# específicas entram primeiro para "heat/hot water" não cair em "water".
_CATEGORY_RULES = [
    ("Heating", ("heat", "hot water", "boiler", "furnace", "steam")),
    ("Elevator", ("elevator",)),
    ("Gas", ("gas", "gas leak")),
    ("Electrical", ("electric", "wiring", "power outage")),
    ("Plumbing", ("plumb", "leak", "sewer", "drain", "water")),
    ("Rodent", ("rodent", "rat", "roach", "mice", "mouse", "vermin")),
    ("Mold", ("mold", "mould", "fungus")),
    ("Lead", ("lead-based", "lead paint", "lead hazard")),
    ("Paint", ("paint", "plaster", "wall")),
    ("Door_Window", ("window", "door", "frame")),
    ("Roof", ("roof", "ceiling", "waterproof")),
    ("Debris", ("debris", "garbage", "trash", "rubbish", "dumpster")),
    ("Unsanitary", ("unsanitary", "dirty", "sanitation", "odor", "pest")),
    ("Structure", ("structur", "facade", "foundation", "wall", "stair", "porch")),
]

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


def map_category(*parts: Optional[str]) -> str:
    text = " ".join(str(part or "") for part in parts).lower()
    for category, keywords in _CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "Unclassified"


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
        since = (self.today - timedelta(days=90)).isoformat()
        rows = socrata(
            "chi_violations",
            {
                "$limit": max(1, int(limit)),
                "$order": "violation_date DESC",
                "$where": f"violation_status = 'OPEN' AND violation_date >= '{since}T00:00:00'",
            },
        )
        grouped: dict = {}
        for row in rows:
            address = normalize_address(row.get("address"))
            if not address:
                continue
            key = make_property_key(address=address, city="Chicago", zip_code=None)
            item = grouped.setdefault(
                key,
                {
                    "property_key": key,
                    "address": address,
                    "city": "Chicago",
                    "state": "IL",
                    "zip_code": None,
                    "signal_type": "legal_obligation",
                    "severity": "critical" if str(row.get("inspection_status") or "").upper() == "FAILED" else "high",
                    "category": map_category(row.get("violation_description"), row.get("violation_code")),
                    "description": _clean(row.get("violation_description")),
                    "received_at": row.get("violation_date"),
                    "history": [],
                    "tags": ["inspection_possible"],
                    "source_record_id": "phase1-chi-violation-" + hashlib.sha1(address.encode("utf-8")).hexdigest()[:16],
                },
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

    # ------------------------------------------------------------- composição
    def build_candidates(
        self,
        *,
        hpd_complaints: int = 20,
        hpd_deadlines: int = 20,
        ecb: int = 40,
        chi_violations: int = 20,
        permit_rows: int = 400,
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
            target["history"] = (target.get("history") or []) + (item.get("history") or [])
        for item in self.fetch_chicago_violations(chi_violations):
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
            target["source_kind"] = "preventive"
            target["source_type"] = "pre_inspection"
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
