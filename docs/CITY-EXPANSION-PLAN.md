# Prioridade C — Plano de Expansão Geográfica

> Estado: **investigação concluída, nada implementado**. Este documento é o
> mapa do que tem de ser tocado para adicionar cidades, e a ordem
> recommended para o fazer sem quebrar nada.

---

## 0. ⚠️ Actualização 2026-10-21 — auditoria empírica que mudou a conclusão

Medi com o **fetcher real** e a **heurística real de colunas** (`_guess_columns`)
contra o catálogo nacional da Socrata. Resultados que contrariam o plano original:

### 0.1 Os ~90 datasets "por categoria" são ARQUIVOS MORTOS

| Dataset | Último registo |
|---|---|
| CUNY HPD paint/plaster · HPD general constr · sewer | **2012-03 / 2014-03** |
| CUNY rodent · industrial waste | 2019-07 / 2019-08 |
| CUNY asbestos · dirty sidewalk · HPD heat/hot water | 2021-09 / 2022-03 / 2020-11 |
| CHI sanitation code · rodent baiting · pot holes · tree debris · graffiti · tree trims | **2018-12-18** |
| CHI abandoned vehicles | 2020-07-23 |
| DAL code violations | 2018-07-31 |
| **CUNY (todos)** · **Kansas City (todos)** | **0 datasets LIVE** |

> **Ligá-los produziria ZERO leads novos.** Uma obra de 2014 não é uma
> oportunidade de hoje. O plano original tratava estes datasets como
> multiplicador de produção — **está errado**, e o teste empírico apanhou-o
> antes de qualquer código ser escrito.

### 0.2 O que é LIVE (e o que isso nos dá)

| Domínio | LIVE | Notas |
|---|---:|---|
| `data.cityofnewyork.us` | 311 (erm2-nwe9), HPD (wvxf-dwi5) + **DOB ECB** (6bgk-3dad) | DOB ECB: endereço é o do *respondente* (Caixa de Correio) → **não usado** |
| `data.cityofchicago.org` | 311 (v6vf-nfxy) + **Building Permits** (ydr8-5enu) | ✅ **activado** |
| `www.dallasopendata.com` | 311 (d7e7-envw, 4n3h-rfqm) | 4n3h tem `lat_long_location`; d7e7 tem `lat_location` |
| `data.lacity.org` | **3 datasets de permits LIVE** (building/electrical/mechanical) | ⚠️ LA é cidade nova — ver §5 |
| `bronx.lehman.cuny.edu` | **0** | mirror estático |
| `data.kcmo.org` | **0** | 311 existe mas parado em 2018 |

**Nenhuma outra cidade dos EUA testadas** (~60) tem 311/permits na Socrata:
Filadélfia, Houston, Phoenix, Atlanta, Miami, Seattle, LA(311), Denver, Austin,
San Antonio, DC, Baltimore, Charlotte, Nashville, Portland, Minneapolis,
Cleveland, St. Louis, Pittsburgh, New Orleans, Vegas, Tucson, Fresno, Omaha,
Albuquerque, El Paso, Jacksonville, Memphis, Louisville, Richmond, Buffalo,
Columbus, Indianapolis, Tulsa, OKC, Rochester, Hartford, Providence, Raleigh,
Norfolk, Fort Worth, San José, San Diego.
→ O portal deles é **ArcGIS/outros** (`data.phila.gov` → 404, `data.seattle.gov`
→ 0 datasets). **Exigem um transportador novo.**

### 0.3 O gargalo real: o filtro de ofício, não as cidades

Medido com o fetcher real (mesmo dataset, filtro antigo vs. novo):

| Fonte | Endereços novos (filtro antigo) | (filtro por ofício) |
|---|---:|---:|
| Dallas | 8 | **1.358** |
| NYC | 1.037 | **4.273** |
| Chicago | 100 | **2.750** |

