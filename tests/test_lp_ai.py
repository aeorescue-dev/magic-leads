"""Testes do provider de tradução/sugestão (Fase 2)."""

from backend.config import settings
from backend.services import lp_ai


def test_detect_language_pt_es_en():
    assert lp_ai.detect_language("Olá, não converto com os anúncios.") == "pt"
    assert lp_ai.detect_language("¿Cómo funciona? Estoy gastando en anuncios.") == "es"
    assert lp_ai.detect_language("En que se diferencia de Angi? Los leads no se comparten.") == "es"
    assert lp_ai.detect_language("How does this work? I spend on ads.") == "en"


def test_suggest_reply_area_uses_city_and_trade():
    text = lp_ai.suggest_reply_pt("area", "Dallas", "Roofing")
    assert "Dallas" in text
    assert "Roofing" in text


def test_translate_identity_does_not_call_provider(monkeypatch):
    monkeypatch.setattr(settings, "LP_AI_PROVIDER", "")
    text, provider = lp_ai.translate("Olá equipa", "pt", "pt")
    assert text == "Olá equipa"
    assert provider == "identity"


def test_translate_mymemory_fallback(monkeypatch):
    monkeypatch.setattr(settings, "LP_AI_PROVIDER", "mymemory")

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"responseData": {"translatedText": "Olá, tudo bem?"}}

    monkeypatch.setattr(lp_ai.httpx, "get", lambda *args, **kwargs: Response())
    text, provider = lp_ai.translate("Hello, how are you?", "en", "pt")
    assert text == "Olá, tudo bem?"
    assert provider == "mymemory"


def test_translate_mymemory_redacts_pii(monkeypatch):
    monkeypatch.setattr(settings, "LP_AI_PROVIDER", "mymemory")

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "responseData": {
                    "translatedText": "Contacte LPEMAILTOKEN1 ou LPPHONETOKEN2."
                }
            }

    monkeypatch.setattr(lp_ai.httpx, "get", lambda *args, **kwargs: Response())
    text, _ = lp_ai.translate(
        "Contact owner@example.com or +1 212 555 0100.", "en", "pt"
    )
    assert "owner@example.com" in text
    assert "+1 212 555 0100" in text
