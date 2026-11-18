"""Extrai condicionantes por processo do SLA/Sisema.

Fontes públicas:
  POST /sla/listarDocumentos/anexado/cidadao/{idSolicitacao}
  GET  /sla/anexarDocumento/downloadPath?path=...&nomeArquivo=...

Combina:
  1. Relatório de Cumprimento de Condicionantes (XLSX) — status/histórico.
  2. Parecer Técnico/Único (PDF) — condicionantes do Anexo I, quando não há XLSX.

Uso:
  python fetch_conditions.py --limit 20
  python fetch_conditions.py --process 352/2025
  python fetch_conditions.py --all
"""
from __future__ import annotations

import argparse
import io
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import pdfplumber
import requests

BR = Path(__file__).resolve().parents[1]
ASSETS = BR / "web" / "assets"
CACHE = BR / ".cache" / "conditions"
OUT = BR / "data" / "conditions.json"
SLA = "https://ecosistemas.meioambiente.mg.gov.br/sla"
DOCS_API = SLA + "/listarDocumentos/anexado/cidadao/{id}"
DOWNLOAD = SLA + "/anexarDocumento/downloadPath"

FREQ_TERMS = (
    ("SEMANAL", "semanal"),
    ("SEMANAIS", "semanal"),
    ("QUINZENAL", "quinzenal"),
    ("QUINZENAIS", "quinzenal"),
    ("MENSAL", "mensal"),
    ("MENSAIS", "mensal"),
    ("BIMESTRAL", "bimestral"),
    ("BIMESTRAIS", "bimestral"),
    ("TRIMESTRAL", "trimestral"),
    ("TRIMESTRAIS", "trimestral"),
    ("QUADRIMESTRAL", "quadrimestral"),
    ("QUADRIMESTRAIS", "quadrimestral"),
    ("SEMESTRAL", "semestral"),
    ("SEMESTRAIS", "semestral"),
    ("ANUAL", "anual"),
    ("ANUAIS", "anual"),
    ("UNICA", "unica"),
    ("CONSTANTE", "constante"),
    ("DIARIO", "diario"),
    ("DIARIA", "diario"),
    ("DIARIOS", "diario"),
    ("DIARIAS", "diario"),
    ("DURANTE A VIGENCIA", "durante_vigencia"),
    ("DURANTE VIGENCIA", "durante_vigencia"),
)
STATUS_MAP = (
    ("CUMPRIDA CONFORME PERIODICIDADE", "cumprida_conforme_periodicidade"),
    ("CUMPRIDA PARCIALMENTE", "cumprida_parcialmente"),
    ("EM ATENDIMENTO", "em_atendimento"),
    ("DESCUMPRIDA", "descumprida"),
    ("CUMPRIDA", "cumprida"),
)
KNOWN_AREAS = {
    "MEIO AMBIENTE", "CARVAO", "CARVÃO", "OUTORGA", "PROJETOS", "PRODUCAO",
    "PRODUÇÃO", "SERVICOS GERAIS", "SERVIÇOS GERAIS", "OFICINA AUTOS",
    "MANUTENCAO", "MANUTENÇÃO", "AUTO DE FISCALIZACAO", "AUTO DE FISCALIZAÇÃO",
}
FREQUENCY_ORDER = [
    "semanal", "quinzenal", "mensal", "bimestral", "trimestral",
    "quadrimestral", "semestral", "anual", "unica", "constante",
    "diario", "durante_vigencia", "nao_classificada",
]


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().upper()


def classify_frequency(raw: object) -> tuple[list[str], str]:
    text = norm(raw)
    found: list[str] = []
    for term, key in FREQ_TERMS:
        if term in text and key not in found:
            found.append(key)
    if found:
        return found, "composta" if len(found) > 1 else found[0]
    cadence = re.search(r"A CADA\s+(\d{1,2})\s+(DIAS?|MESES?|MES)", text)
    if cadence:
        amount = int(cadence.group(1))
        unit = cadence.group(2)
        if unit.startswith("DIA"):
            key = "semanal" if amount == 7 else "quinzenal" if amount == 15 else "diario" if amount == 1 else ""
        else:
            key = {2: "bimestral", 3: "trimestral", 4: "quadrimestral", 6: "semestral", 12: "anual"}.get(amount, "")
        if key:
            return [key], key
    if re.search(r"\b(?:EM ATE\s+)?\d{1,3}\s+DIAS?\b", text) or "APOS A INSTALACAO" in text:
        return ["unica"], "unica"
    if any(term in text for term in ("PREVIAMENTE", "ANTES DO INICIO", "ANTERIOR AO INICIO", "APRESENTAR COMO ANEXO", "CONFORME CRONOGRAMA", "IMEDIATO", "1 ANO")):
        return ["unica"], "unica"
    return [], "nao_classificada"


