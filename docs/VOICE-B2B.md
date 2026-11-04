# Voice B2B — Fase 1/2A (multi-cidade: MA, NY, TX, IL)

Rota: **`/admin/voice`** (link “Voice B2B” no header do `/admin`).
Base própria: **`voice.db`** (`VOICE_DB_PATH`, default `/data/voice.db`).
Sem PII de homeowners; apenas pessoas jurídicas/empreiteiros.

## Âmbito

- Importação de licenças/permits de **Massachusetts, New York, Texas e Illinois** (HIC, trades, permits).
- Gate **`can_call()` fail-closed** antes de liberar o contacto.
- Fila ordenada por score ICP e volume de obras.
- Click-to-call (`tel:`) + registo de tentativa e disposição.
- Supressão automática em “sem interesse”, “número errado” e “não contactar”.

## Schema (`voice.db`)

| Tabela | Função |
|---|---|
| `prospect_sources` | fonte, URL, data de captura, checksum, linhas |
| `prospect_companies` | empresa, responsável, telefone E.164, trade, licença, obras, score |
| `dnc_checks` | check DNC por telefone (federal/estadual/manual), validade 31 dias |
| `voice_suppressions` | opt-out interno por telefone |
| `call_attempts` | tentativa, agente, outcome, notas, callback |
| `voice_meta` | versão do módulo |

Dedupe por **telefone E.164**. Reimportar atualiza a empresa e preserva
`do_not_call`.

## Gate `can_call()`

Bloqueia se qualquer condição falhar:

1. `entity_type != business`
2. telefone inválido (não `+1` com 10 dígitos)
3. estado diferente de `MA`, `NY`, `TX` ou `IL` (piloto multi-cidade)
4. estado do contacto `do_not_call`, `invalid` ou `meeting`
5. supressão interna (`voice_suppressions`)
6. sem check DNC → `dnc_not_checked`
7. check DNC com mais de **31 dias** → `dnc_stale`
8. número listado no DNC → `dnc_listed`
9. **3 tentativas** nos últimos 7 dias → `attempt_cap`
10. fora de **09:00–20:00 locais** (`America/New_York` para MA/NY;
    `America/Chicago` para TX/IL) → `outside_hours`

A janela é configurável por `VOICE_CALL_START_HOUR=9` e
`VOICE_CALL_END_HOUR=20` (fim exclusivo). O fuso vem do **estado** da empresa
(MA/NY → ET; TX/IL → CT). Não usamos ZIP: os 4 estados do piloto têm um único
fuso, por isso o mapeamento por estado é exato e não há ambiguidade. Se o
piloto entrar num estado com vários fusos (ex.: FL, TX com El Paso), aí sim
será preciso um mapa por ZIP/cidade.

O endpoint de registo também aplica o gate: uma chamada “normal” não pode ser
registada num contacto bloqueado. Outcomes de supressão continuam permitidos
para documentar o opt-out.

## CSV de licenças/permits

Obrigatórios: `company_name`, `phone`.

Opcionais:
`contact_name`, `email`, `website`, `city`, `state` (default `MA`), `zip_code`,
`license_number`, `license_status`, `trade`, `permit_count`,
`permit_value_usd`, `years_active`, `employee_estimate`, `entity_type`
(default `business`), `consent_basis` (default `b2b_legit_interest`), `notes`.

Template: `GET /api/admin/voice/template.csv`.

## DNC universal

O importador aceita **qualquer lista crua**:
- CSV, TSV, TXT ou uma coluna;
- cabeçalhos arbitrários ou sem cabeçalho;
- linhas soltas com telefones;
- números com `+1`, parênteses, hífens, pontos ou extensões.

O backend deteta telefones, normaliza para E.164, deduplica e interpreta
`clean/clear/no/false/0` como limpo; em conflito, prevalece “listado”. Linhas
sem telefone são ignoradas. Cada import cria/renova o check por 31 dias.

