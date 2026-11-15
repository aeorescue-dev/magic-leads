# Auditoria geral — 15/11/2026

**Âmbito:** garimpo (Boston, Dallas, NY, Chicago), enriquecimento, exatidão dos
mapas e integração no dashboard.
**Método:** produção em modo **read-only** (SQL e logs), réplica SQL dos
endpoints, testes automatizados e auditoria da UI autenticada em dev.
**Estado:** branch `feat/territory-view-preview` — **nada pushed, produção
intocada**.

---

## 1. Bugs encontrados e corrigidos

| # | Severidade | Bug | Impacto | Correção |
|---|---|---|---|---|
| 1 | **Crítica** | A migração de cidades apagava linhas canónicas: o `DELETE` fazia JOIN da tabela consigo mesma (`v.city='BOSTON'` também casa com `city='Boston'`). | No deploy, apagaria **todos** os leads disponíveis de Boston/Dallas/Chicago (perda de dados em produção). O bug foi reproduzido no DB local durante a auditoria (perda total dessas cidades) e só não chegou a produção porque nada foi deployado. | `AND v.city <> ?` + `v.id <> c.id`; só remove duplicados reais e variantes. Teste de regressão `test_city_normalization.py`. Simulação read-only em produção: 10 renomeações (`CHICAGO`→`Chicago`), **0 deleções**. |
| 2 | **Alta** | Filtro de bairro por ZIP usava `zip IN (...)` sem olhar ao bairro; linhas com **outro** bairro no mesmo ZIP entravam no filtro. | Contagem do bairro ≠ cartões do feed (ex.: NYC ZIP 10462: 200 vs 47). | Semântica exata que espelha o `GROUP BY`: `neighborhood IN (nomes) OR (neighborhood='' AND zip IN (zips))`. Testes + auditoria 32/32. |
| 3 | **Alta** | `Deadline only`, camada (Reactive/Works), tipo de proprietário e busca eram filtrados **só no cliente**. | Mapa mostrava 120 e cartões 17; números não correspondiam aos filtros. | Filtros movidos para SQL no feed (`/api/leads/today`) **e** na agregação (`/api/leads/neighborhoods`). Busca com debounce de 300 ms. |
| 4 | **Média** | `/api/leads/dashboard-summary` devolvia 500 com `updated_at` timezone-aware (`can't subtract offset-naive and offset-aware datetimes`). | KPIs do dashboard a zero. | Normalização para UTC-naive antes da subtração. |
| 5 | **Média** | Variante de cidade `CHICAGO` (10 linhas `import_b2b`) contava como cidade separada no `by_city`/picker. | Contagens duplicadas/subcontadas. | `canonical_city()` na escrita + migração idempotente (sem tocar em linhas canónicas). |
| 6 | **Baixa** | Índice `idx_leads_geo` criado antes das migrações de colunas → BD nova falhava no arranque. | Testes/novas instalações quebravam. | Criação movida para depois das migrações. |
| 7 | **Baixa** | BOM no ficheiro TS e função morta `zoneFilterPayload`. | Ruído/qualidade. | Removidos. |
| 8 | **Baixa** | Filtro "Private" do cliente incluía leads sem proprietário (desalinhado do servidor). | Contagens diferentes entre UI e SQL. | Cliente alinhado: private exige nome e não-institucional; unknown = sem nome. |

## 2. Qualidade do garimpo (produção)

- **Duplicados:** 0 por `(address, city)` e 0 por `(external_id, source_type)`.
- **Coordenadas:** 0 fora dos limites das 4 cidades.
- **Ingestão:** 4 runs `success` em 48h.
- **Feed:** 81.124 linhas `is_feed_ok=1`; 12.727 `is_junk=1`; 15.446 fechadas
  ficam fora do feed por `signal_status`; 216 sem `signal_type` também ficam
  fora (regra explícita do feed).
- **Categorias:** 2.647 `Unclassified` na janela de 7 dias (~18%) — lacuna de
  classificação, **não** erro de agregação. Não foi alterada nesta auditoria.
- **Prazos:** Boston 3.333/3.335 com SLA; Chicago/Dallas sem SLA na fonte.
- **Proprietários:** nome em 72–94% dos leads; **telefone 0%** porque a
  revelação é on-demand (por desenho); preventivo tem 0% de owner (gap de
  importação MA/OPSI e Dallas).

## 3. Cobertura geográfica usada no mapa

| Cidade | Bairro | ZIP | Geo |
|---|---|---|---|
| NYC | 96% (borough) | 99% | 99% |
| Boston | 95% | 100% | 95% |
| Chicago | 10% (community area) | 60% | 99,7% |
| Dallas | 0% | 85% | 14% |

Dallas usa os **centroides por ZIP** já derivados do snapshot preventivo quando
o lead não traz coordenadas. “Other areas” fica na lista e no filtro, mas fora
do mapa para não esticar o enquadramento.

