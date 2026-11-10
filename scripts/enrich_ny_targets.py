"""Bridge de contractor_entities para prospect_companies com escopo estrito.

Só importa NY e apenas os trades operacionais aprovados (ENRICHMENT_TRADES).
Não busca dados novos; consome o que o scraper já gravou em contractor_entities.

Uso:
  python scripts/enrich_ny_targets.py
"""
from __future__ import annotations

import json

from backend.services import b2b_voice as v
from backend.services import showcase, voice_taxonomy


def main() -> None:
    v.init()
    allowed = set(voice_taxonomy.ENRICHMENT_TRADES)
    bridge = v.bridge_contractor_entities(
        limit=50000,
        state_filter="NY",
        allowed_trades=allowed,
    )
    trades = v.sync_company_trades()
    try:
        pages = showcase.build_pages()
    except Exception as exc:  # noqa: BLE001
        pages = {"ok": False, "error": str(exc)[:200]}
    segments = v.rebuild_segments()
    print(
        "ENRICH_NY",
        json.dumps(
            {
                "allowed_trades": sorted(allowed),
                "bridge": bridge,
                "trades": trades,
                "pages": pages,
                "segments": segments,
            },
            ensure_ascii=True,
            default=str,
        ),
    )


if __name__ == "__main__":
    main()
