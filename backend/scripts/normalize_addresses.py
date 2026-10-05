"""Normaliza `leads.address` e funde prédios duplicados.

DUAS CORREÇÕES, NA MESMA PASSAGEM
=================================

1. Normalização do endereço
---------------------------
O scraper gravava a cidade e o estado dentro do `address`
("854 EAST NEW YORK AVENUE, NYC, NY") e também na coluna `city`. Como o
frontend juntava a coluna `city` ao `address` para exibir, o utilizador via
"854 EAST NEW YORK AVENUE, NYC, NY, NYC" em 100% dos leads.

A cidade passa a ser canónica na coluna `city`; o `address` fica só com a rua.

2. Fusão de prédios duplicados
------------------------------
O scraper de NYC produzia DOIS formatos para a mesma rua — `"RUA, NYC, NY"`
(sem zip) e `"RUA, NY 11210"` (com zip). Como a tabela tem
`UNIQUE(address, city)` e o `INSERT` faz `ON CONFLICT(address, city) DO
UPDATE` (ver `backend/services/db.py`), o schema assumes UM lead por prédio. Os
dois formatos, porém, davam chaves diferentes, e por isso o mesmo prédio
ficava com DUAS linhas em vez de a segunda actualizar a primeira.

Importante: as duas linhas são METHODS reclamações diferentes (uma violação de
porta, outra de estrutura) do MESMO prédio. Fundir não é remover lixo: é
aceitar a mesma regra que o `ON CONFLICT` já aplica todos os dias quando duas
reclamações do mesmo prédio chegam no mesmo scrape. A linha que sobrevive é a
mais rica; a reclamação absorvida fica guardada integralmente em
`leads_merge_backup` para reversão.

SEGURANÇA
---------
* Idempotente: correr duas vezes não muda nada.
* `--dry-run` é o default: nada é escrito sem `--apply`.
* A fusão é opt-in (`--merge-duplicates`) e nunca toca em linhas que tenham
  valor comercial ou activity de utilizador: reserva, conversão, contacto
  revelado ou `contact_count > 0`. Esses grupos são saltados e reportados.
* Antes de apagar, a linha absorvida é copiada na íntegra para
  `leads_merge_backup` (JSON), com o `id` que herdou. Reversão possível.
* Campos de enriquecimento que o vencedor não tem são copiados do perdedor
  (ex.: o dono aparecia só numa das duas linhas).
* O `external_id`/`source_type` não é alterado: é chave de deduplicação e vem
  do dataset, não do endereço.

EXEMPLOS
--------
    python -m backend.scripts.normalize_addresses                       # dry-run
    python -m backend.scripts.normalize_addresses --apply               # normaliza
    python -m backend.scripts.normalize_addresses --apply \
        --merge-duplicates                                              # normaliza + funde
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# A regra de stripping vive em `lead_rules` para que a migração e a ingestão
# usem exatamente a mesma. Divergir entre as duas fazia a migração limpar o que
# o scraper voltava a sujar no mesmo dia.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.services.lead_rules import strip_city_state as _strip_city_state  # noqa: E402

BACKUP_TABLE = "leads_address_backup"
MERGE_BACKUP_TABLE = "leads_merge_backup"

# Campos de enriquecimento: se o vencedor não os tiver, herdamos do perdedor em
# vez de os perder. `external_id`/`source_type` ficam de fora de propósito.
ENRICHMENT_FIELDS = (
    "owner_name",
    "owner_phone",
    "owner_email",
    "owner_status",
    "mailing_address",
    "lat",
    "lng",
    "bbl",
    "address_unit",
    "zip_code",
    "image_url",
    "source_url",
    "county",
)

# `lead_status` que indica que o lead ainda está livre para fusão. Qualquer
# outro valor significa que alguém fez alguma coisa com ele.
PRISTINE_STATUSES = ("available", "", "new", "found")

def strip_city_state(address: str, city: str, state: str, zip_code: str) -> str:
    """Reexporta `lead_rules.strip_city_state` (mesma regra, fonte única)."""
    return _strip_city_state(address, city, state, zip_code)


def collision_key(row: sqlite3.Row) -> tuple[str, str]:
    """Chave canónica (address, city) — a mesma que o UNIQUE impõe."""
    addr = strip_city_state(row["address"], row["city"], row["state"], row["zip_code"])
    return (addr.upper(), (row["city"] or "").upper())


def _has_value(value) -> bool:
    """O campo tem conteúdo, seja INTEGER, TEXT ou None.

    `reserved_by`/`converted_by` são INTEGER (REFERENCES users(id)) no schema
    real, não TEXT. Chamar `.strip()` em cima de um int rebenta — e rebentou em
    produção (HTTP 500) só depois de a migração estar deployada. E 0 conta como
    vazio: os ids de utilizador começam em 1, portanto 0 é o estado "sem dono".
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value != 0
    return True