def classify_status(raw: object) -> str:
    text = norm(raw)
    for term, key in STATUS_MAP:
        if term in text:
            return key
    return "nao_informado"


def clean_responsible(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return "Equipe"
    if norm(text) in KNOWN_AREAS:
        return text
    return "Equipe (nome não exibido)"


def make_condition(
    *,
    item: object,
    description: object,
    origin: object = "",
    deadline: object = "",
    periodicity: object = "",
    responsible: object = "",
    status: object = "",
    observation: object = "",
    source: str,
) -> dict:
    frequencies, group = classify_frequency(f"{periodicity or ''} {description or ''} {deadline or ''}")
    return {
        "item": int(item) if str(item).isdigit() else item,
        "description": str(description or "").strip(),
        "origin": str(origin or "").strip(),
        "deadline": str(deadline or "").strip(),
        "periodicity_raw": str(periodicity or deadline or "").strip(),
        "frequencies": frequencies,
        "frequency_group": group,
        "responsible": clean_responsible(responsible),
        "status": classify_status(status),
        "status_raw": str(status or "").strip(),
        "observation": str(observation or "").strip(),
        "source": source,
    }


def parse_xlsx(payload: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    sheet = None
    for name in wb.sheetnames:
        if norm(name) == "CONDICIONANTES":
            sheet = wb[name]
            break
    if sheet is None:
        sheet = wb[wb.sheetnames[0]]
    conditions: list[dict] = []
    blanks = 0
    for row in sheet.iter_rows(min_row=5, max_col=8, values_only=True):
        values = [str(x).strip() if x is not None else "" for x in row]
        item, description, origin, deadline, periodicity, responsible, status, observation = values
        if not item and not description:
            blanks += 1
            if blanks >= 3:
                break
            continue
        blanks = 0
        if not re.fullmatch(r"\d+", item or ""):
            continue
        conditions.append(
            make_condition(
                item=item,
                description=description,
                origin=origin,
                deadline=deadline,
                periodicity=periodicity,
                responsible=responsible,
                status=status,
                observation=observation,
                source="compliance_xlsx",
            )
        )
    return conditions


def parse_parecer(payload: bytes) -> list[dict]:
    """Extrai a tabela 'Item / Condicionante / Prazo' do Parecer Técnico."""
    conditions: list[dict] = []
    seen: set[tuple[str, str]] = set()
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                header_seen = False
                for row in table:
                    cells = [re.sub(r"\s+", " ", (cell or "")).strip() for cell in row]
                    line = " ".join(cells)
                    if not header_seen:
                        if "ITEM" in norm(line) and "PRAZO" in norm(line):
                            header_seen = True
                        continue
                    if len(cells) < 3:
                        continue
                    item, description, deadline = cells[0], cells[1], cells[2]
                    if not re.fullmatch(r"\d{1,3}", item or ""):
                        continue
                    if not description:
                        continue
                    key = (norm(item), norm(description)[:120])
                    if key in seen:
                        continue
                    seen.add(key)
                    conditions.append(
                        make_condition(
                            item=item,
                            description=description,
                            deadline=deadline,
                            status="",
                            source="parecer_tecnico",
                        )
                    )
    return conditions


def merge_conditions(base: list[dict], extra: list[dict]) -> list[dict]:
    merged = list(base)
    index = {norm(item.get("description"))[:160]: item for item in merged}
    for condition in extra:
        key = norm(condition.get("description"))[:160]
        if key and key in index:
            index[key]["also_in_parecer"] = True
            continue
        merged.append(condition)
        if key:
            index[key] = condition
    merged.sort(key=lambda item: (str(item.get("source")), int(item.get("item")) if str(item.get("item")).isdigit() else 999))
    return merged


def summarize(conditions: list[dict]) -> dict:
    by_frequency: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for condition in conditions:
        for frequency in condition.get("frequencies") or [condition.get("frequency_group") or "nao_classificada"]:
            by_frequency[frequency] = by_frequency.get(frequency, 0) + 1
        status = condition.get("status") or "nao_informado"
        by_status[status] = by_status.get(status, 0) + 1
        source = condition.get("source") or "outra"
        by_source[source] = by_source.get(source, 0) + 1
    ordered = {key: by_frequency[key] for key in FREQUENCY_ORDER if key in by_frequency}
    for key, value in by_frequency.items():
        if key not in ordered:
            ordered[key] = value
    return {"total": len(conditions), "by_frequency": ordered, "by_status": by_status, "by_source": by_source}


def candidate_leads(limit: int | None) -> list[dict]:
    path = ASSETS / "data.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict] = []
    seen: set[str] = set()
    for lead in data.get("leads") or []:
        if lead.get("source") != "SEMAD-MG" or not lead.get("url"):
            continue
        process = (lead.get("process") or "").strip()
        match = re.search(r"/acesso-visitante/(\d+)/", str(lead.get("url")))
        if not process or not match or process in seen:
            continue
        seen.add(process)
        out.append(
            {
                "process": process,
                "id_solicitacao": int(match.group(1)),
                "company": lead.get("company"),
                "cnpj": lead.get("cnpj"),
                "url": lead.get("url"),
            }
        )
        if limit and len(out) >= limit:
            break
    return out


def fetch_process(lead: dict) -> dict:
    process = lead["process"]
    id_solicitacao = lead["id_solicitacao"]
    cache_file = CACHE / f"{id_solicitacao}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("status") in ("ok", "ok_parecer"):
                return cached
        except Exception:
            pass
    response = requests.post(
        DOCS_API.format(id=id_solicitacao),
        json={},
        timeout=60,
        headers={"User-Agent": "MagicLeadsBR/0.1", "Content-Type": "application/json"},
    )
    response.raise_for_status()
    documents = response.json().get("content") or []
    compliance_docs = [
        doc for doc in documents
        if "CONDICIONANTE" in norm(doc.get("descTipoDocumento"))
        and str(doc.get("documento") or "").lower().endswith((".xlsx", ".xls", ".pdf"))
    ]
    parecer_docs = [
        doc for doc in documents
        if "PARECER" in norm(doc.get("descTipoDocumento"))
        and str(doc.get("documento") or "").lower().endswith(".pdf")
    ]

    def download(doc: dict) -> bytes:
        result = requests.get(
            DOWNLOAD,
            params={"path": doc.get("path"), "nomeArquivo": doc.get("documento")},
            timeout=120,
            headers={"User-Agent": "MagicLeadsBR/0.1"},
        )
        result.raise_for_status()
        return result.content

    xlsx_conditions: list[dict] = []
    xlsx_doc = None
    for doc in sorted(compliance_docs, key=lambda item: 0 if str(item.get("documento")).lower().endswith(".xlsx") else 1):
        if not str(doc.get("documento")).lower().endswith((".xlsx", ".xls")):
            continue
        try:
            xlsx_conditions = parse_xlsx(download(doc))
            xlsx_doc = doc
        except Exception as exc:  # noqa: BLE001
            print(f"  xlsx erro {doc.get('documento')}: {exc!r}")
        if xlsx_conditions:
            break

    parecer_conditions: list[dict] = []
    parecer_doc = None
    for doc in parecer_docs:
        if doc.get("classificacao") not in (None, "Válido", "Valido"):
            continue
        try:
            parecer_conditions = parse_parecer(download(doc))
            parecer_doc = doc
        except Exception as exc:  # noqa: BLE001
            print(f"  parecer erro {doc.get('documento')}: {exc!r}")
        if parecer_conditions:
            break

    conditions = merge_conditions(xlsx_conditions, parecer_conditions)
    if conditions:
        status = "ok" if xlsx_conditions else "ok_parecer"
    elif compliance_docs or parecer_docs:
        status = "document_without_parsed_conditions"
    else:
        status = "no_conditions_document"
    result = {
        "process": process,
        "id_solicitacao": id_solicitacao,
        "company": lead.get("company"),
        "cnpj": lead.get("cnpj"),
        "status": status,
        "compliance_document": xlsx_doc.get("documento") if xlsx_doc else None,
        "parecer_document": parecer_doc.get("documento") if parecer_doc else None,
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summarize(conditions),
        "conditions": conditions,
    }
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--process", type=str, default="")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    leads = candidate_leads(None if args.all else args.limit)
    if args.process:
        leads = [lead for lead in leads if lead["process"] == args.process]
    previous = {}
    if OUT.exists():
        previous = json.loads(OUT.read_text(encoding="utf-8")).get("processes") or {}
    processes = dict(previous)
    ok = xlsx_ok = no_conditions = no_parse = 0
    for index, lead in enumerate(leads, start=1):
        print(f"[{index}/{len(leads)}] {lead['process']} — {lead.get('company')}")
        try:
            result = fetch_process(lead)
        except Exception as exc:  # noqa: BLE001
            print("  erro:", repr(exc))
            continue
        if not result:
            continue
        if result.get("status") in ("ok", "ok_parecer"):
            ok += 1
            if result.get("status") == "ok":
                xlsx_ok += 1
            processes[lead["process"]] = result
        elif result.get("status") == "no_conditions_document":
            no_conditions += 1
        else:
            no_parse += 1
        time.sleep(0.25)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "SLA/Sisema — CONDICIONANTES + PARECER",
                "summary": {
                    "processes_with_conditions": ok,
                    "processes_with_compliance_xlsx": xlsx_ok,
                    "processes_without_documents": no_conditions,
                    "documents_without_parsed_conditions": no_parse,
                    "total_in_file": len(processes),
                },
                "processes": processes,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"[ok] {OUT} — {len(processes)} processos; {ok} com condicionantes ({xlsx_ok} com XLSX)")


if __name__ == "__main__":
    main()
