"""Testes da fusão de prédios duplicados.

A fusão é a única parte disto que APAGA linhas, por isso o que interessa
testar é sobretudo o que ela NÃO pode fazer: não fundir nada que tenha valor
comercial ou actividad de utilizador, e não perder enriquecimento.
"""
from __future__ import annotations

import importlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts.normalize_addresses import (  # noqa: E402
    ENRICHMENT_FIELDS,
    available_enrichment_fields,
    find_collision_groups,
    is_pristine,
    merge_rank,
    plan_merges,
    plan_normalisation,
)

# Tipos REAIS de `leads` (ver backend/services/db.py). reserved_by/converted_by
# são INTEGER (REFERENCES users(id)) —_declará-los TEXT aqui escondeu um bug que
# só apareceu em produção (HTTP 500 em is_pristine).
INT_COLUMNS = ("id", "contact_count", "reserved_by", "converted_by")

COLUMNS = [
    "id", "external_id", "source_type", "address", "city", "state", "zip_code",
    "lat", "lng", "bbl", "owner_name", "owner_phone", "owner_email", "owner_status",
    "mailing_address", "address_unit", "image_url", "source_url", "county",
    "date_reported", "lead_status", "reserved_by", "reserved_until",
    "contact_count", "converted_by", "converted_at", "revealed_at",
]

DEFAULTS = {
    "external_id": "x", "source_type": "socrata_311", "city": "NYC", "state": "NY",
    "zip_code": "", "lat": None, "lng": None, "bbl": None, "owner_name": None,
    "owner_phone": None, "owner_email": None, "owner_status": None,
    "mailing_address": None, "address_unit": None, "image_url": None,
    "source_url": None, "county": None, "date_reported": "2026-09-01",
    "lead_status": "available", "reserved_by": None, "reserved_until": None,
    "contact_count": 0, "converted_by": None, "converted_at": None,
    "revealed_at": None,
}