Ao importar a **lista oficial completa**, manter ativo **“Aplicar à base
(scrub)”**: os números presentes na lista ficam bloqueados e os restantes
ficam limpos (`source='dnc_scrub'`). Sem scrub, os números sem check continuam
bloqueados por fail-closed.

> **Produção:** o piloto aceita importação de lista e check manual. Antes de
> escalar, ligar um provedor DNC licenciado (federal + estadual) com auditoria
> por chamada. O gate já está preparado para isso: basta gravar o resultado em
> `dnc_checks` com `provider` e `checked_at`.

## Staging (dry-run)

Com `VOICE_STAGING_MODE=true`:
- DNC em falta/expirado é auto-limpo no gate (`dnc_staging_bypass`);
- números listados continuam bloqueados;
- Telnyx fica **forçado em dry-run**, mesmo com chaves configuradas;
- o botão **“Desobstruir staging”** grava checks auditáveis
  (`source='staging'`) e reconstrói os segmentos.

**Nunca** ativar produção com `VOICE_STAGING_MODE=true`. Para chamadas reais:
`VOICE_STAGING_MODE=false`, DNC licenciado importado e chaves Telnyx.

## Voz nativa Telnyx (AI Engine)

O assistente usa **apenas vozes nativas da Telnyx**. Nao ha ElevenLabs,
Deepgram Aura nem outro TTS externo.

| Definicao | Valor |
|---|---|
| Voz default masculina | `Telnyx.Ultra.00967b2f-88a6-4a31-8153-110a92134b9f` (Asher, en-US, male) |
| Voz default feminina | `Telnyx.Ultra.00a77add-48d5-4ef6-8157-71e5437b282d` (Callie, en-US, female) |
| Alternativa feminina en-US | `Telnyx.Ultra.01eaafa9-308a-4276-a017-6ab0cf061b1f` (Clara, en-US, female) |
| Modelo | default da conta Telnyx (`TELNYX_ASSISTANT_MODEL` vazio) |
| Formato | `Telnyx.Ultra.<voice_id>` |

O default do codigo e **Callie**
(`Telnyx.Ultra.00a77add-48d5-4ef6-8157-71e5437b282d`). Cada
roteiro pode fixar a sua voz em `voice_id`. A voz tambem e enviada no
`ai_assistant_start`, com o script ja renderizado para a chamada.

Variaveis de ambiente:

| Variavel | Obrigatoria | Funcao |
|---|---|---|
| `TELNYX_API_KEY` | sim | criar chamadas, assistants e tools |
| `TELNYX_CONNECTION_ID` | sim | Call Control App |
| `TELNYX_FROM_NUMBER` | sim | numero de origem E.164 |
| `TELNYX_WEBHOOK_SECRET` | sim | assinatura dos tool calls |
| `TELNYX_PUBLIC_KEY` | recomendada | verificacao Ed25519 do webhook |
| `PUBLIC_API_URL` | sim | base dos webhooks/tools |
| `TELNYX_ASSISTANT_VOICE` | nao | Callie (`Telnyx.Ultra.00a77add-...`) por defeito |
| `TELNYX_ASSISTANT_MODEL` | nao | vazio usa o default Telnyx |
| `TELNYX_SHARED_ASSISTANT_ID` | recomendada | assistant unico para os 15 roteiros (limite Telnyx) |
| `TELNYX_ASSISTANT_TRANSCRIPTION_MODEL` | nao | `deepgram/nova-3` por defeito |
| `TELNYX_ASSISTANT_NOISE_SUPPRESSION` | nao | `krisp` por defeito |
| `TELNYX_ASSISTANT_EXPRESSIVE_MODE` | nao | `true` para Ultra expressive |
| `VOICE_TEST_NUMBERS` | teste | allowlist E.164 separada por virgulas |
| `VOICE_MAX_DAILY_BUDGET_USD` | sim | teto global diario de voz (default 5) |
| `VOICE_MAX_CALLS_PER_DAY` | sim | teto global de chamadas/dia (default 100) |
| `VOICE_ESTIMATED_CALL_COST_CENTS` | sim | reserva por chamada ativa (default 25c) |
| `VOICE_CAMPAIGN_TOTAL_BUDGET_USD` | sim | default de campanha (100) |
| `VOICE_CAMPAIGN_DAILY_BUDGET_USD` | sim | default diario de campanha (5) |
| `VOICE_CAMPAIGN_MAX_DAYS` | sim | default de dias (30) |
| `VOICE_CAMPAIGN_RESUME_INTERVAL_SECONDS` | sim | cadencia do loop de retoma (300) |
| `VOICE_FALLBACK_AUDIO_URL` | nao | vazio deriva de `PUBLIC_API_URL/api/voice/fallback.mp3` |
| `VOICE_STAGING_MODE` | sim | `false` so durante o teste real |
| `EMAIL_API_KEY` | sim | Resend para o email da vitrine |
| `EMAIL_FROM` | sim | ex. `Magic Leads <support@magicleads.app>` |
| `SHOWCASE_BASE_URL` | sim | `https://www.magicleads.app` (link branded) |

