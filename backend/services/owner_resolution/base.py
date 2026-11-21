"""Contrato unico de resolucao do proprietario (4 cidades, 1 interface).

Porque este modulo existe
-------------------------
Antes, cada chamador recebia um `dict` do `enrichment.py` sem saber *como* o
dono foi casado. Um BBL exacto e um LIKE por rua produziam o mesmo dict, e a
camada paga tratava os dois como iguais. Aqui o resultado passa a ter
proveniencia (`match_method`), confianca e idade do registo, para que a
politica de telefone possa recusar dados fracos antes de gastar dinheiro.

Nada aqui inventa dados: se o dataset nao deu dono, devolve `None`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional

from .. import lead_rules

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

OWNER_KIND_PERSON = "person"
OWNER_KIND_COMPANY = "company"
OWNER_KIND_TRUST = "trust"
OWNER_KIND_PUBLIC = "public"
OWNER_KIND_BUILDING = "building"
OWNER_KIND_UNKNOWN = "unknown"

_EXACT_METHODS = frozenset({"bbl", "exact_address"})
_MEDIUM_METHODS = frozenset({"range", "number_only"})


@dataclass(frozen=True)
class OwnerRecord:
    """Proprietario resolvido + a prova de como foi resolvido."""

    address: str
    city: str
    owner_name: str
    owner_kind: str
    parcel_key: Optional[str]
    mailing_address: Optional[str]
    record_year: Optional[int]
    owner_occupied: Optional[bool]
    confidence: str
    match_method: str
    match_score: float
    source_dataset: Optional[str]
    stale: bool
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_entity(self) -> bool:
        return self.owner_kind in (
            OWNER_KIND_COMPANY,
            OWNER_KIND_TRUST,
            OWNER_KIND_PUBLIC,
            OWNER_KIND_BUILDING,
        )

    @property
    def is_absentee(self) -> Optional[bool]:
        """True/False quando ha prova; None quando a fonte nao permite saber."""
        if self.owner_occupied is not None:
            return not self.owner_occupied
        if not self.mailing_address:
            return None
        return not mailing_matches_property(self.address, self.mailing_address)

    @property
    def phone_lookup_allowed(self) -> bool:
        """Base minima para autorizar uma chamada paga (politica decide mais)."""
        return bool(self.owner_name) and self.confidence in (
            CONFIDENCE_HIGH,
            CONFIDENCE_MEDIUM,
        )


def _norm_tokens(value: Optional[str]) -> set[str]:
    import re

    return {
        token
        for token in re.findall(r"[A-Z0-9]+", str(value or "").upper())
        if token not in {"USA", "US", "STE", "APT", "UNIT", "FL", "FLOOR"}
    }


def names_equivalent(left: Optional[str], right: Optional[str]) -> bool:
    """True se dois nomes partilham prova suficiente (>=60% dos tokens).

    Usado para nunca colar a proveniencia de um registo novo a um nome antigo
    diferente (ex.: o dataset passou a devolver outro titular).
    """
    a = _norm_tokens(left)
    b = _norm_tokens(right)
    if not a or not b:
        return False
    return len(a & b) / len(a) >= 0.6


def mailing_matches_property(property_address: Optional[str], mailing: Optional[str]) -> bool:
    """True se a mailing address aponta para o proprio imovel.

    Compara numero de porta + tokens de rua. Nao usa igualdade literal porque
    as fontes escrevem "199 SAVIN HILL AV" e "199 SAVIN HILL AVE".
    """
    if not property_address or not mailing:
        return False
    prop_tokens = _norm_tokens(str(property_address).split(",")[0])
    mail_tokens = _norm_tokens(str(mailing).split(",")[0])
    if not prop_tokens or not mail_tokens:
        return False
    prop_num = next((t for t in prop_tokens if t.isdigit()), None)
    mail_num = next((t for t in mail_tokens if t.isdigit()), None)
    if prop_num and mail_num and prop_num != mail_num:
        return False
    street_overlap = (prop_tokens & mail_tokens) - {prop_num, mail_num}
    return bool(street_overlap)


def classify_confidence(
    match_method: str,
    match_score: float = 1.0,
    parcel_key: Optional[str] = None,
) -> str:
    """Confianca derivada da prova, nunca do optimismo.

    `bbl`/`exact_address` = o registo identifica a parcela ou a morada exacta.
    `range`/`number_only` = numero certo, rua por semelhanca.
    `street_substring` (e desconhecido) = fraco: nao autoriza telefone.
    """
    method = (match_method or "").strip().lower()
    if method in _EXACT_METHODS:
        return CONFIDENCE_HIGH
    if method in _MEDIUM_METHODS:
        return CONFIDENCE_MEDIUM
    # Metodo desconhecido com score perfeito ainda pode ser exacto, mas sem
    # parcela nem metodo reconhecido fica em baixo de proposito.
    if match_score >= 0.99 and parcel_key:
        return CONFIDENCE_HIGH
    return CONFIDENCE_LOW


def is_stale(record_year: Optional[int], max_age_years: int) -> bool:
    if not record_year:
        return False
    return record_year <= date.today().year - max(1, int(max_age_years))


def _owner_kind(name: str, source_occupied: Optional[bool]) -> str:
    if lead_rules.is_institutional_name(name):
        return OWNER_KIND_PUBLIC
    kind = lead_rules.get_owner_kind(name)
    if kind == "company":
        upper = name.upper()
        if "TRUST" in upper or " TR " in f" {upper} ":
            return OWNER_KIND_TRUST
        return OWNER_KIND_COMPANY
    return OWNER_KIND_PERSON


def build_record(
    *,
    address: str,
    city: str,
    raw: Mapping[str, Any],
    default_parcel: Optional[str] = None,
    max_age_years: Optional[int] = None,
    kind_override: Optional[str] = None,
) -> Optional[OwnerRecord]:
    """Converte a resposta do `enrichment.py` num `OwnerRecord`."""
    if max_age_years is None:
        from ...config import settings

        max_age_years = int(getattr(settings, "PHONE_STALE_YEARS", 5) or 5)
    owner_name = str(raw.get("owner_name") or "").strip()
    if not owner_name:
        return None

    parcel_key = str(raw.get("parcel_key") or default_parcel or "").strip() or None
    mailing = str(raw.get("mailing_address") or "").strip() or None
    record_year = raw.get("record_year")
    try:
        record_year = int(record_year) if record_year is not None else None
    except (TypeError, ValueError):
        record_year = None

    owner_occupied = raw.get("owner_occupied")
    if owner_occupied is None and mailing:
        owner_occupied = mailing_matches_property(address, mailing)

    match_method = str(raw.get("match_method") or "exact_address")
    match_score = float(raw.get("match_score") or 1.0)

    return OwnerRecord(
        address=address,
        city=city,
        owner_name=owner_name,
        owner_kind=kind_override or _owner_kind(owner_name, owner_occupied),
        parcel_key=parcel_key,
        mailing_address=mailing,
        record_year=record_year,
        owner_occupied=owner_occupied,
        confidence=classify_confidence(match_method, match_score, parcel_key),
        match_method=match_method,
        match_score=match_score,
        source_dataset=raw.get("source_dataset"),
        stale=is_stale(record_year, max_age_years),
        raw=dict(raw),
    )
