"""Testa o caminho REAL de escrita do set_admin: promover, confirmar, revogar.

Corre o script como subprocesso (como o Railway shell corre) contra uma
BD temporaria, e verifica o efeito real na base. Um teste que so verifica
"o comando imprime OK" nao apanha o bug das corrotinas: o script dizia OK
sem promover ninguem.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# O interpretador que corre os testes, nao um path de venv hardcoded. O path
# anterior (backend/venv/Scripts/python.exe) so existe em Windows, portanto em
# Linux o subprocesso levantava FileNotFoundError e este ficheiro inteiro
# falhava no CI. sys.executable funciona em qualquer plataforma e garante que o
# script e testado com o mesmo Python que corre a suite.
PY = sys.executable


def _seed(db_path: str) -> None:
    """Cria a tabela `users` com as colunas que o codigo real le.

    `get_all_users` faz `ORDER BY created_at`: sem esta coluna o --list rebenta
    com OperationalError. O resto das colunas nao e preciso para o flag, mas
    `created_at` tem de existir.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, "
            "password_hash TEXT, is_admin INTEGER DEFAULT 0, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.executemany(
            "INSERT INTO users (email, password_hash, is_admin) VALUES (?, 'x', 0)",
            [("fabio@magicleads.com",), ("cliente@example.com",)],
        )
        conn.commit()
    finally:
        conn.close()


def _is_admin(db_path: str, email: str) -> int | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT is_admin FROM users WHERE email = ?", (email,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _run(db_path: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, LEADS_DB_PATH=db_path, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [PY, "-m", "backend.scripts.set_admin", *args],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )


def test_list_reports_no_admins_initially():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "leads.db")
        _seed(db_path)

        proc = _run(db_path, "--list")
        assert proc.returncode == 0, proc.stderr
        assert "Nenhum administrador" in proc.stdout


def test_promote_actually_writes_the_flag():
    """O bug original: imprimia 'OK' sem escrever nada (corrotina truthy)."""
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "leads.db")
        _seed(db_path)

        proc = _run(db_path, "fabio@magicleads.com")
        assert proc.returncode == 0, proc.stderr
        assert "promovido a admin" in proc.stdout
        # O efeito real na base, nao apenas o que o script diz.
        assert _is_admin(db_path, "fabio@magicleads.com") == 1

        listing = _run(db_path, "--list")
        assert "fabio@magicleads.com" in listing.stdout


def test_revoke_clears_the_flag():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "leads.db")
        _seed(db_path)

        assert _run(db_path, "fabio@magicleads.com").returncode == 0
        proc = _run(db_path, "fabio@magicleads.com", "--revoke")
        assert proc.returncode == 0, proc.stderr
        assert _is_admin(db_path, "fabio@magicleads.com") == 0


def test_unknown_email_exits_nonzero():
    """Falha fechada: nao pode reportar sucesso sobre um email inexistente."""
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "leads.db")
        _seed(db_path)

        proc = _run(db_path, "nao-existe@magicleads.com")
        assert proc.returncode == 1
        assert "nao encontrado" in proc.stdout
