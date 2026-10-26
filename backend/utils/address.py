"""
Helper de validacao e normalizacao de enderecos para prevencao de falsos positivos
em cruzamentos e esquinas (F3 e F7).
"""
from __future__ import annotations
import re

_HAS_HOUSE_NUMBER = re.compile(r"^\s*\d")

def is_intersection(address: str | None) -> bool:
    """Retorna True se o endereço for um cruzamento/esquina sem número de imóvel.
    
    Evita falsos positivos em nomes de empresas ou edifícios que contenham '&'
    (ex: 'AT&T Building' ou 'P&R Construction') exigindo que NÃO haja número predial
    no início e que contenha '&' ou ' AND ', ou que comece com 'INTERSECTION'.
    """
    raw = (address or "").strip().upper()
    if not raw:
        return False
    if raw.startswith("INTERSECTION"):
        return True
    if not _HAS_HOUSE_NUMBER.match(raw) and (" & " in raw or " AND " in raw):
        return True
    return False