- **Caller ID ativo:** `+1 929 256 2550` (NYC, overlay 718/347; rate center
  New York City). O `+1 518 942 9910` fica como backup. Em 2026-11-03 os DDDs
  212/646/718 exatos estavam esgotados na Telnyx; 929 e o local NYC disponivel.

`sync_to_telnyx` cria/atualiza o assistant com:
- `instructions` = script aprovado + regras operacionais;
- `voice_settings.voice` nativo;
- `telephony_settings.disable_dtmf=true` (o backend trata 1/2; o LLM nao recebe
  os tons, evitando respostas cortadas);
- tools webhook `send_showcase_link` e `remove_from_list`.

## Limite de assistants e modo shared

A conta Telnyx atual permite **10 TeXML Applications** (erro `10039`). Como os 15
roteiros precisam de assistant, usamos **um assistant unico**:

- `TELNYX_SHARED_ASSISTANT_ID=assistant-...`
- `sync_all` atualiza esse assistant uma vez e grava o mesmo `assistant_id` nos
  15 roteiros.
- O `ai_assistant_start` envia `instructions`, `greeting` e `voice_settings`
  renderizados por chamada, por isso o assistant fala o roteiro do trade certo.
- As tools (`send_showcase_link`, `remove_from_list`) sao as mesmas para todos
  os trades.

Se a conta for upgraded para mais de 15 TeXML apps, basta remover
`TELNYX_SHARED_ASSISTANT_ID` e correr **Sync Telnyx** para criar um assistant
por trade.

## Voicemail / AMD

- Todas as chamadas sao criadas com `answering_machine_detection="premium"`
  (`total_analysis_time_millis=5000`).
- O assistant tem
  `voicemail_detection.on_voicemail_detected.action="stop_assistant"`.
- `call.answered` marca `assistant_pending` e **nao** arranca o assistant. O
  AMD humano arranca-o; se o AMD nao chegar em 8s, um timer fail-open arranca.
- No webhook AMD, `machine/fax_detected/beep` marcam
  `intent=voicemail`, `hangup_cause=voicemail_detected`, `amd_result` e desligam
  a chamada. `human/human_residence/human_business/not_sure/silence` seguem
  para o fluxo normal; `silence` nao e maquina.
- Assim o assistant nao fala com voicemail nem envia links sem um humano.

## DTMF e tools (V3 — website-only)

- O backend recebe os DTMF via Call Control (`call.dtmf.received`); o assistant
  nao os recebe (`disable_dtmf=true`).
- A V3 **nao oferece Tecla 1**. O unico caminho de conversao e o website
  `MagicLeads.app`; a Tecla 2 e opt-out.
- Tecla **2**: chama `opt_out_voice_call()` antes de qualquer audio — cria
  `voice_suppressions`, marca a empresa `do_not_call`, atualiza
  `voice_calls.intent=opt_out` e para o assistant. Depois fala
  “You've been removed from our list. Goodbye.” e desliga no `speak.ended`.
