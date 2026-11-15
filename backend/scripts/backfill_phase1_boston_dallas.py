"""Backfill único da fila preventiva de Boston e Dallas.

O scheduler corre a cada 6h com limites pequenos (novos registos). Este script
carrega o backlog existente uma vez, depois do deploy e durante a janela
aprovada. Por omissão é dry-run; só escreve com `--write`.

Uso (dentro do serviço, após deploy):
    python -m backend.scripts.backfill_phase1_boston_dallas
    python -m backend.scripts.backfill_phase1_boston_dallas --write
"""

from __future__ import annotations

import argparse
from collections import Counter

from backend.services.phase1_enrichment import (
    Phase1EnrichmentService,
    phase1_enrichment,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="gravar na base")
    parser.add_argument("--bos-violations", type=int, default=1000)
    parser.add_argument("--bos-311", type=int, default=500)
    parser.add_argument("--bos-permits", type=int, default=500)
    parser.add_argument("--dal-code", type=int, default=25000)
    parser.add_argument("--dal-311", type=int, default=25000)
    parser.add_argument("--dal-permits", type=int, default=500)
    parser.add_argument("--window", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    service = Phase1EnrichmentService()
    candidates = service.build_candidates(
        hpd_complaints=0,
        hpd_deadlines=0,
        ecb=0,
        chi_violations=0,
        permit_rows=0,
        bos_violations=max(0, args.bos_violations),
        bos_311=max(0, args.bos_311),
        bos_permits=max(0, args.bos_permits),
        dal_code=max(0, args.dal_code),
        dal_311=max(0, args.dal_311),
        dal_permits=max(0, args.dal_permits),
        permit_window_days=max(1, args.window),
    )
    by_city = Counter(item.get("city") for item in candidates)
    print("CANDIDATES", len(candidates), dict(by_city))
    if not args.write:
        print("DRY_RUN: nada foi escrito. Use --write após aprovação.")
        return 0
    stats = phase1_enrichment.ingest(candidates=candidates)
    print("INGEST", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
