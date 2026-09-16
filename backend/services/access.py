"""access.py — FONTE ÚNICA DE VERDADE sobre acesso de assinante.

Regra de negócio: um usuário só acessa a plataforma (e só recebe alertas de
novas oportunidades) enquanto tiver acesso VIGENTE — trial ativo OU plano pago
ativo, sempre validado por `plan_until > now` em UTC.

Qualquer decisão de "este usuário pode acessar / deve receber alertas" DEVE
passar por `is_access_active()`. NÃO replique whitelists de `subscription_status`
em outros módulos (foi exatamente esse drift que silenciou o despacho).
"""

from datetime import datetime, timezone

# Tokens canônicos persistidos.
STATUS_ACTIVE = "active"
STATUS_TRIAL = "trial"
STATUS_EXPIRED = "expired"

# Somente estes status concedem acesso (combinados com plan_until futuro).
ACCESS_GRANTING_STATUSES = (STATUS_ACTIVE, STATUS_TRIAL)

# Mapa rígido de todas as variações conhecidas -> token canônico.
# Qualquer token desconhecido/vazio cai em 'expired' (fail-closed).
_STATUS_ALIASES = {
    "active": STATUS_ACTIVE,
    "subscribed": STATUS_ACTIVE,
    "subscription": STATUS_ACTIVE,
    "pro": STATUS_ACTIVE,
    "paid": STATUS_ACTIVE,
    "trial": STATUS_TRIAL,
    "trialing": STATUS_TRIAL,
    "trial_active": STATUS_TRIAL,
    "in_trial": STATUS_TRIAL,
    "expired": STATUS_EXPIRED,
    "inactive": STATUS_EXPIRED,
    "canceled": STATUS_EXPIRED,
    "cancelled": STATUS_EXPIRED,
    "past_due": STATUS_EXPIRED,
    "pending_payment": STATUS_EXPIRED,
    "unpaid": STATUS_EXPIRED,
    "none": STATUS_EXPIRED,
    "": STATUS_EXPIRED,
}


def normalize_status(subscription_status: object) -> str:
    """Normaliza qualquer token de status para o vocabulário canônico.

    Tolerante a caixa e espaços (' ACTIVE ', 'Trialing'). Desconhecido -> 'expired'.
    """
    token = str(subscription_status or "").strip().lower()
    return _STATUS_ALIASES.get(token, STATUS_EXPIRED)


def parse_dt(value: object) -> datetime | None:
    """Parse tolerante de datas do SQLite (SQLite 'YYYY-MM-DD HH:MM:SS',
    ISO com/sem timezone, 'Z'), retornando sempre datetime naive em UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00").replace("T", " "))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def is_access_active(
    subscription_status: object,
    plan_until: object,
    now: datetime | None = None,
) -> bool:
    """True SOMENTE se o status conceder acesso E o prazo (`plan_until`) for futuro.

    - Status normalizado precisa estar em ACCESS_GRANTING_STATUSES.
    - `plan_until` ausente/inválido => False (sem prazo não há acesso).
    - Comparação sempre em UTC naive.
    """
    if normalize_status(subscription_status) not in ACCESS_GRANTING_STATUSES:
        return False
    until = parse_dt(plan_until)
    if until is None:
        return False
    if now is None:
        now = datetime.utcnow()
    return until > now
