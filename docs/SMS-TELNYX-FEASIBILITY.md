# Parecer — SMS na Telnyx sem LLC (10DLC vs Toll-Free)

**Data:** 2026-11-06  
**Natureza:** estudo e simulação. **Zero código de runtime, zero deploy, zero gasto.**  
**Conta:** Telnyx "Magic Leads", estatuto **VERIFIED** no portal.

---

## 1. Veredicto em três linhas

1. **Não é possível disparar SMS de produção hoje** só porque a conta está VERIFIED. O estatuto de conta não substitui a verificação do número (Toll-Free Verification) nem o registo de marca/campanha (10DLC).
2. **É possível operar sem LLC**, mas apenas por duas vias: Toll-Free Verification com `businessRegistrationType=SSN` + `entityType=SOLE_PROPRIETOR` (1–2 semanas), ou 10DLC Sole Proprietor com OTP e últimos 4 dígitos do SSN (dias).
3. **Recomendação:** usar SMS apenas como **fallback transacional 1:1** para contactos que deram opt-in no chat, com **um** número 10DLC Sole Prop, cap diário baixo e STOP/HELP. **Não** usar SMS para broadcast em massa nem para a base B2B raspada. Push e voz continuam primários.

---

## 2. O que existe hoje no backend

| Componente | Estado |
|---|---|
| `backend/config.py` | Só chaves de **voz** Telnyx (`TELNYX_API_KEY`, `TELNYX_CONNECTION_ID`, `TELNYX_FROM_NUMBER`, `TELNYX_WEBHOOK_SECRET`, `TELNYX_PUBLIC_KEY`, custo/min). **Não existe** `TELNYX_MESSAGING_PROFILE_ID` nem número SMS. |
| `backend/services/telnyx_voice.py` | `API_BASE=https://api.telnyx.com/v2`, `configured()`, `webhook_authorized()` (Ed25519 + segredo), `handle_webhook()` para eventos de **call control**. Não trata `message.*`. |
| `backend/main.py:3283` | `POST /api/voice/telnyx/webhook` valida assinatura e entrega a `telnyx_voice.handle_webhook`. É o único webhook Telnyx. |
| `backend/services/b2b_voice.py` | `voice_suppressions(value, channel, reason)` já existe e pode servir de supressão SMS com `channel='sms'`. `dnc_checks` **não** é DNC real. |
| `backend/services/push_service.py` | Web Push VAPID funcional; `frontend/public/sw.js`. Não há SMS. |
| `landing_contacts` | **Não existe** — o chat/inbox é spec-only (`docs/CHAT-INBOX-ROADMAP.md`). |
| Tabelas SMS | **Não existem** `sms_messages`, `sms_campaigns`, `landing_push_*`. |

Conclusão: qualquer SMS é **implementação nova**, não uma flag num serviço existente.

---

## 3. Viabilidade sem LLC

### 3.1 O que "VERIFIED" significa — e não significa

O estatuto VERIFIED (framework TPVE) desbloqueia compra de números, perfis de mensagens e limites de conta. **Não é** verificação Toll-Free e **não é** brand/campaign 10DLC. São três coisas distintas:

```text
Conta VERIFIED  ≠  Toll-Free Verification (TFV)  ≠  10DLC Brand/Campaign (TCR)
```

Também é preciso distinguir o nível de conta legado (Level 1 = 50 SMS/dia; Level 2 sobe limites) do TPVE (Trial → Paid → Verified → Enterprise). O limite real de envio é o **mínimo** entre nível de conta, verificação do número e throughput da campanha.

### 3.2 Via A — Toll-Free (800/8xx)

**Aceita sole proprietor sem EIN?** Sim, desde 17/02/2026 os três campos BRN são obrigatórios e a documentação aceita explicitamente:

- `businessRegistrationType = "SSN"` para sole proprietors dos EUA sem EIN;
- `businessRegistrationNumber` = SSN;
- `businessRegistrationCountry = "US"`;
- `entityType = "SOLE_PROPRIETOR"` (opcional, mas recomendado).

