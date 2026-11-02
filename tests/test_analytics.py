"""Web Analytics first-party (Fase 29): privacidade, idempotência e resumo."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import app
from backend.services import analytics

NOW = datetime.now(timezone.utc)


@pytest.fixture()
def clean_db():
    analytics.init_db()
    conn = analytics.get_connection()
    try:
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM meta")
        conn.commit()
    finally:
        conn.close()
    analytics.clear_cache()
    yield
    conn = analytics.get_connection()
    try:
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM meta")
        conn.commit()
    finally:
        conn.close()
    analytics.clear_cache()


def _payload(sid: str, *, cta: bool = True, engagement_ms: int = 45000):
    return {
        "session": {
            "id": sid,
            "started_at": (NOW - timedelta(minutes=5)).isoformat(),
            "last_seen_at": NOW.isoformat(),
            "landing_path": "/en",
            "locale": "en",
            "pageviews": 1,
            "engagement_ms": engagement_ms,
            "scroll_pct": 80,
            "utm": {
                "source": "magicleads",
                "medium": "outreach",
                "campaign": "dallas_roofing",
            },
        },
        "events": [
            {
                "uid": f"{sid}-pageview",
                "name": "pageview",
                "ts": (NOW - timedelta(minutes=5)).isoformat(),
                "path": "/en",
            }
        ]
        + (
            [
                {
                    "uid": f"{sid}-cta",
                    "name": "cta_click",
                    "ts": (NOW - timedelta(minutes=4)).isoformat(),
                    "path": "/en",
                    "label": "hero_cta",
                }
            ]
            if cta
            else []
        ),
        "context": {
            "ua": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
            ),
            "country": "US",
            "region": "TX",
            "city": "Dallas",
            "referrer": "",
        },
    }


def test_classifica_utm_de_email_como_email(clean_db):
    out = analytics.classify_source(
        "", {"source": "magicleads", "medium": "outreach", "campaign": "dallas_roofing"}
    )
    assert out["source"] == "email"
    assert out["medium"] == "outreach"
    assert out["campaign"] == "dallas_roofing"


def test_classifica_referrer_organico_e_direto():
    assert analytics.classify_source("https://www.google.com/search?q=x", {})["source"] == "organic"
    assert analytics.classify_source("", {})["source"] == "direct"
    assert analytics.classify_source("https://www.linkedin.com/feed", {})["source"] == "social"
    assert analytics.classify_source("https://example.com/post", {})["source"] == "referral"


def test_user_agent_e_bot():
    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1.15 Safari/604.1"
    parsed = analytics.parse_user_agent(ua)
    assert parsed["device"] == "mobile"
    assert parsed["os"] == "iOS"
    assert analytics.is_bot("Googlebot/2.1 (+http://www.google.com/bot.html)")
    assert analytics.is_bot("Mozilla/5.0 HeadlessChrome/120")
    assert not analytics.is_bot(ua)


def test_ingest_e_idempotente_por_event_uid(clean_db):
    payload = _payload("sess-abc-12345")
    first = analytics.ingest(payload, "203.0.113.10")
    second = analytics.ingest(payload, "203.0.113.10")
    assert first["inserted"] == 2
    assert second["inserted"] == 0
    conn = analytics.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    finally:
        conn.close()


def test_ingest_ignora_bot_e_evento_desconhecido(clean_db):
    payload = _payload("sess-bot-12345")
    payload["context"]["ua"] = "Googlebot/2.1"
    assert analytics.ingest(payload, "203.0.113.11")["status"] == "ignored"

    payload = _payload("sess-evt-12345")
    payload["events"].append(
        {"uid": "x", "name": "hack_event", "ts": NOW.isoformat(), "path": "/en"}
    )
    assert analytics.ingest(payload, "203.0.113.12")["inserted"] == 2
    conn = analytics.get_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE name='hack_event'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_nao_persiste_ip_e_hash_e_diario(clean_db):
    analytics.ingest(_payload("sess-priv-12345"), "203.0.113.20")
    conn = analytics.get_connection()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
        assert "ip" not in cols
        row = conn.execute("SELECT visitor_hash FROM sessions").fetchone()
        assert row and len(row["visitor_hash"]) == 32
    finally:
        conn.close()


def test_summary_conta_visitas_cta_e_funil(clean_db):
    analytics.ingest(_payload("sess-one-12345", cta=True), "203.0.113.30")
    analytics.ingest(_payload("sess-two-12345", cta=False), "203.0.113.31")
    snap = analytics.summary("24h")
    assert snap["cards"]["visits"]["value"] == 2
    assert snap["cards"]["cta_clicks"]["value"] == 1
    assert snap["sources"][0]["source"] == "email"
    funnel = {step["step"]: step["count"] for step in snap["funnel"]}
    assert funnel["Visitas"] == 2
    assert funnel["CTA click"] == 1
    assert snap["overall"]["score"] > 0


def test_rate_limit_por_ip():
    assert analytics.allow_ingest("198.51.100.77", limit=2, window_s=60) is True
    assert analytics.allow_ingest("198.51.100.77", limit=2, window_s=60) is True
    assert analytics.allow_ingest("198.51.100.77", limit=2, window_s=60) is False


def test_maintenance_remove_dados_antigos(clean_db):
    conn = analytics.get_connection()
    try:
        conn.execute(
            "INSERT INTO sessions (session_key, started_at, last_seen_at) "
            "VALUES ('old-session', '2020-01-01T00:00:00+00:00', "
            "'2020-01-01T00:00:00+00:00')"
        )
        sid = conn.execute(
            "SELECT id FROM sessions WHERE session_key='old-session'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO events (event_uid, session_id, ts, name) "
            "VALUES ('old-event', ?, '2020-01-01T00:00:00+00:00', 'pageview')",
            (sid,),
        )
        conn.commit()
    finally:
        conn.close()
    result = analytics.maintenance(90, 180)
    assert result["sessions"] >= 1
    conn = analytics.get_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_uid='old-event'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_ingest_endpoint_exige_chave(monkeypatch):
    monkeypatch.setattr(
        main_module.settings, "ANALYTICS_INGEST_KEY", "pytest-analytics-key"
    )
    client = TestClient(app)
    r = client.post("/api/analytics/ingest", json={})
    assert r.status_code == 401
    r = client.post(
        "/api/analytics/ingest",
        json={},
        headers={"X-Analytics-Key": "errada"},
    )
    assert r.status_code == 401


def test_ingest_endpoint_aceita_chave_e_grava(clean_db, monkeypatch):
    monkeypatch.setattr(
        main_module.settings, "ANALYTICS_INGEST_KEY", "pytest-analytics-key"
    )
    client = TestClient(app)
    payload = _payload("sess-http-12345")
    r = client.post(
        "/api/analytics/ingest",
        json=payload,
        headers={
            "X-Analytics-Key": "pytest-analytics-key",
            "X-Analytics-Client-IP": "203.0.113.40",
        },
    )
    assert r.status_code == 204
    conn = analytics.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    finally:
        conn.close()
