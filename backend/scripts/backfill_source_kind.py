"""Backfill `source_kind` a partir de `signal_type` (P0).

Uso:
    python -m backend.scripts.backfill_source_kind            # dry-run (read-only)
    python -m backend.scripts.backfill_source_kind --apply    # escreve

Regra (a mesma de `phase1_enrichment.build_candidates`):
    legal_obligation -> reactive / violation
    authorized_work  -> permit   / permit
    open_request     -> preventive / pre_inspection

Nao toca em `leads`, nao mexe em precos e nao corre sozinho.
Este ficheiro e' autónomo de proposito: pode ser executado no contentor de
producao (que ainda nao tem o codigo novo) como `python -`.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

DEFAULT_DB = os.getenv("DB_PATH") or "data/leads.db"

RULES = {
    "legal_obligation": ("reactive", "violation"),
    "authorized_work": ("permit", "permit"),
    "open_request": ("preventive", "pre_inspection"),
}


def _connect(db_path: str, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{Path(db_path).as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def _counts(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(signal_type), ''), '(null)') AS signal,
                   COALESCE(NULLIF(TRIM(source_kind), ''), '(null)') AS kind,
                   COALESCE(NULLIF(TRIM(source_type), ''), '(null)') AS type,
                   COUNT(*) AS n
              FROM opportunity_workflow
             GROUP BY signal, kind, type
             ORDER BY n DESC
            """
        ).fetchall()
    ]


def _planned(conn: sqlite3.Connection) -> list[dict]:
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(opportunity_workflow)")
    }
    city_expr = (
        "COALESCE(NULLIF(TRIM(city), ''), '(null)')"
        if "city" in columns
        else "'(null)'"
    )
    rows: list[dict] = []
    for signal, (kind, source_type) in RULES.items():
        for row in conn.execute(
            f"""
            SELECT {city_expr} AS city,
                   COUNT(*) AS n
              FROM opportunity_workflow
             WHERE TRIM(COALESCE(signal_type, '')) = ?
               AND (COALESCE(TRIM(source_kind), '') != ?
                    OR COALESCE(TRIM(source_type), '') != ?)
             GROUP BY city
             ORDER BY city
            """,
            (signal, kind, source_type),
        ).fetchall():
            rows.append(
                {
                    "signal": signal,
                    "target": kind,
                    "city": row["city"],
                    "n": int(row["n"] or 0),
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="escreve (sem isto e' dry-run)")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"ERRO: DB nao encontrada: {args.db}")
        return 2

    conn = _connect(args.db, read_only=not args.apply)
    try:
        before = _counts(conn)
        print("ANTES")
        for row in before:
            print(f"  {row['signal']:20} {row['kind']:12} {row['type']:16} {row['n']}")

        planned_rows = _planned(conn)
        total = sum(row["n"] for row in planned_rows)
        print("\nPLANEJADO")
        for row in planned_rows:
            print(
                f"  {row['city']:10} {row['signal']:20} -> {row['target']:12} {row['n']}"
            )
        print(f"  TOTAL {total}")

        if not args.apply:
            print(f"\nDRY-RUN: {total} linha(s) seriam reclassificadas; use --apply.")
            return 0

        conn.execute("BEGIN IMMEDIATE")
        for signal, (kind, source_type) in RULES.items():
            conn.execute(
                "UPDATE opportunity_workflow "
                "SET source_kind = ?, source_type = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE TRIM(COALESCE(signal_type, '')) = ?",
                (kind, source_type, signal),
            )
        conn.commit()

        after = _counts(conn)
        print("\nDEPOIS")
        for row in after:
            print(f"  {row['signal']:20} {row['kind']:12} {row['type']:16} {row['n']}")
        print(f"\nAPLICADO: {total} linha(s) reclassificadas.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
