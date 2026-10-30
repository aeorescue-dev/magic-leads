"""Copy do produto: o modelo é passe semanal, não venda de créditos.

Guardas estáticos para a barra lateral e para as 3 línguas. Se alguém voltar a
mostrar “Saldo de Créditos”/“créditos disponíveis” ou apagar a cota diária, o
teste falha.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "frontend" / "lib" / "i18n.tsx"
DASHBOARD = (
    ROOT
    / "frontend"
    / "app"
    / "[locale]"
    / "(dashboard)"
    / "dashboard"
    / "page.tsx"
)

NEW_KEYS = (
    "dashboard.sidebar.daily_quota",
    "dashboard.sidebar.daily_quota_used",
    "dashboard.sidebar.daily_quota_reset",
)
OLD_KEYS = (
    "dashboard.sidebar.credit_balance",
    "dashboard.sidebar.credits_available",
    "dashboard.sidebar.today_used",
)
FORBIDDEN_COPY = (
    "saldo de créditos",
    "créditos disponíveis",
    "credit balance",
    "credits available",
    "saldo de créditos",
    "créditos disponibles",
)


def _locale_blocks() -> dict[str, str]:
    text = I18N.read_text(encoding="utf-8")
    pt = text.index("const PT: Dict = {")
    en = text.index("const EN: Dict = {")
    es = text.index("const ES: Dict = {")
    end = text.index("export const DICTS")
    return {
        "pt": text[pt:en],
        "en": text[en:es],
        "es": text[es:end],
    }


def test_new_daily_quota_keys_exist_in_all_locales():
    blocks = _locale_blocks()
    assert set(blocks) == {"pt", "en", "es"}
    for lang, block in blocks.items():
        for key in NEW_KEYS:
            assert f'"{key}"' in block, f"{lang} sem {key}"


def test_old_credit_keys_removed():
    text = I18N.read_text(encoding="utf-8")
    for key in OLD_KEYS:
        assert f'"{key}"' not in text, f"chave antiga ainda presente: {key}"


def test_no_credit_selling_copy_anywhere_in_i18n():
    text = I18N.read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN_COPY:
        assert phrase not in text, f"copy de venda de créditos reapareceu: {phrase!r}"


def test_dashboard_sidebar_renders_daily_usage_not_credit_balance():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "dashboard.sidebar.daily_quota" in source
    assert "dailyStats?.used" in source
    assert "credit_balance" not in source
    assert "credits_available" not in source
    # O rótulo não pode ter fallback hardcoded em português.
    assert "Saldo de Créditos" not in source
    assert "créditos disponíveis" not in source
