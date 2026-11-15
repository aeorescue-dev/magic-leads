"""Endpoint público do mapa: kill switch e forma da resposta."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import public_map


def test_live_map_kill_switch(monkeypatch):
    monkeypatch.setenv("PUBLIC_LIVE_MAP_ENABLED", "0")
    client = TestClient(app)
    response = client.get("/api/public/live-map")
    assert response.status_code == 503
    assert response.json()["detail"] == "live_map_disabled"


def test_live_map_returns_four_cities(monkeypatch):
    monkeypatch.setenv("PUBLIC_LIVE_MAP_ENABLED", "1")
    public_map.reset_cache()
    client = TestClient(app)
    response = client.get("/api/public/live-map")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["cities"]) == 4
    assert payload["window_days"] == 7
    assert response.headers["server-timing"].startswith("db;dur=")
    assert "max-age=30" in response.headers["cache-control"]
    assert response.headers["etag"].startswith('W/"')