O filtro antigo (lista `SCRAPER_KEYWORDS` sobre a descrição) descartava
ofícios **REAIS** cuja redação não bate com a lista: 156 PLUMBING + 16 GRASS +
14 RODENT por ciclo em Dallas, 113 PLUMBING em NYC. → **Corrigido** (filtro por
categoria de ofício, com fallback genérico = ruído).

### 0.4 O multiplicador de 10x (janela de fetch) — medido, **ainda não implementado**

| Fonte | Janela actual (48-96h) | Janela 7 dias | Tempo de fetch |
|---|---:|---:|---:|
| NYC 311 | ~1.037 | **11.170** | 19,6s |
| CHI 311 | 100 | **1.081** | 27,8s |
| DAL 311 | 8 | **574** | 2,8s |

O fetch é barato (≈50s no total), mas o volume de escrita na BD cresce ~30x —
**exige um desenho de backfill** (scrape profundo nocturno vs. incremental de
6h) antes de ser seguro. Fica como **fase 2 do Movimento #1**.

---

## 1. Estado actual

| | |
|---|---|
| Cidades servidas | `NYC`, `CHICAGO`, `DALLAS`, `BOSTON` (`db.py:811`) |
| Cidades do scraper | as mesmas 4 (7 "entries": 2×NYC-311, NYC-HPD, Chicago-311, Dallas-311, Boston-CKAN, NYC-DOB violations, NYC-DOB permits) |
| Leads qualificados | 66.371 (NYC 25.237 / CHI 17.725 / DAL 14.024 / BOS 9.385) |
| Suporte a NJ/Tri-State | **Inexistente** (0 ocorrências de NEWARK/JERSEY/HOBOKEN/TRI-STATE) |

⚠️ **Decisão de produto pendente:** o NJ/Tri-State é o pedido explícito, mas
**Newark e Jersey City não têm fonte 311 pública comparável à do NYC**. Sem
uma fonte com **categoria de obra + estado de chamado**, os leads nunca passam
`_qualified_where` e a cidade fica contada nas métricas sem ter leads
utilizáveis — exactamente o que aconteceu com Norfolk (removido, ver
`db.py:806-810`). A alternativa de maior valor é entrar pelo **condado**
(Essex County) ou procurar a fonte 311 municipal correcta.

---

## 2. Anatomia da expansão (o que há de verdade)

Não existe um ficheiro de configuração central de cidades. A config está
distribuída por 6 sítios:

| Config | Ficheiro:linha | Formato |
|---|---|---|
| Cidades "servidas" (copy/métricas/outbound) | `db.py:811` | tupla Python |
| Fontes de scraping | `main.py:2275-2296` | lista de dicts **inline na função** |
| Datasets de *owner* (enriquecimento) | `enrichment.py:48-111` | dict de dicts |
| Aliases de cidade | `enrichment.py:30-45` | dict |
| Display/State para e-mails | `outbound_templates.py:340-352` | dicts |
| Saúde do scraper | `city_health` (SQLite) | 1 linha por cidade |

### 2.1 O gate real: qualidade do lead, não o scraping

`db.py:145-154` — `_qualified_where` = endereço + categoria dos 16 ofícios +
gatilho preditivo. Sem **categoria de obra** ou **estado de chamado**, o lead
nunca é qualificado (caso Norfolk). Por isso, para cada cidade nova é
obrigatório validar com dados reais antes de a anunciar.

### 2.2 O que NÃO precisa de ser tocado (dinâmico)

- `/api/metrics/public`, `/api/leads/cities`, `/api/leads/cities-with-counts`
- `/api/admin/outbound/config` → `cities` (o selector do admin é automático)
- `HeroSection` (nº de cidades), `outbound_engine.status()`
- Rotas Next.js: **não existem rotas por cidade** — a cidade é sempre filtro.

---

## 3. Checklist para adicionar 1 cidade

### 3.1 Bloqueios de CI (2 linhas, obrigatório)

