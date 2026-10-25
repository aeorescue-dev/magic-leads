"""Helpers de tempo UTC (fonte unica).

Por que existe: `datetime.utcnow()` esta' deprecado no Python 3.12+ e devolve
um datetime NAIVE. Todo o dominio persistido em SQLite (TEXT 'YYYY-MM-DD
HH:MM:SS') e o codigo legado comparam timestamps naive em UTC — trocar por
`datetime.now(timezone.utc)` (aware) diretamente rebentaria essas comparacoes
com `TypeError: can't compare offset-naive and offset-aware datetimes`.

`utcnow()` mantem o contrato antigo (naive, UTC) sem o aviso de deprecacao.
Use `utcnow_aware()` apenas onde o calculo e' feito inteiramente com aware
datetimes (ex.: motor de outbound).
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Agora em UTC, NAIVE (compativel com SQLite e com o codigo existente)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """Agora em UTC, com timezone (para aritmetica aware)."""
    return datetime.now(timezone.utc)


def to_utc_naive(value: datetime) -> datetime:
    """Normaliza um datetime (aware ou naive) para UTC naive.

    Um datetime naive e' assumido como UTC (contrato do projeto).
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
