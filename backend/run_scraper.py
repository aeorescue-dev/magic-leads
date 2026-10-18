"""CLI de execucao unica do scraper (ponto de entrada legado).

Delega para o MESMO worker da API (`POST /api/scraper/run`, backend.main) para
que a ingestao nunca divirja do que o painel mostra. O codigo antigo chamava
`socrata_scraper.run()`, que nao existe (o scraper e um objecto sem `run`), e
falhava sempre com AttributeError antes de tocar numa base de dados.

Uso: python -m backend.run_scraper [max_cities] [hours]
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.main import _scrape_runs, _scrape_worker  # noqa: E402


def main() -> int:
    max_cities = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else None

    run_id = uuid.uuid4().hex[:12]
    # O worker le o estado de _scrape_runs[run_id] na primeira linha; regista
    # aqui como o endpoint faz, senao rebenta com KeyError.
    _scrape_runs[run_id] = {
        "run_id": run_id,
        "running": True,
        "started_at": datetime.utcnow().isoformat(),
        "inserted": 0,
        "total_raw": 0,
        "status": "running",
        "error": None,
    }
    asyncio.run(_scrape_worker(run_id, max_cities=max_cities, hours_override=hours))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
