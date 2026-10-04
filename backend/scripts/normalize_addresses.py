"""Normaliza `leads.address`: deixa de embebir cidade/estado.

PORQUÊ
------
O scraper gravava a cidade e o estado dentro do `address`
("854 EAST NEW YORK AVENUE, NYC, NY") e também na coluna `city`. Como o
frontend juntava a coluna `city` ao `address` para exibir, o utilizador via
"854 EAST NEW YORK AVENUE, NYC, NY, NYC" em 100% dos leads.

A cidade passa a ser canónica na coluna `city`. O `address` fica só com a rua.

SEGURANÇA
---------
* Idempotente: correr duas vezes não muda nada (a 2.ª não encontra padrões).
* `--dry-run` é o default: nada é escrito sem `--apply`.
* NÃO toca em `external_id`/`source_type`, que são chave de deduplicação
  (`UNIQUE(external_id, source_type)`); o `external_id` vem do dataset
  (`unique_key`/`sr_number`), não do endereço.
* Existe também `UNIQUE(address, city)`. Normalizar pode fazer dois leads que
  já eram distintos (porque o address tinha formatos diferentes) passarem a ter
  o mesmo (address, city) — ver `DUPLICADOS DETECTADOS`. Por omissão esses
  pares são **saltados**, nunca apagados: apagá-los é uma decisão do dono do
  produto, não um efeito lateral de uma migração de formatação.
* As linhas saltadas não ficam com aspecto diferente: o frontend deduplica por
  conteúdo (`buildFullAddress`), portanto um address legado que já contém a
  cidade é exibido correctamente na mesma.
* Faz backup do address original em `leads_address_backup`, para reversão.

EXEMPLOS
--------
    python -m backend.scripts.normalize_addresses            # dry-run
    python -m backend.scripts.normalize_addresses --apply    # escreve
    python -m backend.scripts.normalize_addresses --apply --limit 500
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

BACKUP_TABLE = "leads_address_backup"

# Nome completo do estado -> sigla USPS. Necessário porque algumas fontes
# gravam state="Texas" enquanto o address traz a sigla "TX". Um heurístico
# (primeiras duas letras) daria "TE" e não casaria.
_US_STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}


def strip_city_state(address: str, city: str, state: str, zip_code: str) -> str:
    """Remove os segmentos finais que já existem em city/state/zip.

    Só remove segmentos INTEIROS que casem com a cidade/estado/zip, e nunca
    mais do que um segmento de cada. Não faz stripping parcial nem por palavras
    soltas: "EAST NEW YORK AVENUE" tem de sobreviver intacto, mesmo quando a
    cidade é "New York" / "NYC".

    Além dos valores exactos das colunas, reconhece o FORMATO do segmento:
    um ZIP dos EUA (12345 / 12345-6789) é removido mesmo quando a coluna
    `zip_code` está NULL, e um código de 2 letras é removido quando casa com o
    `state` da linha. Sem isto, "847 BROOKHURST DR, DALLAS, TX, 75218" com
    `zip_code` NULL não era normalizado, porque o segmento final não casava com
    nenhuma coluna.
    """
    parts = [p.strip() for p in str(address or "").split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return ""

    def up(v) -> str:
        return str(v or "").strip().upper()

    city_u, state_u, zip_u = up(city), up(state), up(zip_code)

    # Valores que podem ser removidos quando aparecem como segmento inteiro.
    wanted: set[str] = set()
    for v in (city_u, state_u, zip_u):
        if v:
            wanted.add(v)
    # "New York" -> "NEW YORK"; e o inverso, state="Texas" cobre o segmento "TX".
    if city_u:
        wanted.add(city_u.split()[0])
    if state_u:
        wanted.add(_US_STATE_ABBR.get(state_u.lower(), state_u))

    zip_re = re.compile(r"^\d{5}(-\d{4})?$")

    def is_removable(segment: str) -> bool:
        if segment.upper() in wanted:
            return True
        # ZIP no fim, mesmo sem zip_code na coluna.
        if zip_re.match(segment):
            return True
        # "TX 75218" / "NY 11210" -> remove o estado e o zip à mesma.
        bits = segment.upper().split()
        if len(bits) == 2 and bits[0] in wanted and zip_re.match(bits[1]):
            return True
        return False

    while len(parts) > 1 and is_removable(parts[-1]):
        parts.pop()

    return ", ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normaliza leads.address (remove cidade/estado embutidos)")
    parser.add_argument("--apply", action="store_true", help="Escreve as alterações (default: dry-run)")
    parser.add_argument("--limit", type=int, default=0, help="Máximo de linhas a processar (0 = todas)")
    args = parser.parse_args()

    db_path = os.environ.get("LEADS_DB_PATH", "data/leads.db")
    if not os.path.exists(db_path):
        print(f"Base de dados não encontrada: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT id, address, city, state, zip_code FROM leads "
            "WHERE address IS NOT NULL AND TRIM(address) <> ''"
        )
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"

        rows = list(conn.execute(sql))

        # Normaliza em memória primeiro, para só depois detectar colisões:
        # `UNIQUE(address, city)` impede dois leads de partilharem o par.
        proposed: dict[int, str] = {}
        skipped_no_city = 0
        for row in rows:
            new = strip_city_state(row["address"], row["city"], row["state"], row["zip_code"])
            if not row["city"]:
                skipped_no_city += 1
                continue
            if new and new != (row["address"] or "").strip():
                proposed[row["id"]] = new

        # Detecta os grupos que passariam a colidir.
        groups: dict[tuple[str, str], list[int]] = {}
        for row in rows:
            addr = proposed.get(row["id"], (row["address"] or "").strip())
            key = (addr.upper(), (row["city"] or "").upper())
            groups.setdefault(key, []).append(row["id"])

        collisions = {k: v for k, v in groups.items() if len(v) > 1}
        collided_ids = {i for ids in collisions.values() for i in ids}

        changes = []
        for row in rows:
            i = row["id"]
            if i not in proposed or i in collided_ids:
                continue
            changes.append((i, row["address"], proposed[i]))

        print(f"Base: {db_path}")
        print(f"Leads com address: {len(rows)}")
        print(f"A normalizar:      {len(changes)}")
        print(f"Sem city (inalterados): {skipped_no_city}")
        print()
        if collisions:
            print("DUPLICADOS DETECTADOS (address, city passaria a colidir):")
            for key, ids in sorted(collisions.items())[:10]:
                print(f"  {key[0]!r} / {key[1]!r} -> ids {sorted(ids)}")
            if len(collisions) > 10:
                print(f"  ... e mais {len(collisions) - 10}")
            print(
                f"  -> {len(collisions)} grupos, "
                f"{len(collided_ids)} linhas deixadas como estão (nada apagado)."
            )
            print("  -> estes prédios já estavam duplicados em production (formatos")
            print("     diferentes de address). Ver NOTA abaixo; para os fundir é")
            print("     preciso de uma decisão explícita.")
            print()

        for lead_id, old, new in changes[:10]:
            print(f"  #{lead_id}: {old!r} -> {new!r}")
        if len(changes) > 10:
            print(f"  ... e mais {len(changes) - 10}")

        if not changes:
            print("\nNada a fazer.")
            return 0

        if not args.apply:
            print("\nDRY-RUN: nada foi escrito. Use --apply para aplicar.")
            return 0

        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} "
            "(lead_id INTEGER PRIMARY KEY, address TEXT, migrated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        for lead_id, old, _new in changes:
            conn.execute(
                f"INSERT OR IGNORE INTO {BACKUP_TABLE} (lead_id, address) VALUES (?, ?)",
                (lead_id, old),
            )
        conn.executemany(
            "UPDATE leads SET address = ? WHERE id = ?",
            [(new, lead_id) for lead_id, _old, new in changes],
        )
        conn.commit()
        print(f"\nAplicado: {len(changes)} endereços normalizados.")
        print(f"Backup do original em {BACKUP_TABLE} (para reversão).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