## 4. Exatidão das contagens

**Produção (SQL, 7 dias):** 32 combinações cidade × filtro (all, Roof, deadline,
permit, reactive, owner unknown/private, search) — **32/32 OK**: a soma das
zonas é exatamente o total do feed; zero divergências por zona.

**UI autenticada (dashboard real):** 7/7 PASS
- Boston: lista (120) = painel (120) = feed (120).
- Deadline only: pedido enviado com `deadline_only=true` e painel = feed.
- Clique em Dorchester: feed = 17 = contagem da linha.
- NYC: lista (9.514) = painel = feed.

Pins e clusters são construídos a partir da mesma lista de zonas; o cluster soma
`opportunityCount` dos filhos. Nada é contado duas vezes: a agregação é um
`GROUP BY` sem joins, e cada linha pertence a exatamente um grupo (`nb`/`zip`/`none`).

## 5. Performance

| Cenário (produção) | Tempo médio |
|---|---|
| Boston, sem filtros | 19 ms |
| Boston, deadline only | 16 ms |
| Boston, owner private | 47 ms |
| Boston, busca | 21 ms |
| Dallas, camada permit | 15 ms |
| NYC, Roof | 14 ms |

Índice covering `idx_leads_geo` (is_feed_ok, city NOCASE, date_reported,
signal_type, lead_status, signal_status, reserved_by, neighborhood, zip_code,
lat, lng): sem ele a agregação custava ~97 ms. Criação no arranque ~2 s numa base
de 135k linhas.

## 6. Testes e verificação

- Suite backend completa: **1.688 passed / 1 skipped**.
- Nota: numa primeira execução, um teste de voz (`test_test_call_amd_machine_nao_desliga`)
  falhou por ordem/timing; passou isolado, no ficheiro (37/37) e na suite
  completa seguinte. É flake de teste, não regressão do produto.
- Novos testes: agregação geográfica, filtro exato por bairro/ZIP, deadline,
  proprietário, camada, busca e normalização de cidades (incluindo a regressão
  que apagava linhas canónicas).
- `ruff` limpo, `tsc --noEmit` limpo, ESLint **0 erros**.
- Scripts de auditoria versionados: `frontend/scripts/audit-map-ui.mjs` e os
  relatórios em `reports/`.

## 7. Índice de produção `idx_leads_geo` — validação

- **Idempotente por construção:** `CREATE INDEX IF NOT EXISTS` + verificação em
  `sqlite_master`; quando já existe, o caminho é um SELECT + log
  (`[DB] idx_leads_geo já existe (idempotente)`). Segunda execução medida:
  **0,3 ms**.
- **Ordem segura no arranque:** `DatabaseService()` chama `init_db()` no import
  do módulo, **antes** de o uvicorn aceitar pedidos. O índice é criado depois
  das migrações de colunas; não corre com tráfego da API nem com o scheduler
  (que só arranca no lifespan, depois).
- **Custo real** (cópia com as 135.951 linhas de produção, versão final do
  índice já com `created_at` para o agregado de frescos): **234,5 ms** de
  criação; índice **15,9 MB**; `quick_check` = `ok`.
- **Sem bloqueio de leitura:** leitor concorrente em WAL durante a criação —
  11 amostras, latência máxima **21,7 ms**. Escritor concorrente esperou
  **232,1 ms** e concluiu com sucesso (sem erro); no arranque não há escritores.
- **Espaço:** `/data` com **242 MB livres**; o índice ocupa 15,9 MB.
- **Retry:** até 3 tentativas com 1 s de intervalo se outra conexão estiver a
  escrever; uma falha é registada como warning e não derruba o arranque.
- **Migração de índice:** se existir um `idx_leads_geo` antigo (sem
  `created_at`), é removido e recriado uma única vez no arranque, antes de o
  servidor aceitar pedidos. `CREATE INDEX IF NOT EXISTS` mantém a segunda
  execução em **0,57 ms**.
- **Instância:** um único deployment Railway; com réplicas, `IF NOT EXISTS`
  mantém a operação segura.

## 8. SLO pós-deploy do mapa (<50 ms)

- Ambos os endpoints de mapa devolvem **`Server-Timing: db;dur=<ms>`**, medido
  em torno da agregação SQLite (sem rede/WAN).
- **Warm-up no arranque:** 2 passagens por cidade (Boston, NYC, Dallas, Chicago)
  com o gate de utilizador; log `[GEO] warmup <cidade> <ms>`.
- **Ligação de leitura reutilizada:** a agregação usa uma ligação SQLite
  persistente (protegida por lock) em vez de abrir/fechar uma por pedido. Isso
  removeu 20–60 ms de overhead por pedido no Windows e vários ms em Linux; em
  WAL cada `SELECT` vê o último commit.