- Tecla **1** (habito): repete “Visit MagicLeads dot app…” e desliga. Nao envia
  email nem SMS.
- O assistant **nunca pede email** nem promete entrega por email/SMS. As tools
  expostas sao apenas `remove_from_list` para opt-out verbal.
- `send_showcase_link`/`capture_email` ja nao fazem parte do assistant de voz;
  o envio de email da vitrine fica apenas em fluxos manuais/admin.
- `remove_from_list` e idempotente: cria supressao e marca `do_not_call`.
- O auto-scheduler **nao** envia vitrine ao discar; a V3 nao envia nada.
- Os tool calls chegam com `x-telnyx-call-control-id`, correlacionado com
  `voice_calls.provider_call_id`.

## Email da vitrine (legado / manual)

O email da vitrine e o template `/r/<token>` continuam a existir para fluxos
manuais e admin, mas **nao fazem parte da V3 de voz**. A V3 nao pede email, nao
envia email e nao expõe `send_showcase_link` ao assistant.

O envio manual continua a usar o link `/r/<token>` e o email aprovado; qualquer
envio exige o endereco que ja esta na ficha. A transcricao usa
`deepgram/nova-3` com noise suppression `krisp`, mas o email nunca depende de
ASR.

## Guardrails do `showcase_line` (voz)

- O numero vem de `showcase.available(city, trade)`, que lê
  `market_inventory` (build a partir de `leads.db`, janela
  `SHOWCASE_WINDOW_DAYS`, sinais `SHOWCASE_SIGNAL_TYPES`).
- A V3 exige `VOICE_MIN_SHOWCASE_ITEMS` (default **5**) e inventário com menos
  de `VOICE_SHOWCASE_MAX_AGE_HOURS` (default **72 h**).
- Se a contagem exata e a city-wide estiverem abaixo do mínimo, ou o inventário
  estiver velho, `showcase_guard()` devolve `ready=False` e
  `telnyx_voice.create_call()` aborta com `showcase_unavailable` — a chamada
  nao sai.
- Nunca e falado “0”: contagens >= 1.000 sao arredondadas para “over N,XXX”
  para o TTS nao arrastar o numero.

## Analytics de aceite e conversao

`GET /api/admin/voice/metrics?days=30` devolve:

- `summary.accepts` e `accept_rate` — chamadas atendidas em que o contacto
  prime 1 ou diz que sim (`voice_calls.intent='showcase'`).
- `summary.checkouts` e `subscription_rate` — assinaturas Stripe concluidas
  (`checkout_session_id` preenchido) sobre aceites.
- `summary.revenue_per_accept_usd` — receita media por aceite.
- `by_state`, `by_city`, `by_trade` e `by_city_trade` — cada grupo com
  `answered`, `accepts`, `accept_rate`, `checkouts`, `subscription_rate`,
  `revenue_usd` e `net_usd`.

No `/admin/voice`, a overview mostra os gauges **Voice Accept** e
**Assinatura**, o funil com o passo **Aceite (1/Yes)** e tres tabelas:
**Aceite por estado**, **Aceite por cidade** e **Aceite por nicho**. A matriz
cidade x nicho tambem ganhou as colunas Aceite e Assinatura.

Definicoes:

- **Aceite** = `intent='showcase'` na chamada. E marcado pelo DTMF 1 e pelas
  tools de email (`send_showcase_link`); o envio tambem garante
  a marca.
- **Assinatura** = `checkout_session_id` preenchido no webhook Stripe
  `checkout.session.completed` com `source=voice_showcase`.
- **Conversao** = assinaturas / aceites (nao sobre cliques), para medir a
  qualidade do lead de voz.

## Orcamento e horario de campanha

Cada campanha tem estes parametros:

| Parametro | Efeito |
|---|---|
| `budget_total_usd` | ao esgotar, a campanha fica **completed** |
| `budget_daily_usd` | ao esgotar, a campanha fica **paused** ate ao dia seguinte |
| `max_days` | ao passar o numero de dias, a campanha fica **completed** |
| `start_hour_et` | hora local (ET) em que o lote diario arranca (default 9) |
| `call_interval_seconds` | intervalo entre chamadas do lote (default 30) |
| `batch_plan` | lista JSON de lotes por dia (ramp); `plan_index` avanca apos cada lote |

O backend reserva 25c por chamada ativa e substitui pelo custo real no fim.
`campaign_budget_status` corre antes de cada chamada; o auto-scheduler pausa
ou completa a campanha automaticamente. Ha ainda uma rede de seguranca global:
`VOICE_MAX_DAILY_BUDGET_USD=5` e `VOICE_MAX_CALLS_PER_DAY=100`.

**Distribuicao diaria:** o lote nao e espalhado pelo dia. Quando a hora de
inicio chega, o auto-dialer inicia as chamadas do lote com
`call_interval_seconds` entre cada uma e depois pausa ate ao dia seguinte.
Sem `batch_plan`, usa `batch_size`; com `batch_plan` (ex.: `[15,20,25]`), usa
o lote do dia e avanca o `plan_index` no fim. O auto-dialer nao espera que a
chamada anterior termine: com conversas longas pode haver chamadas ativas em
simultaneo.

**Exclusao global:** `campaign_candidates` nao repete um contacto que tenha
`voice_calls` Telnyx nos ultimos 7 dias, mesmo que seja de outra campanha. Isto
evita chamadas duplicadas quando duas campanhas correm em paralelo.

**Erros transitorios:** `http_401`, `http_402`, `http_403`, `http_429`,
`http_5xx` e `network_error` **pausam** a campanha em vez de saltar o contacto;
a linha `voice_calls` failed e apagada para o contacto voltar a ser candidato.

### Retoma automatica

`_voice_campaign_resume_loop` corre a cada 5 min e retoma campanhas `paused`
quando `next_batch_at` venceu. A pausa diaria aponta para a proxima ocorrencia
de `start_hour_et` em Nova Iorque; se o total ou os dias ja esgotaram, a
campanha e fechada como `completed` na retoma. Fora da janela local do estado a
chamada devolve `outside_hours` e a campanha pausa 1h **sem** saltar o contacto.

## Chamada de teste controlada

1. Configurar `TELNYX_API_KEY`, `TELNYX_CONNECTION_ID`, `TELNYX_FROM_NUMBER`,
   `TELNYX_WEBHOOK_SECRET`, `TELNYX_PUBLIC_KEY` e `PUBLIC_API_URL`.
2. `VOICE_TEST_NUMBERS=+1...` ou `+351...` com o telemovel de teste. O gate
   normal so aceita `+1`, mas a chamada de teste permite E.164 internacional
   **apenas** para numeros na allowlist (`allow_international` em
   `create_call`). A conta Telnyx tem de permitir chamadas internacionais e ter
   saldo; caso contrario a operadora devolve erro.
3. **Aprovar Todos** e **Sync Telnyx** para preencher os 15 `assistant_id`.
4. `VOICE_STAGING_MODE=false`.
5. `POST /api/admin/voice/test-call` com `{"confirm": true, "phone": "+1..."}`.
6. Validar audio, disclosure, latencia, tecla 1, email, opt-out e hangup.
7. Reativar `VOICE_STAGING_MODE=true` se nao houver mais testes.

Sem `assistant_id` a chamada real e bloqueada com `assistant_missing`. Se o
`ai_assistant_start` falhar, a chamada e desligada para nunca ficar em silencio.

## API

