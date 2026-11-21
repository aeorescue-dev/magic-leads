# Telnyx 10DLC + SMS após ligação — 2026-11-21

**Modo:** implementação autorizada. `VOICE_FREEZE=1` mantido; nenhuma chamada
ou SMS real foi disparado (o envio fica bloqueado pelo freeze até autorização).

---

## 1. Campanha 10DLC

| Campo | Valor |
|---|---|
| Campanha | `4b3001a1-fff5-c4e5-ee3e-984a6a2e067f` |
| Brand | `BCW3GRB` (`4b2001a1-...`) — VERIFIED |
| Use case | `LOW_VOLUME` (Low Volume Mixed) |
| Sub-use case | `CUSTOMER_CARE` |
| Criada | 2026-11-21T21:14:19Z |
| Custo | $4,50/trimestre (3 meses à cabeça); $1,50/mês depois |
| Saldo antes | $12,99 |
| Estado | **`submissionStatus=PENDING` · `campaignStatus=TCR_PENDING`** |
| failureReasons | null |

Amostras submetidas:
1. "Magic Leads: here is the link you requested during your call:
   https://magicleads.app. Reply STOP to opt out, HELP for help. Msg&data rates
   may apply."
2. "Magic Leads: thanks for calling. The link you requested is
   https://magicleads.app. Reply STOP to unsubscribe, HELP for help."

Opt-in: tecla 1 durante a chamada (descrito no messageFlow). Keywords:
`STOP,STOPALL,UNSUBSCRIBE,CANCEL,END,QUIT` · `HELP,INFO` · `START,YES,UNSTOP`.

**Número SMS `+1***7808`:** está no Messaging Profile
`4001a1d1-8bd1-4cdc-a13b-e05580d2b932`, mas a atribuição à campanha foi
**recusada** com o erro `10036` (campanha ainda pendente). Repetir após
`APPROVED`:
`POST /v2/10dlc/phone_number_campaigns {phoneNumber, campaignId}`.

---

## 2. Implementação no backend

- **`backend/services/telnyx_sms.py`**: envio (`POST /v2/messages`), supressão
  (`sms_suppressions` + `voice_suppressions`), registo em `sms_messages`
  (direção, corpo, provider id, estado, trigger), cache do estado da campanha,
  limite diário (`TELNYX_SMS_MAX_PER_DAY`, 50) e gating:
  `VOICE_FREEZE` → não envia; campanha não aprovada → não envia; número
  suprimido → não envia.
- **Webhook inbound** `POST /api/sms/telnyx/webhook` (Ed25519 + segredo),
  com `STOP/STOPALL/UNSUBSCRIBE/CANCEL/END/QUIT` → supressão e
  `START/YES/UNSTOP` → remoção; `HELP/INFO` registado sem resposta duplicada.
- **Tecla 1**: o gather passou de `valid_digits="2"` para `"12"`; ao receber 1
  o backend envia o SMS pelo número SMS e responde
  "We've texted the link to this number. Goodbye."; se o envio estiver
  bloqueado, responde com o fallback para o website.
- **Guião**: `TEMPLATE_VERSION=2026-11-21.1`; a chamada passa a dizer
  "Press 1 to receive this link by text, or press 2 to opt out." e as regras
  operacionais deixam de proibir SMS (apenas o link pedido).
- **Config**: `TELNYX_SMS_FROM_NUMBER`, `TELNYX_MESSAGING_PROFILE_ID`,
  `TELNYX_SMS_CAMPAIGN_ID`, `TELNYX_SMS_MAX_PER_DAY`.
- **Testes**: `tests/test_telnyx_sms.py` (freeze, campanha pendente, envio,
  STOP/START, tecla 1) — a suíte completa confirma no deploy.

---

## 3. O que falta

1. **Aprovação TCR/operadoras** → estado `ACTIVE`.
2. **Atribuir `+1***7808`** à campanha (após aprovação).
3. **Webhook do Messaging Profile** → `/api/sms/telnyx/webhook?secret=...`.
4. Carregar `VOICE_FREEZE=0` apenas para o teste único em `VOICE_TEST_NUMBERS`.
