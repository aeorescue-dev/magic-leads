"""notifier.py — fachada do despacho de alertas.

O planeamento (teto diário, distribuição fair-equal por especialidade, rotação
persistida e orçamento combinado in-app + push) vive em `alert_planner.py`.

Este módulo mantém apenas:
  * `FanoutReport` — contrato devolvido pelo despacho;
  * `fanout_new_lead_batch` — entrypoint de compatibilidade que delega no planner;
  * `guard_silent_fanout` — Dead Man's Switch (bloqueio de fluxo auditável).

Dead Man's Switch: quando há leads inseridos mas NENHUM destinatário elegível,
há bloqueio de fluxo e escala-se (log CRITICAL + auditoria). Cap diário atingido
NÃO é bloqueio (há elegíveis).
"""

from dataclasses import dataclass

from ..utils.logger import logger
from .db import db_service


@dataclass
class FanoutReport:
    """Resultado de um fan-out.

    - created: notificações in-app efetivamente criadas.
    - audience: nº de usuários ELEGÍVEIS encontrados (independente de cap/dedup).
    """

    created: int = 0
    audience: int = 0


async def guard_silent_fanout(
    inserted: int, notified: int, audience: int, context: dict
) -> bool:
    """Dead Man's Switch do despacho de alertas.

    Dispara log CRITICAL + alerta de auditoria (tabela system_alerts) SOMENTE
    quando leads foram inseridos (`inserted > 0`) mas o fan-out não encontrou
    NENHUM destinatário elegível (`audience == 0`) — cenário do bug de whitelist
    de status que silenciava o despacho.

    Um `notified == 0` com `audience > 0` é considerado SAUDÁVEL: significa que
    os elegíveis já bateram no cap diário (ou os leads já haviam sido notificados).
    """
    if inserted > 0 and audience == 0:
        msg = (
            "BLOQUEIO DE FLUXO DE NOTIFICAÇÕES: "
            f"{inserted} lead(s) inserido(s) mas nenhum destinatário elegível "
            f"encontrado ({notified} notificação(ões) criada(s)). "
            "Possível divergência de status de acesso, interesses ou cities_filter."
        )
        logger.critical(msg)
        try:
            await db_service.record_system_alert(
                level="critical",
                code="NOTIFIER_SILENT_FAILURE",
                message=msg,
                context=context,
            )
        except Exception as e:  # nunca deixar o watchdog derrubar o run
            logger.error(f"Falha ao registrar alerta crítico de fanout: {e}")
        return False
    return True


async def fanout_new_lead_batch(category: str, leads: list) -> FanoutReport:
    """Entrypoint de compatibilidade: delega no planeador central."""
    from .alert_planner import plan_and_dispatch

    report = await plan_and_dispatch(leads)
    return FanoutReport(created=report.created, audience=report.audience)