def is_pristine(row: sqlite3.Row) -> bool:
    """A linha nunca foi tocada por um utilizador nem por uma venda?"""
    # Um schema mais antigo pode não ter todas estas colunas; em vez de rebentar,
    # uma coluna ausente conta como "sem actividade".
    keys = set(row.keys())

    def g(name, default=None):
        return row[name] if name in keys else default

    if _has_value(g("reserved_by")):
        return False
    if _has_value(g("converted_by")) or _has_value(g("converted_at")):
        return False
    if _has_value(g("revealed_at")):
        return False
    if (g("contact_count", 0) or 0) > 0:
        return False
    if str(g("lead_status") or "").strip().lower() not in PRISTINE_STATUSES:
        return False
    return True


def available_enrichment_fields(row: sqlite3.Row) -> tuple[str, ...]:
    """Só os campos de enriquecimento que existem mesmo nesta tabela."""
    keys = set(row.keys())
    return tuple(f for f in ENRICHMENT_FIELDS if f in keys)


def merge_rank(row: sqlite3.Row) -> tuple:
    """Ordem de preferência: quem tem mais dados sobrevive."""
    return (
        1 if row["owner_name"] else 0,
        1 if row["owner_phone"] else 0,
        1 if row["owner_email"] else 0,
        1 if row["mailing_address"] else 0,
        1 if row["lat"] is not None else 0,
        sum(1 for f in available_enrichment_fields(row) if row[f] not in (None, "")),
        str(row["date_reported"] or ""),
        int(row["id"]),
    )


def plan_normalisation(rows: list[sqlite3.Row]) -> dict[int, str]:
    """address actual -> address normalizado, só para quem precisa de mudanca."""
    plan: dict[int, str] = {}
    for row in rows:
        if not row["city"]:
            continue
        new = strip_city_state(row["address"], row["city"], row["state"], row["zip_code"])
        if new and new != (row["address"] or "").strip():
            plan[row["id"]] = new
    return plan


def find_collision_groups(rows: list[sqlite3.Row]) -> dict[tuple[str, str], list[sqlite3.Row]]:
    """Grupos que passam a partilhar (address, city) — prédios duplicados."""
    groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(collision_key(row), []).append(row)
    return {k: v for k, v in groups.items() if len(v) > 1}


def blocking_reasons(rows: list[sqlite3.Row]) -> list[str]:
    """Porque é que um grupo não pode ser fundido — para o relatório."""
    reasons: list[str] = []
    if any(_has_value(r["reserved_by"]) for r in rows):
        reasons.append("reserved_by")
    if any(_has_value(r["converted_by"]) or _has_value(r["converted_at"]) for r in rows):
        reasons.append("converted")
    if any(_has_value(r["revealed_at"]) for r in rows):
        reasons.append("revealed")
    if any((r["contact_count"] or 0) > 0 for r in rows):
        reasons.append("contact_count")
    statuses = sorted(
        {str(r["lead_status"] or "").strip().lower() for r in rows}
        - set(PRISTINE_STATUSES)
    )
    if statuses:
        reasons.append("lead_status=" + ",".join(s for s in statuses if s))
    return reasons


