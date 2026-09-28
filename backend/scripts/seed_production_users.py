#!/usr/bin/env python3
"""Bootstrap idempotente de utilizadores de demonstracao/teste.

Executa no arranque do Railway (ver railway.json). Princípios:

1. NUNCA reescreve `password_hash` de um utilizador existente. O bootstrap
   corre em CADA deploy; sobrescrever a password faria com que qualquer
   pessoa que registe demo@/test@ tivesse a sua palavra-passe reposta para
   um valor conhecido no deploy seguinte.
2. As credenciais vêm SEMPRE do ambiente (DEMO_PASSWORD / TEST_PASSWORD).
   Não há passwords em código-fonte. Sem variável definida, o bootstrap
   não cria o utilizador — é preferível não existir a existir com uma
   credencial exposta.
3. `plan_until` é calculado relativo a agora, nunca uma data fixa no
   passado (a data fixa anterior deixava os utilizadores Pro sem acesso
   a cada deploy).
4. Não mexe em subscrições de utilizadores reais: se o utilizador já
   existe, apenas garante as colunas e sai.
"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

# Add /app to path for imports ( Railway container layout )
sys.path.insert(0, "/app")

from backend.services.security import hash_password

# Database path - check environment variables first, then fallback
DB_PATH = os.environ.get("LEADS_DB_PATH") or os.path.join(
    os.environ.get("DATA_DIR", "/data"), "leads.db"
)

# Duração do acesso inicial para utilizadores recém-criados.
TRIAL_DAYS = 30


def _user_definitions():
    """Monta a lista de utilizadores a bootstrap, a partir do ambiente.

    Devolve [] se as senhas não estiverem definidas no ambiente.
    """
    specs = [
        ("DEMO_EMAIL", "DEMO_PASSWORD", "Demo User"),
        ("TEST_EMAIL", "TEST_PASSWORD", "Test Company"),
    ]

    defs = []
    for email_key, password_key, default_company in specs:
        email = os.environ.get(email_key)
        password = os.environ.get(password_key)
        if not email or not password:
            print(
                f"  - {email_key}/{password_key} nao definido(s): utilizador nao será criado."
            )
            continue
        defs.append(
            {
                "email": email.strip().lower(),
                "password": password,
                "company_name": os.environ.get(f"{email_key}_COMPANY", default_company),
                "locale": os.environ.get("SEED_LOCALE", "pt"),
            }
        )
    return defs


def seed_users():
    """Cria utilizadores de bootstrap se ainda nao existirem. Idempotente."""
    print(f"Looking for database at: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        # Normal no primeiro arranque: a aplicacao cria e migra a base no
        # import (init_db). O bootstrap e uma convenience, nao um requisito —
        # falhar aqui nao pode impedir o arranque do servidor. Os utilizadores
        # de bootstrap serao criados no arranque seguinte.
        print(
            f"Database not found at {DB_PATH} — a aplicacao vai cria-lo no arranque. "
            "Bootstrap ignorado (users de bootstrap serao criados no proximo restart)."
        )
        return True

    user_defs = _user_definitions()
    if not user_defs:
        print(
            "Nenhum utilizador de bootstrap configurado (faltam DEMO_PASSWORD/TEST_PASSWORD). "
            "Nada a fazer."
        )
        return True

    plan_until = (datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()

        # Garante a coluna locale (adicionada por migracao do app) antes de usar
        user_cols = {r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()}
        if user_cols and "locale" not in user_cols:
            c.execute("ALTER TABLE users ADD COLUMN locale TEXT DEFAULT 'pt'")
            conn.commit()

        for user_def in user_defs:
            email = user_def["email"]

            c.execute("SELECT id FROM users WHERE email = ?", (email,))
            user = c.fetchone()

            if user:
                # Bootstrap NAO toca em password_hash, plan ou subscription_status.
                # Um utilizador que exista e real (ou que tenha trocado a password)
                # deve ficar exactamente como esta.
                print(f"  {email} ja existe (id={user['id']}) — password/plano nao alterados.")
                continue

            c.execute(
                """
                    INSERT INTO users
                    (email, password_hash, company_name, plan, subscription_status, plan_until, locale)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email,
                    hash_password(user_def["password"]),
                    user_def["company_name"],
                    "pro",
                    "active",
                    plan_until,
                    user_def["locale"],
                ),
            )
            print(
                f"  {email} criado (id={c.lastrowid}) com acesso ate {plan_until}."
            )

        conn.commit()
        print("Bootstrap concluido.")
        return True

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    print("Seeding bootstrap users...")
    success = seed_users()
    if success:
        print("Bootstrap users OK")
        sys.exit(0)
    else:
        print("Failed to seed bootstrap users")
        sys.exit(1)
