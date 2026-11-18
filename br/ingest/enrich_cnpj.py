"""Enriquecimento de CNPJ para a demo.

Usa a API pública Minha Receita (dados da Receita Federal) e guarda:
  - empresa: CNAE, telefone/e-mail comercial, UF/município, porte, capital, abertura;
  - sócios (QSA): nome, qualificação e data de entrada — **nunca CPF**.

O CPF do sócio nunca é guardado: quando a fonte devolve CPF mascarado ou
apenas o número, o campo é descartado. Para sócio PJ guarda-se o CNPJ público.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
import zipfile
from pathlib import Path

import requests

BR = Path(__file__).resolve().parents[1]
CACHE = BR / ".cache"
ASSETS = BR / "web" / "assets"
OUT = CACHE / "cnpj_cache.json"
API = "https://minhareceita.org/{cnpj}"


def demo_cnpjs(limit: int) -> list[str]:
    """CNPJs que realmente aparecem no snapshot da demo (prioridade)."""
    path = ASSETS / "data.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for item in payload.get("leads") or []:
        digits = re.sub(r"\D", "", str(item.get("cnpj") or ""))
        if len(digits) == 14 and digits not in seen:
            seen.add(digits)
            found.append(digits)
            if len(found) >= limit:
                break
    return found


def ibama_cnpjs(limit: int) -> list[str]:
    path = CACHE / "ibama_auto_infracao.zip"
    if not path.exists():
        return []
    found: list[str] = []
    seen: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.endswith("2026.csv")]
        if not names:
            return []
        with archive.open(names[0]) as handle:
            reader = csv.DictReader(
                io.TextIOWrapper(handle, encoding="utf-8-sig", newline=""),
                delimiter=";",
            )
            for row in reader:
                if (row.get("TP_PESSOA_INFRATOR") or "").strip().upper() != "PJ":
                    continue
                digits = re.sub(r"\D", "", row.get("CPF_CNPJ_INFRATOR") or "")
                if len(digits) == 14 and digits not in seen:
                    seen.add(digits)
                    found.append(digits)
                    if len(found) >= limit:
                        break
    return found


def format_phone(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return ""


def clean_partner(entry: dict) -> dict | None:
    name = str(entry.get("nome_socio") or "").strip()
    if not name:
        return None
    document = re.sub(r"\D", "", str(entry.get("cnpj_cpf_do_socio") or ""))
    is_company = len(document) == 14
    return {
        "name": name,
        "role": str(entry.get("qualificacao_socio") or "").strip(),
        "since": str(entry.get("data_entrada_sociedade") or "").strip(),
        "doc_type": "PJ" if is_company else "PF",
        "doc": (
            f"{document[:2]}.{document[2:5]}.{document[5:8]}/{document[8:12]}-{document[12:]}"
            if is_company
            else None  # CPF nunca é guardado
        ),
    }


def normalize(payload: dict) -> dict:
    phone = format_phone(payload.get("ddd_telefone_1")) or format_phone(payload.get("ddd_telefone_2"))
    partners = [partner for partner in (clean_partner(item) for item in payload.get("qsa") or []) if partner]
    return {
        "cnae": str(payload.get("cnae_fiscal") or ""),
        "cnae_desc": str(payload.get("cnae_fiscal_descricao") or ""),
        "phone": phone,
        "email": str(payload.get("email") or "").strip().lower(),
        "uf": str(payload.get("uf") or "").strip().upper(),
        "municipality": str(payload.get("municipio") or "").strip(),
        "status": str(payload.get("descricao_situacao_cadastral") or "").strip(),
        "status_date": str(payload.get("data_situacao_cadastral") or "").strip(),
        "opened_at": str(payload.get("data_inicio_atividade") or "").strip(),
        "legal_nature": str(payload.get("natureza_juridica") or "").strip(),
        "size": str(payload.get("porte") or "").strip(),
        "capital_social": payload.get("capital_social"),
        "qsa_count": len(partners),
        "partners": partners,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=800)
    parser.add_argument("--refresh", action="store_true", help="Re-consulta CNPJs já em cache")
    args = parser.parse_args()
    data: dict[str, dict] = {}
    if OUT.exists() and not args.refresh:
        try:
            data = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    cnpjs = demo_cnpjs(args.limit) or ibama_cnpjs(args.limit)
    pending = [cnpj for cnpj in cnpjs if cnpj not in data]
    print(f"[info] {len(cnpjs)} CNPJs no snapshot; {len(pending)} por enriquecer; {len(data)} em cache")
    for index, cnpj in enumerate(pending, start=1):
        try:
            response = requests.get(
                API.format(cnpj=cnpj),
                timeout=20,
                headers={"User-Agent": "MagicLeadsBR/0.1"},
            )
            if response.status_code == 200:
                data[cnpj] = normalize(response.json())
            else:
                print(f"  [{index}/{len(pending)}] {cnpj}: HTTP {response.status_code}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{index}/{len(pending)}] {cnpj}: {exc!r}", flush=True)
        if index % 25 == 0:
            OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  ... {index}/{len(pending)} guardados", flush=True)
        time.sleep(0.35)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ok  ] {OUT} ({len(data)} registos)")


if __name__ == "__main__":
    main()