**Passos exatos (sem LLC):**

1. Comprar um número toll-free no portal (≈ **$1/mês**).
2. Criar/associar um **Messaging Profile** ao número.
3. Submeter TFV em `POST /v2/messaging_tollfree/verification/requests` com:
   - `businessName` = nome legal individual ou DBA **consistente** com o SSN;
   - morada, contacto, e-mail e telefone;
   - `messageVolume`, `useCase` (ex.: `Account Notifications` ou `Mixed`);
   - `useCaseSummary` e `productionMessageContent` reais;
   - `optInWorkflow` + `optInWorkflowImageURLs` (screenshots da landing/consentimento);
   - `privacyPolicyURL`, `termsAndConditionURL`;
   - `optInConfirmationResponse`, `helpMessageResponse`, `optOutMessage` com STOP;
   - os três campos BRN acima.
4. Aguardar **1–2 semanas** (fila das operadoras).
5. Só depois enviar com throughput pleno (até 20 MPS).

**Antes de aprovado:** ~0,25 MPS, filtragem pesada das operadoras, entrega pouco fiável. **Não serve para produção.** Não há "aprovação instantânea" por a conta estar VERIFIED.

**Custo:** TFV sem fee próprio; número ≈ $1/mês; SMS $0,0055/parte + carrier fee.

**Riscos:** o nome legal tem de bater com o SSN; amostras de mensagem e opt-in têm de corresponder ao uso real; conteúdo de marketing é escrutinado e pode ser rejeitado. SSN completo é dado sensível — só o owner submete, nunca em repo/BD/log.

### 3.3 Via B — 10DLC Sole Proprietor

**Aceita sem EIN?** Sim. A Telnyx abriu 10DLC a sole proprietors em 04/02/2026.

**Passos exatos (sem LLC):**

1. Comprar um número local US 10DLC (≈ $1/mês).
2. `POST /v2/10dlc/brand` com `entityType=SOLE_PROPRIETOR`, nome, morada, data de nascimento, e-mail, telefone e **mobile US/CA**.
3. `POST /v2/10dlc/brand/{id}/smsOtp` → receber PIN por SMS (janela de 24 h).
4. `PUT /v2/10dlc/brand/{id}/smsOtp` com o PIN → brand `VERIFIED`.
5. `POST /v2/10dlc/campaignBuilder` com `usecase=SOLE_PROPRIETOR`, descrição, message flow, HELP, STOP e duas amostras reais.
6. Atribuir **um** número: `POST /v2/10dlc/phone_number_campaigns`.

**Limites duros:** 1 campanha por brand, 1 número por campanha, throughput baixo (varia por operadora), máximo 3 brands SP por número mobile. Campanhas SP costumam ser auto-aprovadas.

**Custo:** brand **$4,50** (one-time) + vetting **$15** (por submissão) + **$2/mês** de manutenção; SMS $0,004/parte + carrier fee ($0,0035 AT&T; $0,005 Verizon a partir de 01/10/2026).

**Risco:** um único número e throughput baixo **não suportam** broadcast multi-cidade. Serve para fallback 1:1 e notificações transacionais.

### 3.4 Alternativa que evita expor o SSN: EIN sem LLC

Um sole proprietor pode pedir um **EIN gratuito** ao IRS (Form SS-4) sem formar LLC. Com EIN:

- evita usar o SSN no registo;
- abre a via de **standard brand** 10DLC (melhor throughput, vários números, campanha de marketing);
- custa $4,50 + $15 + $10/mês (standard) em vez de $2/mês (SP), mas remove o teto de 1 número.

**Recomendação:** se o volume justificar, pedir EIN é o melhor caminho a 2–4 semanas. Para o piloto, 10DLC SP chega.

### 3.5 Pré-requisitos que podem bloquear tudo

