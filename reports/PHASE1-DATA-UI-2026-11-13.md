# Fase 1 — Dados reais na dashboard e no drawer (staging)

Data: 2026-11-13
Âmbito: staging (`staging/opportunity-foundation`). Produção `master` em `3b53962` intocada.
Landing page: congelada; zero alterações em `frontend/app/[locale]/(marketing)`.

## 1. O que ficou implementado

### Backend
- Novos campos em `opportunity_workflow`: `fine_balance`, `fine_imposed`, `fine_paid`,
  `hearing_date`, `hearing_status`, `value_source`, `history_json`, `property_json`.
- `create_opportunity` e `update_enrichment` persistem e expõem esses campos.
- `insights` passa a devolver `fines_at_risk` (saldo real em aberto) e `fines_count`;
  `value_at_risk` continua a ser valor de obra.
- `source_payload` continua interno; `history` e `property` são os únicos campos novos
  expostos ao cliente.
- Texto de sinal e histórico passa por `privacy.scrub` (sem termos de fonte/arquitetura).

### Ingestão
`backend/services/phase1_enrichment.py` + `scripts/ingest_phase1_staging.py`
(guardas `ALLOW_STAGING_INGEST=1` e `LEADS_DB_PATH`, recusa o repo de produção).

Fontes reais ligadas:
- chamados de habitação abertos (fila preventiva);
- violações de habitação com prazo legal futuro;
- multas e audiências com saldo em aberto (ECB);
- violações de construção de Chicago;
- valores de obra declarados em alvarás (NYC e Chicago);
- ficha do imóvel por BBL (PLUTO): dono, classe, unidades, ano, pisos, áreas, valor avaliado.

Deduplicação por imóvel; o histórico de cada ocorrência fica em `history` e a ficha em
`property`.

### Frontend
- Drawer com:
  - bloco de **multa real** (saldo, imposta, paga, audiência e estado);
  - linha do tempo coerente com multa/prazo;
  - **dossiê do imóvel** (classe, valor avaliado, unidades, ano, pisos, área do lote);
  - **histórico do imóvel** com data, estado e valor da ocorrência;
  - legenda da base do valor (“Declarada em alvará” / “Não publicada”).
- Toolbar preventiva com:
  - prazo: qualquer / ≤ 3 dias / ≤ 7 dias;
  - **Com multa** (saldo real > 0).
- KPI “Multas em Risco” passou a usar `fines_at_risk` real; o subtítulo diz
  “saldo de multas em aberto”.
- PT/EN/ES completos (paridade de i18n validada).

## 2. Estado atual do staging

| Métrica | Valor |
|---|---|
| Preventivos | **52** |
| Com multa real em aberto | **10** |
| Saldo de multas em risco | **US$ 166.600** |
| Prazos publicados | **19** |
| Prazos ≤ 7 dias | **16** |
| Prazos ≤ 3 dias | **14** |
| Com valor de obra | **25** (13 de alvará) |
| Com dossiê do imóvel | **27** |
| Com histórico | **38** |
| NYC / Chicago / Boston / Dallas | 36 / 13 / 2 / 1 |

Exemplos reais visíveis:
- **1185 Avenue of the Americas** — multa em aberto de US$ 20.000, audiência 2027-01-21,
  dossiê PLUTO (50 unidades, 42 pisos, 1970) e histórico com valor de alvará.
- **3430 Broadway** — prazo legal em 2 dias (seed) e proprietário identificado.
- **238 East 26 Street / 2029 West 9 Street** — prazos legais reais ≤ 3 dias.

## 3. Como validar

1. Abrir `http://localhost:3000/pt/dashboard`.
2. Clicar em **Pré-inspeção** na barra lateral.
3. Confirmar os KPI: 52 preventivos, prazos ≤ 3/≤ 7 dias, multas em risco com saldo real.
4. Em **Prazo**, escolher **≤ 3 dias** → devem restar 14 cartões.
5. Ligar **Com multa** → devem restar 10 cartões; abrir um deles.
6. No drawer confirmar: multa real, audiência, dossiê do imóvel e histórico.
7. Repetir em `/en/dashboard` e `/es/dashboard` para confirmar as etiquetas.

## 4. Qualidade

- `pytest tests -q`: **1678 passed, 1 skipped**.
- `npm test`: **123 passed** (inclui paridade i18n).
- `npx tsc --noEmit`: limpo.
- `ruff check backend tests --select=E,F,W,I --ignore=E501`: limpo.
- ESLint: 0 erros (avisos pré-existentes).
- Landing: sem alterações; produção `master` em `3b53962`.

## 5. Limitações conhecidas (Fase 1)

- O valor de obra é o **último valor declarado em alvará** do imóvel (janela de 3 anos),
  não uma estimativa do serviço específico; a UI identifica a base.
- Multas reais só existem onde a fonte publica saldo (ECB / ordenanças de Chicago);
  chamados sem multa ficam com bloco “Ainda sem multa”.
- O histórico mostra ocorrências da janela ingerida; não é ainda um ledger completo.
- Chicago tem menos valores de alvará casados por morada; a cobertura cresce com o
  volume de alvarás lido.
- Boston/Dallas continuam com os leads de seed nesta fase; a Fase 2 cobre as fontes
  adicionais do relatório exaustivo.
