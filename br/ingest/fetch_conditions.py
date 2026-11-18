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
import random
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import openpyxl
import pdfplumber
import requests

BR = Path(__file__).resolve().parents[1]
ASSETS = BR / "web" / "assets"
CACHE = BR / ".cache" / "conditions"
MG_RAW = BR / ".cache" / "mg_licencas.json"
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
    compact = text.replace(" ", "")
    if "DURANTEAVIGENCIA" in compact or "AVIGENCIA" in compact and "DURANTE" in compact:
        return ["durante_vigencia"], "durante_vigencia"
    if re.search(r"\bCADA ANO\b", text) or re.search(r"\bMES DE [A-Z]+ DE CADA ANO\b", text):
        return ["anual"], "anual"
    if re.search(r"\b(?:EM ATE\s+)?\d{1,3}\s*(?:\([A-Z ]+\))?\s*DIAS?\b", text) or "APOS A INSTALACAO" in text:
        return ["unica"], "unica"
    if re.search(r"\b\d{1,3}\s+MESES?\b", text):
        return ["unica"], "unica"
    if any(term in text for term in ("PREVIAMENTE", "ANTES DO INICIO", "ANTES DE INICIAR", "ANTES DA OPERACAO", "ANTES DE QUALQUER", "ANTERIOR AO INICIO", "ANTES DA PROXIMA", "APRESENTAR COMO ANEXO", "CONFORME CRONOGRAMA", "IMEDIATO", "1 ANO", "ATE AGOSTO/")):
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


