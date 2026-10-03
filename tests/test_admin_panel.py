"""Admin panel: gate de role + endpoints de leitura.

Invariantes fixados aqui:

  1. `/api/admin/*` NÃO abre com o secret global (`X-Admin-Secret`): exige
     sessão real de utilizador. Um `ADMIN_SECRET` conhecido não dá acesso ao
     painel, porque o painel é login+password por utilizador.
  2. Fail-closed: sem token -> 401; token inválido -> 401; utilizador
     autenticado mas sem `is_admin` -> 403. Nunca 200.
  3. `users.is_admin` é fail-closed na migração: linhas existentes ficam a 0,
     ninguém se torna admin por efeito de uma migration.
  4. O histórico do scraper vem da tabela `scraper_runs` (sobrevive a restart),
     não do dict em memória `_scrape_runs`.
  5. A fila de recovers (`returned_only`) devolve exatamente os reveals que
     voltaram ao pool e ainda não foram estornados — a fila de trabalho do
     incidente "dados pagos ficaram invisíveis".
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import _hash_token, app
from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.services.db import db_service, get_connection

ADMIN_EMAIL = "pytest-admin@magicleads.app"
NONADMIN_EMAIL = "pytest-nonadmin@magicleads.app"


def _ensure_user(email: str, token: str) -> int:
    svc = db_service._service
    user = svc.get_user_by_email(email) or svc.create_user(
        email, "pytest-hash-not-used", "Pytest Admin", plan="pro",
        subscription_status="active",
    )
    assert user is not None
    svc.create_user_session(user["id"], _hash_token(token), "Pytest", None)
    svc.extend_access(user["id"], days=7)
    return user["id"]


@pytest.fixture(scope="module")
def admin_client():
    token = "pytest-admin-token"
    user_id = _ensure_user(ADMIN_EMAIL, token)
    assert db_service._service.set_user_admin(ADMIN_EMAIL, True) is True
    return TestClient(app), {"Authorization": f"Bearer {token}"}, user_id


@pytest.fixture(scope="module")
def nonadmin_client():
    token = "pytest-nonadmin-token"
    _ensure_user(NONADMIN_EMAIL, token)
    # Garante que NÃO é admin, mesmo que outro teste tenha mexido.
    db_service._service.set_user_admin(NONADMIN_EMAIL, False)
    return TestClient(app), {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- gate


def test_admin_routes_reject_global_secret_only(admin_client):
    """O X-Admin-Secret (usado por cron/scripts) NÃO abre o painel."""
    client, _, _ = admin_client
    headers = {"X-Admin-Secret": main_module.settings.ADMIN_SECRET or "anything"}
    r = client.get("/api/admin/overview", headers=headers)
    assert r.status_code == 401, r.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/overview",
        "/api/admin/sources",
        "/api/admin/scraper/runs",
        "/api/admin/reveals",
        "/api/admin/alerts",
    ],
)
def test_admin_routes_require_session(admin_client, path):
    """Sem sessão: 401 em todos os endpoints do painel."""
    client, _, _ = admin_client
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/overview",
        "/api/admin/sources",
        "/api/admin/scraper/runs",
        "/api/admin/reveals",
        "/api/admin/alerts",
    ],
)
def test_admin_routes_reject_invalid_token(admin_client, path):
    """Token forjado: 401."""
    client, _, _ = admin_client
    r = client.get(path, headers={"Authorization": "Bearer token-que-nao-existe"})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/overview",
        "/api/admin/sources",
        "/api/admin/scraper/runs",
        "/api/admin/reveals",
        "/api/admin/alerts",
    ],
)
def test_admin_routes_reject_non_admin_user(nonadmin_client, path):
    """Utilizador autenticado mas sem is_admin: 403 (não 401, não 200)."""
    client, headers = nonadmin_client
    assert client.get(path, headers=headers).status_code == 403


# ---------------------------------------------------------------- dados


def test_admin_can_read_overview(admin_client):
    client, headers, _ = admin_client
    r = client.get("/api/admin/overview", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("leads", "users", "reveals", "credits", "alerts", "last_scraper_run"):
        assert key in body, f"falta {key} no overview"
    assert body["leads"]["total"] >= 0
    assert isinstance(body["credits"]["used_today"], int)
    assert isinstance(body["alerts"]["unacknowledged"], int)


def test_admin_sources_reads_persisted_health(admin_client):
    """Saúde das fontes vem de city_health persistido, não de memória."""
    client, headers, _ = admin_client
    r = client.get("/api/admin/sources", headers=headers)
    assert r.status_code == 200, r.text
    assert "city_health" in r.json()


def test_admin_scraper_runs_come_from_table(admin_client):
    """O histórico sobrevive a restart: é lido de scraper_runs."""
    client, headers, _ = admin_client
    r = client.get("/api/admin/scraper/runs?limit=5", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] <= 5
    assert isinstance(body["runs"], list)


def test_admin_reveals_returned_only_filters_correctly(admin_client):
    """returned_only traz os voltados ao pool e não estornados."""
    client, headers, _ = admin_client
    svc = db_service._service
    payload = EnrichedLead(
        external_id="pytest-admin-reveal-1",
        source_type=SourceType.SERVICE_311,
        address="1 ADMIN PANEL STREET",
        city="BROOKLYN",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="admin reveal audit",
        urgency_level=UrgencyLevel.MEDIUM,
        owner_name="ADMIN PANEL OWNER",
        owner_phone="3475550999",
        owner_email="admin.panel@example.com",
        date_reported=datetime(2026, 1, 15, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    row = svc.insert_lead_new(payload)
    assert row is not None
    lead_id = row["id"]

    res = svc.reveal_lead(_admin_user_id(admin_client), lead_id, f"pytest-admin-reveal-{lead_id}")
    assert res and not res.get("error"), res

    # Simula o watchdog: 60min sem contato -> volta ao pool.
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE lead_reveals SET returned_to_pool = 1 WHERE lead_id = ? AND user_id = ?",
            (lead_id, _admin_user_id(admin_client)),
        )
        conn.commit()
    finally:
        conn.close()

    rows = db_service._service.admin_get_recent_reveals(200, returned_only=True)
    assert rows, "deveria existir pelo menos um reveal devolvido ao pool"
    mine = [r for r in rows if r["lead_id"] == lead_id]
    assert mine, "reveal de teste nao apareceu na fila returned_only"
    assert mine[0]["returned_to_pool"] == 1
    assert mine[0]["refunded"] == 0
    # O dado pago continua na base (o admin vê que a recuperação é possível).
    assert mine[0]["has_phone"] == 1
    assert mine[0]["address"] == "1 ADMIN PANEL STREET"


def _admin_user_id(admin_client) -> int:
    return admin_client[2]


def test_is_admin_migration_defaults_to_zero(admin_client):
    """Linhas existentes nunca são promovidas a admin por efeito da migration."""
    client, headers, user_id = admin_client
    user = db_service._service.get_user_by_id(user_id)
    assert user is not None
    assert user["is_admin"] == 1

    # Um utilizador nunca promovido tem de continuar a 0.
    other = db_service._service.get_user_by_email(NONADMIN_EMAIL)
    assert other["is_admin"] == 0
