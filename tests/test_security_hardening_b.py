"""Fase B — endurecimento de superfície: CORS, headers e endpoints dormentes.

Cobre:
  * CORS aceita apenas allowlist exata / domínio base Vercel exato;
  * headers de segurança em todas as respostas;
  * `/api/scraper/enrich` e `/api/leads/{id}/enrich` exigem admin (não só login).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import (
    VercelAwareCORSMiddleware,
    _hash_token,
    app,
)
from backend.services.db import db_service

ADMIN_EMAIL = "pytest-phaseb-admin@magicleads.app"
ADMIN_TOKEN = "pytest-phaseb-admin-token"
USER_EMAIL = "pytest-phaseb-user@magicleads.app"
USER_TOKEN = "pytest-phaseb-user-token"

ALLOWED = "https://www.magicleads.app"
VERCEL_BASE = "magicleads-oficial.vercel.app"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ensure(email: str, token: str, *, admin: bool = False) -> int:
    svc = db_service._service
    user = svc.get_user_by_email(email) or svc.create_user(
        email, "pytest-hash", "Pytest Phase B", plan="pro",
        subscription_status="active",
    )
    try:
        svc.create_user_session(user["id"], _hash_token(token), "Pytest", None)
    except Exception:
        pass
    svc.extend_access(user["id"], days=7)
    if admin:
        svc.set_user_admin(email, True)
    return user["id"]


@pytest.fixture(scope="module")
def users(client):
    _ensure(ADMIN_EMAIL, ADMIN_TOKEN, admin=True)
    _ensure(USER_EMAIL, USER_TOKEN)
    return True


# ---------------------------------------------------------------- CORS


def _cors() -> VercelAwareCORSMiddleware:
    return VercelAwareCORSMiddleware(
        app=None,
        allowed_origins=[ALLOWED],
        vercel_preview_base_domains=[VERCEL_BASE],
    )


def test_cors_allows_exact_production_and_vercel_base():
    cors = _cors()
    assert cors._is_origin_allowed(ALLOWED)
    assert cors._is_origin_allowed(f"https://{VERCEL_BASE}")


@pytest.mark.parametrize(
    "origin",
    [
        "https://magicleads-oficial-evil.vercel.app",
        "https://magicleads-oficial-git-main.vercel.app",
        "https://magicleads-oficial-anything.vercel.app",
        "http://www.magicleads.app",
        "https://evil.example",
        "",
    ],
)
def test_cors_rejects_suffixes_http_and_unknown(origin):
    assert _cors()._is_origin_allowed(origin) is False


# ---------------------------------------------------------------- headers


def test_security_headers_present_on_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "geolocation=(self)" in r.headers["permissions-policy"]


def test_security_headers_present_on_api_error(client):
    r = client.get("/api/leads")
    assert r.status_code == 401
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


# ---------------------------------------------------------------- endpoints


def test_bulk_enrich_requires_admin(client, users):
    assert client.post("/api/scraper/enrich").status_code == 401
    assert client.post(
        "/api/scraper/enrich", headers=_headers(USER_TOKEN)
    ).status_code == 403

    r = client.post(
        "/api/scraper/enrich?city=NOWHERE&limit=1",
        headers=_headers(ADMIN_TOKEN),
    )
    assert r.status_code == 200, r.text


def test_single_enrich_requires_admin(client, users):
    assert client.post("/api/leads/999999/enrich").status_code == 401
    assert client.post(
        "/api/leads/999999/enrich", headers=_headers(USER_TOKEN)
    ).status_code == 403
    # Admin passa o gate; o lead inexistente devolve 404.
    assert client.post(
        "/api/leads/999999/enrich", headers=_headers(ADMIN_TOKEN)
    ).status_code == 404
