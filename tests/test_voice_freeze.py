"""Trava global VOICE_FREEZE (contenção de campanhas)."""
from __future__ import annotations

import asyncio

import backend.main as main_module
from backend.services import auto_dialer


def test_launch_is_blocked_when_frozen(monkeypatch):
    monkeypatch.setattr(main_module.settings, "VOICE_FREEZE", True)
    called: list[int] = []
    monkeypatch.setattr(
        main_module.auto_dialer,
        "run_campaign",
        lambda cid: called.append(cid),
    )
    main_module._voice_campaign_tasks.clear()
    main_module._launch_voice_campaign(13)
    assert called == []
    assert main_module._voice_campaign_tasks == {}


def test_run_campaign_is_noop_when_frozen(monkeypatch):
    monkeypatch.setattr(auto_dialer.settings, "VOICE_FREEZE", True)

    def _must_not_touch_db(*_args, **_kwargs):
        raise AssertionError("run_campaign tocou na BD com VOICE_FREEZE=1")

    monkeypatch.setattr(auto_dialer.b2b_voice, "get_campaign", _must_not_touch_db)
    asyncio.run(auto_dialer.run_campaign(13))


def test_resume_due_returns_empty_when_frozen(monkeypatch):
    monkeypatch.setattr(main_module.settings, "VOICE_FREEZE", True)

    def _must_not_query(*_args, **_kwargs):
        raise AssertionError("resume consultou a BD com VOICE_FREEZE=1")

    monkeypatch.setattr(
        main_module.b2b_voice, "paused_campaigns_due", _must_not_query
    )
    assert asyncio.run(main_module._resume_due_voice_campaigns()) == []


def test_freeze_defaults_to_true():
    # Sem override explicito, o produto nasce congelado.
    from backend.config import Settings

    assert Settings.model_fields["VOICE_FREEZE"].default is True
