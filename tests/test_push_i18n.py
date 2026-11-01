"""i18n estrita do Web Push (Fase 25).

Guardas:
  * payloads EN/ES não contêm vocabulário português;
  * o locale é resolvido por subscription (en/pt/es), não pelo utilizador;
  * a subscription guarda o locale e é atualizada quando o utilizador muda;
  * textos de ciclo de vida têm chave+params e renderizam nos 3 idiomas.
"""

from __future__ import annotations

import anyio

from backend.services import alert_planner as ap
from backend.services import push_service, translations
from backend.services.db import db_service

LEAD = {
    "id": 1,
    "external_id": "SR26-1",
    "address": "3215 N PAGE AVE",
    "city": "Chicago",
    "lat": 41.938317,
    "lng": -87.827274,
    "issue_category": "Roof",
    "signal_type": "legal_obligation",
    "signal_status": "open",
    "owner_name": "OWNER",
    "phone_verified": 0,
    "date_reported": "2026-10-31T19:25:11",
    "oldest_open_days": 12,
    "repeat_365": 1,
}

# Palavras que só existem em PT (não em EN nem ES).
PT_ONLY = (
    "Chamado",
    "chamado",
    "obrigação",
    "Obrigação",
    "licença emitida",
    "aberto há",
    "telefone sob consulta",
    "Dispensar",
    "Ver lead",
    "mi de si",
    "do centro de",
    "Nova oportunidade",
    "disponível agora",
    "perto de si",
)


def _payload(loc: str, source: str = "gps", distance: float = 2.3) -> dict:
    return ap._build_push_payload(
        LEAD, "Roof", "legal_obligation", loc,
        distance_mi=distance, show_distance=True, confidence_pct=None,
        show_address=True, distance_source=source, base_label="CHICAGO",
    )


def test_payload_pt_usa_mockup():
    p = _payload("pt")
    assert p["title"].startswith("⚖️ Obrigação legal")
    assert "a 2,3 mi de si" in p["body"]
    assert p["actions"][0]["title"] == "Ver lead"
    assert p["actions"][1]["title"] == "Dispensar"


def test_payload_en_sem_vocabulario_portugues():
    p = _payload("en")
    haystack = " ".join([p["title"], p["body"], *[a["title"] for a in p["actions"]]])
    for word in PT_ONLY:
        assert word not in haystack, f"EN vazou PT: {word!r} em {haystack!r}"
    assert p["title"].startswith("⚖️ Legal obligation")
    assert "2.3 mi away" in p["body"]
    assert [a["title"] for a in p["actions"]] == ["View lead", "Dismiss"]


def test_payload_es_sem_vocabulario_portugues():
    p = _payload("es")
    haystack = " ".join([p["title"], p["body"], *[a["title"] for a in p["actions"]]])
    # "Ver lead" é espanhol correto (igual ao PT) — não conta como vazamento.
    for word in [w for w in PT_ONLY if w != "Ver lead"]:
        assert word not in haystack, f"ES vazou PT: {word!r} em {haystack!r}"
    assert p["title"].startswith("⚖️ Obligación legal")
    assert "a 2,3 mi de ti" in p["body"]
    assert [a["title"] for a in p["actions"]] == ["Ver lead", "Descartar"]


def test_city_distance_localizada_nos_tres_idiomas():
    pt = _payload("pt", source="city", distance=10.97)
    en = _payload("en", source="city", distance=10.97)
    es = _payload("es", source="city", distance=10.97)
    assert "~11,0 mi do centro de Chicago" in pt["body"]
    assert "about 11.0 mi from downtown Chicago" in en["body"]
    assert "a unos 11,0 mi del centro de Chicago" in es["body"]
    for p in (en, es):
        assert "do centro de" not in p["body"]


def test_ios_cta_localizada():
    for loc, cta in (
        ("pt", "Toque para abrir o lead."),
        ("en", "Tap to open the lead."),
        ("es", "Toca para abrir el lead."),
    ):
        ios = ap._ios_variant(_payload(loc), loc)
        assert cta in ios["body"]
        assert "actions" not in ios


def test_digest_actions_localizadas():
    assert ap._DIGEST_ACTIONS["en"] == ("View opportunities", "Dismiss")
    assert ap._DIGEST_ACTIONS["es"] == ("Ver oportunidades", "Descartar")
    assert ap._DIGEST_ACTIONS["pt"] == ("Ver oportunidades", "Dispensar")


