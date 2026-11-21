"""Politica unica de telefone: o que entrega, o que bloqueia e o selo."""
from __future__ import annotations

import asyncio

import pytest

from backend.config import settings
from backend.services import phone_policy
from backend.services.owner_resolution.base import build_record


def _lead(**overrides):
    base = {
        "id": 9001,
        "address": "10 MAIN ST",
        "city": "BOSTON",
        "state": "MA",
        "zip_code": "02127",
        "owner_name": "JOHN SMITH",
        "owner_phone": None,
        "phone_verified": 0,
        "mailing_address": None,
        "bbl": None,
    }
    base.update(overrides)
    return base


def _record(**overrides):
    raw = {
        "owner_name": "JOHN SMITH",
        "parcel_key": "PID123",
        "match_method": "exact_address",
        "match_score": 1.0,
        "record_year": 2025,
    }
    raw.update(overrides)
    return build_record(address="10 MAIN ST", city="BOSTON", raw=raw)


def _decide(lead, owner=None):
    return asyncio.run(
        phone_policy.decide(lead, owner=owner, allow_resolve=False)
    )


def test_person_high_confidence_uses_l2(monkeypatch):
    monkeypatch.setattr(settings, "PHONE_L3_UNNAMED_ENABLED", False, raising=False)
    decision = _decide(_lead(), _record())
    assert decision.state == phone_policy.STATE_IN_PROGRESS
    assert decision.allow_paid_call is True
    assert decision.candidates[0].layer == "L2"
    assert decision.candidates[0].owner_name == "JOHN SMITH"


def test_stale_record_blocks_paid_call(monkeypatch):
    monkeypatch.setattr(settings, "PHONE_ALLOW_STALE", False, raising=False)
    decision = _decide(_lead(), _record(record_year=2011))
    assert decision.state == phone_policy.STATE_BLOCKED
    assert decision.reason == "stale_property_record"
    assert decision.allow_paid_call is False


def test_low_confidence_owner_blocks(monkeypatch):
    decision = _decide(
        _lead(), _record(match_method="street_substring", match_score=0.7, parcel_key=None)
    )
    assert decision.state == phone_policy.STATE_BLOCKED
    assert decision.reason.startswith("owner_confidence_")


def test_medium_confidence_allows_l2_but_never_verified(monkeypatch):
    rec = _record(match_method="number_only", match_score=0.75)
    decision = _decide(_lead(), rec)
    assert decision.state == phone_policy.STATE_IN_PROGRESS
    candidate = decision.candidates[0]
    assert candidate.layer == "L2"
    assert phone_policy.verified_result(candidate, True, rec) is False


def test_entity_without_l3_is_blocked(monkeypatch):
    monkeypatch.setattr(settings, "PHONE_ENTITY_MODE", "address_only", raising=False)
    monkeypatch.setattr(settings, "PHONE_L3_UNNAMED_ENABLED", False, raising=False)
    decision = _decide(_lead(owner_name="ACME HOLDINGS LLC"), _record(owner_name="ACME HOLDINGS LLC"))
    assert decision.state == phone_policy.STATE_BLOCKED
    assert decision.reason == "entity_l3_disabled"


def test_entity_address_only_is_labeled_unverified(monkeypatch):
    monkeypatch.setattr(settings, "PHONE_ENTITY_MODE", "address_only", raising=False)
    monkeypatch.setattr(settings, "PHONE_L3_UNNAMED_ENABLED", True, raising=False)
    decision = _decide(_lead(owner_name="ACME HOLDINGS LLC"), _record(owner_name="ACME HOLDINGS LLC"))
    assert decision.state == phone_policy.STATE_IN_PROGRESS
    assert decision.candidates[0].layer == "L3"
    assert decision.candidates[0].can_verify is False
    assert phone_policy.label_for(decision.candidates[0], False) == phone_policy.LABEL_ENTITY_UNVERIFIED


def test_absentee_tries_mailing_first(monkeypatch):
    monkeypatch.setattr(settings, "PHONE_L3_UNNAMED_ENABLED", False, raising=False)
    rec = _record(
        owner_name="JOHN SMITH",
        mailing_address="500 OCEAN DR, MIAMI, 33139",
        owner_occupied=False,
    )
    decision = _decide(_lead(), rec)
    assert decision.state == phone_policy.STATE_IN_PROGRESS
    assert decision.candidates[0].kind == "mailing"
    assert decision.candidates[0].address.startswith("500 OCEAN DR")


def test_absentee_property_fallback_requires_l3_flag(monkeypatch):
    rec = _record(
        owner_name="JOHN SMITH",
        mailing_address="500 OCEAN DR, MIAMI, 33139",
        owner_occupied=False,
    )
    monkeypatch.setattr(settings, "PHONE_L3_UNNAMED_ENABLED", False, raising=False)
    assert len(_decide(_lead(), rec).candidates) == 1

    monkeypatch.setattr(settings, "PHONE_L3_UNNAMED_ENABLED", True, raising=False)
    decision = _decide(_lead(), rec)
    assert [c.kind for c in decision.candidates] == ["mailing", "property"]
    assert decision.candidates[1].can_verify is False


def test_verified_requires_l2_and_fresh_record():
    candidate_l2 = phone_policy.LookupCandidate(
        address="10 MAIN ST", kind="property", layer="L2",
        owner_name="JOHN SMITH", can_verify=True,
    )
    candidate_l3 = phone_policy.LookupCandidate(
        address="10 MAIN ST", kind="property", layer="L3",
        owner_name=None, can_verify=False,
    )
    fresh = _record()
    stale = _record(record_year=2011)

    assert phone_policy.verified_result(candidate_l2, True, fresh) is True
    assert phone_policy.verified_result(candidate_l2, True, stale) is False
    assert phone_policy.verified_result(candidate_l3, True, fresh) is False
    assert phone_policy.verified_result(candidate_l2, False, fresh) is False


def test_cached_phone_is_served_without_call():
    decision = _decide(_lead(owner_phone="+16175550100", phone_verified=1), None)
    assert decision.state == phone_policy.STATE_READY
    assert decision.phone == "+16175550100"
    assert decision.verified is True
    assert decision.allow_paid_call is False


def test_property_phone_is_not_verified():
    decision = _decide(_lead(owner_phone="+16175550100", phone_verified=0), None)
    assert decision.state == phone_policy.STATE_READY
    assert decision.verified is False
    assert decision.label == phone_policy.LABEL_UNVERIFIED


@pytest.mark.parametrize("name", ["", None])
def test_missing_owner_never_calls(name):
    decision = _decide(_lead(owner_name=name), None)
    assert decision.state == phone_policy.STATE_NO_PHONE
    assert decision.reason == "owner_missing"