def plan_merges(groups: dict[tuple[str, str], list[sqlite3.Row]]) -> tuple[list[dict], list[dict], list[dict]]:
    """Separa os grupos fundiveis dos que tem de ser saltados por seguranca.

    Devolve (mergeable, blocked, preserved).

    `preserved` e o caso que motivou a politica: dois registos do MESMO predio
    vindos de fontes/ocorrencias diferentes (`SR30309JR` e `SR30305JR`, dois
    eventos 311 distintos no mesmo endereco). Colidir no `UNIQUE(address, city)`
    nao e motivo para os fundir: fundir apaga o `external_id`, a categoria e a
    data do segundo, e o cliente perde um contacto real. Preferimos manter as
    linhas separadas e nao as normalizar, para naoirem de colidir.

    So se funde quando as linhas partilham o mesmo `external_id`, ou seja, o
    mesmo registo de origem ingerido duas vezes. Aí não há nada a perder.
    """
    mergeable: list[dict] = []
    blocked: list[dict] = []
    preserved: list[dict] = []
    for key, rows in groups.items():
        if not all(is_pristine(r) for r in rows):
            # Guardamos o porquê e os endereços para o relatório: sem isto, um
            # `blocked_merges: 1` não diz ao operador o que fazer a seguir.
            blocked.append(
                {
                    "key": key,
                    "rows": rows,
                    "reasons": blocking_reasons(rows),
                    "ids": sorted(int(r["id"]) for r in rows),
                    "addresses": sorted({str(r["address"] or "") for r in rows}),
                }
            )
            continue

        # Mesmo `external_id` = mesmo registo de origem duas vezes: fundir é
        # seguro. `external_id` diferente = eventos diferentes no mesmo prédio:
        # preservar, e é o caminho normal em datasets 311.
        ext_ids = {str(r["external_id"] or "").strip() for r in rows}
        if len(ext_ids) > 1:
            preserved.append(
                {
                    "key": key,
                    "rows": rows,
                    "reasons": ["distinct_external_id"],
                    "ids": sorted(int(r["id"]) for r in rows),
                    "external_ids": sorted(e for e in ext_ids if e),
                    "addresses": sorted({str(r["address"] or "") for r in rows}),
                }
            )
            continue

        ordered = sorted(rows, key=merge_rank, reverse=True)
        winner, losers = ordered[0], ordered[1:]
        # Não apagar nada que o vencedor não consiga substituir. Só se
        # consideram campos que existam na tabela.
        fields = available_enrichment_fields(winner)
        absorbed = {}
        for loser in losers:
            for f in fields:
                if winner[f] in (None, "") and loser[f] not in (None, ""):
                    absorbed[f] = loser[f]
        mergeable.append(
            {"key": key, "winner": winner, "losers": losers, "absorbed": absorbed}
        )
    return mergeable, blocked, preserved


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _blocked_summary(blocked: list[dict]) -> list[dict]:
    """Os grupos bloqueados, de forma JSON-serializável e sem payloads."""
    return [
        {
            "ids": b["ids"],
            "reasons": b["reasons"],
            "addresses": b["addresses"],
            "city": b["key"][1],
        }
        for b in blocked
    ]


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _verify(conn: sqlite3.Connection) -> dict:
    """Contadores de prova, para o operador não ter de confiar no log.

    `empty_addresses` e `rows_with_city_in_address` são as duas regressões que
    esta migração existe para eliminar; se voltarem a subir, algo escreveste.
    Uma base mais antiga sem estas colunas dá 0 em vez de rebentar.
    """
    cols = _columns(conn, "leads") if _table_exists(conn, "leads") else set()
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    out: dict = {}
    if "address" in cols:
        out["empty_addresses"] = q(
            "SELECT COUNT(*) FROM leads WHERE address IS NULL OR TRIM(address) = ''"
        )
    if "address" in cols and "city" in cols:
            # Substring: apanha tambem nomes de rua legitimos como
            # "NEW YORK AVE" numa cidade chamada NEW YORK. Util para ver a
            # ordem de grandeza, nao para acusar ninguem.
            out["rows_with_city_in_address"] = q(
                "SELECT COUNT(*) FROM leads WHERE address IS NOT NULL AND city IS NOT NULL"
                " AND TRIM(city) <> ''"
                " AND UPPER(address) LIKE '%' || UPPER(TRIM(city)) || '%'"
            )
            # A assinatura real do bug: a cidade no FIM do address
            # ("123 MAIN ST, AUSTIN" / "123 MAIN ST AUSTIN"). Esta e a
            # contagem accionavel; a de cima e so contexto.
            out["rows_ending_with_city"] = q(
                "SELECT COUNT(*) FROM leads WHERE address IS NOT NULL AND city IS NOT NULL"
                " AND TRIM(city) <> ''"
                " AND UPPER(TRIM(address)) LIKE '%' || UPPER(TRIM(city))"
            )
            out["duplicate_address_city_groups"] = q(
                "SELECT COUNT(*) FROM (SELECT address, city FROM leads"
                " WHERE address IS NOT NULL AND TRIM(address) <> ''"
                " GROUP BY address, city HAVING COUNT(*) > 1)"
            )
    for table, key in ((BACKUP_TABLE, "address_backup_rows"),
                       (MERGE_BACKUP_TABLE, "merge_backup_rows")):
        if _table_exists(conn, table):
            out[key] = q(f"SELECT COUNT(*) FROM {table}")
    return out


