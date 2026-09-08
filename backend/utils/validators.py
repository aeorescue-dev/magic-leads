import re
from typing import Optional


def is_valid_phone(phone: str) -> bool:
    """Valida número de telefone US (10 dígitos)"""
    if not phone:
        return False
    digits = re.sub(r"\D", "", phone)
    return len(digits) == 10


def is_valid_zip(zip_code: Optional[str]) -> bool:
    """Valida CEP US (5 dígitos)"""
    if not zip_code:
        return False
    return bool(re.fullmatch(r"\d{5}", zip_code.strip()))


def normalize_address(address: str) -> str:
    """Normaliza endereço para evitar duplicatas"""
    return re.sub(r"\s+", " ", address.strip()).upper()