def parecer_candidate_pages(payload: bytes) -> list[int]:
    """Localiza (via pypdf, mais rápido) as páginas com o Anexo de condicionantes."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(payload))
    indices: list[int] = []
    for index, page in enumerate(reader.pages):
        try:
            text = norm(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            continue
        if "CONDICIONANTE" in text and ("ANEXO" in text or "PRAZO" in text or "ITEM" in text):
            indices.append(index)
            if index + 1 < len(reader.pages):
                indices.append(index + 1)
    return sorted(set(indices))


def parse_parecer(payload: bytes) -> list[dict]:
    """Extrai a tabela 'Item / Condicionante / Prazo' do Parecer Técnico.

    Só as páginas do Anexo I são abertas no pdfplumber: evita parsear 30+
    páginas de texto corrido por processo.
    """
    conditions: list[dict] = []
    seen: set[tuple[str, str]] = set()
    pages = parecer_candidate_pages(payload)
    if not pages:
        return conditions
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        total = len(pdf.pages)
        for page_index in pages:
            if page_index >= total:
                continue
            page = pdf.pages[page_index]
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


def format_cnpj(digits: str) -> str | None:
    if len(digits) != 14:
        return None
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def candidate_leads_from_demo(limit: int | None) -> list[dict]:
    """Amostra do dashboard (450 licenças MG) — útil para QA rápido."""
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


def candidate_leads_from_mg() -> list[dict]:
    """Todas as licenças do WFS de MG (19.713), em ordem determinística.

    A ordem é embaralhada com semente fixa para que lotes iniciais sejam uma
    amostra representativa (sem viés de região/data) e o progresso seja
    retomável por --offset.
    """
    if not MG_RAW.exists():
        return []
    data = json.loads(MG_RAW.read_text(encoding="utf-8"))
    out: list[dict] = []
    seen: set[int] = set()
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        link = str(props.get("link") or "")
        match = re.search(r"/acesso-visitante/(\d+)/", link)
        if not match:
            continue
        id_solicitacao = int(match.group(1))
        if id_solicitacao in seen:
            continue
        seen.add(id_solicitacao)
        out.append(
            {
                "process": (props.get("n_processo") or "").strip(),
                "id_solicitacao": id_solicitacao,
                "company": (props.get("nome_pf_pj") or "").strip(),
                "cnpj": format_cnpj(re.sub(r"\D", "", str(props.get("cpf_cnpj") or ""))),
                "url": link,
                "municipality": props.get("mun_solic"),
                "status": props.get("status_pro"),
            }
        )
    random.Random(42).shuffle(out)
    return out


def candidate_leads(source: str, limit: int | None, offset: int = 0) -> list[dict]:
    leads = candidate_leads_from_mg() if source == "mg" else candidate_leads_from_demo(None)
    if offset:
        leads = leads[offset:]
    if limit:
        leads = leads[:limit]
    return leads


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


def write_output(processes: dict, coverage: dict) -> dict:
    status_counts: dict[str, int] = {}
    for entry in coverage.values():
        key = entry.get("status") or "error"
        status_counts[key] = status_counts.get(key, 0) + 1
    with_conditions = len(processes)
    summary = {
        "checked": len(coverage),
        "with_conditions": with_conditions,
        "with_compliance_xlsx": sum(1 for item in processes.values() if item.get("status") == "ok"),
        "without_documents": status_counts.get("no_conditions_document", 0),
        "document_without_parsed_conditions": status_counts.get("document_without_parsed_conditions", 0),
        "errors": status_counts.get("error", 0),
        "total_in_file": len(processes),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "SLA/Sisema — CONDICIONANTES + PARECER",
                "summary": summary,
                "coverage": coverage,
                "processes": processes,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    temp.replace(OUT)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--source", choices=["demo", "mg"], default="demo")
    parser.add_argument("--process", type=str, default="")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--reclassify", action="store_true", help="Recalcula frequências no ficheiro existente, sem rede")
    args = parser.parse_args()

    if args.reclassify:
        payload = json.loads(OUT.read_text(encoding="utf-8"))
        processes = payload.get("processes") or {}
        for process in processes.values():
            for condition in process.get("conditions") or []:
                frequencies, group = classify_frequency(
                    f"{condition.get('periodicity_raw', '')} {condition.get('description', '')} {condition.get('deadline', '')}"
                )
                condition["frequencies"] = frequencies
                condition["frequency_group"] = group
            process["summary"] = summarize(process.get("conditions") or [])
        summary = write_output(processes, payload.get("coverage") or {})
        print(f"[ok] reclassificado — {summary}")
        return

    leads = candidate_leads(args.source, None if args.all else args.limit, args.offset)
    if args.process:
        leads = [lead for lead in leads if lead["process"] == args.process]
    previous: dict = {}
    if OUT.exists():
        previous = json.loads(OUT.read_text(encoding="utf-8"))
    processes: dict = dict(previous.get("processes") or {})
    coverage: dict = dict(previous.get("coverage") or {})
    print(
        f"[start] {len(leads)} processos ({args.source}, offset={args.offset}, "
        f"workers={args.workers}); já verificados: {len(coverage)}"
    )

    lock = Lock()
    done = 0
    started = time.time()

    def run(lead: dict) -> dict:
        try:
            return fetch_process(lead)
        except Exception as exc:  # noqa: BLE001
            return {
                "process": lead.get("process"),
                "id_solicitacao": lead.get("id_solicitacao"),
                "company": lead.get("company"),
                "status": "error",
                "error": repr(exc)[:300],
            }

    results = []
    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run, lead): lead for lead in leads}
            for future in as_completed(futures):
                results.append(future.result())
                done += 1
                if done % 25 == 0 or done == len(leads):
                    rate = done / max(time.time() - started, 1)
                    print(f"  [{done}/{len(leads)}] {rate:.1f} proc/s")
    else:
        for lead in leads:
            results.append(run(lead))
            done += 1
            if done % 25 == 0 or done == len(leads):
                rate = done / max(time.time() - started, 1)
                print(f"  [{done}/{len(leads)}] {rate:.1f} proc/s")

    for result in results:
        sid = str(result.get("id_solicitacao"))
        status = result.get("status") or "error"
        coverage[sid] = {
            "process": result.get("process"),
            "company": result.get("company"),
            "status": status,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if status in ("ok", "ok_parecer"):
            processes[result.get("process") or sid] = result
        time.sleep(0.02)

    summary = write_output(processes, coverage)
    print(f"[ok] {OUT} — {summary}")


if __name__ == "__main__":
    main()