| Ficheiro | Linha | O que fazer |
|---|---|---|
| `tests/test_nyc_pipeline.py` | 222 | `assert set(SERVED_CITIES) == {...}` → parametrizar |
| `tests/test_admin_panel.py` | 651 | `assert body["cities"] == [...]` → parametrizar |

### 3.2 Backend — scraping (obrigatório)

| Ficheiro | Linha | O que fazer |
|---|---|---|
| `backend/main.py` | 2275-2296 | **+1 entry** em `base_cities`: `domain`, `dataset`, `city`, `state`, `hours`, `limit`, `fields` |
| `backend/main.py` | 2547-2619 | Branch dedicado **só se** a fonte não for Socrata (Boston é CKAN) |
| `backend/services/enrichment.py` | 48-111 | **+1 entry** em `CITY_DATASETS` (dataset de *property tax* / owner + colunas) — **sem isto não há `owner_name` → lead não é vendável** |
| `backend/services/enrichment.py` | 30-45 | Aliases (`"NEWARK": "NEWARK"`, etc.) — respeitar `test_todo_alias_aponta_para_uma_cidade_existente` |
| `backend/services/outbound_templates.py` | 340-352 | `CITY_DISPLAY` + `CITY_STATE` (sem isto: `city.title()` e `state=""`) |
| `backend/services/db.py` | 811 | **+1 cidade** em `SERVED_CITIES` (UPPERCASE) |

### 3.3 Frontend — produto (se a cidade for visível ao cliente)

| Ficheiro | Linha | O que fazer |
|---|---|---|
| `frontend/app/[locale]/(dashboard)/dashboard/page.tsx` | 240, 1932 | Array `CITIES` / `allCities` |
| `frontend/app/[locale]/(dashboard)/dashboard/page.tsx` | 1160-1168 | `normalizeCity` (mapa de variações de nome) |
| `frontend/components/LiveLeadsSection.tsx` | 12-18 | `getLocationTag` (tag "NEWARK, NJ") |
| `frontend/app/[locale]/(marketing)/page.tsx` | 14, 18, 35-56 | `type City` + `CITIES` + `SAMPLE_LEADS` (**o TS exige uma entrada por cidade no `Record<City, ...>`**) |
| `frontend/components/landing/LandingShell.tsx` | 187 | String do footer |
| `frontend/lib/i18n.tsx` | PT 121/131/215/769/926 · EN 1263/1273/1355/1899/2050 · ES 2388/2398/2480/3024/3175 | Copy de pricing / FAQ / hero — **×3 idiomas** |

### 3.4 Operação

| Ficheiro | Linha | O que fazer |
|---|---|---|
| `scripts/run_enrich_all.py` | 111 | `--cities` default → incluir a nova cidade |
| `backend/services/skip_trace.py` | 46 | Fonte de telefone DOB é só NYC; as novas cidades dependem do Searchbug pago |
| `DOSSIE-INVESTIDORES-MAGIC-LEADS.md` | 40, 56, 185… | Afirma "4 cidades" — actualizar |

---

## 4. Armadilhas verificadas (importante)

1. **`max_cities` é um parâmetro MORTO** (`main.py:2260` — nunca é lido no
   corpo da função). Cada cidade nova = **1 fetch HTTP sequencial extra por
   run**, sempre. O poll do GitHub Actions dá 55 min
   (`.github/workflows/scraper.yml:54`) e o timeout é 60 min (`:18`).
   → **Com 10+ cidades, o scraping passa a falhar por timeout.** É preciso
   paralelizar os fetches ou dividir por workflow.
2. **Grafia inconsistente da cidade**: `SERVED_CITIES` é UPPERCASE; a BD
   grava mixed case (`Chicago`, `Dallas`, `Boston`). `get_public_metrics`
   compensa com `UPPER(TRIM(city))` (`db.py:5274`), mas
   `alert_planner._city_allows` faz match **exacto** (`alert_planner.py:59`) e
   o `outbound_config` é uppercase. → Fixar a mesma grafia em todo o lado.
