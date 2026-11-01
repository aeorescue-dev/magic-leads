# Ingestão & Enriquecimento — saúde operacional

Correções da auditoria de 01/11/2026 (P0/P1). Este documento é o runbook: o que
muda, porquê e como verificar.

## 1. Cadência da ingestão (P0)

Antes: `_scheduler_loop` fazia `sleep(6h)` **depois** do boot. Cada deploy
reiniciava o processo e o relógio; a ingestão ficou 8h18 parada em 01/11 e o
run das 18:17 do GitHub Actions não existiu.

Agora (`backend/main.py`):

- O scheduler lê o último run **bem-sucedido** (`success`/`partial`) da tabela
  `scraper_runs` e calcula o próximo slot por relógio.
- Se o slot já passou (deploy/OOM), dispara **imediatamente** em vez de esperar
  6h. Um run falhado pode ser retentado após `SCRAPER_RETRY_MINUTES` (30 min),
  mas nunca em paralelo.
- `_run_scrape_guarded` grava a linha `running` **no arranque**; um deploy a
  meio do run deixa rasto na BD (e `mark_stale_scraper_runs` fecha-o no boot).
- Acorda no máximo a cada 15 min para reavaliar o relógio.
- O webhook passa a receber o `trigger` real (`scheduler`/`watchdog`/`manual`).

Verificação:

```sql
SELECT run_id, trigger, status, inserted, started_at, finished_at
FROM scraper_runs ORDER BY id DESC LIMIT 5;
```

## 2. Watchdog de frescura (P0)

`_run_scrape_watchdog()` corre a cada `SCRAPER_WATCHDOG_INTERVAL_MIN` (30 min).
Critérios (todos viram `system_alerts`):

| Código | Condição | Limiar |
|---|---|---|
| `SCRAPER_CITY_STALE:<CIDADE>` | `MAX(date_reported)` da cidade | > 24h (`SCRAPER_STALE_HOURS`) |
| `SCRAPER_ZERO_INSERTS` | runs concluídos consecutivos com `inserted=0` | ≥ 2 |
| `SCRAPER_CITY_ZERO_INSERTS:<CIDADE>` | anomalia por cidade (inseridos, não raw) | ≥ 2 runs |
| `SCRAPER_OVERDUE` | nenhum run iniciado | intervalo × 1,75 (~10,5h) |

- Alertas deduplicados por código/cidade durante 6h.
- Se houver problema e nenhum run ativo, força uma recolha, no máximo a cada 3h
  (`SCRAPER_WATCHDOG_FORCE_MIN_HOURS`). Um run `running` recente (BD ou
  memória) nunca é duplicado.
- A anomalia por cidade passou a usar `inserted_by_city`, não `len(leads)`:
  um run com 11.690 raw todos duplicados já não fica verde.

## 3. Moradas de Boston (P0)

O `location` do 311 já traz bairro/estado/ZIP (`"2 Columbus Ave  Boston  MA
02116"`). O pipeline antigo acrescentava `, Boston, MA`, corrompendo
10.095/10.097 moradas e impedindo o owner enrichment.

- `backend/services/boston_address.py`
  - `clean_boston_location(location, fallback_zip)` → `(rua, zip5)`.
  - `parcel_match_key(full_address)` → `(número, rua)` **sem unidade**:
    `"526 COLUMBUS AV 2"` → `("526", "COLUMBUS AV")`;
    `"107 -109 SAVIN HILL AV 1"` → `("107-109", "SAVIN HILL AV")`.
- A ingestão grava a rua limpa; cidade/estado/ZIP ficam nas colunas próprias.
- `normalize_street` passou a mapear `AV` → `AVE` (o parcel dataset usa `AV`).
- `_lookup_ckan` usa **filtros exactos** `ST_NUM`+`ST_NAME` (o `q` do CKAN
  é OR: `"132 bernard"` devolve 132 Beaver e o número certo raramente entra no
  top). Fallbacks: `ST_NAME` só (ordenado por `ST_NUM`, 500 linhas) para
  intervalos/unidades, e por fim `q`.
- Números/intervalos casam por sobreposição (`970` ↔ `980 970`,
  `81-83` ↔ `81 83`); em condomínios prefere-se a linha sem unidade (dono do
  edifício). A rua é normalizada antes do dispatch (`Savin Hill Ave` →
  `SAVIN HILL AVE`), porque os filtros e o dataset são maiúsculos.
- Backfill idempotente: `python -m backend.scripts.backfill_boston`
  (moradas + owners do parcel dataset + `enrich_enabled=1`).

Residual conhecido: ~1.000 linhas duplicadas do mesmo imóvel em que o
`UPDATE` da morada colide com a linha canónica (índice único `address+city`).
O owner é preenchido na mesma; a fusão segura (re-parent de
`lead_case_history`/referências + delete) fica para fase própria — nunca
apagar leads sem esse merge.

Medição (01/11/2026): 7.705 moradas normalizadas; owners de Boston
**4.404 → 7.798** (77,2%); 2.301 sem owner, dos quais 1.054 são interseções
(não são imóveis enriquecíveis) e ~1.001 são os duplicados acima (a linha
canónica já tem owner).

## 4. Quotas de descoberta (P1)

Orçamento Brave é global; as 750 entidades/cidade/dia esgotavam-no na primeira
hora e queimavam as 2 tentativas de 24k entidades.

- `domain_per_city_day(enabled)` = `BRAVE_DAILY_QUERIES // cidades_activas`
  (250/4 = 62, hoje). Override: `ENRICH_DOMAIN_PER_CITY_DAY`.
- `city_enrichment_state.domain_jobs_today` mede a quota separada (e reseta no
  dia operacional de Nova Iorque).
- Sem orçamento (`brave_search.budget_left() == 0`), o estágio de domínio nem é
  listado; `_domain_stage` devolve `deferred` **sem** marcar tentativa. O
  estágio de e-mail (SMTP, gratuito) continua.

## 5. Backfill de owners (P1)

`backend/services/owner_backfill.py`, em processo:

- Leads reais com `owner_name` vazio (exclui `B2B contact%`).
- Cursor descendente por `id`, wrap-around ao chegar ao início.
- Quota `OWNER_BACKFILL_PER_CITY_DAY` (200) por cidade/dia; lote de 25 com
  1 s entre lookups.
- Falha de API não aborta o lote; o cursor avança e a próxima volta retenta.
- Estado em `owner_backfill_state` (dia, jobs, cursor).

## 6. Variáveis novas

```
SCRAPER_RETRY_MINUTES=30
SCRAPER_WATCHDOG_ENABLED=1
SCRAPER_WATCHDOG_INTERVAL_MIN=30
SCRAPER_STALE_HOURS=24
SCRAPER_WATCHDOG_FORCE_MIN_HOURS=3
SCRAPER_ALERT_DEDUPE_HOURS=6
OWNER_BACKFILL_ENABLED=1
OWNER_BACKFILL_PER_CITY_DAY=200
OWNER_BACKFILL_INTERVAL_HOURS=3
ENRICH_DOMAIN_PER_CITY_DAY=        # vazio = derivar do Brave
```

## 7. Verificação

```bash
pytest tests/ -q
cd backend && ruff check . --select=E,F,W,I --ignore=E501
```

Testes de regressão: `tests/test_boston_address.py`,
`tests/test_scrape_guard.py`, `tests/test_enrichment_quota.py`,
`tests/test_owner_backfill.py`.