| Método | Rota | Função |
|---|---|---|
| GET | `/api/admin/voice/queue` | fila + elegibilidade |
| GET | `/api/admin/voice/stats` | KPIs e configuração do piloto |
| POST | `/api/admin/voice/import/licenses` | importar licenças/permits |
| POST | `/api/admin/voice/import/dnc` | importar lista DNC |
| POST | `/api/admin/voice/ingest` | importar + rebuild de vitrines + segmentos |
| GET | `/api/admin/voice/segments` | filas agregadas por cidade+nicho |
| GET | `/api/admin/voice/metrics` | funil: answer, engagement, CTR, checkout, receita |
| GET | `/api/admin/voice/sources` | fontes e último estado |
| POST | `/api/admin/voice/sources` | criar fonte `http_csv` |
| POST | `/api/admin/voice/sources/{id}/sync` | sincronizar fonte |
| POST | `/api/admin/voice/sources/bridge-licensing` | converter contractor_entities |
| POST | `/api/admin/voice/campaigns/start` | arrancar campanha autónoma |
| GET | `/api/admin/voice/campaigns` | listar campanhas |
| POST | `/api/admin/voice/campaigns/{id}/stop` | parar campanha |
| POST | `/api/admin/voice/campaigns/{id}/resume` | retomar lote pausado |
| GET | `/api/admin/voice/scripts` | listar roteiros |
| PUT | `/api/admin/voice/scripts/{trade}` | guardar draft |
| POST | `/api/admin/voice/scripts/{trade}/approve` | aprovar roteiro |
| POST | `/api/admin/voice/scripts/{trade}/preview` | renderizar variáveis |
| POST | `/api/admin/voice/scripts/{trade}/sync-telnyx` | criar/atualizar assistant |
| POST | `/api/admin/voice/scripts/approve-all` | aprovar todos + sync |
| POST | `/api/admin/voice/scripts/sync-all` | sincronizar todos |
| POST | `/api/admin/voice/test-call` | 1 chamada real controlada |
| POST | `/api/admin/voice/dnc/check` | check manual (limpo/listado) |
| POST | `/api/admin/voice/contacts/{id}/call` | registar tentativa |
| POST | `/api/admin/voice/suppress` | suprimir telefone |
| GET | `/api/admin/voice/template.csv` | template de importação |

Todas exigem sessão **admin** (`_require_admin_user`).

## Base pré-carregada

- `contractor_entities` guarda licenças já ingeridas (NY/TX/IL/MA). O botão
  **“Sincronizar licenças existentes”** / `POST /sources/bridge-licensing`
  converte-as em `prospect_companies`, com dedupe por telefone, cidade/estado
  normalizados e trade inferido.
- `voice_sources` + `raw_ingest` registam fontes, checksum, linhas, erros e
  última sincronização. `http_csv` exige HTTPS e host em
  `VOICE_SOURCE_ALLOWED_HOSTS`.
- `voice_segments` materializa cidade+nicho com `Dedicada`, `Fallback cidade`
  ou `Sem vitrine`; o painel lê esta tabela.
- O operador não faz upload de CSV no fluxo normal: escolhe cidade/nicho, cota
  total, lote e inicia.

## Automação no Admin

1. **Importar e processar**: sobe o CSV bruto; o backend faz parsing, limpeza,
   dedupe por telefone, mapeamento de campos, rebuild das vitrines e devolve os
   segmentos cidade+nicho.
2. **Segmentos**: cada linha é uma fila por cidade/estado/nicho, classificada
   como `Dedicada`, `Fallback cidade` ou `Sem vitrine` via
   `showcase.available()`.
3. **Iniciar campanha autónoma**: escolhe cidade/nicho (ou usa os filtros da
   fila), define o máximo de chamadas e arranca. O worker:
   - consome a fila por score;
   - aplica `can_call()` (DNC, supressão, tentativas, horário local);
   - dispara Telnyx + link/email da vitrine;
   - respeita `VOICE_AUTOSCHED_DELAY_SECONDS` entre chamadas reais;
   - marca a campanha como `completed`, `stopped` ou `error`.
