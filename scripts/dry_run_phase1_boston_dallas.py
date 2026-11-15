"""Dry-run dos novos fetchers de Boston e Dallas.

Não escreve na base: chama apenas `build_candidates` (rede + mapeamento) e
imprime a contagem por cidade, tipo de sinal, categoria e prazos.

Uso:
    python -m scripts.dry_run_phase1_boston_dallas
"""

from __future__ import annotations

from collections import Counter

from backend.services.phase1_enrichment import Phase1EnrichmentService


def main() -> int:
    service = Phase1EnrichmentService()
    candidates = service.build_candidates(
        hpd_complaints=0,
        hpd_deadlines=0,
        ecb=0,
        chi_violations=0,
        permit_rows=0,
        bos_violations=1000,
        bos_311=500,
        bos_permits=500,
        dal_code=25000,
        dal_311=25000,
        dal_permits=500,
        permit_window_days=30,
    )

    by_city = Counter(item.get("city") for item in candidates)
    by_signal = Counter((item.get("city"), item.get("signal_type")) for item in candidates)
    by_category = Counter((item.get("city"), item.get("category")) for item in candidates)
    with_deadline = Counter(
        item.get("city") for item in candidates if item.get("compliance_deadline")
    )
    with_value = Counter(
        item.get("city") for item in candidates if item.get("job_value")
    )

    print("TOTAL", len(candidates))
    print("BY_CITY", dict(by_city))
    print("BY_SIGNAL", {f"{city}/{signal}": count for (city, signal), count in by_signal.items()})
    print("WITH_DEADLINE", dict(with_deadline))
    print("WITH_VALUE", dict(with_value))
    print("TOP_CATEGORIES")
    for (city, category), count in by_category.most_common(20):
        print(f"  {city:8} {category:16} {count}")

    print("SAMPLES")
    seen: Counter = Counter()
    for item in candidates:
        city = item.get("city")
        if seen[city] >= 2:
            continue
        seen[city] += 1
        print(
            "  ",
            city,
            "|",
            item.get("signal_type"),
            "|",
            item.get("category"),
            "|",
            item.get("received_at"),
            "|",
            item.get("description"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