def build_db(rows: list[dict]) -> sqlite3.Connection:
    """Cria uma BD em memória com a forma de `leads` e insere as linhas dadas."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ddl = ",".join(
        f"{c} {'INTEGER' if c in INT_COLUMNS else 'TEXT'}" for c in COLUMNS
    )
    conn.execute(f"CREATE TABLE leads ({ddl})")
    payload = []
    for r in rows:
        data = dict(DEFAULTS)
        data.update(r)
        payload.append([data[c] for c in COLUMNS])
    conn.executemany(
        f"INSERT INTO leads VALUES ({','.join('?' for _ in COLUMNS)})", payload
    )
    conn.commit()
    return conn


def load_rows(rows: list[dict]) -> list[sqlite3.Row]:
    conn = build_db(rows)
    try:
        return conn.execute("SELECT * FROM leads ORDER BY id").fetchall()
    finally:
        conn.close()


def make_row(**overrides) -> sqlite3.Row:
    data = dict(DEFAULTS)
    data.update(overrides)
    data.setdefault("address", "X")
    return load_rows([data])[0]


def test_same_building_two_formats_is_detected():
    rows = load_rows([
        {"id": 1, "address": "441 BROOKLYN AVENUE, NYC, NY 11225"},
        {"id": 2, "address": "441 BROOKLYN AVENUE, NYC, NY"},
    ])
    groups = find_collision_groups(rows)
    assert len(groups) == 1
    assert sorted(r["id"] for r in next(iter(groups.values()))) == [1, 2]


def test_different_buildings_are_not_a_group():
    rows = load_rows([
        {"id": 1, "address": "441 BROOKLYN AVENUE, NYC, NY"},
        {"id": 2, "address": "442 BROOKLYN AVENUE, NYC, NY"},
    ])
    assert find_collision_groups(rows) == {}


def test_street_named_after_city_is_not_a_collision():
    """Regressão: duas ruas diferentes que só partilham o nome não colidem."""
    rows = load_rows([
        {"id": 1, "address": "1267 NEW YORK AVENUE, NYC, NY", "city": "NYC"},
        {"id": 2, "address": "1268 NEW YORK AVENUE, NYC, NY", "city": "NYC"},
    ])
    assert find_collision_groups(rows) == {}


def test_winner_is_the_row_with_contact_data():
    rows = load_rows([
        {"id": 1, "address": "441 BROOKLYN AVENUE, NYC, NY", "date_reported": "2026-10-01"},
        {"id": 2, "address": "441 BROOKLYN AVENUE, NYC, NY 11225", "owner_name": "BROOKLYN441 LLC"},
    ])
    groups = find_collision_groups(rows)
    mergeable, blocked = plan_merges(groups)
    assert not blocked
    assert len(mergeable) == 1
    assert mergeable[0]["winner"]["id"] == 2


def test_enrichment_is_inherited_not_lost():
    """O dono aparecia só na linha mais pobre: tem de chegar à vencedora."""
    rows = load_rows([
        {"id": 1, "address": "441 BROOKLYN AVENUE, NYC, NY", "owner_name": "OWNER LLC"},
        {"id": 2, "address": "441 BROOKLYN AVENUE, NYC, NY 11225", "owner_phone": "5551234"},
    ])
    mergeable, _ = plan_merges(find_collision_groups(rows))
    m = mergeable[0]
    assert m["winner"]["id"] == 1  # tem nome
    assert m["absorbed"] == {"owner_phone": "5551234"}


@pytest.mark.parametrize(
    "signal",
    [
        {"reserved_by": "user-1"},
        {"converted_by": "user-2"},
        {"converted_at": "2026-10-01T00:00:00"},
        {"revealed_at": "2026-10-01T00:00:00"},
        {"contact_count": 1},
        {"lead_status": "sold"},
        {"lead_status": "reserved"},
    ],
)
def test_rows_with_user_or_commercial_activity_are_never_merged(signal):
    rows = load_rows([
        {"id": 1, "address": "441 BROOKLYN AVENUE, NYC, NY", **signal},
        {"id": 2, "address": "441 BROOKLYN AVENUE, NYC, NY 11225"},
    ])
    mergeable, blocked = plan_merges(find_collision_groups(rows))
    assert not mergeable, "nao devia fundir um lead com actividade"
    assert len(blocked) == 1


def test_is_pristine_accepts_the_normal_unused_row():
    assert is_pristine(make_row(id=1, address="X", lead_status="available"))
    assert is_pristine(make_row(id=1, address="X", lead_status=None))


@pytest.mark.parametrize("col", ["reserved_by", "converted_by"])
def test_is_pristine_handles_integer_user_ids(col):
    """Regressão de produção: estas colunas são INTEGER, não TEXT.

    Com TEXT, `(row[col] or "").strip()` funcionava. Com INTEGER rebentava com
    AttributeError e a rota devolvia HTTP 500 em produção.
    """
    blocked = is_pristine(make_row(id=1, address="X", **{col: 42}))
    assert blocked is False, f"{col}=42 tem de contar como actividade"


def test_is_pristine_with_zero_integer_ids_is_still_pristine():
    """0 e o valor vazio de uma coluna INTEGER: nao e actividade."""
    assert is_pristine(make_row(id=1, address="X", reserved_by=0, converted_by=0))


def test_merge_with_integer_columns_survives():
    """O caminho completo da fusao tem de funcionar com o schema real."""
    rows = load_rows([
        {"id": 1, "address": "441 BROOKLYN AVENUE, NYC, NY 11225", "owner_name": "LLC",
         "reserved_by": 0, "converted_by": 0, "contact_count": 0},
        {"id": 2, "address": "441 BROOKLYN AVENUE, NYC, NY", "owner_phone": "5551234",
         "reserved_by": 0, "converted_by": 0, "contact_count": 0},
    ])
    mergeable, blocked = plan_merges(find_collision_groups(rows))
    assert not blocked
    assert len(mergeable) == 1
    assert mergeable[0]["absorbed"] == {"owner_phone": "5551234"}


def test_available_enrichment_fields_ignores_missing_columns():
    """Uma base mais antiga, sem `county`, nao pode rebentar a migracao."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE leads (id INTEGER, address TEXT, owner_name TEXT)")
    conn.execute("INSERT INTO leads VALUES (1, 'X', 'LLC')")
    conn.commit()
    row = conn.execute("SELECT * FROM leads").fetchone()
    fields = available_enrichment_fields(row)
    assert "owner_name" in fields
    assert "county" not in fields
    conn.close()


