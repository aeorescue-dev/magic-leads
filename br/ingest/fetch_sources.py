"""Baixa e prepara as fontes do protótipo Brasil.

Uso:
    python fetch_sources.py --all
    python fetch_sources.py --ibama --sislic --mg --geo

Os ficheiros ficam em br/.cache. Se já existirem, não são rebaixados.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import requests

BR = Path(__file__).resolve().parents[1]
CACHE = BR / ".cache"
ASSETS = BR / "web" / "assets"

IBAMA_URL = (
    "https://stibamadadosabertosprd.blob.core.windows.net/"
    "dados-abertos/dados/SIFISC/auto_infracao/auto_infracao/auto_infracao_csv.zip"
)
SISLIC_URL = (
    "https://stibamadadosabertosprd.blob.core.windows.net/"
    "dados-abertos/dados/SISLIC/sislic-licencas.csv"
)
MG_WFS = "https://geoserver.meioambiente.mg.gov.br/ows"
MG_LAYER = "IDE:ide_2101_mg_empreendimentos_licenciados_pto"
STATES_GEO = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
    "?formato=application/vnd.geo+json&qualidade=intermediaria&intrarregiao=UF"
)
MUNI_CSV = (
    "https://raw.githubusercontent.com/kelvins/Municipios-Brasileiros/"
    "main/csv/municipios.csv"
)


def _download(url: str, path: Path, *, timeout: int = 180) -> Path:
    if path.exists() and path.stat().st_size > 0:
        print(f"[skip] {path.name} ({path.stat().st_size:,} bytes)")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[get ] {url}")
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        done = 0
        tmp = path.with_suffix(path.suffix + ".part")
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
                    done += len(chunk)
                    if total and done % (20 * 1024 * 1024) < 1024 * 1024:
                        print(f"       {done / 1_048_576:.0f}/{total / 1_048_576:.0f} MB")
        shutil.move(str(tmp), str(path))
    print(f"[ok  ] {path.name} ({path.stat().st_size:,} bytes)")
    return path


def fetch_ibama() -> Path:
    return _download(IBAMA_URL, CACHE / "ibama_auto_infracao.zip")


def fetch_sislic() -> Path:
    return _download(SISLIC_URL, CACHE / "sislic.csv")


def fetch_mg() -> Path:
    path = CACHE / "mg_licencas.json"
    if path.exists() and path.stat().st_size > 0:
        print(f"[skip] {path.name} ({path.stat().st_size:,} bytes)")
        return path
    print("[get ] MG WFS")
    response = requests.get(
        MG_WFS,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": MG_LAYER,
            "outputFormat": "application/json",
            "count": 25000,
        },
        timeout=180,
        headers={"User-Agent": "MagicLeadsBR/0.1"},
    )
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    print(f"[ok  ] {path.name} ({path.stat().st_size:,} bytes)")
    return path


def fetch_geo() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    _download(STATES_GEO, ASSETS / "br-states.geojson")
    _download(MUNI_CSV, ASSETS / "municipios.csv")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--ibama", action="store_true")
    parser.add_argument("--sislic", action="store_true")
    parser.add_argument("--mg", action="store_true")
    parser.add_argument("--geo", action="store_true")
    args = parser.parse_args()
    if args.all or args.ibama:
        fetch_ibama()
    if args.all or args.sislic:
        fetch_sislic()
    if args.all or args.mg:
        fetch_mg()
    if args.all or args.geo:
        fetch_geo()


if __name__ == "__main__":
    main()
