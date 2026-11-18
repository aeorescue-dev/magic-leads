"""Agrega condicionantes por empresa (CNPJ quando existe, senão nome).

Lê `br/data/conditions.json` e escreve `br/data/conditions_by_company.json`
com a lista de obrigações de cada empresa, contagem por periodicidade e por
status, e os processos/documentos de origem.

Uso:
  python aggregate_conditions.py
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

BR = Path(__file__).resolve().parents[1]
CONDITIONS = BR / "data" / "conditions.json"
OUT = BR / "data" / "conditions_by_company.json"

FREQUENCY_ORDER = [
    "semanal", "quinzenal", "mensal", "bimestral", "trimestral",
    "quadrimestral", "semestral", "anual", "unica", "constante",
    "diario", "durante_vigencia", "nao_classificada",
]


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().upper()


def company_key(process: dict) -> str:
    digits = re.sub(r"\D", "", str(process.get("cnpj") or ""))
    if len(digits) == 14:
        return f"cnpj:{digits}"
    return f"name:{norm(process.get('company'))}"


def main() -> None:
    payload = json.loads(CONDITIONS.read_text(encoding="utf-8"))
    processes = payload.get("processes") or {}
    companies: dict[str, dict] = {}
    for process_number, process in processes.items():
        key = company_key(process)
        company = companies.setdefault(
            key,
            {
                "company": process.get("company"),
                "cnpj": process.get("cnpj"),
                "processes": [],
                "conditions": [],
                "by_frequency": {},
                "by_status": {},
            },
        )
        company["processes"].append(
            {
                "process": process_number,
                "compliance_document": process.get("compliance_document"),
                "parecer_document": process.get("parecer_document"),
                "total": len(process.get("conditions") or []),
            }
        )
        for condition in process.get("conditions") or []:
            record = {
                "process": process_number,
                "item": condition.get("item"),
                "description": condition.get("description"),
                "origin": condition.get("origin"),
                "deadline": condition.get("deadline"),
                "periodicity_raw": condition.get("periodicity_raw"),
                "frequencies": condition.get("frequencies") or [],
                "frequency_group": condition.get("frequency_group"),
                "status": condition.get("status"),
                "source": condition.get("source"),
            }
            company["conditions"].append(record)
            for frequency in record["frequencies"] or [record["frequency_group"] or "nao_classificada"]:
                company["by_frequency"][frequency] = company["by_frequency"].get(frequency, 0) + 1
            status = record["status"] or "nao_informado"
            company["by_status"][status] = company["by_status"].get(status, 0) + 1

    for company in companies.values():
        ordered = {key: company["by_frequency"][key] for key in FREQUENCY_ORDER if key in company["by_frequency"]}
        for key, value in company["by_frequency"].items():
            ordered.setdefault(key, value)
        company["by_frequency"] = ordered
        company["total"] = len(company["conditions"])

    ordered_companies = dict(
        sorted(companies.items(), key=lambda item: (-item[1]["total"], item[1]["company"] or ""))
    )
    total_conditions = sum(company["total"] for company in ordered_companies.values())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "SLA/Sisema — condicionantes por empresa",
                "summary": {
                    "companies": len(ordered_companies),
                    "conditions": total_conditions,
                    "processes": len(processes),
                },
                "companies": ordered_companies,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"[ok] {OUT} — {len(ordered_companies)} empresas; {total_conditions} condicionantes")


if __name__ == "__main__":
    main()