Ambas as vias sem LLC exigem:

- **SSN** (completo na TFV; últimos 4 no 10DLC);
- **morada nos EUA**;
- **mobile US/CA** para o OTP do 10DLC;
- nome/identidade coerentes entre conta, brand e amostras.

Se o owner não tiver SSN ou morada US, **não há via sem EIN/LLC**. Nesse caso, a resposta a (a) passa a ser "não".

---

## 4. Simulação de integração no backend

### 4.1 Fluxo de envio

```text
Admin / fallback engine
        │
        ▼
sms_service.send_sms(to, text, kind, idempotency_key)
        │  valida E.164
        │  verifica supressão (voice_suppressions channel='sms')
        │  verifica quiet hours do destinatário
        │  calcula partes/encoding e reserva orçamento
        ▼
POST https://api.telnyx.com/v2/messages
  Authorization: Bearer TELNYX_API_KEY
  Idempotency-Key: <uuid>
  {
    "from": "+1XXXXXXXXXX",
    "messaging_profile_id": "...",
    "to": "+1YYYYYYYYYY",
    "text": "...",
    "type": "SMS",
    "webhook_url": "https://.../api/messaging/telnyx/webhook"
  }
        │
        ▼
sms_messages: status='queued' → 'sent' (data.id)
        │
        ▼
message.sent / message.finalized (webhook)
        │
        ▼
status final + cost.amount + parts + errors
```

### 4.2 Webhook e DLR

- Endpoint novo: `POST /api/messaging/telnyx/webhook`.
- Reutiliza `telnyx_voice.webhook_authorized()` para validar `telnyx-signature-ed25519` + `telnyx-timestamp` com `TELNYX_PUBLIC_KEY`. Responde **200 rápido** e processa fora do request.
- Eventos:
  - `message.sent` → `status='sent'`;
  - `message.finalized` → `to[0].status` ∈ `delivered`, `delivery_failed`, `delivery_unconfirmed`; guardar `completed_at`, `cost.amount`, `parts`, `errors`;
  - `message.received` → inbound; tratar STOP/HELP/START.
- Idempotência por `payload.id` (unique) para tolerar retries da Telnyx.
- Se o webhook falhar repetidamente, a Telnyx desativa-o; monitorizar e ter failover URL.

### 4.3 Opt-out

- `STOP`, `STOPALL`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT` → inserir em `voice_suppressions` com `channel='sms'` e, por defesa, `channel='phone'`.
- `HELP`/`INFO` → resposta automática com identificação, preço e STOP (custo de 1 SMS).
- `START`/`UNSTOP` → remover **apenas** a supressão SMS, nunca a de voz.
- A Telnyx tem advanced opt-in/out, mas a **nossa** lista é a fonte de verdade e tem de ser consultada antes de cada envio.
- Opt-out no chat/push não é automaticamente opt-out SMS; são consentimentos separados.

### 4.4 Tabelas novas (proposta, não criada)

```sql
sms_messages (
  id INTEGER PRIMARY KEY,
  provider_message_id TEXT UNIQUE,
  direction TEXT NOT NULL,              -- outbound | inbound
  from_e164 TEXT NOT NULL,
  to_e164 TEXT NOT NULL,
  body TEXT NOT NULL,
  kind TEXT NOT NULL,                   -- transactional | marketing | otp | chat_fallback
  language TEXT,
  status TEXT NOT NULL,                 -- queued | sent | delivered | failed | unconfirmed
  parts INTEGER,
  encoding TEXT,                        -- GSM-7 | UCS-2
  cost_cents INTEGER,
  error TEXT,
  conversation_id TEXT,
  campaign_id INTEGER,
  idempotency_key TEXT UNIQUE,
  sent_at TEXT,
  finalized_at TEXT,
  created_at TEXT NOT NULL
);

