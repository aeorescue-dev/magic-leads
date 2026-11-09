"""Reclassificacao segura de categorias (P1).

Uso:
    python -m backend.scripts.reclassify_categories            # dry-run
    python -m backend.scripts.reclassify_categories --apply --confirm
    python -m backend.scripts.reclassify_categories --json-out /tmp/diff.json

Regras de seguranca:
* dry-run e' o default; nada e' escrito sem --apply;
* --apply exige --confirm;
* antes de escrever faz um backup SQLite consistente para
  `<DB_PATH>.bak-YYYYMMDD-HHMMSS`;
* imprime o diff por cidade/fonte/transicao e uma amostra de cada mudanca;
* a classificacao usa `category_taxonomy.classify` (a mesma do ingest e da UI).

Nao toca em voz, Telnyx, DIDs, pacing ou campanhas.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Permite `python backend/scripts/reclassify_categories.py`.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.models.schemas import IssueCategory  # noqa: E402
from backend.services.category_taxonomy import (  # noqa: E402
    TRADE_CATEGORIES,
    UNCLASSIFIED,
    classify,
    normalize_category,
)
from backend.services.db import DB_PATH, get_connection, refresh_lead_quality  # noqa: E402


def _new_category(row: dict[str, Any]) -> IssueCategory:
    source_type = str(row.get("source_type") or "").strip().lower()
    stored = str(row.get("issue_category") or "").strip()

    # B2B: o rotulo do parceiro e' a fonte primaria. Se ja' e' canonico,
    # preserva; se e' um alias conhecido, normaliza; se e' desconhecido,
    # tenta a descricao e, no limite, Unclassified.
    if source_type == "import_b2b":
        canonical = normalize_category(stored)
        if canonical in TRADE_CATEGORIES:
            return IssueCategory(canonical)
        result = classify(
            row.get("issue_description"),
            source_type,
            city=row.get("city"),
            case_title=row.get("case_title"),
            descriptor=row.get("descriptor"),
        )
        return result.category

    result = classify(
        row.get("issue_description"),
        source_type,
        city=row.get("city"),
        case_title=row.get("case_title"),
        descriptor=row.get("descriptor"),
    )
    return result.category


def _backup(db_path: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = f"{db_path}.bak-{stamp}"
    src = sqlite3.connect(db_path, timeout=30.0)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def run(*, apply: bool, confirm: bool, json_out: str | None = None) -> dict[str, Any]:
    if apply and not confirm:
        raise SystemExit("--apply exige --confirm (dry-run e' o default)")

    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, city, source_type, issue_category, issue_description, "
            "case_title, descriptor FROM leads ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    transitions: Counter[tuple[str, str, str, str]] = Counter()
    by_city: Counter[tuple[str, str]] = Counter()
    by_source: Counter[tuple[str, str]] = Counter()
    samples: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    updates: list[tuple[str, int]] = []
    old_counts: Counter[str] = Counter()
    new_counts: Counter[str] = Counter()

    for raw in rows:
        row = dict(raw)
        old = str(row.get("issue_category") or "")
        new = _new_category(row).value
        old_counts[old] += 1
        new_counts[new] += 1
        if old == new:
            continue
        city = str(row.get("city") or "")
        src = str(row.get("source_type") or "")
        key = (city, src, old, new)
        transitions[key] += 1
        by_city[(city, new)] += 1
        by_source[(src, new)] += 1
        updates.append((new, int(row["id"])))
        if len(samples[key]) < 3:
            desc = str(row.get("issue_description") or "")[:160]
            samples[key].append(desc)

    result: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "db": DB_PATH,
        "rows": len(rows),
        "would_change": len(updates),
        "old_counts": dict(old_counts.most_common()),
        "new_counts": dict(new_counts.most_common()),
        "new_unclassified": new_counts.get(UNCLASSIFIED, 0),
        "by_city_new_category": {
            f"{city}|{cat}": n for (city, cat), n in by_city.most_common()
        },
        "by_source_new_category": {
            f"{src}|{cat}": n for (src, cat), n in by_source.most_common()
        },
        "transitions": [
            {
                "city": city,
                "source": src,
                "from": old,
                "to": new,
                "n": n,
                "samples": samples[(city, src, old, new)],
            }
            for (city, src, old, new), n in transitions.most_common()
        ],
    }

    if json_out:
        Path(json_out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if not apply:
        return result

    backup_path = _backup(DB_PATH)
    result["backup"] = backup_path

    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "UPDATE leads SET issue_category=? WHERE id=?", updates
        )
        # Recalcula uma vez os predicados materializados; os triggers por linha
        # fariam o mesmo, mas esta passagem e' explicita e mais barata.
        refresh_lead_quality(conn, "1=1", ())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    result["applied"] = len(updates)
    if json_out:
        Path(json_out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Reclassifica categorias com dry-run/backup.")
    parser.add_argument("--apply", action="store_true", help="escreve na BD")
    parser.add_argument("--confirm", action="store_true", help="confirma a escrita")
    parser.add_argument("--json-out", default=None, help="grava o diff em JSON")
    args = parser.parse_args()
    result = run(apply=args.apply, confirm=args.confirm, json_out=args.json_out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
