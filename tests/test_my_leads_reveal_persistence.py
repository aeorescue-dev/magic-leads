"""Regressão: depois de reservar e pagar, "Meus Leads" tem de devolver os dados
do proprietário que o utilizador acabou de revelar.

Histórico do bug: o utilizador clicava em "Reservar 1 Hora", o modal abria com
Nome/Telefone/E-mail corretos (o POST /reserve devolve o lead já enriquecido em
memória), o crédito era debitado e a cota consumida. Ao fechar o modal e abrir a
aba "Meus Leads", os mesmos campos apareciam como "sem dados".

Os dados NÃO se perdiam na escrita. A perda era na LEITURA:

  * main.py:111 — `_to_lead_response` mascara owner_name/owner_phone/owner_email
    sempre que `lead["_revealed"]` é falsy (gate de consentimento).
  * O flag `_revealed` só era preenchido em `_annotate_visibility`, invocada
    apenas pelos endpoints de listagem de leads.
  * `/api/me/history` (a aba "Meus Leads") e `/api/me/taken-leads` serializavam
    as linhas de `get_user_leads_history` / `list_leads_with_status` diretamente,
    sem o flag. Logo `show_owner` era sempre False e o proprietary data era
    descartado na resposta — apesar de a linha do SQLite ter tudo e de o reveal
    estar ativo.

Invariantes fixados aqui:
  1. `get_user_leads_history` devolve owner_name/owner_phone/owner_email da linha.
  2. A linha em `leads` mantém os dados depois da reserva (persistência real).
  3. O reveal ativo NO DIA faz `_mark_revealed` marcar `_revealed` => os dados
     aparecem em /api/me/history.
  4. Sem reveal ativo, o gate de consentimento mantém a máscara (None) — a
     correção não abre uma fuga de dados para quem não pagou.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import _hash_token, _to_lead_response, app
from backend.models.schemas import (
    EnrichedLead,
    IssueCategory,
    SourceType,
    UrgencyLevel,
)
from backend.services.db import db_service

EMAIL = "pytest-my-leads-reveal@magicleads.app"
_EXT = {"n": 0}

OWNER_NAME = "MAYNOR WILLIAM"
OWNER_PHONE = "3475550142"
OWNER_EMAIL = "wm.owner@example.com"


def _make_lead() -> int:
    _EXT["n"] += 1
    payload = EnrichedLead(
        external_id=f"pytest-my-leads-reveal-{_EXT['n']}",
        source_type=SourceType.SERVICE_311,
        address=f"{_EXT['n']} REGRESSION STREET",
        city="BROOKLYN",
        state="NY",
        zip_code="11201",
        lat=None,
        lng=None,
        county="KINGS",
        issue_category=IssueCategory.ROOF,
        issue_description="Building collapse - teste de persistencia",
        urgency_level=UrgencyLevel.HIGH,
        owner_name=OWNER_NAME,
        owner_phone=OWNER_PHONE,
        owner_email=OWNER_EMAIL,
        date_reported=datetime(2026, 1, 15, 12, 0, 0),
        image_url=None,
        source_url=None,
    )
    row = db_service._service.insert_lead_new(payload)
    assert row is not None
    return row["id"]


@pytest.fixture(scope="module")
def user_and_client():
    svc = db_service._service
    user = svc.get_user_by_email(EMAIL) or svc.create_user(
        EMAIL, "pytest-hash-not-used", "Pytest MyLeads", plan="pro",
        subscription_status="active",
    )
    assert user is not None
    user_id = user["id"]
    token = "pytest-my-leads-reveal-token"
    svc.create_user_session(user_id, _hash_token(token), "Pytest", None)
    svc.extend_access(user_id, days=7)
    return TestClient(app), {"Authorization": f"Bearer {token}"}, user_id


def _history_entry(client, headers, lead_id: int) -> dict:
    r = client.get("/api/me/history", headers=headers)
    assert r.status_code == 200, r.text
    for lead in r.json()["leads"]:
        if lead["id"] == str(lead_id):
            return lead
    return {}


def test_history_query_returns_owner_columns(user_and_client):
    """A consulta de 'Meus Leads' projeta owner_name/owner_phone/owner_email."""
    _, _, user_id = user_and_client
    lead_id = _make_lead()

    # A consulta parte de lead_holds, por isso o lead tem de estar reservado.
    res = db_service._service.reveal_lead(user_id, lead_id, f"pytest-cols-{lead_id}")
    assert res and not res.get("error"), res

    rows, _kpis = db_service._service.get_user_leads_history(user_id, limit=200)
    row = next((r for r in rows if r["id"] == lead_id), None)
    assert row is not None, "lead reservado nao apareceu em get_user_leads_history"
    assert row["owner_name"] == OWNER_NAME
    assert row["owner_phone"] == OWNER_PHONE


def test_persisted_in_leads_table(user_and_client):
    """A escrita está correta: a linha em `leads` tem os dados enriquecidos."""
    _, _, _ = user_and_client
    lead_id = _make_lead()
    row = db_service._service.get_lead_by_id(lead_id)
    assert row["owner_name"] == OWNER_NAME
    assert row["owner_phone"] == OWNER_PHONE


def test_my_leads_shows_owner_data_after_reveal(user_and_client):
    """Cenário do utilizador: reservar -> fechar modal -> abrir 'Meus Leads'."""
    client, headers, user_id = user_and_client
    lead_id = _make_lead()

    res = db_service._service.reveal_lead(user_id, lead_id, f"pytest-myleads-{lead_id}")
    assert res and not res.get("error"), res

    entry = _history_entry(client, headers, lead_id)
    assert entry, "lead não apareceu em /api/me/history"
    assert entry["owner_name"] == OWNER_NAME, f"owner_name perdido: {entry.get('owner_name')!r}"
    assert entry["owner_phone"] == OWNER_PHONE, f"owner_phone perdido: {entry.get('owner_phone')!r}"
    assert entry["owner_email"] == OWNER_EMAIL, f"owner_email perdido: {entry.get('owner_email')!r}"


def test_masking_still_applies_without_active_reveal():
    """A correção NÃO pode expor dados a quem não revelou (gate de consentimento)."""
    svc = db_service._service
    other = svc.get_user_by_email(EMAIL) or svc.create_user(
        EMAIL + ".b", "pytest-hash-not-used", "Pytest MyLeads B", plan="pro",
        subscription_status="active",
    )
    lead_id = _make_lead()

    reveal = svc.reveal_lead(other["id"], lead_id, f"pytest-mask-{lead_id}")
    assert reveal and not reveal.get("error")

    # Row crua: os dados existem.
    row = svc.get_lead_by_id(lead_id)
    assert row["owner_name"] == OWNER_NAME

    # ...mas o _to_lead_response sem _revealed tem de continuar a mascarar.
    masked = _to_lead_response(dict(row))
    assert masked.owner_name is None
    assert masked.owner_phone is None
    assert masked.owner_email is None


def test_mark_revealed_marks_only_active_reveals(user_and_client):
    """_mark_revealed usa o mesmo predicado de get_revealed_ids (dia + não devolvido)."""
    _, _, user_id = user_and_client
    svc = db_service._service

    revealed_id = _make_lead()
    assert svc.reveal_lead(user_id, revealed_id, f"pytest-flag-a-{revealed_id}")

    # Lead apenas inserido, nunca revelado: não pode receber _revealed=True.
    never_revealed_id = _make_lead()

    rows, _ = svc.get_user_leads_history(user_id, limit=200)
    assert not any(r.get("_revealed") for r in rows), "linhas j\u00e1 vinham marcadas"

    asyncio.run(main_module._mark_revealed(rows, {"id": user_id}))

    flagged = {r["id"]: r["_revealed"] for r in rows}
    assert flagged[revealed_id] is True, "lead com reveal ativo não foi marcado"
    assert flagged.get(never_revealed_id, False) is False, "lead sem reveal foi marcado"

    # Utilizador diferente, sem qualquer reveal, não vê nada marcado.
    other = svc.get_user_by_email(EMAIL + ".c") or svc.create_user(
        EMAIL + ".c", "pytest-hash-not-used", "Pytest MyLeads C", plan="pro",
        subscription_status="active",
    )
    rows3, _ = svc.get_user_leads_history(user_id, limit=200)
    asyncio.run(main_module._mark_revealed(rows3, {"id": other["id"]}))
    assert all(r.get("_revealed") is False for r in rows3)
