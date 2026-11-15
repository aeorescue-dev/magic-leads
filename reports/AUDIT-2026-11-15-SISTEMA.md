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

## 7. Pendências de dados (não são bugs de código)

1. `Unclassified` (~18% dos leads) — melhorar o classificador numa fase própria,
   com revisão de amostras.
2. Telefones de proprietário 0% — por desenho (on-demand); não deve ser
   pré-carregado.
3. Preventivos sem owner — depende do importador OPSI/API MA e de fonte Dallas.
4. Chicago: ZIP em 60% e bairro em 10%; Dallas: geo em 14% (mitigado por
   centroides de ZIP).
5. Fornecedor de tiles (Esri) e CDN do Leaflet: dependência externa a documentar
   no runbook; CSP já permite os domínios.

## 8. Regra de ouro

Nenhuma sugestão de subida a produção foi feita. As correções só entram depois
desta auditoria verde; o deploy deve correr o índice e a migração de cidades
(idempotentes) e ser validado com os mesmos scripts de consistência.