4. **Dry-run**: sem chaves Telnyx, as chamadas ficam registadas em `voice_calls`
   e os emails ficam em dry-run; nenhum contacto real é feito.

## Roteiros de voz (V3)

- 15 roteiros default com o template V3 aprovado; `TEMPLATE_VERSION` bump
  aplica-o e deixa todos `approved` (a V3 foi aprovada pelo operador).
- O template V3 e website-only: `{{company | Contractor}}`,
  `{{showcase_line}}`, URL `MagicLeads.app`, Tecla 2 = opt-out. Nao tem
  “If Yes / Press 1” nem CTA de email.
- Variáveis: `{{company}}` (fallback `Contractor`), `{{city}}`, `{{trade}}`,
  `{{permit_count}}`, `{{showcase_line}}`, `{{price_weekly}}`,
  `{{price_monthly}}`.
- O parser suporta `{{var | fallback}}`; nunca deixa braces no áudio.
- Aba **Roteiros** no `/admin/voice`: editar, pré-visualizar por cidade/empresa,
  guardar draft, aprovar, **Aprovar Todos** e sincronizar com a Telnyx.
- Só roteiro `approved` com `assistant_id` pode ser usado em chamada real.
- **Overrides**: `voice_script_overrides` por estado/cidade. Resolução runtime
  **cidade > estado > global**; só overrides `approved` entram em produção.
- No `call.answered`, o backend inicia o assistant; se falhar, desliga a
  chamada para não ficar em silêncio.
- Teste real: `POST /voice/test-call` com `confirm=true`, telefone em
  `VOICE_TEST_NUMBERS`, staging off e Telnyx configurado.

## Operação

1. Importar licenças/permits de MA, NY, TX ou IL.
2. Importar lista DNC (ou fazer check manual por número).
3. Abrir `/admin/voice`; a fila mostra só contactos que passam o gate.
4. Usar os filtros de cidade/nicho e a cobertura agrupada por cidade/nicho.
5. Clicar no telefone (`tel:`) e registar o resultado.
6. “Sem interesse / número errado / não contactar” suprime automaticamente.

## Checklist de ativação (piloto real)

1. **Railway env**
   - `TELNYX_API_KEY`
   - `TELNYX_CONNECTION_ID`
   - `TELNYX_FROM_NUMBER`
   - `TELNYX_WEBHOOK_SECRET`
   - `TELNYX_WEBHOOK_URL` (ou `PUBLIC_API_URL`)
   - `EMAIL_API_KEY` / `EMAIL_FROM` (Resend) para envio real
2. **Importar CSV B2B** em `/admin/voice` (company_name, phone, city,
   state, trade, license_status, permit_count, email).
3. **Importar DNC** (`phone, listed`) ou fazer check manual por número.
4. **Rebuild pages** em `/admin/voice` se a ingestão tiver mudado.
5. **Testar uma empresa**:
   - `showcase.available(city, trade)` → `available=true`
   - “Enviar vitrine” → link `/r/<token>` + email
   - abrir `/r/<token>` → 302 para `/en/<city>/<trade>?vt=...`
6. **Ligar Telnyx** em dry-run primeiro; confirmar `voice_calls` e o webhook
   DTMF 1 antes de ativar chamadas reais.
7. **Confirmar filtros** de cidade/nicho e a cobertura agrupada no
   `/admin/voice`.

## Limites da Fase 1/2A

- Sem dialer automático/predictive: apenas click-to-call manual.
- Sem gravação de chamadas (Fase 2; exige consentimento all-party em MA).
- DNC por CSV/manual; provedor licenciado na Fase 2.
- Piloto restrito a **MA, NY, TX e IL**.
- Sem importação de dados de homeowners ou de contas de concorrentes.

## Testes

- `tests/test_b2b_voice.py`: importação/dedupe, DNC, supressão, horário,
  estado, limite de tentativas, supressão automática.
- `tests/test_admin_panel.py`: fluxo API completo (importar → DNC → fila →
  chamada → stats) e gate de admin.
