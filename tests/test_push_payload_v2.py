"""Web Push v2: distância (GPS/cidade), ícones PNG e variante iOS.

Guardas:
  * `source='city'` mostra distância aproximada com a cidade da base;
  * GPS/manual mostram "a X,X mi de si" (mockup PT);
  * o payload usa os PNGs nativos, não o SVG legado;
  * iOS recebe CTA no corpo e não recebe `actions`;
  * `send_to_user` escolhe o payload por user-agent da subscription.
"""

from __future__ import annotations

import anyio

from backend.services import alert_planner as ap
from backend.services import push_service
from backend.services.push_service import _is_ios_ua


def _lead() -> dict:
    return {
        "id": 1884884,
        "external_id": "SR26-02203168",
        "address": "3215 N PAGE AVE",
        "city": "Chicago",
        "lat": 41.938317,
        "lng": -87.827274,
        "issue_category": "Structure",
        "signal_type": "open_request",
        "signal_status": "open",
        "owner_name": "JULITA PIOTROWSKA",
        "phone_verified": 0,
        "date_reported": "2026-10-31T19:25:11",
        "oldest_open_days": 1,
        "repeat_365": 1,
    }


# --------------------------------------------------------------- distância


def test_distance_phrase_gps_alinha_com_mockup():
    assert ap._distance_phrase(2.3, "pt", "gps", "") == "a 2,3 mi de si"
    assert ap._distance_phrase(2.3, "en", "manual", "") == "2.3 mi away"
    assert ap._distance_phrase(2.3, "es", "gps", "") == "a 2,3 mi de ti"


def test_distance_phrase_city_e_aproximada_e_nomeia_a_cidade():
    assert (
        ap._distance_phrase(10.97, "pt", "city", "CHICAGO")
        == "~11,0 mi do centro de Chicago"
    )
    assert (
        ap._distance_phrase(10.97, "en", "city", "NYC")
        == "about 11.0 mi from downtown New York City"
    )
    assert (
        ap._distance_phrase(10.97, "es", "city", "DALLAS")
        == "a unos 11,0 mi del centro de Dallas"
    )


def test_payload_city_inclui_distancia_estimada_no_corpo():
    payload = ap._build_push_payload(
        _lead(), "Structure", "open_request", "pt",
        distance_mi=10.97, show_distance=True, confidence_pct=None,
        show_address=True, distance_source="city", base_label="CHICAGO",
    )
    assert "~11,0 mi do centro de Chicago" in payload["body"]
    assert "N PAGE AVE" in payload["body"]


def test_payload_sem_base_omite_distancia():
    payload = ap._build_push_payload(
        _lead(), "Structure", "open_request", "pt",
        distance_mi=None, show_distance=False, confidence_pct=None,
        show_address=True,
    )
    assert " mi" not in payload["body"]


# --------------------------------------------------------------- assets


def test_payload_usa_pngs_nativos():
    payload = ap._build_push_payload(
        _lead(), "Structure", "open_request", "pt",
        distance_mi=None, show_distance=False, confidence_pct=None,
        show_address=True,
    )
    assert payload["icon"].endswith("/icons/push-icon-192.png")
    assert payload["badge"].endswith("/icons/push-badge-72.png")
    assert ".svg" not in payload["icon"] and ".svg" not in payload["badge"]
    assert push_service.ICON_URL.endswith("/icons/push-icon-192.png")
    assert push_service.BADGE_URL.endswith("/icons/push-badge-72.png")


# --------------------------------------------------------------- iOS


def test_is_ios_ua():
    assert _is_ios_ua("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")
    assert _is_ios_ua("Mozilla/5.0 (iPad; CPU OS 16_4 like Mac OS X)")
    assert not _is_ios_ua("Mozilla/5.0 (Linux; Android 10; K)")
    assert not _is_ios_ua("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    assert not _is_ios_ua(None)


def test_ios_variant_tem_cta_e_sem_acoes():
    base = ap._build_push_payload(
        _lead(), "Structure", "open_request", "pt",
        distance_mi=10.97, show_distance=True, confidence_pct=None,
        show_address=True, distance_source="gps",
    )
    ios = ap._ios_variant(base, "pt")
    assert "Toque para abrir o lead." in ios["body"]
    assert "actions" not in ios
    assert "requireInteraction" not in ios
    assert "vibrate" not in ios
    # O Android mantém os botões nativos.
    assert base["actions"]
    assert ios["url"] == base["url"]
    assert ios["tag"] == base["tag"]


def test_ios_variant_english():
    base = ap._build_push_payload(
        _lead(), "Structure", "open_request", "en",
        distance_mi=None, show_distance=False, confidence_pct=None,
        show_address=True,
    )
    assert "Tap to open the lead." in ap._ios_variant(base, "en")["body"]


# --------------------------------------------------------------- envio


def test_send_to_user_escolhe_payload_por_plataforma(monkeypatch):
    svc = push_service.push_service
    monkeypatch.setattr(svc, "_configured", True)

    async def _enabled(user_id):
        return True

    async def _subs(user_id):
        return [
            {"endpoint": "ios", "p256dh": "a", "auth": "b", "user_id": user_id,
             "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"},
            {"endpoint": "android", "p256dh": "a", "auth": "b", "user_id": user_id,
             "user_agent": "Mozilla/5.0 (Linux; Android 10; K)"},
        ]

    sent: list = []

    async def _fake_send(sub, payload, kind="custom", user_id=None, ttl=14400,
                         urgency="high", **_kw):
        sent.append((sub["endpoint"], payload))
        return True

    monkeypatch.setattr(push_service.db_service, "is_push_enabled", _enabled)
    monkeypatch.setattr(push_service.db_service, "get_user_push_subscriptions", _subs)
    monkeypatch.setattr(svc, "_send_single", _fake_send)

    android = {"title": "t", "body": "android body", "actions": [{"action": "open", "title": "Ver"}]}
    ios = {"title": "t", "body": "ios body\nToque para abrir o lead."}

    async def run():
        return await svc.send_to_user(1, android, "lead_alert", ios_payload=ios)

    assert anyio.run(run) == 2
    by_endpoint = dict(sent)
    assert by_endpoint["ios"]["body"].startswith("ios body")
    assert "actions" not in by_endpoint["ios"]
    assert by_endpoint["android"]["actions"]
