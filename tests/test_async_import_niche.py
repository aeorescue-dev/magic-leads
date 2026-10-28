"""Regressao: o wrapper async tem de encaminhar os kwargs de nicho.

O importador chama `db_service.import_b2b_lead(..., niche_key=...)` e o wrapper
async e' o que esta' em `db_service`. Se ele nao repassar os kwargs, o import
rebenta com TypeError em producao (foi apanhado no probe de inventario).
"""
from __future__ import annotations

import pytest

from backend.services.db import AsyncDatabaseService, DatabaseService


@pytest.mark.asyncio
async def test_async_import_b2b_forwards_niche_kwargs(monkeypatch):
    svc = AsyncDatabaseService()
    captured: dict = {}

    def fake_import(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"id": 1, "lead_id": 2, "email": args[0]}

    monkeypatch.setattr(svc._service, "import_b2b_lead", fake_import)

    out = await svc.import_b2b_lead(
        email="a@b.com",
        company_name="Acme Plumbing",
        city="CHICAGO",
        category="Plumbing",
        niche_key="plumbing",
        niche_status="confirmed",
        niche_score=5.0,
        niche_evidence="{}",
        create_contact=False,
    )

    assert out["id"] == 1
    assert captured["kwargs"]["niche_key"] == "plumbing"
    assert captured["kwargs"]["niche_status"] == "confirmed"
    assert captured["kwargs"]["create_contact"] is False