def test_lifecycle_render_localizado_sem_pt():
    en = translations.render(
        "reveal_urgent", "en", subject="3215 N PAGE AVE", category="Roof"
    )
    es = translations.render(
        "stage_warning_negotiate", "es", address="3215 N PAGE AVE"
    )
    assert en and es
    for text in (en["title"], en["message"], es["title"], es["message"]):
        for word in ("Últimos", "obrigação", "Chamado", "Dispensar", "Faltam"):
            assert word not in text
    assert "Last 15 minutes" in en["title"]
    assert "Quedan 24 horas" in es["title"]


# --------------------------------------------------------------- DB / envio


def _user(locale: str = "en") -> int:
    svc = db_service._service
    row = svc.create_user(
        email=f"i18n-{locale}-push@example.com",
        password_hash="x",
        company_name="I18N Co",
        locale=locale,
    )
    assert row
    return int(row["id"])


def test_subscription_guarda_e_propaga_locale():
    svc = db_service._service
    uid = _user("en")
    try:
        assert svc.add_push_subscription(
            uid, f"https://example.invalid/{uid}", "p", "a", "UA", "label"
        )
        rows = svc.get_user_push_subscriptions(uid)
        assert rows and rows[0]["locale"] == "en"

        svc.update_user_locale(uid, "es")
        rows = svc.get_user_push_subscriptions(uid)
        assert rows[0]["locale"] == "es"
        assert svc.get_user_locale(uid) == "es"
    finally:
        from backend.services.db import get_connection

        conn = get_connection()
        try:
            conn.execute("DELETE FROM push_subscriptions WHERE user_id=?", (uid,))
            conn.execute("DELETE FROM users WHERE id=?", (uid,))
            conn.commit()
        finally:
            conn.close()


def test_send_to_user_escolhe_payload_pelo_locale_da_subscription(monkeypatch):
    svc = push_service.push_service
    monkeypatch.setattr(svc, "_configured", True)

    async def _enabled(user_id):
        return True

    async def _subs(user_id):
        return [
            {"endpoint": "pt", "p256dh": "a", "auth": "b", "user_id": user_id,
             "locale": "pt", "user_agent": "Mozilla/5.0 (Windows NT 10.0)"},
            {"endpoint": "en", "p256dh": "a", "auth": "b", "user_id": user_id,
             "locale": "en", "user_agent": "Mozilla/5.0 (Windows NT 10.0)"},
            {"endpoint": "es", "p256dh": "a", "auth": "b", "user_id": user_id,
             "locale": "es", "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"},
        ]

    async def _locale(user_id):
        return "en"

    sent: list = []

    async def _fake_send(sub, payload, kind="custom", user_id=None, ttl=14400,
                         urgency="high", **_kw):
        sent.append((sub["endpoint"], payload))
        return True

    monkeypatch.setattr(push_service.db_service, "is_push_enabled", _enabled)
    monkeypatch.setattr(push_service.db_service, "get_user_push_subscriptions", _subs)
    monkeypatch.setattr(push_service.db_service, "get_user_locale", _locale)
    monkeypatch.setattr(svc, "_send_single", _fake_send)

    payloads = {
        "pt": {"title": "t", "body": "a 2,3 mi de si", "actions": [{"action": "open", "title": "Ver lead"}]},
        "en": {"title": "t", "body": "2.3 mi away", "actions": [{"action": "open", "title": "View lead"}]},
        "es": {"title": "t", "body": "a 2,3 mi de ti", "actions": [{"action": "open", "title": "Ver lead"}]},
    }
    ios = {
        "pt": {"body": "a 2,3 mi de si\nToque para abrir o lead."},
        "en": {"body": "2.3 mi away\nTap to open the lead."},
        "es": {"body": "a 2,3 mi de ti\nToca para abrir el lead."},
    }

    async def run():
        return await svc.send_to_user(
            1, payloads["en"], "lead_alert",
            payloads_by_locale=payloads, ios_payloads_by_locale=ios,
        )

    assert anyio.run(run) == 3
    by_endpoint = dict(sent)
    assert by_endpoint["pt"]["body"].startswith("a 2,3 mi de si")
    assert by_endpoint["en"]["body"].startswith("2.3 mi away")
    # iOS recebe a variante com CTA (ES) e sem ações.
    assert "Toca para abrir el lead." in by_endpoint["es"]["body"]
    assert "actions" not in by_endpoint["es"]
    assert by_endpoint["pt"]["actions"]
