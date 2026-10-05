"""Purga os leads de uma cidade que deixou de ser servida.

Motivo (Norfolk): `data.norfolk.gov/qva7-tzrf` e um cadastro fiscal de predios
(parcel tax roll) — owner, valor, acreage, transfer_date. Nao tem categoria de
obra nem estado de chamado, por isso nunca passou `_qualified_where`
(endereco + 16 oficios + gatilho). Ficava invisivel na dashboard mas continuava
a contar em `/api/metrics/public`, que faz `SELECT DISTINCT city` sem filtro, e
a landing page anunciava `cities_count: 5` com uma cidade que o produto nao
serve. A config foi removida de `enrichment.py`; este script limpa as linhas.

Por seguranca, o script:
  - e dry-run por omissao (nao escreve sem `--apply`);
  - copia integralmente as linhas para `leads_city_purge_backup` antes de apagar;
  - recusa apagar uma cidade que nao esteja numa lista explicita de `ALLOWED`;
  - nao toca em linhas com valor comercial (reserva/conversao/reveal).

Uso (DENTRO do servidor — a base de producao e um volume do Railway):
    python -m backend.scripts.purge_city --city NORFOLK            # dry-run
    python -m backend.scripts.purge_city --city NORFOLK --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import db as dbmod  # noqa: E402

BACKUP_TABLE = "leads_city_purge_backup"

# allow-list explicita: evita `purgar uma cidade por engano` num typo.
ALLOWED: Tuple[str, ...] = ("NORFOLK",)


def _city_variants(city: str) -> List[str]:
    """Chave de comparacao: a base guarda 'Norfolk', 'NORFOLK' e 'norfolk'.

    Nao usamos lista de variantes porque `.title()`/`.capitalize()` colidem numa
    palavra so e deixam passar a forma minuscula — o purge ficava incompleto.
    `UPPER(TRIM(city))` cobre todas as grafias numa so comparacao.
    """
    return [city.strip().upper()]


def _distinct_spellings(conn: sqlite3.Connection, key: str) -> List[str]:
    """Grafias reais presentes na base, so para o relatorio."""
    return [
        r["city"]
        for r in conn.execute(
            "SELECT DISTINCT city FROM leads WHERE UPPER(TRIM(city)) = ? ORDER BY city",
            (key,),
        ).fetchall()
    ]


def plan(conn: sqlite3.Connection, city: str) -> dict:
    variants = _city_variants(city)
    rows = conn.execute(
        f"SELECT * FROM leads WHERE UPPER(TRIM(city)) IN ({','.join('?' * len(variants))})",
        variants,
    ).fetchall()

    commercial, disposable = [], []
    for r in rows:
        keys = set(r.keys())
        is_commercial = (
            (r["reserved_by"] if "reserved_by" in keys else None) is not None
            or (r["converted_by"] if "converted_by" in keys else None) is not None
            or (r["contact_count"] or 0) > 0
            or str(r["lead_status"] or "").lower() in ("converted", "reserved")
        )
        (commercial if is_commercial else disposable).append(r)

    return {
        "city": city,
        "variants": variants,
        "spellings_found": _distinct_spellings(conn, variants[0]),
        "total": len(rows),
        "disposable": disposable,
        "commercial": commercial,
    }


def _verify(conn: sqlite3.Connection, city: str) -> dict:
    variants = _city_variants(city)
    left = conn.execute(
        f"SELECT COUNT(*) AS c FROM leads WHERE UPPER(TRIM(city)) IN ({','.join('?' * len(variants))})",
        variants,
    ).fetchone()["c"]
    cities = [
        r["city"]
        for r in conn.execute(
            "SELECT DISTINCT city FROM leads WHERE city IS NOT NULL AND TRIM(city) != '' ORDER BY city"
        ).fetchall()
    ]
    return {"remaining_rows": left, "cities": cities, "cities_count": len(cities)}


def run(city: str, apply: bool = False, log=lambda *a: None) -> dict:
    up = city.strip().upper()
    if up not in ALLOWED:
        raise ValueError(f"cidade {up!r} nao esta na allow-list {ALLOWED}")

    db_path = str(dbmod.DB_PATH)
    if not Path(db_path).exists():
        return {"ok": False, "error": "db_not_found", "db_path": db_path}

    conn = dbmod.get_connection()
    conn.row_factory = sqlite3.Row
    try:
        p = plan(conn, city)
        log(f"Base: {db_path}")
        log(f"Cidade: {up} (grafias na base: {p['spellings_found']})")
        log(f"Linhas encontradas:       {p['total']}")
        log(f"  descartaveis (lixo):    {len(p['disposable'])}")
        log(f"  com valor comercial:    {len(p['commercial'])} (NUNCA apagadas)")
        log("")

        for r in p["disposable"][:10]:
            log(f"  # {r['id']} city={r['city']!r} ext={r['external_id']!r} "
                f"cat={r['issue_category']!r} addr={str(r['address'])[:44]!r}")
        if len(p["disposable"]) > 10:
            log(f"  ... e mais {len(p['disposable']) - 10}")
        if p["commercial"]:
            log("")
            log("COM VALOR COMERCIAL (preservadas):")
            for r in p["commercial"][:10]:
                log(f"  # {r['id']} status={r['lead_status']!r} "
                    f"contacts={r['contact_count']} converted_by={r['converted_by']}")
        log("")

        if not p["disposable"]:
            log("Nada a apagar.")
            return {"ok": True, "applied": False, "city": up, "deleted": 0, **_verify(conn, city)}

        if not apply:
            log("DRY-RUN: nada escrito. Use --apply para apagar.")
            return {
                "ok": True, "applied": False, "city": up, "db_path": db_path,
                "to_delete": len(p["disposable"]),
                "preserved_commercial": len(p["commercial"]),
                **_verify(conn, city),
            }

        ids = [r["id"] for r in p["disposable"]]
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} "
                "(id INTEGER PRIMARY KEY, city TEXT, payload TEXT, "
                "purged_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            for r in p["disposable"]:
                conn.execute(
                    f"INSERT OR REPLACE INTO {BACKUP_TABLE} (id, city, payload) VALUES (?, ?, ?)",
                    (r["id"], r["city"], _dump(r)),
                )
            qs = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM leads WHERE id IN ({qs})", ids)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        log(f"Apagadas {len(ids)} linhas. Backup em {BACKUP_TABLE} ({len(ids)} registos).")
        return {
            "ok": True, "applied": True, "city": up, "db_path": db_path,
            "deleted": len(ids),
            "preserved_commercial": len(p["commercial"]),
            "backup_table": BACKUP_TABLE,
            **_verify(conn, city),
        }
    finally:
        conn.close()


def _dump(row: sqlite3.Row) -> str:
    import json

    return json.dumps({k: row[k] for k in row.keys()}, ensure_ascii=False, default=str)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Purga leads de uma cidade nao servida")
    ap.add_argument("--city", required=True, help=f"cidade a purgar (allow-list: {', '.join(ALLOWED)})")
    ap.add_argument("--apply", action="store_true", help="apaga de facto (default: dry-run)")
    args = ap.parse_args(argv)
    try:
        res = run(args.city, apply=args.apply, log=lambda m: print(m, flush=True))
    except ValueError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 2
    print()
    for k, v in res.items():
        print(f"{k}: {v}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
