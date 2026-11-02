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

## CSV DNC

`phone, listed` — `listed` aceita `1/0`, `yes/no`, `true/false`, `sim/não`.
Cada import cria/renova o check por 31 dias.

> **Produção:** o piloto aceita importação de lista e check manual. Antes de
> escalar, ligar um provedor DNC licenciado (federal + estadual) com auditoria
> por chamada. O gate já está preparado para isso: basta gravar o resultado em
> `dnc_checks` com `provider` e `checked_at`.

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
