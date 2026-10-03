"""Furos de segurança #1 e #2 (P0).

#1 — `GET /api/scraper/status` era público e devolvia o estado interno da
     operação: `city_health` (failure_count, circuit_open_until,
     anomaly_counter por cidade) e o dict `running` com os `error` de cada
     run. Qualquer visitante (a landing page chama este endpoint) via a
     diagnóstico completo de quais scrapers estão a falhar e que cidades
     têm o circuit breaker aberto. Passa a devolver só o mínimo público
     (`active` + `finished_at`), e o detalhe completo apenas a admins.

#2 — `GET /api/leads/{id}/history` e `/api/leads/{id}/occurrences` exigiam
     apenas uma sessão válida, NÃO posse do lead. Um assinante que
     enumerasse `lead_id` lia o histórico e a timeline 311 de qualquer
     imóvel da plataforma — incluindo moradas de clientes de outros
     contratores. Passam a exigir posse (hold/reveal/conversão) ou admin.

Invariantes fixados aqui:
  1. Anónimo não recebe `city_health` nem `running` em /api/scraper/status.
  2. Admin autenticado recebe o detalhe completo.
  3. Utilizador autenticado SEM posse do lead recebe 404 (não 403: não pode
     servir de oráculo de existência).
  4. Utilizador COM posse (reveal) recebe 200.
  5. Admin lê qualquer lead.
  6. O payload público mantém o que a landing/dashboard usam
     (`active` + `last_run.finished_at`).
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.main import _hash_token, app
from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.services.db import db_service, get_connection

OWNER_EMAIL = "pytest-owner@magicleads.app"
INTRUDER_EMAIL = "pytest-intruder@magicleads.app"
ADMIN_EMAIL = "pytest-secadmin@magicleads.app"

_EXT = {"n": 0}


def _make_lead() -> int:
    _EXT["n"] += 1
    payload = EnrichedLead(
        external_id=f"pytest-sec-{_EXT['n']}",
        source_type=SourceType.SERVICE_311,
        address=f"{_EXT['n']} SECURITY STREET",
        city="BROOKLYN",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="security guard regression",
        urgency_level=UrgencyLevel.MEDIUM,
        owner_name="SECURITY OWNER",
        owner_phone="3475550888",
        owner_email="security.owner@example.com",
        date_reported=datetime(2026, 1, 15, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    row = db_service._service.insert_lead_new(payload)
    assert row is not None
    return row["id"]


def _session(email: str, token: str, admin: bool = False) -> dict:
    svc = db_service._service
    user = svc.get_user_by_email(email) or svc.create_user(
        email, "pytest-hash-not-used", "Pytest Security",
        plan="pro", subscription_status="active",
    )
    assert user is not None
    svc.create_user_session(user["id"], _hash_token(token), "Pytest", None)
    svc.extend_access(user["id"], days=7)
    svc.set_user_admin(email, admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def ctx():
    client = TestClient(app)
    return {
        "client": client,
        "owner": _session(OWNER_EMAIL, "tok-owner", admin=False),
        "intruder": _session(INTRUDER_EMAIL, "tok-intruder", admin=False),
        "admin": _session(ADMIN_EMAIL, "tok-secadmin", admin=True),
    }


@pytest.fixture(scope="module")
def owned_lead_id(ctx):
    """Lead que o 'owner' pagou para revelar."""
    svc = db_service._service
    lead_id = _make_lead()
    owner_id = svc.get_user_by_email(OWNER_EMAIL)["id"]
    res = svc.reveal_lead(owner_id, lead_id, f"pytest-sec-reveal-{lead_id}")
    assert res and not res.get("error"), res
    return lead_id


# ------------------------------------------------- #1 scraper status


def test_scraper_status_anonymous_has_no_internals(ctx):
    """#1: anónima não vê city_health nem running."""
    r = ctx["client"].get("/api/scraper/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "city_health" not in body
    assert "running" not in body
    # O que a landing/dashboard usam continua disponível.
    assert "active" in body
    assert "last_run" in body
    if body["last_run"] is not None:
        assert set(body["last_run"].keys()) <= {"finished_at", "status"}


def test_scraper_status_authenticated_non_admin_still_minimal(ctx):
    """Ser assinante não dá direito ao diagnóstico interno."""
    r = ctx["client"].get("/api/scraper/status", headers=ctx["owner"])
    assert r.status_code == 200, r.text
    assert "city_health" not in r.json()
    assert "running" not in r.json()


def test_scraper_status_admin_gets_full_detail(ctx):
    """Admin autenticado mantém o acesso operacional completo."""
    r = ctx["client"].get("/api/scraper/status", headers=ctx["admin"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "city_health" in body
    assert "running" in body


def test_admin_sources_endpoint_still_serves_health(ctx):
    """O detalhe completo continua disponível em /api/admin/sources."""
    r = ctx["client"].get("/api/admin/sources", headers=ctx["admin"])
    assert r.status_code == 200, r.text
    assert "city_health" in r.json()


# ------------------------------------------------- #2 posse do lead


def test_history_denied_for_user_without_possession(ctx, owned_lead_id):
    """#2: assinante sem posse recebe 404, não 403 nem 200."""
    r = ctx["client"].get(
        f"/api/leads/{owned_lead_id}/history", headers=ctx["intruder"]
    )
    assert r.status_code == 404, r.text


def test_occurrences_denied_for_user_without_possession(ctx, owned_lead_id):
    """#2: mesma porta nas occurrences (timeline 311)."""
    r = ctx["client"].get(
        f"/api/leads/{owned_lead_id}/occurrences", headers=ctx["intruder"]
    )
    assert r.status_code == 404, r.text


def test_history_allowed_for_owner(ctx, owned_lead_id):
    """Quem pagou o reveal continua a ler o seu histórico."""
    r = ctx["client"].get(
        f"/api/leads/{owned_lead_id}/history", headers=ctx["owner"]
    )
    assert r.status_code == 200, r.text
    events = r.json()
    assert isinstance(events, list)
    assert any(e["event_type"] == "revealed" for e in events), events


def test_occurrences_allowed_for_owner(ctx, owned_lead_id):
    r = ctx["client"].get(
        f"/api/leads/{owned_lead_id}/occurrences", headers=ctx["owner"]
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_history_requires_authentication(ctx, owned_lead_id):
    """Sem sessão: 401 (não leakage, não 200)."""
    r = ctx["client"].get(f"/api/leads/{owned_lead_id}/history")
    assert r.status_code == 401


def test_admin_can_read_any_lead_history(ctx):
    """Admin tem visão global — é o objetivo do painel."""
    lead_id = _make_lead()
    r = ctx["client"].get(f"/api/leads/{lead_id}/history", headers=ctx["admin"])
    assert r.status_code == 200, r.text


def test_unknown_lead_is_404_not_500(ctx):
    """Lead inexistente com sessão válida: 404 limpo."""
    r = ctx["client"].get("/api/leads/99999999/history", headers=ctx["owner"])
    assert r.status_code == 404, r.text


def test_possession_helper_requires_existing_lead(ctx):
    """A própria função de posse não pode dar true para lead inexistente."""
    assert (
        db_service._service.user_has_lead_history_access(
            db_service._service.get_user_by_email(OWNER_EMAIL)["id"], 99999999
        )
        is False
    )


def test_possession_helper_rejects_null_inputs(ctx):
    svc = db_service._service
    assert svc.user_has_lead_history_access(0, 0) is False
    assert svc.user_has_lead_history_access(None, 1) is False


def test_possession_survives_reveal_returned_to_pool(ctx):
    """A posse NÃO depende de o reveal ainda estar ativo.

    Um reveal que voltou ao pool (60min sem contato) é um lead que o
    utilizador pagou e sobre o qual tem direito a histórico. Se a posse
    dependesse de returned_to_pool=0, o utilizador perderia o acesso ao
    histórico dos seus próprios leads pagos.
    """
    svc = db_service._service
    lead_id = _make_lead()
    owner_id = svc.get_user_by_email(OWNER_EMAIL)["id"]
    res = svc.reveal_lead(owner_id, lead_id, f"pytest-sec-pooled-{lead_id}")
    assert res and not res.get("error"), res

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE lead_reveals SET returned_to_pool = 1 WHERE lead_id = ? AND user_id = ?",
            (lead_id, owner_id),
        )
        conn.commit()
    finally:
        conn.close()

    assert svc.user_has_lead_history_access(owner_id, lead_id) is True

    # E o endpoint continua a servir.
    r = ctx["client"].get(f"/api/leads/{lead_id}/history", headers=ctx["owner"])
    assert r.status_code == 200, r.text