def test_merge_rank_prefers_more_enriched_then_newer():
    poorer = make_row(id=1, address="X", date_reported="2026-10-01")
    richer = make_row(id=2, address="X", owner_name="LLC")
    assert merge_rank(richer) > merge_rank(poorer)


def test_normalisation_plan_skips_already_canonical_rows():
    rows = load_rows([
        {"id": 1, "address": "448 WEST 54 STREET"},  # ja canonico
        {"id": 2, "address": "447 16 STREET, NYC, NY 11215"},
    ])
    plan = plan_normalisation(rows)
    assert 1 not in plan
    assert plan[2] == "447 16 STREET"


def test_enrichment_fields_exclude_identity_columns():
    """O external_id nao pode ser herdado: e chave de deduplicacao."""
    assert "external_id" not in ENRICHMENT_FIELDS
    assert "source_type" not in ENRICHMENT_FIELDS
    assert "address" not in ENRICHMENT_FIELDS


def test_end_to_end_merge_and_rollback_possible(tmp_path):
    """Execução real: duas linhas viram uma e a absorvida fica guardada."""
    import importlib

    mod = importlib.import_module("backend.scripts.normalize_addresses")
    db = tmp_path / "leads.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE leads ("
        + ",".join(
            c + (" INTEGER" if c in ("id", "contact_count") else " TEXT")
            for c in COLUMNS
        )
        + ")"
    )
    conn.executemany(
        f"INSERT INTO leads VALUES ({','.join('?' for _ in COLUMNS)})",
        [
            [
                1, "ext-1", "socrata_311", "441 BROOKLYN AVENUE, NYC, NY 11225",
                "NYC", "NY", "11225", 40.6, -73.9, "b1", "BROOKLYN441 LLC", None,
                None, None, None, None, None, None, None, "2026-09-23", "available",
                None, None, 0, None, None, None,
            ],
            [
                2, "ext-2", "socrata_311", "441 BROOKLYN AVENUE, NYC, NY",
                "NYC", "NY", None, None, None, None, None, "5551234", None, None,
                None, None, None, None, None, "2026-10-01", "available", None, None,
                0, None, None, None,
            ],
        ],
    )
    conn.commit()
    conn.close()

    import os

    os.environ["LEADS_DB_PATH"] = str(db)
    argv = sys.argv
    sys.argv = ["normalize_addresses", "--apply", "--merge-duplicates"]
    try:
        rc = mod.main()
    finally:
        sys.argv = argv
    assert rc == 0

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    left = conn.execute("SELECT * FROM leads").fetchall()
    assert len(left) == 1, "as duas linhas deviam virar uma"
    winner = left[0]
    assert winner["id"] == 1
    assert winner["address"] == "441 BROOKLYN AVENUE"
    assert winner["owner_name"] == "BROOKLYN441 LLC"
    assert winner["owner_phone"] == "5551234", "o telefone tinha de ser herdado"
    assert winner["external_id"] == "ext-1", "o external_id nao pode mudar"

    backup = conn.execute(
        f"SELECT * FROM {mod.MERGE_BACKUP_TABLE}"
    ).fetchall()
    assert len(backup) == 1
    assert backup[0]["lead_id"] == 2
    assert backup[0]["merged_into"] == 1
    assert "ext-2" in backup[0]["payload"], "a linha absorvida tem de ser recuperável"
    conn.close()


