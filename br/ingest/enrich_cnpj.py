"""Enriquecimento mínimo de CNPJ para a demo.

Usa a API pública Minha Receita (dados da Receita Federal) e guarda apenas
campos de empresa: CNAE, telefone/e-mail comercial, UF/município e n.º de sócios.
Nunca guarda CPF, nome de sócio ou telefone pessoal.
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
OUT = CACHE / "cnpj_cache.json"
API = "https://minhareceita.org/{cnpj}"


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


def normalize(payload: dict) -> dict:
    phone = ""
    ddd = str(payload.get("ddd1") or "").strip()
    number = str(payload.get("telefone1") or "").strip()
    if ddd and number:
        phone = f"({ddd}) {number}"
    return {
        "cnae": str(payload.get("cnae_fiscal") or ""),
        "cnae_desc": str(payload.get("cnae_fiscal_descricao") or ""),
        "phone": phone,
        "email": str(payload.get("email") or "").strip().lower(),
        "uf": str(payload.get("uf") or "").strip().upper(),
        "municipality": str(payload.get("municipio") or "").strip(),
        "status": str(payload.get("descricao_situacao_cadastral") or "").strip(),
        "qsa_count": len(payload.get("qsa") or []),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args()
    if OUT.exists():
        print(f"[skip] {OUT}")
        return
    cnpjs = ibama_cnpjs(args.limit)
    print(f"[info] {len(cnpjs)} CNPJs para enriquecer")
    data: dict[str, dict] = {}
    for index, cnpj in enumerate(cnpjs, start=1):
        try:
            response = requests.get(
                API.format(cnpj=cnpj),
                timeout=20,
                headers={"User-Agent": "MagicLeadsBR/0.1"},
            )
            if response.status_code == 200:
                data[cnpj] = normalize(response.json())
            else:
                print(f"  [{index}] {cnpj}: HTTP {response.status_code}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [{index}] {cnpj}: {exc!r}")
        time.sleep(0.35)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ok  ] {OUT} ({len(data)} registos)")


if __name__ == "__main__":
    main()
