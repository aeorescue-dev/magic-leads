# Performance do dashboard — auditoria e Fase 22

Data: 2026-11-01 · âmbito: `/pt/dashboard` (Visão geral) e `/dashboard/leads`.

## Sintoma

Refresh e troca de abas levavam **5–10 s** para mostrar dados. A UI ficava em
“Coletando dados…” / “0 oportunidades”.

## Medições (produção, read-only)

### HTTP público (p50 de 5, desta máquina)

| Endpoint | p50 |
|---|---|
| `/health` (baseline de rede) | 103 ms |
| `/api/metrics/public` | 102 ms |
| `/api/leads/stats` | 81 ms |
| `/api/leads/cities-with-counts` (código morto) | **1 211 ms** |
| `/api/scraper/status` | 42 ms |
| `/pt/dashboard` (HTML) | 231 ms |

### Queries reais (in-process, só leitura)

| Chamada | p50 |
|---|---|
| **`get_leads_feed` (total + página)** | **555 ms** (258 + 297); **3 074 ms a frio** |
| `get_stats` | 45 ms |
| `get_public_metrics` | 51 ms |
| `get_dashboard_summary` | 0 ms (cache 45 s; 41 ms frio) |
| `count_leads_by_interests` | 125 ms |
| `daily-stats`, `subscription`, `notifications`, `interests`, `contractor-metrics` | ≤1 ms |

Universo: 106 785 leads · 18 728 nos últimos 7 dias · 13 073 qualificados.

## Causas

1. **Filtro de ruído não indexável** (`_junk_where`, `db.py:66-72`): 20 ×
   `LIKE '%termo%'` sobre 5 colunas concatenadas — avaliado em cada linha.
2. **Qualificação não materializada** (`_qualified_where`): `LENGTH(TRIM(address))`
   e `OR` de gatilhos impedem índice.
3. **Planner**: `idx_leads_category` + `USE TEMP B-TREE FOR ORDER BY` sobre 13 mil
   linhas, em vez de percorrer `date_reported` e parar às 60.
4. **Duas passagens** por pedido (`COUNT` + `SELECT`).
5. **Frontend sem cache**: 12 pedidos por montagem, `Promise.all` bloqueado pelo
   feed, `/me` + subscription sequenciais, polling de 30 s mesmo com aba oculta.

## Correção (Fase 22, backend)

- Colunas materializadas `is_junk`, `is_feed_ok` (endereço+categoria+não-ruído) e
  `is_qualified` (acrescenta o gatilho), recalculadas na escrita
  (`insert_lead`, `update_lead_historical`, `update_lead_freshness`) e no
  arranque (backfill só de linhas NULL).
- Índices: `(is_feed_ok, date_reported DESC, id DESC)`,
  `(is_qualified, date_reported DESC, id DESC)` e
  `(is_qualified, city, issue_category)`.
- `get_leads_feed`, `count_qualified_contractors_in_city` e
  `get_dashboard_summary` passam a ler as colunas.
- Cache in-process de **60 s** para `get_stats` e `get_public_metrics`,
  invalidado no fim de cada run de ingestão.
- `/api/users/{id}/daily-stats` deixa de correr `expire_holds` e
  `check_reveal_watchdogs` (eram escritas a cada poll de 60 s; continuam no
  watchdog de 15 min e no cron).

## Prova (benchmark numa cópia da base, já eliminada)

| Cenário | COUNT | Página |
|---|---|---|
| Atual | 258 ms | 297 ms |
| `is_junk` + índice | 92 ms | 87 ms |
| **`is_qualified` + índice composto** | **13 ms** | **0,4 ms** |

Migração/backfill medido na cópia: ~2 s para 106 785 linhas.

## Paridade

`tests/test_leads_quality_materialized.py` compara, nos dois sentidos, o conjunto
de ids das colunas materializadas com `_qualified_where`/`_feed_where`, cobre
casos (lixo, morada curta, categoria fora, fechado, legado sem `signal_type`) e
verifica que a escrita recalcula. A verificação pós-deploy compara as contagens
em produção.

## 7. Fase 23 — frontend (cache, auth global, ondas)

Implementado com SWR 2.5.1:

- **AuthProvider** no layout do locale: `/me` + `/subscription-status` uma vez
  por sessão de app (antes: em cada página montada). O provider persiste entre
  navegações; login, passkey e demo atualizam o estado.
- **SWRConfig** no layout do dashboard: cache sobrevive à troca de rota
  (`stale-while-revalidate`), `keepPreviousData`, dedupe e polling pausado com
  a aba oculta.
- **Onda 1** = feed (`/api/leads/today`) é a única que bloqueia a lista;
  **onda 2** = stats, resumo, scraper e métricas públicas, com keys fixas —
  mudar filtros refaz só o feed.
- `router.prefetch()` no hover/focus de Configurações e do botão de voltar;
  links passaram a incluir o locale (evita o salto de redirect).

### Medições no browser (demo login, produção, 3 ciclos)

| Métrica | Antes (Fase 22) | Depois (Fase 23) | Ganho |
|---|---|---|---|
| Dashboard → Configurações | 733 ms (321–978) | **78 ms** (58–99) | 9,4× |
| Configurações → Dashboard (shell) | 522 ms (324–1 028) | **55 ms** (40–73) | 9,5× |
| Configurações → Dashboard (dados prontos) | 1 227 ms (1 124–1 310) | **118 ms** (98–146) | 10,4× |
| `/me` + `subscription` por transição | 2 chamadas | **0** (1 no load) | — |
| Feed em 6 transições | 1 por montagem | 1 (resto cache) | — |
| LCP (hard load) | ~1 140 ms | **428 ms** (240–928) | ~2,7× |
| CLS | 0,013 | **0,001** | — |

Sem erros de consola em `/pt`, `/pt/dashboard`,
`/pt/dashboard/settings` e `/pt/auth`.

## Veredicto

**Backend (Fase 22):** feed de 555 ms → **15 ms** (página 0,4 ms, total 13 ms),
com paridade exata nas 78 112 linhas qualificadas e 94 369 do feed.

**Frontend (Fase 23):** troca de rota de 733/1 227 ms → **78/118 ms**, com o
cache a pintar de imediato e a revalidação em background. Nenhum pedido de
`/me` ou subscription por transição.