- **Plano COVERING:** `SEARCH l USING COVERING INDEX idx_leads_geo
  (is_feed_ok=? AND city=? AND date_reported>?)`; o agregado de frescos não
  força lookups na tabela.
- **Query no tamanho de produção** (135.951 linhas, 7 dias): Boston 0,4 ms ·
  NYC 7,1 ms · Dallas 0,9 ms · Chicago 2,3 ms (média de 7 execuções).
- **Script:** `frontend/scripts/audit-map-ui.mjs --latency-only`
  - `AUDIT_API_URL` (default `http://127.0.0.1:8011`)
  - `AUDIT_TOKEN` (sessão com acesso ativo) · `AUDIT_MAX_MS` (default **50**)
  - 1 chamada de aquecimento + **3 medições** por cidade; falha em HTTP ≠200,
    payload inválido ou `db` ≥ 50 ms.
- **Resultado local (4/4 PASS, gate 50 ms):**

| Cidade | db min / mediana / max |
|---|---|
| Boston | 0,7 / 1,0 / 1,4 ms |
| NYC | 21,9 / 22,8 / 24,7 ms |
| Dallas | 0,8 / 0,9 / 1,4 ms |
| Chicago | 0,8 / 1,2 / 4,0 ms |

Produção tem mais folga ainda (a query é a mesma, com índice covering); correr
logo após o deploy e considerar **no-go** se qualquer cidade falhar. O modo
completo valida também lista = painel = feed, o clique no bairro, o destaque de
frescos (<24 h) e a agregação ao vivo do separador Pre-inspection.

## 9. Destaque de oportunidades frescas (<24 h)

- **Definição:** lead com `created_at` nas últimas 24 h. No preventivo conta
  também prazo de inspeção ≤3 dias (inclui vencidos).
- **Backend:** `get_leads_geo_summary` devolve `fresh` por grupo e
  `territories` devolve `fresh` por zona + `totals.fresh`.
- **Mapa:** pin e cluster âmbar com anel pulsante (`is-fresh`), mais um ponto
  no canto; `prefers-reduced-motion` desliga a animação.
- **Lista:** selo `NEW <n>` em cada bairro, chip `N NEW` no cabeçalho e
  toggle **New (<24h)** que mostra só zonas com frescos. Ordenação automática
  fresh-first (e o toggle "Nearest" continua disponível).
- **Pre-inspection ao vivo:** o painel deixou de usar o snapshot estático e
  passou a ler `GET /api/opportunities/territories` (com fallback ao snapshot
  se a API falhar). O snapshot continua a fornecer os centroides dos ZIPs.
- **Testes:** `test_leads_geo.py` (frescos por grupo) e
  `test_opportunity_territories.py` (frescos por zona/prazo). O
  `audit-map-ui.mjs` valida selo + pin + toggle nas duas abas.
- **Capturas:** `reports/opportunities-tab-preview/fresh-opportunities-boston.png`
  e `fresh-prevention-boston.png`.

## 10. Pendências de dados (não são bugs de código)

1. `Unclassified` (~18% dos leads) — melhorar o classificador numa fase própria,
   com revisão de amostras.
2. Telefones de proprietário 0% — por desenho (on-demand); não deve ser
   pré-carregado.
3. Preventivos sem owner — depende do importador OPSI/API MA e de fonte Dallas.
4. Chicago: ZIP em 60% e bairro em 10%; Dallas: geo em 14% (mitigado por
   centroides de ZIP).
5. Fornecedor de tiles (Esri) e CDN do Leaflet: dependência externa a documentar
   no runbook; CSP já permite os domínios.

## 11. Regra de ouro

Nenhuma sugestão de subida a produção foi feita. As correções só entram depois
desta auditoria verde; o deploy deve correr o índice e a migração de cidades
(idempotentes) e ser validado com os mesmos scripts de consistência.

## 12. Deploy de produção — 2026-11-15 (`7b2a0fd`)

- Merge **fast-forward** de `feat/territory-view-preview` em `master` e push
  `d103aac..7b2a0fd`; Railway deployment **SUCCESS**.
- **Arranque:** `[DB] idx_leads_geo criado em 789 ms` na primeira subida (base
  de 135.951 linhas, volume `/data`), seguido de `[GEO] warmup` Boston 32 ms ·
  NYC 25 ms · Dallas 2 ms · Chicago 5 ms. `idx_leads_geo` já existe
  (idempotente) nos restarts seguintes.
- **Runbook `--latency-only` (produção):**

| Cidade | db min / mediana / max |
|---|---|
| Boston | 1,8 / 1,8 / 2,5 ms |
| NYC | 23,3 / 24,7 / 26,6 ms |
| Dallas | 1,6 / 1,8 / 2,0 ms |
| Chicago | 4,4 / 6,5 / 7,6 ms |

