"""Auto-lote: escolha de cidade/nicho e travas de seguranca."""
from __future__ import annotations

import pytest

from backend.services import auto_batch


def test_escolhe_cidade_com_mais_prontos_e_respeita_zero():
    readiness = {
        "NYC": {"ready": 3},
        "CHICAGO": {"ready": 12},
        "BOSTON": {"ready": 0},
    }
    assert auto_batch.choose_city(readiness) == ("CHICAGO", 12)
    assert auto_batch.choose_city({"BOSTON": {"ready": 0}}) is None


def test_cidade_prioriza_owner_osint_mesmo_com_menos_prontos():
    readiness = {"NYC": {"ready": 40}, "DALLAS": {"ready": 20}}
    assert auto_batch.choose_city(readiness, {"NYC": 1, "DALLAS": 4}) == (
        "DALLAS", 20,
    )
    assert auto_batch.choose_city(readiness, {}) == ("NYC", 40)


def test_nicho_usa_o_topo_do_inventario_ou_default():
    assert auto_batch.choose_niche(
        {"by_niche": [{"niche_key": "plumbing", "c": 9}]}
    ) == "plumbing"
    assert auto_batch.choose_niche({"by_niche": []}) == "general_contractors"


def test_escolhe_nicho_com_as_duas_origens():
    mix = [
        {"niche": "general_contractors", "osint": 0, "generic": 71},
        {"niche": "roofing", "osint": 6, "generic": 2},
        {"niche": "plumbing", "osint": 3, "generic": 0},
    ]
    assert auto_batch.choose_balanced_niche(mix) == "roofing"
    assert auto_batch.choose_balanced_niche(
        [{"niche": "roofing", "osint": 0, "generic": 5}]
    ) is None


def _patch(monkeypatch, *, send="1", quiet=False, queued=0, capacity=4,
           ready=10, enqueue_queued=4):
    calls: dict = {}

    async def fake_cfg(city=""):
        return {"send_enabled": send, "auto_batch_enabled": "1"}

    async def fake_status():
        return {"quiet_hours_now": quiet, "queued": queued,
                "mailbox_remaining_today": capacity}

    async def fake_ready(city, niche=None):
        return {"ready": ready,
                "by_niche": [{"niche_key": "plumbing", "c": ready}]}

    async def fake_enqueue(batch):
        calls["enqueued"] = batch
        return {"queued": enqueue_queued}

    async def fake_mix(city):
        return [{"niche": "plumbing", "osint": 4, "generic": 6}]

    async def fake_set_kv(key, value):
        calls[key] = value

    svc = auto_batch.db_service._service
    monkeypatch.setattr(svc, "get_system_kv", lambda key: None)
    monkeypatch.setattr(
        svc, "create_outbound_batch", lambda **kw: {"id": 7, **kw}
    )
    monkeypatch.setattr(svc, "mark_outbound_batch_previewed", lambda *a, **k: True)
    monkeypatch.setattr(
        svc, "start_outbound_batch", lambda bid: {"id": bid, "status": "started"}
    )
    monkeypatch.setattr(auto_batch.db_service, "get_outbound_config", fake_cfg)
    monkeypatch.setattr(auto_batch.db_service, "outbound_readiness", fake_ready)
    monkeypatch.setattr(auto_batch.db_service, "ready_source_mix", fake_mix)
    monkeypatch.setattr(auto_batch.db_service, "set_system_kv", fake_set_kv)
    monkeypatch.setattr(auto_batch.engine, "status", fake_status)
    monkeypatch.setattr(auto_batch.engine, "enqueue_batch", fake_enqueue)
    monkeypatch.setattr(auto_batch.enrichment_scheduler, "cities", lambda: ("NYC",))
    return calls


@pytest.mark.asyncio
async def test_cria_lote_quando_elegivel(monkeypatch):
    calls = _patch(monkeypatch)
    result = await auto_batch.maybe_create_batch()
    assert result["status"] == "created"
    assert result["city"] == "NYC"
    assert result["niche"] == "plumbing"
    assert result["size"] == 4  # limitado pela capacidade do dia
    assert result["queued"] == 4
    assert calls["enqueued"]["id"] == 7


@pytest.mark.asyncio
async def test_travas_send_off_quiet_fila_e_capacidade(monkeypatch):
    _patch(monkeypatch, send="0")
    assert (await auto_batch.maybe_create_batch())["status"] == "send_off"

    _patch(monkeypatch, quiet=True)
    assert (await auto_batch.maybe_create_batch())["status"] == "quiet_hours"

    _patch(monkeypatch, queued=5)
    assert (await auto_batch.maybe_create_batch())["status"] == "queue_ok"

    _patch(monkeypatch, capacity=0)
    assert (await auto_batch.maybe_create_batch())["status"] == "no_capacity"

    _patch(monkeypatch, ready=0)
    assert (await auto_batch.maybe_create_batch())["status"] == "no_inventory"
