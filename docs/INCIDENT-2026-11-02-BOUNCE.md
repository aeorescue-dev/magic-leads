# Incidente 02/11/2026 — bounce duplicado e pausa falsa (Pedro)

## Resumo

- **1 endereço real** devolveu bounce: `info@alliedroofingtexas.com`
  (Allied Roofing of Texas, Dallas, nicho `roofing`, origem `import`).
- Campanha: **"4 roofing projects open in Dallas"** (passo 1), enviada por
  `pedro@magicleads.app` às **12:00:30 UTC**.
- Resposta do servidor remoto (qmail, `mail.hostingplatform.com`):

  ```
  <info@alliedroofingtexas.com>:
  user is over quota
  ```

  A caixa do destinatário estava cheia. O qmail classificou como permanente
  ("permanent error; I've given up"), portanto não houve retry.
- A taxa **4,5%** no relatório = **1 bounce / 22 envios** na janela de 30 dias.
- O endereço foi **suprimido às 12:05:02** (`suppressions.reason='bounce'`) e o
  contacto ficou `unsubscribed=1`. Não volta a receber e-mail.

## Causa raiz da pausa (bug)

1. O inbox sync relê a inbox (`newer_than:2d`) a cada ciclo e **não guardava os
   message-ids já processados**.
2. O mesmo DSN foi processado duas vezes (12:05 e 12:10), inserindo **dois
   `mailbox_bounce_events` para o mesmo e-mail**.
3. O disjuntor interpretou os dois eventos como **2 bounces consecutivos**
   (regra pensada para dois endereços distintos) e pausou
   `pedro@magicleads.app` às 12:10:34 com `paused_reason='consecutive_bounces'`.
4. A taxa agregada duplicou temporariamente (9,09%) e o alerta crítico
   `MAILBOX_PAUSED` foi criado.

## Correções

- `inbox_processed_messages(message_id PRIMARY KEY)`: cada mensagem do Gmail é
  processada **uma vez**; retenção de 30 dias.
- Índice único `(mailbox_id, lower(email), kind)` em
  `mailbox_bounce_events` + `INSERT OR IGNORE`; migração remove duplicados
  antigos mantendo o mais antigo.
- `mailbox_guard` só considera "2 bounces consecutivos" quando os **e-mails são
  distintos**.
- System Health: bounce/complaint só penalizam com **≥20 envios por caixa**
  (a mesma amostra do disjuntor). Abaixo disso, a taxa fica visível como
  `warn` com `amostra X/20`, sem pintar Outreach de vermelho.
- Control Tower: `queue_age` com blocker **quiet hours** ou **limite de caixa**
  passa a `ok` ("retenção esperada"); `send_enabled=0` e cidade desligada
  continuam `warn`.

## Estado após a correção

- 1 bounce real / 22 envios = **4,5%**, endereço suprimido.
- `pedro@magicleads.app` fica pausado até **retoma manual** no Admin (a pausa
  foi um falso positivo; o fix remove a causa).
- Fila de 1 mensagem parada por cap/quiet hours é **esperada** e não gera
  amarelo.

## Prevenção

- Regressões: `tests/test_inbox_sync.py`,
  `tests/test_outbound_auto_ramp.py`, `tests/test_system_health.py`,
  `tests/test_outbound_queue_resilience.py`.
- O bounce real não é um problema de código: é um destinatário com quota cheia.
  A supressão é a resposta correta; a taxa de 30 dias dilui com o volume.
