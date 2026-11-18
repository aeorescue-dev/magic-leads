"""Executa o pipeline completo do protótipo Brasil."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script: str, *args: str) -> None:
    print(f"\n=== {script} {' '.join(args)}")
    subprocess.run([sys.executable, str(HERE / script), *args], check=True)


def main() -> None:
    run("fetch_sources.py", "--all")
    run("enrich_cnpj.py", "--limit", "60")
    run("build_demo.py")


if __name__ == "__main__":
    main()
