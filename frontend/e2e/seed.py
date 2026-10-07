"""Prepara a base de dados para o E2E do Playwright.

Corre isolated (`LEADS_DB_PATH`), por isso nunca toca na base de dev/prod.

Cria um utilizador com:
  - plano pro e acesso valido (a reserva exige `can_access`)
  - sessao com token CONHECIDO (o teste injeta-o no localStorage)
  - cota diaria 10/10 (esgotada: e o cenario que bloqueava a reserva gratis)

E insere leads em city="NYC" para aparecerem no feed por omissao:
  - 1 lead INCOMPLETO: nome, sem telefone, sem morada  (o caso do bug)
  - 1 lead CORPORATIVO: nome + morada, sem telefone      (0 creditos)
  - 1 lead COMPLETO: nome + telefone                    (pago)

Uso:  python e2e/seed.py <caminho_db>
Devolve o token em stdout (ultima linha).
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone


def build(db_path: str) -> str:
    os.environ["LEADS_DB_PATH"] = db_path
    # Nao faz fetch de seeds remotas durante o arranque.
    os.environ.setdefault("LEADS_SEED_FILE", "")

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

    from backend.main import _hash_token  # noqa: E402
    from backend.models.schemas import (  # noqa: E402
        EnrichedLead,
        IssueCategory,
        SourceType,
        UrgencyLevel,
    )
    from backend.services.db import db_service, get_connection, init_db  # noqa: E402

    svc = db_service._service
    init_db()

    TOKEN = "e2e-token-cota-esgotada"
    EMAIL = "e2e-cota-esgotada@magicleads.app"

    async def setup() -> None:
        user = svc.get_user_by_email(EMAIL)
        if not user:
            user = svc.create_user(
                EMAIL, "hash-nao-usado", "E2E Cota Esgotada", plan="pro",
                subscription_status="active",
            )
        user_id = user["id"]
        svc.create_user_session(user_id, _hash_token(TOKEN), "E2E", None)
        svc.extend_access(user_id, days=7)
        # O WelcomePopup (overlay z-[90]) abre para users com welcome_popup_shown=0
        # e intercepta cliques no dashboard — no E2E tiramos essa variável de vez.
        conn0 = get_connection()
        try:
            conn0.execute("UPDATE users SET welcome_popup_shown = 1 WHERE id = ?", (user_id,))
            conn0.commit()
        finally:
            conn0.close()

        # Cota esgotada: e a condicao que mantinha a "reserva gratis" bloqueada.
        conn = get_connection()
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO user_daily_stats
                   (user_id, date, leads_used, leads_limit, reset_at)
                   VALUES (?, ?, 10, 10, ?)""",
                (user_id, today, svc._utc_tomorrow_midnight().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

        now = datetime.now(timezone.utc)
        leads = [
            ("E2E-INCOMPLETO", "John Doe", None, None, "1 INCOMPLETO ST"),
            ("E2E-CORPORATIVO", "65 MS LLC", None, "PO BOX 9, NEW YORK, NY 10001", "2 CORPORATE AVE"),
            ("E2E-COMPLETO", "Maria Santos", "(718) 555-0199", "12 MAIN ST, NEW YORK, NY 10001", "3 COMPLETE BLVD"),
        ]
        for external_id, name, phone, mailing, address in leads:
            payload = EnrichedLead(
                external_id=external_id,
                source_type=SourceType.DOB_VIOLATION,
                address=address,
                city="NYC",
                state="NY",
                zip_code="10001",
                lat=None,
                lng=None,
                county="KINGS",
                issue_category=IssueCategory.ROOF,
                issue_description=f"Lead E2E {external_id}",
                urgency_level=UrgencyLevel.HIGH,
                owner_name=name,
                owner_phone=phone,
                owner_email=None,
                mailing_address=mailing,
                date_reported=now,
                image_url=None,
                source_url=None,
            )
            svc.insert_lead_new(payload)

    async def setup_lifecycle() -> None:
        """Utilizador do ciclo de vida (1h/48h/48h) com cota fresca."""
        TOKEN = "e2e-token-ciclo"
        EMAIL = "e2e-ciclo@magicleads.app"
        user = svc.get_user_by_email(EMAIL)
        if not user:
            user = svc.create_user(
                EMAIL, "hash-nao-usado", "E2E Ciclo Vida", plan="pro",
                subscription_status="active",
            )
        user_id = user["id"]
        svc.create_user_session(user_id, _hash_token(TOKEN), "E2E", None)
        svc.extend_access(user_id, days=7)
        conn0 = get_connection()
        try:
            conn0.execute("UPDATE users SET welcome_popup_shown = 1 WHERE id = ?", (user_id,))
            conn0.commit()
        finally:
            conn0.close()
        # Cota zera (0/10): o utilizador do ciclo tem créditos para reservar.
        conn = get_connection()
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            conn.execute(
                "DELETE FROM user_daily_stats WHERE user_id = ?", (user_id,)
            )
            conn.execute(
                """INSERT OR REPLACE INTO user_daily_stats
                   (user_id, date, leads_used, leads_limit, reset_at)
                   VALUES (?, ?, 0, 10, ?)""",
                (user_id, today, svc._utc_tomorrow_midnight().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

        now = datetime.now(timezone.utc)
        for external_id, name, phone, mailing, address in [
            ("E2E-CICLO", "Carlos Ciclo", "(718) 555-0201", None, "9 CYCLE AVE"),
            ("E2E-TIMER", "Tina Timer", "(718) 555-0202", None, "10 TIMER ST"),
        ]:
            # Mesma fonte/categoria dos leads "visíveis" (dob_violation/ROOF):
            # são os que passam na regra de qualificação e entram no feed por
            # omissão. SERVICE_311/PLUMBING ficavam de fora do `today`.
            payload = EnrichedLead(
                external_id=external_id,
                source_type=SourceType.DOB_VIOLATION,
                address=address,
                city="NYC",
                state="NY",
                zip_code="10001",
                lat=None,
                lng=None,
                county="KINGS",
                issue_category=IssueCategory.ROOF,
                issue_description=f"Lead E2E {external_id}",
                urgency_level=UrgencyLevel.HIGH,
                owner_name=name,
                owner_phone=phone,
                owner_email=None,
                mailing_address=mailing,
                date_reported=now,
                image_url=None,
                source_url=None,
            )
            svc.insert_lead_new(payload)

    asyncio.run(setup())
    asyncio.run(setup_lifecycle())
    return TOKEN


if __name__ == "__main__":
    target = sys.argv[1]
    print(build(target))