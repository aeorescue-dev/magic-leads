"""Fase E — telemetria de custo nunca falha em silêncio.

As chamadas pagas (Snov/EmailListVerify) têm de continuar fail-soft, mas uma
falha ao gravar o custo precisa de aparecer nos logs para reconciliação.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from backend.services import db as db_module
from backend.services.enrichment_emaillistverify import EmailListVerifyService
from backend.services.snov import SnovService


def _result() -> SimpleNamespace:
    return SimpleNamespace(
        outcome="valid",
        billed_calls=1,
        latency_ms=10,
        http_status=200,
        email="ops@example.com",
        error=None,
        provider="test",
    )


def test_snov_cost_telemetry_failure_is_logged(monkeypatch, caplog):
    def boom(**_kwargs):
        raise RuntimeError("db busy")

    monkeypatch.setattr(db_module, "record_outbound_enrichment_call", boom)
    with caplog.at_level(logging.WARNING, logger="garimpador"):
        # Não levanta.
        SnovService()._record(_result(), "NYC", "ops@example.com")
    assert any("[SNOV]" in r.message for r in caplog.records)


def test_elv_cost_telemetry_failure_is_logged(monkeypatch, caplog):
    def boom(**_kwargs):
        raise RuntimeError("db busy")

    monkeypatch.setattr(db_module, "record_outbound_enrichment_call", boom)
    with caplog.at_level(logging.WARNING, logger="garimpador"):
        EmailListVerifyService()._record(_result(), "NYC", "ops@example.com")
    assert any("[ELV]" in r.message for r in caplog.records)