sms_campaigns (
  id INTEGER PRIMARY KEY,
  name TEXT,
  segment_json TEXT,
  source_lang TEXT,
  status TEXT,
  budget_usd REAL,
  created_by INTEGER,
  created_at TEXT,
  sent_at TEXT
);

sms_optouts (
  phone_e164 TEXT PRIMARY KEY,
  keyword TEXT,
  source TEXT,
  created_at TEXT
);
```

`voice_suppressions` continua a ser a lista central; `sms_optouts` é só auditoria do keyword.

### 4.5 Configuração nova (proposta)

```text
TELNYX_MESSAGING_PROFILE_ID=
TELNYX_SMS_FROM_NUMBER=
SMS_ENABLED=0
SMS_MARKETING_ENABLED=0
SMS_FALLBACK_ENABLED=0
SMS_DAILY_BUDGET_USD=2.00
SMS_MAX_PER_DAY=100
SMS_QUIET_START=21:00
SMS_QUIET_END=08:00
SMS_ESTIMATED_COST_CENTS=1
```

Todos os defaults fechados. Ativação só admin, depois de TFV/10DLC aprovados.

### 4.6 Onde liga ao que já existe

| Ponto | Ligação |
|---|---|
| Chat / iOS non-push | `landing_contacts.push_eligible=false` + `fallback_channel='sms'` → broadcast seleciona e envia. Depende do chat, que ainda não existe. |
| Broadcast push | Se o locale falhar tradução, **não** cair para SMS em silêncio; bloquear e registar. SMS é canal separado, com consentimento próprio. |
| Voz | Após `no_answer`/`voicemail`, um SMS de seguimento é o caso de maior ROI — **mas só para números com opt-in**, nunca para a base raspada. |
| Custos | O DLR `message.finalized` traz o custo real; reconciliar com a reserva estimada. |
| Supressão | Reutilizar `voice_suppressions`; `channel='sms'`. |
| Segurança | Mesma assinatura Ed25519; rate limit por número/IP; sem PII no log. |

### 4.7 Sequência iOS → SMS (simulação)

```text
1. Visitante iPhone insere telefone e aceita opt-in.
2. iOS não instala PWA / nega push.
3. landing_contacts.push_eligible = false
   landing_contacts.fallback_channel = 'sms'
   landing_contacts.fallback_consent = true