def run(
    *,
    apply: bool = False,
    merge_duplicates: bool = False,
    limit: int = 0,
    db_path: str | None = None,
    log=print,
) -> dict:
    """Executa a migração e devolve um resumo estruturado.

    Função em vez de só CLI de propósito: a rota de manutenção
    (`POST /api/admin/normalize-addresses`) chama isto directamente. Manipular
    `sys.argv` dentro de um servidor async seria perigoso — outro pedido a
    correr ao mesmo tempoeria herdar os argumentos.
    """
    if merge_duplicates and not apply:
        log("--merge-duplicates exige --apply (nada e escrito em dry-run).")
        return {"ok": False, "error": "merge_duplicates_requires_apply"}

    db_path = db_path or os.environ.get("LEADS_DB_PATH", "data/leads.db")
    if not os.path.exists(db_path):
        log(f"Base de dados não encontrada: {db_path}")
        return {"ok": False, "error": "db_not_found", "db_path": db_path}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT * FROM leads WHERE address IS NOT NULL AND TRIM(address) <> ''"
        )
        if limit:
            sql += f" ORDER BY id LIMIT {int(limit)}"
        rows = list(conn.execute(sql))

        plan = plan_normalisation(rows)
        groups = find_collision_groups(rows)
        mergeable, blocked, preserved = plan_merges(groups)

        # Endereços que NORMALIZAMOS mas que ficariam em colisão -> não tocar:
        # o `address` ficaria igual ao do par e o UNIQUE rebentaria.
        mergeable_ids = {m["winner"]["id"] for m in mergeable} | {
            r["id"] for m in mergeable for r in m["losers"]
        }
        blocked_ids = {r["id"] for b in blocked for r in b["rows"]}
        # Mesma regra para os preservados: ficam com o endereço como está, que é
        # o que os mantém distintos e dentro do UNIQUE(address, city).
        preserved_ids = {r["id"] for p in preserved for r in p["rows"]}

        changes = [
            (r["id"], r["address"], plan[r["id"]])
            for r in rows
            if r["id"] in plan
            and r["id"] not in mergeable_ids
            and r["id"] not in blocked_ids
            and r["id"] not in preserved_ids
        ]

        log(f"Base: {db_path}")
        log(f"Leads com address: {len(rows)}")
        log(f"A normalizar:      {len(changes)}")
        log(f"Prédios duplicados a fundir: {len(mergeable)}")
        log(f"Prédios duplicados bloqueados (com valor comercial): {len(blocked)}")
        log(f"Prédios preservados (mesmo prédio, eventos diferentes): {len(preserved)}")
        log()

        if mergeable:
            log("DUPLICADOS A FUNDIR (o endereço passa a ser canónico em ambos):")
            for m in mergeable[:10]:
                w, ls = m["winner"], m["losers"]
                log(f"  {m['key'][0]!r} / {m['key'][1]!r}")
                log(f"    mantem  id={w['id']} ext={w['external_id']} owner={w['owner_name']!r}")
                for loser in ls:
                    log(f"    absorve id={loser['id']} ext={loser['external_id']} owner={loser['owner_name']!r}")
                if m["absorbed"]:
                    log(f"    herda: {sorted(m['absorbed'])}")
            if len(mergeable) > 10:
                log(f"  ... e mais {len(mergeable) - 10}")
            log()

        if blocked:
            log("BLOQUEADOS (nao fundir: reserva/conversao/contacto revelado):")
            for b in blocked:
                log(
                    f"  {b['key'][0]!r} / {b['key'][1]!r}"
                    f" -> ids {b['ids']} porque {b['reasons']}"
                )
            log()

        if preserved:
            log(
                "PRESERVADOS (mesmo prédio, `external_id` diferentes: fundir apagaria "
                "um contacto real; ficam separados e sem normalizar):"
            )
            for p in preserved[:10]:
                log(f"  {p['key'][0]!r} / {p['key'][1]!r}")
                log(f"    ids {p['ids']} ext={p['external_ids']}")
            if len(preserved) > 10:
                log(f"  ... e mais {len(preserved) - 10}")
            log()

        for lead_id, old, new in changes[:10]:
            log(f"  #{lead_id}: {old!r} -> {new!r}")
        if len(changes) > 10:
            log(f"  ... e mais {len(changes) - 10}")

        if not changes and not mergeable:
            log("\nNada a fazer.")
            return {
                "ok": True, "applied": False, "db_path": db_path,
                "leads": len(rows), "to_normalise": 0, "to_merge": 0,
                "blocked_merges": len(blocked), "preserved_groups": len(preserved),
                "normalised": 0, "merged": 0,
                "blocked": _blocked_summary(blocked),
                **_verify(conn),
            }

        if not apply:
            log("\nDRY-RUN: nada foi escrito. Use --apply para aplicar.")
            return {
                "ok": True, "applied": False, "db_path": db_path,
                "leads": len(rows), "to_normalise": len(changes),
                "to_merge": len(mergeable), "blocked_merges": len(blocked),
                "preserved_groups": len(preserved),
                "normalised": 0, "merged": 0,
                "blocked": _blocked_summary(blocked),
                **_verify(conn),
            }

        conn.execute("BEGIN IMMEDIATE")
        try:
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

            merged_rows = 0
            if mergeable:
                if not _table_exists(conn, MERGE_BACKUP_TABLE):
                    conn.execute(
                        f"CREATE TABLE {MERGE_BACKUP_TABLE} ("
                        " lead_id INTEGER PRIMARY KEY,"
                        " merged_into INTEGER NOT NULL,"
                        " payload TEXT NOT NULL,"
                        " merged_at TEXT DEFAULT CURRENT_TIMESTAMP)"
                    )
                for m in mergeable:
                    winner_id = m["winner"]["id"]
                    for loser in m["losers"]:
                        payload = {k: loser[k] for k in loser.keys()}
                        conn.execute(
                            f"INSERT OR REPLACE INTO {MERGE_BACKUP_TABLE}"
                            " (lead_id, merged_into, payload) VALUES (?, ?, ?)",
                            (loser["id"], winner_id, json.dumps(payload, default=str)),
                        )
                    if m["absorbed"]:
                        sets = ", ".join(f"{f}=?" for f in m["absorbed"])
                        conn.execute(
                            f"UPDATE leads SET {sets} WHERE id = ?",
                            [*m["absorbed"].values(), winner_id],
                        )
                    # ORDEM IMPORTA: apagar os absorvidos ANTES de mexer no
                    # address do vencedor. Numa das linhas duplicadas o
                    # perdedor ja tinha o endereço canónico exacto, e
                    # actualizar o vencedor primeiro batia no
                    # UNIQUE(address, city) e abortava a migração inteira.
                    # Como tudo está dentro de uma transacção, apagar primeiro
                    # continua a ser atómico.
                    conn.executemany(
                        "DELETE FROM leads WHERE id = ?", [(loser["id"],) for loser in m["losers"]]
                    )
                    conn.execute(
                        "UPDATE leads SET address = ? WHERE id = ?",
                        (strip_city_state(
                            m["winner"]["address"], m["winner"]["city"],
                            m["winner"]["state"], m["winner"]["zip_code"],
                        ), winner_id),
                    )
                    merged_rows += len(m["losers"])

            conn.commit()
        except Exception:
            conn.rollback()
            raise

        leads_after = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        log()
        log(f"Aplicado: {len(changes)} endereços normalizados, {merged_rows} linhas fundidas.")
        if preserved:
            log(
                f"{len(preserved)} grupos preservados sem fusão "
                f"({len(preserved_ids)} linhas): mesmo prédio, `external_id` diferentes."
            )
        if changes:
            log(f"Backup do address original em {BACKUP_TABLE}.")
        if merged_rows:
            log(f"Backup integral das linhas absorvidas em {MERGE_BACKUP_TABLE}.")
            return {
                "ok": True, "applied": True, "db_path": db_path,
                "leads": len(rows), "leads_after": leads_after,
                "to_normalise": len(changes), "normalised": len(changes),
                "to_merge": len(mergeable), "merged": merged_rows,
                "blocked_merges": len(blocked),
                "preserved_groups": len(preserved),
                "blocked": _blocked_summary(blocked),
                **_verify(conn),
            }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normaliza leads.address e (opcionalmente) funde prédios duplicados"
    )
    parser.add_argument("--apply", action="store_true", help="Escreve as alterações (default: dry-run)")
    parser.add_argument(
        "--merge-duplicates",
        action="store_true",
        help="Funde prédios duplicados que passem a colidir (exige --apply)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Máximo de linhas a processar (0 = todas)")
    args = parser.parse_args()

    result = run(
        apply=args.apply,
        merge_duplicates=args.merge_duplicates,
        limit=args.limit,
    )
    return 0 if result.get("ok") else (2 if "requires_apply" in str(result.get("error")) else 1)


if __name__ == "__main__":
    raise SystemExit(main())
