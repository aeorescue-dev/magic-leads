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
    - candidates: leads despacháveis após o filtro de qualidade.
    - city_filtered: a audiência ficou a 0 apenas por causa do cities_filter.
    """

    created: int = 0
    audience: int = 0
    candidates: int = 0
    city_filtered: bool = False


async def guard_silent_fanout(
    inserted: int,
    notified: int,
    audience: int,
    candidates: int,
    city_filtered: bool = False,
    context: dict | None = None,
) -> bool:
    """Dead Man's Switch do despacho de alertas.

    Dispara log CRITICAL + alerta de auditoria (tabela system_alerts) SOMENTE
    quando todas as condições se verificam:

      * `inserted > 0` — houve leads inseridos no run;
      * `candidates > 0` — havia leads despacháveis (o filtro de qualidade não
        esvaziou o lote: leads institucionais ou sem categoria dão candidates=0
        e NÃO são bloqueio de fluxo);
      * `audience == 0` — nenhum destinatário elegível;
      * `not city_filtered` — a audiência não foi zerada apenas pelo
        `cities_filter` dos utilizadores (ruído de configuração, não bloqueio).

    Um `notified == 0` com `audience > 0` é SAUDÁVEL: significa que os elegíveis
    já bateram no cap diário (ou os leads já haviam sido notificados).
    """
    if inserted > 0 and candidates > 0 and audience == 0 and not city_filtered:
        msg = (
            "BLOQUEIO DE FLUXO DE NOTIFICAÇÕES: "
            f"{inserted} lead(s) inserido(s) mas nenhum destinatário elegível "
            f"encontrado ({notified} notificação(ões) criada(s); "
            f"{candidates} lead(s) despachável(is)). "
            "Possível divergência de status de acesso ou de interesses."
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
    return FanoutReport(
        created=report.created,
        audience=report.audience,
        candidates=report.candidates,
        city_filtered=report.city_filtered,
    )
