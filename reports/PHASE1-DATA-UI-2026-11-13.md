# Fase 1 â€” dados reais, janela de 7 dias e ingestÃ£o contÃ­nua (staging)

Data: 2026-11-13
Ã‚mbito: staging (`staging/opportunity-foundation`). ProduÃ§Ã£o `master` em `3b53962` intocada.
Landing page: congelada; zero alteraÃ§Ãµes em `frontend/app/[locale]/(marketing)`.

## 1. Regras aprovadas e implementadas

| Regra | Valor |
|---|---|
| Janela da fila preventiva | **7 dias** (`PREVENTIVE_FEED_WINDOW_DAYS=7`) |
| RetenÃ§Ã£o na BD | **90 dias** (`PREVENTIVE_RETENTION_DAYS=90`); 30 dias ficam para auditoria |
| Purga | diÃ¡ria; nunca apaga `reserved`/`contacted`/`in_negotiation` |
| ExibiÃ§Ã£o | **50 por omissÃ£o**, botÃ£o â€œCarregar maisâ€ atÃ© **100 mÃ¡ximo** |
| Chamados/prazos/multas | scheduler a cada **6h** |
| AlvarÃ¡s/PLUTO | scheduler a cada **24h** |
| Filtros | cidade, especialidade, gravidade, prazo â‰¤3/â‰¤7, com multa e busca â€” todos no servidor |
| Gatilho manual | `POST /api/admin/phase1/run` (admin) |

O scheduler da Fase 1 Ã© independente do scraper reativo. Arranca apenas com
`PHASE1_SCHEDULER_ENABLED=1`; por omissÃ£o fica desligado.

## 2. Estado atual do staging (com scheduler ligado)

| MÃ©trica | Valor |
|---|---|
| Preventivos na janela de 7 dias | **417** |
| Total na BD (auditoria) | 423 |
| Com multa real em aberto | **39** |
| Saldo de multas em risco | **US$ 304.300** |
| Prazos â‰¤ 7 dias | **44** |
| Prazos â‰¤ 3 dias | **18** |
| Com valor de obra | **42** (32 de alvarÃ¡) |
| Com dossiÃª do imÃ³vel | **67** |
| Com histÃ³rico | **405** |
| NYC / Chicago / Boston / Dallas | 331 / 84 / 1 / 1 |

Primeiro run do scheduler (arranque): **397 candidatos**, 369 criados, 28
enriquecidos, 29 multas, 76 prazos e 20 valores.

## 3. Como validar

1. Abrir `http://localhost:3000/pt/dashboard`.
2. Clicar em **PrÃ©-inspeÃ§Ã£o**.
3. Confirmar: **417** preventivos, **44** prazos â‰¤7 dias, **18** â‰¤3 dias,
   **US$ 299k** em multas (38 imÃ³veis).
4. A lista comeÃ§a com **50 de 417**; â€œCarregar maisâ€ leva a **100 de 417** e
   desaparece (mÃ¡ximo de 100 cartÃµes).
5. Filtrar **Com multa** â†’ **39** cartÃµes.
6. Filtrar **Prazo â‰¤ 3 dias** â†’ **18** cartÃµes.
7. Abrir um cartÃ£o com multa (ex.: **1185 Avenue of the Americas**) e confirmar
   multa, audiÃªncia, dossiÃª e histÃ³rico.
8. Repetir em `/en/dashboard` e `/es/dashboard`.

## 4. IngestÃ£o contÃ­nua

O scheduler corre:
- **a cada 6h**: chamados, prazos, multas e violaÃ§Ãµes de Chicago;
- **a cada 24h**: o run acima + alvarÃ¡s/PLUTO;
- **a cada 24h**: purga de linhas com mais de 90 dias;
- **no arranque**: um run diÃ¡rio completo (se `PHASE1_RUN_ON_START=1`).

Comandos de staging:

```powershell
$env:LEADS_DB_PATH="<staging.db>"
$env:PHASE1_SCHEDULER_ENABLED="1"
$env:PHASE1_RUN_ON_START="1"
# limites do primeiro run (ajustÃ¡veis)
$env:PHASE1_OPERATIONAL_LIMIT="300"
$env:PHASE1_ECB_LIMIT="600"
$env:PHASE1_DAILY_PERMIT_ROWS="1000"
```

## 5. Qualidade

- `pytest tests -q`: **1681 passed, 1 skipped** (13 testes do workflow incluem
  janela, paginaÃ§Ã£o, filtros e purga).
- `npm test`: **123 passed** (inclui paridade i18n).
- `npx tsc --noEmit`: limpo.
- `ruff check backend tests --select=E,F,W,I --ignore=E501`: limpo.
- ESLint: 0 erros (avisos prÃ©-existentes).
- Landing: sem alteraÃ§Ãµes; produÃ§Ã£o `master` em `3b53962`.

## 6. LimitaÃ§Ãµes conhecidas

- O valor de obra Ã© o Ãºltimo valor declarado em alvarÃ¡ (janela de 3 anos),
  nÃ£o uma estimativa do serviÃ§o especÃ­fico; a UI identifica a base.
- Multas reais sÃ³ existem onde a fonte publica saldo; chamados sem multa ficam
  com o bloco â€œAinda sem multaâ€.
- O histÃ³rico Ã© a janela ingerida, nÃ£o um ledger contabilÃ­stico completo.
- Boston/Dallas continuam com os leads de seed nesta fase.
- O scheduler estÃ¡ limitado por fonte; para produÃ§Ã£o, os limites podem subir
  sem alterar a janela de 7 dias nem o top 100.
