"""Renderização de notificações in-app no locale do utilizador.

O texto gravado serve de fallback; quando existe msg_key + msg_params a
notificação é localizada na leitura, sem alterar a API do frontend.
"""

from backend.main import _localize_notification


def test_without_msg_key_returns_original():
    row = {"title": "Resumo", "message": "M", "msg_key": None, "msg_params": None}
    out = _localize_notification(row, "pt")
    assert out["title"] == "Resumo"
    assert out["message"] == "M"


def test_with_msg_key_renders_user_locale():
    row = {
        "title": "Daily digest",
        "message": "fallback",
        "msg_key": "digest",
        "msg_params": '{"n": 3, "limit": 6}',
    }
    pt = _localize_notification(row, "pt")
    assert pt["title"] == "Resumo diário de alertas"
    assert "3" in pt["message"] and "6" in pt["message"]

    en = _localize_notification(row, "en")
    assert en["title"] == "Daily digest"


def test_malformed_params_fall_back_to_group_text():
    row = {
        "title": "Status updated",
        "message": "The lead X is now 'done'",
        "msg_key": "status_change",
        "msg_params": "not-json",
    }
    out = _localize_notification(row, "en")
    assert out["title"] == "Status updated"
    # sem params válidos, os placeholders ficam por preencher (texto do grupo)
    assert "{" in out["message"]


def test_locale_none_defaults_to_english():
    row = {"title": "t", "message": "m", "msg_key": "digest", "msg_params": None}
    out = _localize_notification(row, None)
    assert out["title"] == "Daily digest"
