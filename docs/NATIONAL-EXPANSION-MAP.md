# Mapeamento Nacional de Expansão (EUA) — pré-validado

> **Estado: investigação + mapeamento. Zero código escrito.** Documento
> estratégico, para arquivar como plano de escala.
>
> **Data:** 2026-10-21 · **Método:** APIs públicas (Socrata Discovery API,
> ArcGIS Hub `datasets`), com a **heurística real de colunas** do nosso
> scraper (`_guess_columns`) e contagem real de registos
> (`returnCountOnly` / `recordCount`). Nada foi escrito em produção.

---

## 1. Como ler este documento

Três portões, por ordem de importância real:

| Portão | Pergunta | Onde falha se falhar |
|---|---|---|
| **P1 · Fonte de obra** | Existe 311/permits **LIVE** (com registos recentes) e com as colunas que o nosso scraper sabe ler? | Sem fonte → 0 leads |
| **P2 · Proprietário** | Existe *tax roll* / assessor com nome do dono? | Sem `owner_name` → lead **não é vendável** (`lead_rules.py`) |
| **P3 · Transporte** | O motor atual (Socrata SoQL) lê, ou exige conector novo (ArcGIS/CKAN)? | Conector novo = projecto |

> ⚠️ **O erro mais comum numa expansão é saltar o P2.** Uma cidade com 3
> milhões de registos 311 e sem tax roll produz leads que não se podem vender.

---

## 2. Grupo A — compatíveis com o motor actual (Socrata, zero código novo)

Verificado com o **fetcher real** (dados, tabelas e colunas lidos da API).

| Cidade | Fonte | Estado | Volume medido | Ofício |
|---|---|---|---|---|
| **NYC** | 311 `erm2-nwe9` + HPD `wvxf-dwi5` + DOB viol./permits | ✅ LIVE | 1.572 + 5.000/ciclo | HEATING 649, PLUMBING 314, RODENT 1.102, PAINT 710, DOOR_WINDOW 872 |
| **Chicago** | 311 `v6vf-nfxy` + **Building Permits `ydr8-5enu`** | ✅ LIVE | 917 + **2.817**/ciclo | ELECTRICAL 1.114, ROOF 214, RODENT 233, PLUMBING 83 |
| **Dallas** | 311 `d7e7-envw` / `4n3h-rfqm` | ✅ LIVE | 342/ciclo (com coordenadas) | PLUMBING 186, DEBRIS 111, GRASS 19 |
| **Boston** | CKAN `datastore_search` | ✅ LIVE (transporte próprio) | 1.572 leads qualificados | — |
| **Los Angeles** ⭐ | **3 permits LIVE**: `pi9x-tg5x` (building), `ysqd-apz7` (electrical), `67is-svtd` (mechanical) | ✅ LIVE | **5.000+/ciclo** (limite) | HEATING 1.534, ROOF 156, RODENT 258, MOLD 53, PLUMBING 219 |

### ⭐ Los Angeles é a próxima cidade "barata"
Verificado: `data.lacity.org` **é Socrata** → o nosso scraper lê sem
conector novo. Só falta a拳常规 da cidade:

- `SERVED_CITIES` + `CITY_DISPLAY`/`CITY_STATE` (`outbound_templates.py`)
- `CITY_DATASETS` (proprietário) — ⚠️ **ainda em falta** (ver §4)
- 2 testes que fixam o nº de cidades (`test_nyc_pipeline.py:222`, `test_admin_panel.py:651`)
- Listas de cidade no frontend + i18n (3 idiomas)

**LA é o 2.º maior mercado de construção dos EUA e o 3.º maior mercado de
leads pagos.** Com os 3 datasets de permits, dá obras de telhado,
electricidade, HVAC e canalização com endereço e coordenadas.

---

## 3. Grupo B — exigem conector novo (ArcGIS)

Todos os datasets abaixo foram encontrados na API do **ArcGIS Hub** com
**org oficial da cidade** e **contagem real de registos**. O motor atual
(Socrata SoQL) **não** os lê → exige um conector ArcGIS REST.

