# Fase 1 — dados reais, classificador e ingestão contínua (staging)

Data: 2026-11-13
Âmbito: staging (`staging/opportunity-foundation`). Produção `master` em `3b53962` intocada.
Landing page: congelada; zero alterações em `frontend/app/[locale]/(marketing)`.

## 1. Regras em vigor

| Regra | Valor |
|---|---|
| Janela da fila preventiva | **7 dias** (`PREVENTIVE_FEED_WINDOW_DAYS=7`) |
| Retenção na BD | **90 dias** (`PREVENTIVE_RETENTION_DAYS=90`); 30 dias ficam para auditoria |
| Purga | diária; nunca apaga `reserved`/`contacted`/`in_negotiation` |
| Exibição | **50 por omissão** → “Carregar mais” até **100 máximo** |
| Chamados/prazos/multas | scheduler a cada **6h** |
| Alvarás/PLUTO | scheduler a cada **24h** |
| Filtros | cidade, especialidade, gravidade, prazo ≤3/≤7, com multa e busca — no servidor |
| Gatilho manual | `POST /api/admin/phase1/run` (admin) |
| Reclassificação manual | `POST /api/admin/phase1/reclassify` (admin) |

O scheduler da Fase 1 é independente do scraper reativo. Arranca apenas com
`PHASE1_SCHEDULER_ENABLED=1`; por omissão fica desligado.

## 2. Classificador de ofícios (fix “Unclassified”)

O classificador foi expandido para os termos reais de obra das fontes:

- estrutura/andaimes: `sidewalk shed`, `scaffold`, `scaffolding`,
  `pedestrian protection`, `construction`, `new building`, `structural`,
  `facade`, `foundation`, `demolition`, `excavation`, `shoring`, `beam`,
  `column`, `concrete`, `masonry`, `brick`, `wall`, `floor`, `ceiling`,
  `stair`, `porch`, `fence`, `fire escape`, `balcony`, `canopy`, `shed`,
  `hoist`, `crane`, `jobsite`, `site safety`, `netting`, `curtain wall`,
  `cornice`, `sidewalk`;
- elevadores: `elevator`, `eleva`, `lift`;
- elétrica: `electric`, `wiring`, `smoke detector`, `bell`, `buzzer`,
  `intercom`, `light fixture`, `outlet`, `circuit`;
- cobertura: `roof`, `roofing`, `waterproof`, `chimney`, `parapet`,
  `skylight`, `flashing`, `gutter`;
- canalização, aquecimento, gás, mofo, chumbo, roedores, pintura, portas/janelas,
  entulho, insalubridade e permissões.

Regras de segurança:
- o fallback deixou de ser o texto cru `Unclassified`; passa a **Structure**
  (“Estrutura”), uma categoria traduzida e filtrável;
- descrições administrativas/genéricas (`OPEN`, `ARRANGE PREMISE INSPECTION`,
  `OWNER OR LICENSED CONTRACTOR`, `SAFE WORKING CONDITIONS`) são **descartadas
  na ingestão** quando não têm multa nem prazo;
- a UI também traduz qualquer resíduo `Unclassified`/`General` para
  `dashboard.cat.general` (“Geral”), como rede de segurança.

Reclassificação aplicada ao staging:

| Métrica | Valor |
|---|---|
| Registos analisados | 423 |
| Reclassificados | **77** |
| Descartados (genéricos sem multa/prazo) | **15** |
| `Unclassified` restantes | **0** |

Exemplos do utilizador:
- `362 West 54th Street` → **Structure**;
- `315 West 70th Street` → **Structure**;
- `609 Columbus Avenue` → **Structure**.

## 3. Estado atual do staging

| Métrica | Valor |
|---|---|
| Preventivos na janela de 7 dias | **402** |
| Total na BD (auditoria) | 408 |
| Com multa real em aberto | **39** |
| Saldo de multas em risco | **US$ 304.300** |
| Prazos ≤ 7 dias | **44** |
| Prazos ≤ 3 dias | **18** |
| Com valor de obra | **42** (32 de alvará) |
| Com dossiê do imóvel | **67** |
| Com histórico | **390** |
| NYC / Chicago / Boston / Dallas | 331 / 69 / 1 / 1 |

Distribuição por ofício (janela de 7 dias): Heating 173, Rodent 72,
Structure 32, Plumbing 25, Elevator 20, Electrical 19, Paint 13, Roof 12,
Unsanitary 10, Door_Window 8, Mold 6, Permit_Rejected 5, Gas 4, Debris 2,
Lead 1.

## 4. Como validar

1. Abrir `http://localhost:3000/pt/dashboard` e clicar em **Pré-inspeção**.
2. Confirmar: **402** preventivos, **44** prazos ≤7 dias, **18** ≤3 dias,
   **US$ 304k** em multas (39 imóveis).
3. A lista começa em **50 de 402**; “Carregar mais” leva a **100 de 402**.
4. Filtrar **Com multa** → **39** cartões.
5. Filtrar **Prazo ≤ 3 dias** → **18** cartões.
6. Confirmar que nenhum cartão mostra “Unclassified”; os exemplos
   `362 West 54th`, `315 West 70th` e `609 Columbus` aparecem como
   **Estrutura**.
7. Repetir em `/en/dashboard` e `/es/dashboard`.

## 5. Ingestão contínua

O scheduler corre:
- **a cada 6h**: chamados, prazos, multas e violações de Chicago;
- **a cada 24h**: o run acima + alvarás/PLUTO;
- **a cada 24h**: purga de linhas com mais de 90 dias;
- **no arranque**: um run diário completo (`PHASE1_RUN_ON_START=1`).

Comandos de staging:

```powershell
$env:LEADS_DB_PATH="<staging.db>"
$env:PHASE1_SCHEDULER_ENABLED="1"
$env:PHASE1_RUN_ON_START="1"
$env:PHASE1_OPERATIONAL_LIMIT="300"
$env:PHASE1_ECB_LIMIT="600"
$env:PHASE1_DAILY_PERMIT_ROWS="1000"
```

## 6. Qualidade

- `pytest tests -q`: **1716 passed, 1 skipped** (35 testes novos do classificador,
  além de janela, paginação, filtros e purga).
- `npm test`: **123 passed** (inclui paridade i18n).
- `npx tsc --noEmit`: limpo.
- `ruff check backend tests --select=E,F,W,I --ignore=E501`: limpo.
- ESLint: 0 erros (avisos pré-existentes).
- Landing: sem alterações; produção `master` em `3b53962`.

## 7. Limitações conhecidas

- O valor de obra é o último valor declarado em alvará (janela de 3 anos),
  não uma estimativa do serviço específico; a UI identifica a base.
- Multas reais só existem onde a fonte publica saldo; chamados sem multa ficam
  com o bloco “Ainda sem multa”.
- O histórico é a janela ingerida, não um ledger contabilístico completo.
- Boston/Dallas continuam com os leads de seed nesta fase.
- O fallback Structure é deliberado para sinais de obra sem termo específico;
  não é um ofício “inventado”, é uma das 16 categorias ativas.
