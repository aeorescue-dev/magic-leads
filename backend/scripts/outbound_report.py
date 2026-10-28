#!/usr/bin/env python3
"""Relatorio de envios de outbound (colunas correctas).

Substitui as queries ad-hoc que falhavam com
`no such column: provider_message_id` — a coluna real e' `provider_id`.

Uso:
    python -m backend.scripts.outbound_report
    python -m backend.scripts.outbound_report --batch 31
    python -m backend.scripts.outbound_report --csv relatorio.csv
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys


def _connect() -> sqlite3.Connection:
    from ..services.db import DB_PATH as _DB_PATH
    db = _DB_PATH
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def _summary(con: sqlite3.Connection, batch: int | None) -> None:
    where = "WHERE batch_id = ?" if batch else ""
    params = (batch,) if batch else ()
    rows = con.execute(
        f"SELECT status, COUNT(1) c FROM outbound_messages {where} GROUP BY status",
        params,
    ).fetchall()
    print("=== por estado ===")
    for r in rows:
        print(f"   {r['status']:10} {r['c']}")

    print("\n=== por caixa ===")
    q = """
    SELECT COALESCE(mb.email, '(sem caixa)') AS mailbox, m.status, COUNT(1) c
    FROM outbound_messages m
    LEFT JOIN sending_mailboxes mb ON mb.id = m.mailbox_id
    """
    if batch:
        q += "WHERE m.batch_id = ? "
    q += "GROUP BY mailbox, m.status ORDER BY mailbox, m.status"
    for r in con.execute(q, params):
        print(f"   {r['mailbox']:28} {r['status']:10} {r['c']}")

    print("\n=== erros ===")
    q = "SELECT id, to_email, error FROM outbound_messages WHERE COALESCE(error,'') <> ''"
    if batch:
        q += " AND batch_id = ?"
    q += " ORDER BY id DESC LIMIT 15"
    errs = con.execute(q, params).fetchall()
    if not errs:
        print("   (nenhum)")
    for r in errs:
        print(f"   #{r['id']} {r['to_email']:32} {str(r['error'])[:70]}")


def _messages(con: sqlite3.Connection, batch: int | None) -> list[dict]:
    q = """
    SELECT m.id, m.batch_id, m.to_email, m.subject, m.status,
           COALESCE(mb.email, '') AS from_addr, m.provider_id,
           m.queued_at, m.sent_at, COALESCE(m.error, '') AS error,
           m.sequence_step, m.next_step_at
    FROM outbound_messages m
    LEFT JOIN sending_mailboxes mb ON mb.id = m.mailbox_id
    """
    params: tuple = ()
    if batch:
        q += "WHERE m.batch_id = ? "
        params = (batch,)
    q += "ORDER BY m.id"
    return [dict(r) for r in con.execute(q, params)]


def main() -> int:
    ap = argparse.ArgumentParser(description="Relatorio de envios outbound")
    ap.add_argument("--batch", type=int, help="filtrar por lote")
    ap.add_argument("--csv", help="exportar as mensagens para CSV")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    con = _connect()
    try:
        _summary(con, args.batch)

        rows = _messages(con, args.batch)
        print(f"\n=== mensagens ({len(rows)}) ===")
        for r in rows[: args.limit]:
            print(f"   #{r['id']:<4} {r['status']:9} {r['to_email'][:34]:34} "
                  f"{r['from_addr'][:26]:26} id={r['provider_id'] or '-'}")
        if len(rows) > args.limit:
            print(f"   ... (+{len(rows) - args.limit} omitidas; use --limit)")

        if args.csv:
            with open(args.csv, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["id"])
                w.writeheader()
                w.writerows(rows)
            print(f"\nCSV: {args.csv}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
