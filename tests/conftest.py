"""Configuração de testes.

Isola o SQLite de teste ANTES de qualquer import do backend, para que os testes
de despacho NUNCA toquem o banco de desenvolvimento/produção (data/leads.db).
"""

import os
import tempfile

_TMP_DB = os.path.join(tempfile.gettempdir(), "magicleads_test_leads.db")
_TMP_ANALYTICS = os.path.join(tempfile.gettempdir(), "magicleads_test_analytics.db")
_TMP_INVESTOR = os.path.join(tempfile.gettempdir(), "magicleads_test_investor.db")
_TMP_VOICE = os.path.join(tempfile.gettempdir(), "magicleads_test_voice.db")
_TMP_SHOWCASE = os.path.join(tempfile.gettempdir(), "magicleads_test_showcase.db")
for _suffix in ("", "-wal", "-shm"):
    try:
        os.remove(_TMP_DB + _suffix)
    except OSError:
        pass
    try:
        os.remove(_TMP_ANALYTICS + _suffix)
    except OSError:
        pass
    try:
        os.remove(_TMP_INVESTOR + _suffix)
    except OSError:
        pass
    try:
        os.remove(_TMP_VOICE + _suffix)
    except OSError:
        pass
    try:
        os.remove(_TMP_SHOWCASE + _suffix)
    except OSError:
        pass

os.environ["LEADS_DB_PATH"] = _TMP_DB
os.environ["ANALYTICS_DB_PATH"] = _TMP_ANALYTICS
os.environ["INVESTOR_DB_PATH"] = _TMP_INVESTOR
os.environ["VOICE_DB_PATH"] = _TMP_VOICE
os.environ["SHOWCASE_DB_PATH"] = _TMP_SHOWCASE
os.environ.pop("LEADS_RESET_ON_BOOT", None)
os.environ.pop("LEADS_SEED_FILE", None)
os.environ.pop("DATA_DIR", None)
# Segredo determinístico para assinatura de cliques push nos testes.
os.environ.setdefault("PUSH_CLICK_SECRET", "pytest-push-click-secret")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _voice_clock(monkeypatch):
    """Congela o relogio da voz num horario permitido (09:00-20:00 ET).

    Sem isto, testes de fila/chamada falham conforme a hora real do CI.
    Ficheiros que precisam de outro instante sobrepoem com o seu monkeypatch.
    """
    monkeypatch.setenv("VOICE_NOW_ISO", "2026-11-02T16:00:00+00:00")
    yield


@pytest.fixture(autouse=True)
def _clear_perf_caches():
    """Fase 22: isola os caches in-process entre testes.

    `get_stats`/`get_public_metrics`/`get_dashboard_summary` guardam 45–60 s.
    Os testes escrevem direto na BD (sem `record_scrape_run`), por isso o cache
    de outro teste apareceria como valor stale.
    """
    from backend.services import db as dbmod

    dbmod.clear_global_metrics_cache()
    dbmod.clear_dashboard_summary_cache()
    yield
    dbmod.clear_global_metrics_cache()
    dbmod.clear_dashboard_summary_cache()
