"""Correção crítica: contas novas nascem em Inglês (mercado EUA).

`pt` e `es` continuam suportados, mas apenas por escolha explícita.
O fallback de locale inválido/ausente passa a ser `en`, não `pt`.
"""

import uuid

from backend.services.db import db_service
from backend.services.translations import DEFAULT_LOCALE, normalize


def test_default_locale_is_english():
    assert DEFAULT_LOCALE == "en"
    assert normalize(None) == "en"
    assert normalize("") == "en"
    assert normalize("fr") == "en"


def test_explicit_locales_still_work():
    assert normalize("pt-BR") == "pt"
    assert normalize("en-US") == "en"
    assert normalize("es") == "es"


def test_create_user_defaults_to_english():
    email = f"locale_{uuid.uuid4().hex[:10]}@test.com"
    user = db_service._service.create_user(email, "not-a-real-hash", "Test Co")
    assert user is not None
    assert user["locale"] == "en"