4. Admin cria broadcast "Nova oportunidade em <cidade>".
5. Segmento: push_eligible=false, fallback_channel='sms', opt-in ativo.
6. Para cada contacto: traduzir para o locale → contar partes → verificar budget.
7. POST /v2/messages (1 número 10DLC SP, pacing).
8. message.finalized → delivered/failed; STOP → supressão imediata.
9. Falha definitiva → registar; não repetir no mesmo dia.
```

---

## 5. Custos

### 5.1 Preços unitários (referência Telnyx, 2026)

| Item | Valor |
|---|---|
| SMS outbound 10DLC | $0,004/parte |
| Carrier fee AT&T | $0,0035/parte |
| Carrier fee Verizon | $0,005/parte (a partir de 01/10/2026) |
| SMS outbound toll-free | $0,0055/parte + carrier fee |
| SMS inbound | ~$0,004/parte |
| Número | ~$1/mês |
| 10DLC SP: brand | $4,50 one-time |
| 10DLC SP: vetting | $15,00 por submissão |
| 10DLC SP: manutenção | $2,00/mês |
| 10DLC standard: manutenção | $10,00/mês |

### 5.2 Custo por mensagem

- **10DLC, 1 parte:** $0,004 + $0,0035–$0,005 ≈ **$0,0075–$0,009**.
- **Toll-free, 1 parte:** $0,0055 + carrier ≈ **$0,009–$0,010**.
- **2 partes (UCS-2):** duplica.

### 5.3 Cenários

| Cenário | Partes | Custo aprox. |
|---|---|---|
| 500 contactos, EN, 1 parte | 500 | **$3,75–$4,50** |
| 500 contactos, PT/VI/ZH, 2 partes | 1.000 | **$7,50–$9,00** |
| 5.000 contactos, 2 partes | 10.000 | **$75–$90** |
| 100 SMS/dia, 1 parte, 30 d | 3.000 | **$22,50–$27 + $2/mês** |

**Atenção à codificação:** GSM-7 permite 160 caracteres; UCS-2 (emoji, acentos não-GSM, chinês, vietnamita, árabe) corta para **70 caracteres por parte**. Uma frase traduzida de 120 caracteres pode custar 2 partes. O serviço deve calcular e mostrar a estimativa **antes** do envio.

### 5.4 Comparação com os canais existentes

| Canal | Custo por contacto | Observação |
|---|---|---|
| Web Push | **$0** | Só com PWA/permissão; iOS limitado |
| Voz (30 s) | ~$0,01 | 2 ¢/min configurado; resposta humana incerta |
| SMS (1 parte) | ~$0,008 | Assíncrono, mas exige registo e consentimento |

SMS não é mais barato que voz por contacto; é mais **assíncrono e silencioso**. O valor está na entrega, não no preço.

---

## 6. Recomendação (a / b / c)

### a) É possível disparar SMS imediatamente via Toll-Free/Sole Prop na conta atual?

**Não.** A conta VERIFIED resolve a identidade da conta; não resolve o número. É preciso:

- comprar número;
- submeter TFV (1–2 semanas) **ou** registar 10DLC SP (dias);
- só depois enviar em produção.

Sem verificação, um toll-free fica em ~0,25 MPS com filtragem pesada — inaceitável para fallback. **Nenhum SMS de produção hoje.**

### b) Passos de compliance sem LLC

**Caminho recomendado — 10DLC Sole Proprietor (piloto):**

1. Confirmar SSN, morada US e mobile US/CA.
2. Comprar 1 número local.
3. Criar brand `SOLE_PROPRIETOR` (nome/morada/DOB/e-mail/telefone/mobile).
4. OTP por SMS (24 h) → brand VERIFIED.
5. Criar campanha `SOLE_PROPRIETOR` com descrição, message flow, HELP, STOP e 2 amostras reais.
6. Atribuir o número.
7. Ativar `SMS_ENABLED=1` só para admin/teste; depois fallback.
8. Registar opt-in (texto, timestamp, IP hash, URL) e manter supressão própria.
9. Incluir STOP em todas as mensagens; responder HELP; respeitar quiet hours 21:00–08:00 local.
10. Monitorizar DLR, taxa de falha e custo; parar se falha >5% ou custo > cap.

**Caminho alternativo — Toll-Free:** igual, mas com TFV e 1–2 semanas. Melhor se precisar de vários números/volume; pior para começar já.

**Evolução:** pedir EIN gratuito ao IRS (sem LLC) e migrar para standard brand quando o volume passar de ~1 número/1.000 SMS/dia.

**Nunca:** usar a base B2B raspada para SMS. Não há consentimento; é risco TCPA direto.

### c) Seguir com SMS no fallback iOS ou manter voz/push?

**Seguir, mas em modo estreito:**

- **Push primeiro** ($0) e **voz** como segundo canal.
- **SMS só para contactos do chat com opt-in explícito**, conteúdo transacional ("nova oportunidade", "responda no chat"), 1 número 10DLC SP, cap **$2/dia** e **100 SMS/dia**.
- **Não** usar SMS para broadcast de marketing em massa enquanto não houver EIN/LLC e standard brand. O limite de 1 campanha/1 número e o throughput baixo tornam isso impossível, e o risco TCPA é desproporcionado.
- O fallback iOS resolve **entrega de alerta**, não substitui o inbox. Se o cliente responder por SMS, é preciso tratar inbound (STOP/HELP e encaminhar para o chat) — senão criamos um canal cego.

**Decisão sugerida:** aprovar 10DLC SP agora, mas **não ativar** até o chat/inbox existir e o opt-in estar a gravar `consent_at`/`ip_hash`. Até lá, push + voz.

---

## 7. Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Usar SSN no registo | Exposição de PII | Só o owner submete; nunca em repo/BD/log; preferir EIN quando possível |
| Base raspada sem consentimento | TCPA / class action | SMS só para opt-in do chat; suprimir o resto |
| Marketing sem opt-in claro | Bloqueio de campanha e multas | Consentimento separado, STOP em cada mensagem, quiet hours |
| 10DLC SP: 1 número/1 campanha | Não escala | Piloto; migrar para EIN/standard brand |
| TFV rejeitada | 1–2 semanas perdidas | Amostras reais, opt-in workflow coerente, privacidade/termos públicos |
| UCS-2 inesperado | Custo 2× | Calcular partes antes; limitar a 160/70 caracteres |
| Webhook desativado | DLR perdido | 200 rápido, idempotência, monitorização, failover URL |
| SMS como canal cego | Cliente responde e ninguém vê | Inbound no inbox ou auto-resposta clara |
| Conta VERIFIED mal interpretada | Expectativa errada | Tratar conta, TFV e 10DLC como três gates separados |

---

## 8. Plano de rollout (se aprovado)

| Fase | Ação | Gate |
|---|---|---|
| D0 | Confirmar SSN/morada/mobile; decidir 10DLC SP vs TFV | pré-requisitos |
| D1 | Comprar número + messaging profile | número ativo |
| D1–D3 | Brand SP + OTP + campanha + assign | brand/campaign VERIFIED |
| D3–D5 | Implementar `telnyx_sms.py`, tabelas, webhook, opt-out | testes + dry-run |
| D5 | Ativar admin-only, enviar para números internos | DLR `delivered` |
| D7 | Ativar fallback para 10 contactos com opt-in | falha <5%, zero STOP ignorado |
| D14 | Alargar ao segmento non-push iOS | custo dentro do cap |
| D30 | Avaliar EIN/standard brand | volume e falha |

**Nada disto entra no deploy de hoje.**

---

## 9. Decisões que precisam de aprovação

1. Confirmar que existe SSN + morada US + mobile US/CA (sem isto, não há via sem LLC).
2. 10DLC SP (rápido, 1 número) vs Toll-Free (1–2 semanas, mais volume).
3. Cap de SMS: $2/dia e 100/dia no piloto? Ou outro?
4. Conteúdo: só transacional ou também marketing? (Marketing exige consentimento separado.)
5. Quem submete o SSN/EIN e quem é o owner legal na Telnyx.
6. Tratar inbound SMS no inbox do chat ou auto-resposta apenas.

---

## 10. Fontes

- Telnyx — Toll-Free Verification (BRN/SSN, 1–2 semanas, throughput): https://developers.telnyx.com/docs/messaging/toll-free-verification
- Telnyx — Toll-Free troubleshooting (unverified ~0,25 MPS): https://developers.telnyx.com/docs/messaging/toll-free-verification/troubleshooting
- Telnyx — 10DLC Sole Proprietor (1 campanha/1 número, OTP, fees): https://developers.telnyx.com/docs/messaging/10dlc/sole-proprietor
- Telnyx — release notes 10DLC SP: https://telnyx.com/release-notes/10dlc-sole-proprietor-support
- Telnyx — Messaging API `POST /v2/messages`: https://developers.telnyx.com/api-reference/messages/send-a-message
- Telnyx — Webhooks `message.sent` / `message.finalized` / DLR: https://developers.telnyx.com/docs/messaging/messages/receiving-webhooks
- Telnyx — Account verification (Level 1/2, TPVE): https://support.telnyx.com/en/articles/1130595-account-verification
- Telnyx — SMS pricing: https://telnyx.com/pricing/messaging
- Telnyx — 10DLC fees: https://support.telnyx.com/en/articles/5634625-10dlc-fees-and-charges
