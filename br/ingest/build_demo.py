"""Gera o snapshot JSON do protótipo Brasil.

Entradas (br/.cache):
  - ibama_auto_infracao.zip  (CSV 2026)
  - sislic.csv               (licenças federais)
  - mg_licencas.json         (WFS MG)
  - cnpj_cache.json          (enriquecimento opcional)

Saída:
  - br/web/assets/data.json
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from datetime import date, datetime
from pathlib import Path

csv.field_size_limit(50_000_000)

BR = Path(__file__).resolve().parents[1]
CACHE = BR / ".cache"
ASSETS = BR / "web" / "assets"
TODAY = date(2026, 11, 18)

UF_BY_CODE = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
    21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL",
    28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR",
    42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF",
}
UF_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().upper()


def as_float(value: object) -> float | None:
    raw = str(value or "").strip().replace(".", "").replace(",", ".")
    try:
        number = float(raw)
        return number if number else None
    except ValueError:
        return None


def as_int(value: object) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def as_date(value: object) -> date | None:
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:19], fmt).date()
        except ValueError:
            continue
    return None


def cnpj_digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def cnpj_valid(digits: str) -> bool:
    if len(digits) != 14 or digits == "0" * 14:
        return False

    def dv(base: str) -> str:
        weights = (
            [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
            if len(base) == 12
            else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        )
        total = sum(int(a) * b for a, b in zip(base, weights))
        rest = total % 11
        return "0" if rest < 2 else str(11 - rest)

    return digits[12] == dv(digits[:12]) and digits[13] == dv(digits[:13])


def load_municipalities() -> tuple[list[dict], dict[tuple[str, str], tuple[float, float]]]:
    path = ASSETS / "municipios.csv"
    if not path.exists():
        return [], {}
    rows: list[dict] = []
    index: dict[tuple[str, str], tuple[float, float]] = {}
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            uf = UF_BY_CODE.get(as_int(row.get("codigo_uf")) or 0)
            if not uf:
                continue
            name = str(row.get("nome") or "").strip()
            try:
                lat = float(row["latitude"])
                lng = float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            item = {"uf": uf, "name": name, "lat": lat, "lng": lng}
            rows.append(item)
            index[(uf, norm(name))] = (lat, lng)
    return rows, index


def parse_ibama(limit: int, muni_index: dict) -> tuple[list[dict], dict]:
    path = CACHE / "ibama_auto_infracao.zip"
    if not path.exists():
        return [], {"rows": 0, "distinct_cnpj": 0, "by_uf": {}}
    leads: list[dict] = []
    seen: set[str] = set()
    by_uf: dict[str, int] = {}
    cnpjs: set[str] = set()
    total_pj = 0
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.endswith("2026.csv")]
        if not names:
            return [], {"rows": 0, "distinct_cnpj": 0, "by_uf": {}}
        with archive.open(names[0]) as handle:
            reader = csv.DictReader(
                io.TextIOWrapper(handle, encoding="utf-8-sig", newline=""),
                delimiter=";",
            )
            for row in reader:
                if (row.get("TP_PESSOA_INFRATOR") or "").strip().upper() != "PJ":
                    continue
                if (row.get("SIT_CANCELADO") or "").strip().upper() == "S":
                    continue
                cnpj = cnpj_digits(row.get("CPF_CNPJ_INFRATOR"))
                if len(cnpj) != 14:
                    continue
                total_pj += 1
                cnpjs.add(cnpj)
                uf = (row.get("UF") or "").strip().upper()
                by_uf[uf] = by_uf.get(uf, 0) + 1
                number = (row.get("NUM_AUTO_INFRACAO") or "").strip()
                key = number or (row.get("SEQ_AUTO_INFRACAO") or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                municipality = (row.get("MUNICIPIO") or "").strip()
                lat = as_float(row.get("NUM_LATITUDE_AUTO"))
                lng = as_float(row.get("NUM_LONGITUDE_AUTO"))
                if not (lat and lng and -34 <= lat <= 6 and -74 <= lng <= -34):
                    lat = lng = None
                centroid = muni_index.get((uf, norm(municipality)))
                if centroid:
                    lat, lng = centroid
                category = (row.get("DES_INFRACAO") or "").split("(")[0].strip()
                fine = as_float(row.get("VAL_AUTO_INFRACAO")) or 0
                reported = as_date(row.get("DAT_HORA_AUTO_INFRACAO"))
                priority = 50
                if fine >= 100_000:
                    priority += 25
                elif fine >= 50_000:
                    priority += 15
                elif fine >= 10_000:
                    priority += 8
                if reported and (TODAY - reported).days <= 90:
                    priority += 10
                leads.append(
                    {
                        "id": f"ibama:{key}",
                        "kind": "infraction",
                        "source": "IBAMA",
                        "source_label": "Auto de infração federal",
                        "source_id": key,
                        "company": (row.get("NOME_INFRATOR") or "").strip(),
                        "cnpj": cnpj,
                        "cnpj_root": cnpj[:8],
                        "uf": uf,
                        "municipality": municipality,
                        "lat": lat,
                        "lng": lng,
                        "geo_precision": "municipality" if centroid else "source",
                        "category": category,
                        "activity": None,
                        "description": (row.get("DES_AUTO_INFRACAO") or "").strip()[:700],
                        "fine": fine,
                        "date": reported.isoformat() if reported else None,
                        "expires_at": None,
                        "process": (row.get("NU_PROCESSO_FORMATADO") or row.get("NUM_PROCESSO") or "").strip(),
                        "status": (row.get("DES_STATUS_FORMULARIO") or "Lavrado").strip(),
                        "license_type": None,
                        "url": "https://dadosabertos.ibama.gov.br/dataset/fiscalizacao-auto-de-infracao",
                        "verified": True,
                        "priority": min(100, priority),
                    }
                )
    leads.sort(key=lambda item: (item["priority"], item["fine"]), reverse=True)
    return leads[:limit], {
        "rows": total_pj,
        "distinct_cnpj": len(cnpjs),
        "by_uf": by_uf,
        "last_update": "2026-11-18",
    }


def parse_sislic(limit: int) -> tuple[list[dict], dict]:
    path = CACHE / "sislic.csv"
    if not path.exists():
        return [], {"total": 0, "distinct_companies": 0}
    rows = list(
        csv.DictReader(
            io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace")),
            delimiter=";",
        )
    )
    leads: list[dict] = []
    companies: set[str] = set()
    expiring_90 = expiring_180 = expiring_365 = 0
    last_update = ""
    for row in rows:
        company = (row.get("NOM_PESSOA") or "").strip()
        if not company:
            continue
        companies.add(norm(company))
        last_update = (row.get("ultima_atualizacao_relatorio") or last_update).strip()
        expiry = as_date(row.get("DAT_VENCIMENTO"))
        if not expiry:
            continue
        days = (expiry - TODAY).days
        if 0 <= days <= 90:
            expiring_90 += 1
        if 0 <= days <= 180:
            expiring_180 += 1
        if 0 <= days <= 365:
            expiring_365 += 1
        if days < -365:
            continue
        kind = "license_expiring" if days >= 0 else "license_expired"
        issued = as_date(row.get("DAT_EMISSAO"))
        priority = 45 if days >= 0 else 30
        if 0 <= days <= 90:
            priority = 85
        elif 0 <= days <= 180:
            priority = 70
        elif 0 <= days <= 365:
            priority = 58
        leads.append(
            {
                "id": f"sislic:{(row.get('NUM_LICENCA') or '').strip()}",
                "kind": kind,
                "source": "IBAMA SISLIC",
                "source_label": "Licença federal",
                "source_id": (row.get("NUM_LICENCA") or "").strip(),
                "company": company,
                "cnpj": None,
                "cnpj_root": None,
                "uf": None,
                "municipality": None,
                "lat": None,
                "lng": None,
                "category": "Licenciamento federal",
                "activity": (row.get("DES_TIPOLOGIA") or "").strip(),
                "description": (row.get("NOM_EMPREENDIMENTO") or "").strip(),
                "fine": None,
                "date": issued.isoformat() if issued else None,
                "expires_at": expiry.isoformat(),
                "process": (row.get("NUM_PROCESSO_IBAMA") or "").strip(),
                "status": "Licença emitida",
                "license_type": (row.get("DES_TIPOLICENCA") or "").strip(),
                "url": None,
                "verified": False,
                "priority": priority,
            }
        )
    leads.sort(key=lambda item: (item["priority"], item["expires_at"] or ""), reverse=True)
    return leads[:limit], {
        "total": len(rows),
        "distinct_companies": len(companies),
        "expiring_90": expiring_90,
        "expiring_180": expiring_180,
        "expiring_365": expiring_365,
        "last_update": last_update or "2026-11-18",
    }


def parse_mg(limit: int, muni_index: dict) -> tuple[list[dict], dict]:
    path = CACHE / "mg_licencas.json"
    if not path.exists():
        return [], {"total": 0, "distinct_roots": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") or []
    leads: list[dict] = []
    roots: set[str] = set()
    expiring_365 = expiring_730 = 0
    max_issued: date | None = None
    for feature in features:
        props = feature.get("properties") or {}
        expiry = as_date(props.get("data_val"))
        if not expiry:
            continue
        issued = as_date(props.get("data_emiss"))
        if issued and (not max_issued or issued > max_issued):
            max_issued = issued
        days = (expiry - TODAY).days
        if 0 <= days <= 365:
            expiring_365 += 1
        if 0 <= days <= 730:
            expiring_730 += 1
        if days < -730:
            continue
        raw_doc = cnpj_digits(props.get("cpf_cnpj"))
        root = raw_doc[:8] if len(raw_doc) >= 8 else None
        full = raw_doc if cnpj_valid(raw_doc) else None
        if root:
            roots.add(root)
        municipality = (props.get("mun_solic") or "").strip()
        centroid = muni_index.get(("MG", norm(municipality)))
        lat = as_float(props.get("latitude"))
        lng = as_float(props.get("longitude"))
        if not (lat and lng and -25 <= lat <= -14 and -52 <= lng <= -39):
            lat = centroid[0] if centroid else None
            lng = centroid[1] if centroid else None
        kind = "license_expiring" if days >= 0 else "license_expired"
        priority = 55 if days >= 0 else 35
        if 0 <= days <= 90:
            priority = 88
        elif 0 <= days <= 180:
            priority = 75
        elif 0 <= days <= 365:
            priority = 62
        leads.append(
            {
                "id": f"mg:{(props.get('n_solicit') or props.get('n_processo') or '').strip()}",
                "kind": kind,
                "source": "SEMAD-MG",
                "source_label": "Licença estadual (MG)",
                "source_id": (props.get("n_solicit") or props.get("n_processo") or "").strip(),
                "company": (props.get("nome_pf_pj") or "").strip(),
                "cnpj": full,
                "cnpj_root": root,
                "uf": "MG",
                "municipality": municipality,
                "lat": lat,
                "lng": lng,
                "geo_precision": "property" if lat and lng else None,
                "category": (props.get("listagem") or "Licenciamento estadual").strip(),
                "activity": (props.get("des_atvpri") or "").strip(),
                "description": (props.get("des_atvpri") or "").strip(),
                "fine": None,
                "date": issued.isoformat() if issued else None,
                "expires_at": expiry.isoformat(),
                "process": (props.get("n_processo") or "").strip(),
                "status": (props.get("status_pro") or "Deferido").strip(),
                "license_type": (props.get("modl_licen") or "").strip(),
                "url": (props.get("link") or "").strip() or None,
                "verified": bool(full),
                "priority": priority,
            }
        )
    leads.sort(key=lambda item: (item["priority"], item["expires_at"] or ""), reverse=True)
    return leads[:limit], {
        "total": len(features),
        "distinct_roots": len(roots),
        "expiring_365": expiring_365,
        "expiring_730": expiring_730,
        "max_issued": max_issued.isoformat() if max_issued else None,
        "last_update": "atualização quadrimestral",
    }


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    municipalities, muni_index = load_municipalities()
    cnpj_cache_path = CACHE / "cnpj_cache.json"
    cnpj_cache = (
        json.loads(cnpj_cache_path.read_text(encoding="utf-8"))
        if cnpj_cache_path.exists()
        else {}
    )

    ibama, ibama_stats = parse_ibama(650, muni_index)
    sislic, sislic_stats = parse_sislic(260)
    mg, mg_stats = parse_mg(450, muni_index)

    for item in ibama + mg:
        extra = cnpj_cache.get(item["cnpj"] or "") or {}
        if extra:
            item["cnae"] = extra.get("cnae")
            item["cnae_desc"] = extra.get("cnae_desc")
            item["phone"] = extra.get("phone")
            item["email"] = extra.get("email")
            item["qsa_count"] = extra.get("qsa_count")
            item["cnpj_status"] = extra.get("status")
        else:
            item["cnae"] = None
            item["cnae_desc"] = None
            item["phone"] = None
            item["email"] = None
            item["qsa_count"] = None
            item["cnpj_status"] = None

    for item in sislic + mg:
        item.setdefault("cnae", None)
        item.setdefault("cnae_desc", None)
        item.setdefault("phone", None)
        item.setdefault("email", None)
        item.setdefault("qsa_count", None)
        item.setdefault("cnpj_status", None)

    leads = ibama + sislic + mg
    leads.sort(key=lambda item: (item["priority"], item.get("date") or ""), reverse=True)

    states: dict[str, dict] = {}
    for uf, name in UF_NAMES.items():
        federal = ibama_stats["by_uf"].get(uf, 0)
        state_licenses = mg_stats["total"] if uf == "MG" else 0
        states[uf] = {
            "uf": uf,
            "name": name,
            "federal_autos": federal,
            "state_licenses": state_licenses,
            "state_source": "SEMAD-MG WFS" if uf == "MG" else None,
            "state_freshness": "quadrimestral" if uf == "MG" else None,
            "municipal": False,
            "coverage": "federal+estadual" if uf == "MG" else "federal",
        }

    expiring_90 = sum(
        1 for item in leads if item["kind"] == "license_expiring" and item.get("expires_at")
        and 0 <= (date.fromisoformat(item["expires_at"]) - TODAY).days <= 90
    )
    expiring_365 = sum(
        1 for item in leads if item["kind"] == "license_expiring" and item.get("expires_at")
        and 0 <= (date.fromisoformat(item["expires_at"]) - TODAY).days <= 365
    )

    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": TODAY.isoformat(),
        "kpis": {
            "leads": len(leads),
            "infractions": len(ibama),
            "licenses": len(sislic) + len(mg),
            "federal_companies_2026": ibama_stats.get("distinct_cnpj", 0),
            "federal_autos_2026": ibama_stats.get("rows", 0),
            "mg_licenses": mg_stats.get("total", 0),
            "sislic_licenses": sislic_stats.get("total", 0),
            "expiring_90": expiring_90,
            "expiring_365": expiring_365,
        },
        "coverage": {
            "federal": {
                "autos_2026": ibama_stats.get("rows", 0),
                "distinct_cnpj_2026": ibama_stats.get("distinct_cnpj", 0),
                "last_update": ibama_stats.get("last_update"),
                "source": "IBAMA — Dados Abertos",
            },
            "sislic": sislic_stats,
            "mg": mg_stats,
            "states": states,
            "municipal": {
                "coverage": "seletiva — diários oficiais/parceiros",
                "status": "fase 3",
            },
        },
        "municipalities": municipalities,
        "leads": leads,
    }
    (ASSETS / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"[ok] {ASSETS / 'data.json'} — {len(leads)} leads, "
        f"{len(municipalities)} municípios"
    )


if __name__ == "__main__":
    main()