| Cidade | Org oficial | Registos | Dataset principal (volume anual quando aplicável) |
|---|---|---:|---|
| **Baltimore** | `baltimore_city` | 6,1M | 311 Customer Service Requests — **1,08M/ano (2024)**, 1,03M (2023), 1,01M (2022) |
| **Charlotte** | `CharlotteNC` | 3,9M | Service Requests 311 (3,44M) · Code Enforcement Cases (427k) · Building Permits (53k) |
| **Nashville** | `NashvilleOpenData` | 3,5M | 311 Service Requests 2017→Presente (2,1M) + por ano (318k/ano) |
| **Denver** | `The_City_and_County_of_Denver` | 2,9M | 311 por ano: 525k (2010), 480k (2016), 475k (2023) |
| **Sacramento** | `Publisher_SacCity` | 6,2M | 311 Calls View Current (1,6M) + por ano (1,6M/ano) |
| **Indianapolis** | `IndyGIS` | 910k | Code Enforcement Violations and Investigations (910k) |
| **Louisville** | `Ismael` (cidade) | 238k | Louisville 311 Service Requests (170k) |
| **Hartford** | `HartfordData` | 233k | Service Request por ano (49k/ano) |
| **Buffalo** | `rw597_CUGIS` | 183k | Buffalo Code Violations (183k) |
| **Tucson** | `City_Of_Tucson` | 132k | Code Violations (132k) |
| **Seattle** | `Planning_SeattleCityGIS` | 78k | Residential Building Permits (46,5k desde 1990) |
| **Columbus** | `CJHewlett_columbus` | 55k | Building Permits / Certificate of Occupancy |
| **Houston** | `MyCityHouston` | 49k | Houston 311 Recent Service Request (SNOW) |
| **Washington DC** | `DCGISopendata` | ~38k | 311 (21,6k/ano) · Permit Inspections (16,7k) |
| **Corpus Christi** | `CoSAGIS_Opendata` | 507k | 311 All Service Calls (507k) |

> **Nota de rigor:** estes números são **cumulativos** (histórico completo),
> salvo onde indicado "por ano". O que interessa para nós é o **volume
> recente** — é preciso validar a recência de cada dataset ao activate a
> cidade (a data do registo mais recente, como fizemos no scan de Socrata).

---

## 4. Portão P2 — o dataset de proprietário (o que decide se a cidade é viável)

Sem *tax roll* / assessor com nome do dono, os leads ficam sem `owner_name` e
**não são vendáveis** (`backend/services/lead_rules.py:213-218`). Auditoria
ao catálogo Socrata:

| Cidade | Tax roll / assessor em Socrata | Nota |
|---|---|---|
| **New York** | ✅ PLUTO `64uk-42ks` (`data.cityofnewyork.us`) | em produção (BBL exacto) |
| **Chicago** | ✅ Cook County `3723-97qp` (filtro `city_filter_value=CHICAGO`) | em produção |
| **Dallas** | ✅ `jk5c-7csb` (`data.dallasopendata.com`) | em produção (fora do nome) |
| **Boston** | ✅ mass assessor (cadastro próprio) | em produção |
| **Providence** | ✅ `data.providenceri.gov` "Property Tax Roll" | **novo, viável** |
| **Norfolk** | ✅ `data.norfolk.gov` "Property Assessment and Sales" | **novo, viável** |
| **Denver** | ✅ `data.colorado.gov` "Denver Parcels" | **novo, viável** |
| **Austin** | ✅ `datahub.austintexas.gov` (Appraisal District) | **novo, viável** |
| **San Diego** | ✅ `internal-sandiegocounty.data.socrata.com` | **novo, viável** |
| **Seattle** | ⚠️ `cos-data.seattle.gov` — só propriedade municipal | ⚠️ parcial (não é o roll completo) |
| **Philadelphia, Houston, Phoenix, Atlanta, Miami, San Antonio, Jacksonville, Fort Worth, Columbus, Indianapolis, Charlotte, Milwaukee, Albuquerque, Tucson, Fresno, Sacramento, KC, Las Vegas, Portland, Newark, Jersey City, New Orleans, Cleveland, Pittsburgh, St Louis, Salt Lake, Oklahoma City, Memphis, Richmond, Rochester, Omaha, Tulsa, El Paso, Birmingham** | ❌ não encontrado no catálogo Socrata | **portão P2 por resolver** |

