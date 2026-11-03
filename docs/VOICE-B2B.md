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
10. fora de **08:00–21:00 locais** (`America/New_York` para MA/NY;
    `America/Chicago` para TX/IL) → `outside_hours`

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
| Voz default masculina | `Telnyx.Ultra.Asher` (en, male) |
| Voz default feminina | `Telnyx.Ultra.Callie` (en, female) |
| Alternativa feminina en-US | `Telnyx.Ultra.Clara` (en-US, female) |
| Modelo | default da conta Telnyx (`TELNYX_ASSISTANT_MODEL` vazio) |
| Formato | `Telnyx.Ultra.<voice_id>` |

O default do codigo e `Telnyx.Ultra.Callie` (`TELNYX_ASSISTANT_VOICE`). Cada
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
| `TELNYX_ASSISTANT_VOICE` | nao | `Telnyx.Ultra.Callie` por defeito |
| `TELNYX_ASSISTANT_MODEL` | nao | vazio usa o default Telnyx |
| `TELNYX_ASSISTANT_EXPRESSIVE_MODE` | nao | `true` para Ultra expressive |
| `VOICE_TEST_NUMBERS` | teste | allowlist E.164 separada por virgulas |
| `VOICE_STAGING_MODE` | sim | `false` so durante o teste real |

`sync_to_telnyx` cria/atualiza o assistant com:
- `instructions` = script aprovado + regras operacionais;
- `voice_settings.voice` nativo;
- `telephony_settings.disable_dtmf=false` (DTMF ativo por defeito);
- tools webhook `send_showcase_link`, `capture_email` e `remove_from_list`.

## DTMF e tools

- O assistant recebe DTMF como texto. A tecla **1** conta como "sim"; o
  backend apenas marca `intent=showcase` e **nao** envia email nesse momento.
- O assistant pergunta o email e chama `capture_email`; so essa tool envia o
  link, evitando emails duplicados.
- `send_showcase_link` envia para o email ja existente; sem email devolve
  `email_required` e o assistant pede o endereco.
- `remove_from_list` cria supressao e marca a empresa `do_not_call`.
- O auto-scheduler **nao** envia a vitrine ao discar; o email so sai depois de
  o contacto atender e autorizar, para nao enviar links sem consentimento.
- Os tool calls chegam com `x-telnyx-call-control-id`, correlacionado com
  `voice_calls.provider_call_id`.

## Chamada de teste controlada

1. Configurar `TELNYX_API_KEY`, `TELNYX_CONNECTION_ID`, `TELNYX_FROM_NUMBER`,
   `TELNYX_WEBHOOK_SECRET`, `TELNYX_PUBLIC_KEY` e `PUBLIC_API_URL`.
2. `VOICE_TEST_NUMBERS=+1...` com o telemovel de teste.
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

## Roteiros de voz

- 15 roteiros default com o template oficial aprovado, status `draft`.
- O template inclui Opening & Pitch, “If Yes / Press 1” e “If No / Stop”.
- Variáveis: `{{company}}`, `{{city}}`, `{{trade}}`, `{{permit_count}}`,
  `{{showcase_line}}`, `{{price_weekly}}`, `{{price_monthly}}`.
- Aba **Roteiros** no `/admin/voice`: editar, pré-visualizar por cidade/empresa,
  guardar draft, aprovar, **Aprovar Todos** e sincronizar com a Telnyx.
- Só roteiro `approved` com `assistant_id` pode ser usado em chamada real.
- **Overrides futuros**: `voice_script_overrides` por estado/cidade. Resolução
  runtime **cidade > estado > global**; só overrides `approved` entram em
  produção. O global por trade continua a ser o default.
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
