"""Politica unica de telefone para as 4 cidades.

O que decide
------------
1. Se ja ha telefone (lead ou cache) -> entrega.
2. Se o dono nao existe / morada nao resolve -> nao entrega e nao paga.
3. Se o registo esta velho (> PHONE_STALE_YEARS) -> nao paga.
4. Se a confianca do casamento e' baixa -> nao paga.
5. Entidade (LLC/trust/building): so com `PHONE_ENTITY_MODE`; por defeito
   `address_only`, sempre rotulado e nunca `verified`.
6. Pessoa: L2 por nome+morada. Absentee: tenta a mailing primeiro; o imovel
   so como fallback rotulado.

`verified` nunca e' "o provider respondeu". E' uma conjuncao de prova:
parcela exacta + nome compativel + linha activa + camada L2 + registo fresco.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..config import settings
from . import phone_cache
from .lead_rules import address_is_resolvable, get_owner_kind
from .owner_resolution import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    OWNER_KIND_BUILDING,
    OWNER_KIND_COMPANY,
    OWNER_KIND_PUBLIC,
    OWNER_KIND_TRUST,
    OwnerRecord,
    resolve_owner,
)
from .owner_resolution.base import is_stale, mailing_matches_property

STATE_READY = "ready"
STATE_IN_PROGRESS = "in_progress"
STATE_NO_PHONE = "no_phone"
STATE_BLOCKED = "blocked"

LABEL_OWNER_VERIFIED = "owner_verified"
LABEL_PROPERTY_UNVERIFIED = "property_phone_unverified"
LABEL_ENTITY_UNVERIFIED = "entity_phone_unverified"
LABEL_UNVERIFIED = "unverified"

ENTITY_KINDS = frozenset(
    {OWNER_KIND_COMPANY, OWNER_KIND_TRUST, OWNER_KIND_PUBLIC, OWNER_KIND_BUILDING}
)


@dataclass(frozen=True)
class LookupCandidate:
    address: str
    kind: str  # property | mailing
    layer: str  # L2 | L3
    owner_name: Optional[str]
    can_verify: bool


@dataclass(frozen=True)
class PhoneDecision:
    state: str
    reason: str
    cache_key: str
    phone: Optional[str] = None
    verified: bool = False
    label: Optional[str] = None
    owner: Optional[OwnerRecord] = None
    owner_name: Optional[str] = None
    owner_kind: str = "unknown"
    candidates: tuple[LookupCandidate, ...] = field(default_factory=tuple)

    @property
    def allow_paid_call(self) -> bool:
        return self.state == STATE_IN_PROGRESS and bool(self.candidates)

    @property
    def lookup_address_kind(self) -> Optional[str]:
        return self.candidates[0].kind if self.candidates else None


def _owner_from_lead(lead: dict[str, Any]) -> Optional[OwnerRecord]:
    """Reconstroi o OwnerRecord a partir da proveniencia persistida.

    Evita repetir a consulta publica no clique e no worker. Sem proveniencia
    (leads antigos) a confianca fica `medium`: pode procurar, nunca "verificar".
    """
    name = str(lead.get("owner_name") or "").strip()
    if not name:
        return None
    persisted_kind = str(lead.get("owner_kind") or "").strip()
    if persisted_kind:
        owner_kind = persisted_kind
    else:
        kind = get_owner_kind(name)
        owner_kind = (
            "company" if kind == "company" else ("person" if kind == "person" else "unknown")
        )
    mailing = str(lead.get("mailing_address") or "").strip() or None
    owner_occupied = None
    if mailing:
        owner_occupied = mailing_matches_property(lead.get("address"), mailing)
    record_year = lead.get("owner_record_year")
    try:
        record_year = int(record_year) if record_year is not None else None
    except (TypeError, ValueError):
        record_year = None
    confidence = str(lead.get("owner_confidence") or CONFIDENCE_MEDIUM)
    return OwnerRecord(
        address=str(lead.get("address") or ""),
        city=str(lead.get("city") or ""),
        owner_name=name,
        owner_kind=owner_kind,
        parcel_key=str(lead.get("owner_parcel_key") or lead.get("bbl") or "").strip() or None,
        mailing_address=mailing,
        record_year=record_year,
        owner_occupied=owner_occupied,
        confidence=confidence,
        match_method=str(lead.get("owner_match_method") or "persisted_unknown"),
        match_score=1.0 if confidence == CONFIDENCE_HIGH else 0.75,
        source_dataset=lead.get("owner_source_dataset"),
        stale=is_stale(
            record_year, int(getattr(settings, "PHONE_STALE_YEARS", 5) or 5)
        ),
    )


def _lead_owner_kind(lead: dict[str, Any], owner: Optional[OwnerRecord]) -> str:
    if owner is not None:
        return owner.owner_kind
    kind = get_owner_kind(lead.get("owner_name"))
    return "company" if kind == "company" else ("person" if kind == "person" else "unknown")


async def decide(
    lead: dict[str, Any],
    *,
    owner: Optional[OwnerRecord] = None,
    trigger: str = "user_click",
    allow_resolve: bool = True,
) -> PhoneDecision:
    """Decide o que fazer com o telefone deste lead, sem chamar o provider.

    `allow_resolve=False` no worker: o endpoint ja resolveu e persistiu o dono;
    repetir a consulta publica no job so adicionaria latencia e carga.
    """
    lead_id = int(lead.get("id") or 0)
    address = str(lead.get("address") or "").strip()
    zip_code = str(lead.get("zip_code") or "").strip() or None
    owner_name = str(lead.get("owner_name") or "").strip() or None

    if owner is None and allow_resolve and owner_name and address:
        owner = await resolve_owner(address, lead.get("city"), bbl=lead.get("bbl"))
    if owner is None and not allow_resolve:
        owner = _owner_from_lead(lead)

    if owner is not None:
        owner_name = owner.owner_name
    owner_kind = _lead_owner_kind(lead, owner)

    cache_key = phone_cache.build_cache_key(lead_id, owner_name, address, zip_code)

    # 1) Telefone ja persistido no lead.
    existing_phone = str(lead.get("owner_phone") or "").strip()
    if existing_phone:
        verified = bool(int(lead.get("phone_verified") or 0))
        return PhoneDecision(
            state=STATE_READY,
            reason="lead_phone",
            cache_key=cache_key,
            phone=existing_phone,
            verified=verified,
            label=LABEL_OWNER_VERIFIED if verified else LABEL_UNVERIFIED,
            owner=owner,
            owner_name=owner_name,
            owner_kind=owner_kind,
        )

    # 2) Cache persistente (positiva ou negativa).
    cached = phone_cache.get(cache_key)
    if cached is not None:
        cached_phone = str(cached.get("phone") or "").strip()
        if cached_phone:
            return PhoneDecision(
                state=STATE_READY,
                reason="cache_hit",
                cache_key=cache_key,
                phone=cached_phone,
                verified=bool(int(cached.get("verified") or 0)),
                label=cached.get("label") or LABEL_UNVERIFIED,
                owner=owner,
                owner_name=owner_name,
                owner_kind=owner_kind,
            )
        return PhoneDecision(
            state=STATE_NO_PHONE,
            reason=str(cached.get("result_code") or "cache_negative"),
            cache_key=cache_key,
            owner=owner,
            owner_name=owner_name,
            owner_kind=owner_kind,
        )

    # 3) Sem dono ou sem morada resolvivel: nunca pagar.
    if not owner_name:
        return PhoneDecision(
            state=STATE_NO_PHONE,
            reason="owner_missing",
            cache_key=cache_key,
            owner_kind=owner_kind,
        )
    if not address_is_resolvable(address):
        return PhoneDecision(
            state=STATE_NO_PHONE,
            reason="address_incomplete",
            cache_key=cache_key,
            owner=owner,
            owner_name=owner_name,
            owner_kind=owner_kind,
        )

    # 4) Registo velho / confianca baixa: nao pagar.
    if owner is not None and owner.stale and not bool(
        getattr(settings, "PHONE_ALLOW_STALE", False)
    ):
        return PhoneDecision(
            state=STATE_BLOCKED,
            reason="stale_property_record",
            cache_key=cache_key,
            owner=owner,
            owner_name=owner_name,
            owner_kind=owner_kind,
        )
    if owner is not None and owner.confidence == CONFIDENCE_LOW:
        # Casamento fraco (so' rua por substring): nao se paga para adivinhar.
        # `medium` (numero exacto, rua por LIKE/intervalo) pode seguir para L2,
        # mas NUNCA sai como verificado — a formula exige `high`.
        return PhoneDecision(
            state=STATE_BLOCKED,
            reason=f"owner_confidence_{owner.confidence}",
            cache_key=cache_key,
            owner=owner,
            owner_name=owner_name,
            owner_kind=owner_kind,
        )

    mailing = str(
        (owner.mailing_address if owner else lead.get("mailing_address")) or ""
    ).strip()
    absentee = bool(owner.is_absentee) if owner is not None else False

    # 5) Entidades: nunca entregar telefone de imovel como "dono verificado".
    if owner_kind in ENTITY_KINDS:
        mode = str(getattr(settings, "PHONE_ENTITY_MODE", "address_only") or "address_only")
        if mode == "off":
            return PhoneDecision(
                state=STATE_BLOCKED,
                reason="entity_phone_disabled",
                cache_key=cache_key,
                owner=owner,
                owner_name=owner_name,
                owner_kind=owner_kind,
            )
        if mode == "address_only" and not bool(
            getattr(settings, "PHONE_L3_UNNAMED_ENABLED", False)
        ):
            # O L3 sem nome continua desligado por defeito. Sem essa flag, uma
            # entidade sem decisor nao tem como ser consultada sem violar o
            # guard de custo — logo nao se entrega telefone nenhum.
            return PhoneDecision(
                state=STATE_BLOCKED,
                reason="entity_l3_disabled",
                cache_key=cache_key,
                owner=owner,
                owner_name=owner_name,
                owner_kind=owner_kind,
            )
        officer_name = None
        if mode == "officer":
            from .corporate_officers import resolve_officer

            officer = await resolve_officer(owner_name, lead.get("city"), lead.get("state"))
            if officer is not None:
                officer_name = officer.name
            else:
                mode = "address_only"
                if not bool(getattr(settings, "PHONE_L3_UNNAMED_ENABLED", False)):
                    return PhoneDecision(
                        state=STATE_BLOCKED,
                        reason="entity_l3_disabled",
                        cache_key=cache_key,
                        owner=owner,
                        owner_name=owner_name,
                        owner_kind=owner_kind,
                    )
        if mode == "officer" and officer_name:
            candidates = _person_candidates(
                address, mailing, absentee, officer_name,
                allow_property_fallback=True,
            )
        else:
            candidates = (
                LookupCandidate(
                    address=address,
                    kind="property",
                    layer="L3",
                    owner_name=None,
                    can_verify=False,
                ),
            )
        return PhoneDecision(
            state=STATE_IN_PROGRESS,
            reason="entity_address_only" if not officer_name else "entity_officer",
            cache_key=cache_key,
            owner=owner,
            owner_name=officer_name or owner_name,
            owner_kind=owner_kind,
            candidates=candidates,
        )

    # 6) Pessoa.
    candidates = _person_candidates(
        address, mailing, absentee, owner_name, allow_property_fallback=True
    )
    return PhoneDecision(
        state=STATE_IN_PROGRESS,
        reason="person_lookup",
        cache_key=cache_key,
        owner=owner,
        owner_name=owner_name,
        owner_kind=owner_kind,
        candidates=candidates,
    )


def _person_candidates(
    address: str,
    mailing: str,
    absentee: bool,
    owner_name: Optional[str],
    *,
    allow_property_fallback: bool,
) -> tuple[LookupCandidate, ...]:
    candidates: list[LookupCandidate] = []
    if absentee and mailing:
        candidates.append(
            LookupCandidate(
                address=mailing, kind="mailing", layer="L2",
                owner_name=owner_name, can_verify=True,
            )
        )
        if allow_property_fallback and bool(
            getattr(settings, "PHONE_L3_UNNAMED_ENABLED", False)
        ):
            candidates.append(
                LookupCandidate(
                    address=address, kind="property", layer="L3",
                    owner_name=None, can_verify=False,
                )
            )
    else:
        candidates.append(
            LookupCandidate(
                address=address, kind="property", layer="L2",
                owner_name=owner_name, can_verify=True,
            )
        )
    return tuple(candidates)


def label_for(candidate: LookupCandidate, verified: bool) -> str:
    if verified:
        return LABEL_OWNER_VERIFIED
    if candidate.kind == "mailing":
        return LABEL_UNVERIFIED
    if candidate.layer == "L3":
        return LABEL_ENTITY_UNVERIFIED
    return LABEL_PROPERTY_UNVERIFIED


def verified_result(
    candidate: LookupCandidate,
    result_verified: bool,
    owner: Optional[OwnerRecord],
) -> bool:
    """Formula unica: so e' verificado com prova em todas as dimensoes."""
    return bool(
        result_verified
        and candidate.can_verify
        and candidate.layer == "L2"
        and (owner is None or (owner.confidence == CONFIDENCE_HIGH and not owner.stale))
    )