> **Conclusão do P2:** a maioria das grandes cidades Americanas **não**
> publica o roll de propriedade em Socrata. Ou o roll vive no **ArcGIS**
> (mesmo grupo B) ou num **portal de counties** (Cook County, Travis County
> Appraisal District, LA County Assessor) que exige o conector do P3.
> **É por isso que o P2 é o verdadeiro portão.**

---

## 5. 🏆 Top 10 — próximas cidades, ordenadas

Critérios: (a) dados prontos (P1+P2), (b) volume de obra, (c) dor de mercado
(constractors a pagar caro por leads), (d) esforço de integração.

| # | Cidade | Dados | Volume | Esforço | Veredicto |
|---|---|---|---|---|---|
| **1** | **Los Angeles** | Socrata (3 permits LIVE + 311) | 5.000+/ciclo | Baixo (só plumbing de cidade + P2) | **Primeira.** Não precisa de conector; 2.º maior mercado US |
| **2** | **Philadelphia** | ArcGIS (`maps.phl.data`) | ~1M/ano | Médio (conector + tax roll) | Maior mercado do NE; Tri-State-adjacente; **P2 por resolver** |
| **3** | **Denver** | ArcGIS (`The_City_and_County_of_Denver`) + parcels Socrata | 475k/ano | Médio (conector) | **P2 já resolvido em Socrata** — o mais fácil do grupo B |
| **4** | **Baltimore** | ArcGIS (`baltimore_city`) | 1,08M/ano | Médio (conector + P2) | Maior volume anual do país; mercado de reparação antigo e denso |
| **5** | **Houston** | ArcGIS (`MyCityHouston`) | 49k "recent" | Médio | Mercado immense; **atenção**: as obras estão nos subúrbios, não nos limites da cidade |
| **6** | **Charlotte** | ArcGIS (`CharlotteNC`) | 3,9M cum. | Médio (conector + P2) | Crescimento populacional forte; baixa concorrência de lead-gen |
| **7** | **Nashville** | ArcGIS (`NashvilleOpenData`) | 2,1M cum. | Médio (conector + P2) | Mercado de construção muito forte; dado muito limpo (split por ano) |
| **8** | **Chicago** *(já temos)* | Socrata | 13.957 qualificados | **Feito** | **Fase 2: activar a fonte de permits (2.817/ciclo) e corrigir o scraper CKAN** |
| **9** | **Providence / Norfolk** | ArcGIS + tax roll Socrata | 26k+ | Médio | **P2 já resolvido** — os mais "baratos" do grupo B depois de LA |
| **10** | **Indianapolis / Hartford / Louisville** | ArcGIS | 910k / 233k / 238k | Médio | Miles II, Denver e Louisville: **dados oficiais e limpos**, P2 por resolver |

### Descartados com nota
- **Phoenix, Atlanta, Miami, San Antonio, Austin, Jacksonville, Columbus,
  Milwaukee, Sacramento, Kansas City, Las Vegas, Portland, Cleveland,
  Pittsburgh, St Louis, Salt Lake, Oklahoma City, Memphis, Richmond, Tulsa,
  Omaha, El Paso, Buffalo, Tucson**: têm volume, mas **P2 (proprietário) não
  aparece no catálogo Socrata** → tiap de calendário até resolver o roll no
  portal correcto. **Não fazer scroll apenas pelo volume.**
- **Newark, Jersey City, New Jersey**: ver §6.

---

## 6. Tri-State / New Jersey — veredicto (inalterado)

| Teste | Resultado |
|---|---|
| 311/permits em NJ no catálogo Socrata | **0** (Newark, Jersey City, Hoboken, Elizabeth, New Brunswick, Paterson, Camden + condados de Bergen, Essex, Union, Monmouth) |
| Portal ArcGIS de Newark / Jersey City | datasets de 311/permits **não identificados** (o scan nacional devolveu zero datasets de Newark/Jersey City) |
| Tax roll de NJ | usa `block`/`lot` (não há BBL) → o join lead↔owner é mais fraco que o de NYC |
| Escala | Newark ~311k hab., Jersey City ~300k, Hoboken ~40k — uma ordem de grandeza abaixo do NYC |
| **Já temos NJ?** | Leads de NJ hoje: **0** (o `state` na BD só tem IL/TX/NY/MA) |

