"""scrape_cron.py — Roda o scraper nacional 311 a cada hora (Windows Task Scheduler).

Chama o endpoint /api/scraper/run do backend local. Se o backend não estiver
no ar, tenta iniciá-lo (fallback) e refaz a chamada.

Uso (Task Scheduler):
  <VENV_PYTHON> scripts\scrape_cron.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

BACKEND_URL = "http://127.0.0.1:8000"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(ROOT, "backend", "venv", "Scripts", "python.exe")
LOG_FILE = os.path.join(ROOT, "data", "scraper_cron.log")


def log(msg: str):
    line = f"[{datetime.now().isoformat()}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _run(endpoint: str) -> dict:
    req = urllib.request.Request(
        BACKEND_URL + endpoint,
        data=b"",
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read())


def main():
    # 1) Tenta chamar o backend que já está rodando
    try:
        res = _run("/api/scraper/run?max_cities=8")
        log(f"OK via backend: {json.dumps(res)}")
        return 0
    except urllib.error.URLError:
        log("Backend fora do ar — tentando iniciar...")
    except Exception as e:
        log(f"Erro ao chamar backend: {e!r} — tentando iniciar...")

    # 2) Fallback: inicia o backend em segundo plano e reenvia
    try:
        subprocess.Popen(
            [
                PYTHON,
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=ROOT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        log(f"Não foi possível iniciar o backend: {e!r}")
        return 2

    # espera o backend subir (até ~90s)
    for _ in range(18):
        time.sleep(5)
        try:
            with urllib.request.urlopen(BACKEND_URL + "/health", timeout=5) as r:
                if r.status == 200:
                    break
        except Exception:
            continue
    else:
        log("Backend não subiu a tempo.")
        return 2

    try:
        res = _run("/api/scraper/run?max_cities=8")
        log(f"OK após iniciar backend: {json.dumps(res)}")
        return 0
    except Exception as e:
        log(f"Erro final: {e!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
