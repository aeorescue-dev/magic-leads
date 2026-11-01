"""Limpeza de moradas do portal de Boston (CKAN).

O campo `location` do 311 de Boston já vem com bairro/cidade, estado e ZIP:
`"2 Columbus Ave  Boston  MA  02116"`. O pipeline antigo acrescentava
`, Boston, MA` e guardava a morada duplicada; além de feia, isso quebrava o
casamento com o dataset de proprietários.

Esta função é pura e partilhada pelo ingest e pelo backfill.
"""
from __future__ import annotations

import re
from typing import Optional

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_STATE_ZIP_RE = re.compile(r"\s+MA\s+\d{5}(?:-\d{4})?\s*$", re.IGNORECASE)
_TRAILING_ZIP_RE = re.compile(r"\s+\d{5}(?:-\d{4})?\s*$")
_HOUSE_RE = re.compile(r"^(\d+[A-Za-z]?(?:\s*-\s*\d+[A-Za-z]?)?)\s+(.*)$")
# Sufixos de via usados pelo parcel dataset de Boston (full_address).
_STREET_SUFFIXES = {
    "ST", "STREET", "AVE", "AV", "AVENUE", "PL", "PLACE", "RD", "ROAD",
    "BLVD", "BOULEVARD", "LN", "LANE", "DR", "DRIVE", "TER", "TERRACE",
    "PKWY", "PARKWAY", "CT", "COURT", "SQ", "SQUARE", "HWY", "HIGHWAY",
    "CIR", "CIRCLE", "WAY",
}
_BOSTON_PLACES = (
    "BOSTON", "DORCHESTER", "ROXBURY", "JAMAICA PLAIN", "HYDE PARK",
    "EAST BOSTON", "WEST ROXBURY", "ROSLINDALE", "MATTAPAN", "BRIGHTON",
    "ALLSTON", "CHARLESTOWN", "SOUTH BOSTON", "BEACON HILL", "BACK BAY",
    "NORTH END", "WEST END", "FENWAY", "MISSION HILL", "DORCHESTER CENTER",
)
_PLACE_RE = re.compile(
    r"\s+(?:" + "|".join(re.escape(p) for p in _BOSTON_PLACES) + r")\s*$",
    re.IGNORECASE,
)


def clean_boston_location(
    location: Optional[str], fallback_zip: Optional[str] = None
) -> tuple[str, Optional[str]]:
    """Devolve (rua, zip5) a partir do `location` do 311.

    Formatos reais:
      * ``"2 Columbus Ave  Boston  MA  02116"`` (duplo espaço)
      * ``"970 American Legion Hwy  Hyde Park  MA  02136"``
      * ``"2 Columbus Ave, Boston, MA 02116"``
    """
    raw = str(location or "").strip()
    zip_from_fallback = _ZIP_RE.search(str(fallback_zip or ""))
    fallback = zip_from_fallback.group(1) if zip_from_fallback else None
    if not raw:
        return "", fallback

    # 1) Separadores por duplo espaço são os mais fiáveis neste portal.
    segments = [s.strip() for s in re.split(r"\s{2,}", raw) if s.strip()]
    if len(segments) >= 3:
        last = segments[-1]
        state = segments[-2].upper()
        m = _ZIP_RE.search(last)
        if state == "MA" and m:
            return segments[0].strip(" ,"), m.group(1)

    # 2) Formato com vírgulas.
    if "," in raw:
        first = raw.split(",")[0].strip()
        zip_match = _ZIP_RE.search(raw)
        return first.strip(" ,"), (zip_match.group(1) if zip_match else fallback)

    # 3) Formato linear: remover "MA 02116" e, se sobrar, o ZIP.
    street = _STATE_ZIP_RE.sub("", raw).strip()
    street = _TRAILING_ZIP_RE.sub("", street).strip()
    street = _PLACE_RE.sub("", street).strip()
    zip_match = _ZIP_RE.search(raw)
    return street.strip(" ,"), (zip_match.group(1) if zip_match else fallback)


def parcel_match_key(full_address: Optional[str]) -> Optional[tuple[str, str]]:
    """(número, rua) de uma morada do parcel dataset, ignorando a unidade.

    O portal guarda ``"526   COLUMBUS AV 2"`` (unidade 2) e
    ``"107 -109 SAVIN HILL AV 1"``. O parser antigo usava toda a cauda como
    rua, por isso nunca casava com o 311 (``"526 Columbus Ave"``): 1.500+
    imóveis ficavam sem proprietário mesmo com a morada já limpa.

    A rua devolvida vem em maiúsculas e sem normalização de sufixos; o
    chamador aplica ``normalize_street`` para alinhar ``AV``/``AVE``.
    """
    text = " ".join(str(full_address or "").upper().split())
    if not text:
        return None
    match = _HOUSE_RE.match(text)
    if not match:
        return None
    num = re.sub(r"\s+", "", match.group(1))
    tokens = match.group(2).split()
    # Intervalo escrito com espaço ("604 608 COLUMBUS AV"): o primeiro
    # número é a chave; o segundo é a outra extremidade do intervalo.
    if len(tokens) > 1 and tokens[0].isdigit():
        tokens = tokens[1:]
    cut = None
    for idx, tok in enumerate(tokens):
        if tok.strip(".,") in _STREET_SUFFIXES:
            cut = idx
            break
    street = " ".join(tokens[: cut + 1] if cut is not None else tokens)
    street = street.strip(" .,")
    if not street:
        return None
    return num, street