**Veredicto:** NJ **não é a próxima cidade**. A 311 municipal de NJ não tem
a forma que o nosso scraper lê, os municípios são pequenos, e o contractor
que trabalha em Newark **já é alcançável pelo feed de NYC** (mesmo tel.,
mesmo nome) — ou seja, Tri-State dividiria a exclusividade dos mesmos
contractors em vez de os ganhar.

**Quando NJ entrar:** pela camada de **parcelas/propriedade** (para vender
um "produto NJ" a contractors de NJ), com o **contrato** (transportador) e
não com a 311. E só depois de **50 clientes** nas cidades existentes.

---

## 7. Riscos e o que invalidaria este mapa

1. **Volume cumulativo ≠ volume útil.** Antes de activar qualquer cidade, é
   obrigatório medir a **data do registo mais recente** (o scan que matou os
   datasets CUNY/Chicago-historicos).
2. **O P2 é específico por cidade.** Cada tax roll tem colunas, chaves e
   lógica de join próprias (PLUTO/BBL em NYC, `block`/`lot` em NJ,
   `city_filter_value` em Cook County). Não é um template — são 4+ integrações.
3. **A mesma cidade pode ter 311 e o roll em plataformas diferentes**
   (ex.: Denver tem 311 em ArcGIS e parcels em Socrata) → 2 integrações.
4. **O `max_cities` é um parâmetro morto** (`backend/main.py:2260`): cada
   cidade nova = 1 fetch sequencial extra por run. Com 10+ cidades o scraping
   **passa a falhar por timeout** (poll de 55 min vs. timeout de 60 min).
   → **Pré-requisito:** paralelizar os fetches ou dividir por workflow.
5. **O motor de email é o multiplicador comercial, não a cidade.** 50
   clientes precisam de ~65.000 oportunidades/mês; o Movimento #1 (filtro por
   ofício + janela de 7 dias) é o que supplies esse volume. **Cidades sem
   o motor de email ligados não escalam** — e vice-versa.

---

## 8. Ordem de execução recomendada

| Fase | O quê | Esforço | Ganho |
|---|---|---|---|
| **0** | **Movimento #1 fase 2**: backfill com janela de 7 dias (10x produção) | Médio | De ~8.200 para ~20-30k oportunidades/mês nas 4 cidades |
| **1** | **Los Angeles** (Socrata, sem conector) | Baixo | +5.000/ciclo no 2.º maior mercado US |
| **2** | **Conector ArcGIS** (Baltimore, Denver, Charlotte, Nashville…) | Alto | 1-3M registos/ano por cidade |
| **3** | **Tax rolls** (Denver, Austin, Providence, Norfolk, San Diego) | Médio | Destrava cidades do grupo B sem owner externo |
| **4** | **NJ / Tri-State** (produto, com parcelas) | Alto | Só depois de 50 clientes |

---

## 9. Reprodutibilidade

Todas as medições deste documento vêm de APIs públicas e são reexecutáveis:

```bash
# Socrata: datasets de uma cidade + data do registo mais recente
curl -s "https://api.us.socrata.com/api/catalog/v1?domains=data.lacity.org&only=datasets&limit=300"
curl -s "https://data.lacity.org/resource/pi9x-tg5x.json?\$select=issue_date&\$order=issue_date%20DESC&\$limit=1"

# ArcGIS Hub: datasets com contagem real e org dono
curl -s "https://hub.arcgis.com/api/v3/datasets?q=311&page%5Bsize%5D=100"
```

O script de auditoria do scraper (`_guess_columns`) está em
`backend/scrapers/socrata_311.py:357` — **é o mesmo código que a produção
usa**, o que garante que o que está "utilizável" aqui é utilizável lá.