3. **Matching por substring** em `enrichment._config_for` (`enrichment.py:211-219`):
   `alias in city_upper`. Nomes contidos noutros podem colidir.
4. **`bbl_col` é exclusivo de NYC** por teste (`test_nyc_pipeline.py:238-241`).
   Datasets de NJ/Chicago usam `block`/`lot`.
5. **O `if city == "Boston"` (`main.py:2548`) é um `if` independente**, não
   `elif` — funciona por acidente. Não copiar o padrão.
6. **`SOCRATA_DOMAINS` (`config.py:58-62`) é config morta** — nunca é lida.
7. **A qualidade é o gate, não o scraping**: anunciar uma cidade sem leads
   qualificados é pior do que não a anunciar (foi o erro do Norfolk).

---

## 5. Ordem de execução recomendada

### Fase 1 — Instrumentar (sem novas cidades)
1. Parametrizar os 2 testes que bloqueiam (`test_nyc_pipeline.py:222`,
   `test_admin_panel.py:651`) — para que a expansão não quebre a CI.
2. Corrigir o `max_cities` (usá-lo de facto) ou paralelizar os fetches.
3. Extrair `base_cities` de `main.py:2275` para um ficheiro de config
   próprio (`backend/config/cities.py`) — é a mudança que torna a 2.ª cidade
   barata.

### Fase 2 — Cidades de maior densidade (as 4 primeiras)
Critério: fonte 311 **pública** com categoria de obra, **+** dataset de
property-tax para o owner, **+** volume comprovado.

Ordem sugerida (volume de construção + disponibilidade de dados):
1. **Philadelphia, PA** — 311 público (Socrata), grande volume.
2. **Houston, TX** — 311 público, Texas já coberto (Dallas).
3. **Phoenix, AZ** — volume enorme, clima = obra contínua.
4. **San Antonio / Austin, TX** —能与 Dallas reaproveitar o dataset de owner?

### Fase 3 — Tri-State / New Jersey
Requer **primeiro** identificar a fonte. Candidatos a investigar:
- `data.newarknj.gov` (Newark 311), `data.jerseycitynj.gov`
- Essex County property records (NJ não tem PLUTO; usa `block`/`lot`)
- A alternativa de maior valor: **New York + Newark num único anúncio
  "Tri-State"**, porque o contractor de NYC já trabalha em NJ (Brooklyn e
  Manhattan contractors fazem obras em NJ) — o valor comercial está no
  cruzamento, não na cidade isolada.

### Fase 4 — Validação antes de anunciar
Para cada cidade nova, antes de a meter no `SERVED_CITIES`:
1. Correr o scraper 3-5 dias e medir: nº de leads, % qualificados,
   % com `owner_name` resolvido, duplicados.
2. Só anunciar se `qualificados > 0` e `owner_name` acima de ~60%.
3. Actualizar `city_health` e o `DOSSIE-INVESTIDORES`.

---

## 6. Impacto no objectivo comercial

O motor de email precisa de **volume de leads por cidade** para encontrar
contratores endereçáveis. Com 4 cidades, o pool de 66k leads é grande mas
concentrado. Com 8-10 cidades:

| | 4 cidades | 10 cidades |
|---|---|---|
| Leads qualificados | 66.371 | ~160.000-200.000 |
| Pool de e-mails encontráveis (estimativa) | limitado | 3-4x maior |
| Clientes alcançáveis (a 1 e-mail/dia, 1 caixa) | ~1-2 | ~5-8 |
| Clientes alcançáveis (5 caixas @25/dia) | ~10-15 | ~40-60 |

**A expansão de cidades é o multiplicador do canal de email** — mais
efectiva do que mais caixas, porque cada caixa nova é uma rampa de 14 dias
enquanto as cidades are o feedstock imediato.