def test_merge_when_loser_already_holds_the_canonical_address(tmp_path):
    """Regressão real: o perdedor tinha JÁ o endereço canónico exacto.

    Actualizar o vencedor antes de apagar o perdedor batia no
    UNIQUE(address, city) e abortava a migração toda (não só o grupo). A ordem
    tem de ser apagar -> actualizar.
    """
    import importlib

    mod = importlib.import_module("backend.scripts.normalize_addresses")
    db = tmp_path / "leads3.db"
    conn = sqlite3.connect(db)
    ddl = ",".join(
        f"{c} {'INTEGER' if c in INT_COLUMNS else 'TEXT'}" for c in COLUMNS
    )
    conn.execute(f"CREATE TABLE leads ({ddl})")

    def row(i, address, owner=None, ext="e"):
        data = dict(DEFAULTS)
        data.update({"id": i, "address": address, "owner_name": owner, "external_id": ext})
        return [data[c] for c in COLUMNS]

    conn.executemany(
        f"INSERT INTO leads VALUES ({','.join('?' for _ in COLUMNS)})",
        [
            # vencedor: tem dono, address ainda com zip
            row(842, "132-45 MAPLE AVENUE, NYC, NY 11355", "MAPLE VENTURES LLC", "ext-a"),
            # perdedor: mesmo predio, address JA canonico
            row(268310, "132-45 MAPLE AVENUE", None, "ext-b"),
        ],
    )
    conn.commit()
    conn.close()

    os.environ["LEADS_DB_PATH"] = str(db)
    argv = sys.argv
    sys.argv = ["normalize_addresses", "--apply", "--merge-duplicates"]
    try:
        rc = mod.main()
    finally:
        sys.argv = argv
    assert rc == 0, "a fusão tem de passar mesmo quando o perdedor ja e canonico"

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    left = conn.execute("SELECT * FROM leads").fetchall()
    assert len(left) == 1
    assert left[0]["address"] == "132-45 MAPLE AVENUE"
    assert left[0]["owner_name"] == "MAPLE VENTURES LLC"
    assert left[0]["external_id"] == "ext-a"
    conn.close()


def test_merge_is_idempotent(tmp_path):

    mod = importlib.import_module("backend.scripts.normalize_addresses")
    db = tmp_path / "leads2.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE leads ("
        + ",".join(
            c + (" INTEGER" if c in ("id", "contact_count") else " TEXT") for c in COLUMNS
        )
        + ")"
    )
    conn.executemany(
        f"INSERT INTO leads VALUES ({','.join('?' for _ in COLUMNS)})",
        [
            [1, "e1", "s", "441 BROOKLYN AVENUE, NYC, NY 11225", "NYC", "NY", "11225",
             None, None, None, "LLC", None, None, None, None, None, None, None, None,
             "2026-09-23", "available", None, None, 0, None, None, None],
            [2, "e2", "s", "441 BROOKLYN AVENUE, NYC, NY", "NYC", "NY", None,
             None, None, None, None, None, None, None, None, None, None, None, None,
             "2026-10-01", "available", None, None, 0, None, None, None],
        ],
    )
    conn.commit()
    conn.close()

    os.environ["LEADS_DB_PATH"] = str(db)
    for _ in range(2):
        argv = sys.argv
        sys.argv = ["normalize_addresses", "--apply", "--merge-duplicates"]
        try:
            assert mod.main() == 0
        finally:
            sys.argv = argv

    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    assert n == 1, "a 2a execucao nao pode voltar a fundir"
    conn.close()


def test_merge_duplicates_requires_apply():
    import importlib

    mod = importlib.import_module("backend.scripts.normalize_addresses")
    argv = sys.argv
    sys.argv = ["normalize_addresses", "--merge-duplicates"]
    try:
        assert mod.main() == 2, "--merge-duplicates sem --apply tem de ser recusado"
    finally:
        sys.argv = argv