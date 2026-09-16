"""
Teste de sanidade: valida se todos os imports críticos funcionam
e se a aplicação FastAPI sobe sem erros.
"""
import pytest


def test_critical_imports():
    """Valida se todas as instâncias essenciais importam sem erro."""
    from backend.scrapers.socrata_311 import socrata_scraper
    from backend.services.db import db_service
    from backend.services.push_service import push_service
    from backend.services.notifier import notify_users_for_lead, fanout_new_lead_batch
    from backend.services.enrichment import owner_enrichment
    from backend.services.phone_lookup import phone_lookup_service
    from backend.services.security import hash_password, verify_password, new_session_token
    from backend.main import app

    assert socrata_scraper is not None
    assert db_service is not None
    assert push_service is not None
    assert notify_users_for_lead is not None
    assert fanout_new_lead_batch is not None
    assert owner_enrichment is not None
    assert phone_lookup_service is not None
    assert hash_password is not None
    assert verify_password is not None
    assert new_session_token is not None
    assert app is not None


def test_fastapi_startup():
    """Valida se a aplicação FastAPI sobe e responde no /health."""
    from backend.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "healthy"
    assert "timestamp" in data


def test_scraper_status_endpoint():
    """Valida se o endpoint de status do scraper responde."""
    from backend.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/scraper/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data
    assert "running" in data
    assert "last_run" in data
    assert "city_health" in data


def test_leads_endpoint():
    """Valida se o endpoint de leads responde."""
    from backend.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/leads?limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "leads" in data
    assert isinstance(data["leads"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])