- **Audit completo em `www.magicleads.app` (`ALL PASS`):** Boston lista = painel
  = feed **384**; Dorchester **58** no feed e na linha; deadline only **383**;
  NYC **9.703**; frescos com **17 selos** e **5 pins âmbar**; toggle liga e
  filtra; pedido `territories` do Pre-inspection presente.
- **Base de produção (leitura direta em `/data/leads.db`):**
  `idx_leads_geo` com `created_at` e plano **COVERING INDEX**; 135.951 leads;
  Boston 0,4 ms · NYC 9,5 ms (máx. 14,4) · Dallas 0,9 ms · Chicago 2,4 ms;
  `quick_check = ok`.
- **Observação:** a conta de demonstração `demo@magicleads.app` está com o
  plano expirado (“Access paused”). O gate `_require_active_access` devolve
  **402** em `territories`, por isso o painel Pre-inspection cai no snapshot
  (sem frescos) nessa conta. Clientes com acesso ativo recebem a agregação ao
  vivo, como validado localmente e no benchmark de produção. Renovar o plano
  demo (ou usar uma conta de validação dedicada) é uma decisão de produto.

## 13. Landing live map (preview, ainda não deployado)

- **Branch:** `feat/landing-live-map-preview` (sem push/deploy).
- **Endpoint público:** `GET /api/public/live-map` — agregado por zona, sem
  sessão, 60/min/IP, `Server-Timing`, `Cache-Control` e `ETag`/304.
- **Privacidade:** só contagens; zonas `<5` em `other`; `fresh` só `>=3`;
  centroides a 3 casas; sem ids/moradas/owners/telefones. O audit confirma a
  ausência de campos proibidos e a igualdade com o trade grid (Boston 176=176).
- **Índice parcial:** `idx_leads_public_geo` — **102,4 ms** de criação,
  **6,5 MB**, plano `SEARCH … USING INDEX … (city=? AND date_reported>?)`.
- **Produção (cópia de 135.951 linhas):** as 4 cidades numa query em
  **16,1 ms** (15,0–16,9 ms); cache in-process de 60 s → ≤1 cálculo/min.
- **Audit local `audit-landing-map.mjs`: ALL PASS** — endpoint 0,5–1,8 ms,
  mapa por defeito, **3 bolhas + 3 chips + “+N áreas”**, troca de cidade
  (Boston 176), separador By trade, teaser com “Dorchester · 26” e formulário
  em modo **Create account**.
- **Números e escopos (P0):** `Intl.NumberFormat` por locale — EN `7,788`,
  PT-BR `7.788`; o herói/mapa são da cidade selecionada e a faixa inferior
  identifica **“Todas as cidades”** (9.4xx global) para não parecer divergência.
- **Mapa e descoberta (P1):** top 3 bolhas + botão **“+N áreas”** expansível,
  legenda “New in the last 24h”, instrução em callout verde, e **um seletor
  de cidade por breakpoint** (cartão em desktop, chips do herói em mobile).
- **Copy (P2):** “novas oportunidades”, “oportunidades registradas”,
  “Do serviço pequeno à obra completa” e “Todas as cidades”; removidos
  “novas entradas” e “sinais na base”.
- **i18n (v2):** o prefixo da URL manda (`/en` abre EN mesmo com cookie PT);
  trocar a bandeira **navega** para `/pt`/`/es` preservando query/hash;
  `<html lang>` = `en-US`/`pt-BR`/`es-ES`. Copy PT do mapa/teaser em **PT-BR**
  (“Isso está acontecendo perto de você”, “endereços”, “contatos”).
- **Audit v2/v4:** valida instrução e seletor, top 3 + expansão, legenda,
  formatação por locale, escopos, `/en` com cookie PT, navegação da bandeira,
  `lang` e ausência de PT-PT no teaser, mobile e kill switch — **ALL PASS**.
- **Stacking (v3):** o mapa está isolado (`relative isolate z-0` +
  `isolation: isolate`); o header da landing passou a `z-[900]`, acima das
  camadas Leaflet e abaixo do modal (`z-[1000]`). O audit faz scroll e
  hit-test: navbar, bandeira e CTA ficam por cima (`header=true flag=true
  cta=true`).
- **Kill switch:** `PUBLIC_LIVE_MAP_ENABLED=0` → 503 `live_map_disabled`; o
  frontend esconde a aba Map e mantém “By trade”.
- **Capturas:** `reports/landing-live-map-preview/01-hero-map.png`,
  `01b-hero-areas.png`, `02-hero-trades.png`, `03-teaser-modal.png`,
  `04-locale-en.png`, `05-locale-pt-teaser.png`, `06-scroll-navbar.png`,
  `07-mobile-map.png`.
- **Plano completo:** `docs/LANDING-LIVE-MAP-PLAN.md`.
