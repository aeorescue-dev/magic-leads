"""Regressao: a migracao do esquema tem de correr em bases JA' EXISTENTES.

Bug apanhado antes do deploy (Prioridade A/D): o `DEFAULT_SCHEMA` criava
`CREATE INDEX ... ON outbound_messages (status, next_step_at)` — uma coluna que
so' existe DEPOIS de `_migrate_schema` (ALTER TABLE). Numa base antiga, o
`executescript` levantava "no such column", o `init_db` abortava e logava
"Filesystem read-only" (mensagem enganosa) — as colunas da sequencia nunca eram
criadas e o indice de dedup nunca era recriado.

Invariantes:
  1. Numa base com o esquema antigo, a migracao adiciona `sequence_step`,
     `next_step_at` e `replied_at`.
  2. O indice de dedup passa a ser (to_email, sequence_step).
  3. A tabela `checkout_sessions` e' criada.
  4. Os dados existentes sobrevivem intactos.
  5. O DEFAULT_SCHEMA nao cria indices sobre colunas de migracao (ver bug).

Nota: este ficheiro NAO recarrega `backend.services.db` — mexer em
`sys.modules` contamina os outros testes (a instancia global `db_service`
passa a apontar para outra base).
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from backend.services.db import DEFAULT_SCHEMA, _migrate_schema


def _tmp_db_path() -> str:
    return os.path.join(tempfile.gettempdir(), "pytest_migration_regression.db")


def _cleanup(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            os.remove(p)


def _build_old_schema_db(path: str) -> None:
    """Cria uma base com o esquema ATUAL e degrada-a para o esquema antigo."""
    _cleanup(path)
    conn = sqlite3.connect(path)
    conn.executescript(DEFAULT_SCHEMA)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("DROP INDEX IF EXISTS ux_outbound_messages_to_email_active")
    cur.execute("DROP INDEX IF EXISTS idx_outbound_messages_sequence")
    cur.execute(
        "CREATE UNIQUE INDEX ux_outbound_messages_to_email_active "
        "ON outbound_messages (to_email) "
        "WHERE to_email IS NOT NULL AND status IN ('queued', 'sending', 'sent')"
    )
    try:
        cur.execute("ALTER TABLE outbound_messages DROP COLUMN next_step_at")
        cur.execute("ALTER TABLE outbound_messages DROP COLUMN sequence_step")
        cur.execute("ALTER TABLE outbound_contacts DROP COLUMN replied_at")
    except sqlite3.OperationalError:
        conn.close()
        pytest.skip("SQLite sem suporte a DROP COLUMN")
    cur.execute("DROP TABLE IF EXISTS checkout_sessions")
    conn.commit()
    conn.close()


def test_migrate_schema_repairs_old_database():
    db_path = _tmp_db_path()
    _build_old_schema_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Dados representativos (tem de sobreviver).
    cur.execute(
        "INSERT INTO sending_mailboxes (email, provider, transport, display_name, city, "
        "daily_cap, enabled, warmup_state) "
        "VALUES ('box@magicleads.app','gmail','gmail_api','Magic Leads','',25,1,'cold')"
    )
    cur.execute(
        "INSERT INTO outbound_contacts (lead_id, kind, company_name, email, "
        "email_source, email_status, city, state) "
        "VALUES (NULL,'business','ACME ROOFING','ops@acme.test','manual','valid','NYC','NY')"
    )
    cur.execute(
        "INSERT INTO outbound_messages (batch_id, contact_id, city, channel, to_email, "
        "subject, body_hash, status) "
        "VALUES (NULL,1,'NYC','email','ops@acme.test','s','h','sent')"
    )
    conn.commit()

    # --- estado ANTES ---
    cols = {r["name"] for r in cur.execute("PRAGMA table_info(outbound_messages)")}
    assert "sequence_step" not in cols
    assert "next_step_at" not in cols
    ccols = {r["name"] for r in cur.execute("PRAGMA table_info(outbound_contacts)")}
    assert "replied_at" not in ccols

    # --- a mesma ordem do init_db: 1) schema, 2) migracao ---
    # O passo 1 e' o que rebentava antes (CREATE INDEX sobre `next_step_at`).
    conn.executescript(DEFAULT_SCHEMA)
    conn.commit()
    _migrate_schema(conn)
    conn.commit()

    # --- estado DEPOIS ---
    cols = {r["name"] for r in cur.execute("PRAGMA table_info(outbound_messages)")}
    assert "sequence_step" in cols, "a coluna sequence_step nao foi criada"
    assert "next_step_at" in cols, "a coluna next_step_at nao foi criada"

    ccols = {r["name"] for r in cur.execute("PRAGMA table_info(outbound_contacts)")}
    assert "replied_at" in ccols, "a coluna replied_at nao foi criada"

    row = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' "
        "AND name='ux_outbound_messages_to_email_active'"
    ).fetchone()
    assert row is not None, "o indice de dedup desapareceu"
    assert "sequence_step" in row["sql"], (
        "o indice de dedup nao foi recriado com o passo da sequencia: " + row["sql"]
    )

    assert cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='checkout_sessions'"
    ).fetchone(), "a tabela checkout_sessions nao foi criada"

    # Dados intactos.
    assert cur.execute("SELECT COUNT(*) FROM sending_mailboxes").fetchone()[0] == 1
    assert cur.execute("SELECT COUNT(*) FROM outbound_contacts").fetchone()[0] == 1
    assert cur.execute("SELECT COUNT(*) FROM outbound_messages").fetchone()[0] == 1
    assert cur.execute("SELECT sequence_step FROM outbound_messages").fetchone()[0] == 1

    conn.close()
    _cleanup(db_path)


def test_schema_does_not_reference_columns_added_by_migration():
    """O DEFAULT_SCHEMA nao pode criar indices sobre colunas de migracao.

    Se o fizesse, o `executescript` falharia numa base antiga e abortaria o
    `init_db` ANTES de aplicar as migracoes (ver bug no docstring).

    So' interessam os STATEMENTS executados — os comentarios de explicacao
    podem (e devem) mencionar os nomes dos indices.
    """
    import re

    statements = []
    for raw in DEFAULT_SCHEMA.split(";"):
        line = "\n".join(
            ln for ln in raw.splitlines() if not ln.strip().startswith("--")
        )
        if line.strip():
            statements.append(line)

    executable = "\n".join(statements)
    for index_name in (
        "idx_outbound_messages_sequence",
        "ux_outbound_messages_to_email_active",
    ):
        assert not re.search(
            rf"CREATE\s+(UNIQUE\s+)?INDEX[^;]*\b{index_name}\b", executable
        ), (
            f"o indice {index_name} depende de colunas criadas em _migrate_schema "
            "e nao pode ser criado pelo DEFAULT_SCHEMA"
        )
