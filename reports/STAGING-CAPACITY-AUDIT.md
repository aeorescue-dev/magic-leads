# Auditoria de capacidade, volumetria e cobertura — staging

Data: 2026-11-13
Âmbito: dashboard preventivo/reativo, ingestão e exclusividade.
Produção: `master` em `3b53962` — intocada; nenhuma migração ou deploy.

## 1. Sumário executivo

- **Cobertura:** as 4 cidades têm fontes contínuas, mas o volume é muito desigual:
  NYC ≈ **61,6%**, Chicago ≈ **26,0%**, Dallas ≈ **8,0%**, Boston ≈ **4,4%** do total
  qualificado em 7 dias.
- **Stock atual (7 dias, qualificados):** **9.620** sinais → **≈1.374/dia**.
  Isto suporta, em teoria, **≈137 utilizadores** a 10 revelações/dia (100% de quota) ou
  **≈274** a 50% de utilização — mas **não** distribuídos por cidade/ofício.
- **100 utilizadores:** viável no agregado apenas com **alocação proporcional à oferta**
  (NYC ~62, Chicago ~26, Dallas ~8, Boston ~4) e utilização moderada. Distribuição
  uniforme (25/cidade) **falha** em Boston e Dallas; nichos como Roof/Structure falham
  mesmo em NYC.
- **Preventivo real:** **0** oportunidades preventivas vindas de ingestão; as 14 de staging
  são seed. A fila preventiva só escala depois de ligar HPD Complaints, deadlines HPD,
  Chicago Building Violations e ECB.
- **Backend:** teste de carga a 100 concorrentes deu **p50 ≈5,6 s / p95 ≈6,0 s** e
  **≈16–17 req/s**; o processo de produção arranca **1 worker uvicorn** e alguns endpoints
  fazem chamadas SQLite síncronas dentro de `async def`. **É o principal bloqueio técnico
  para 100+ utilizadores.**
- **Veredicto:** o modelo de exclusividade é atómico e lida bem com conflitos, mas
  **100 utilizadores simultâneos não estão prontos** sem: (a) ingestão preventiva real,
  (b) múltiplos workers/consultas não bloqueantes e (c) limites de onboarding por
  cidade/ofício.

## 2. Metodologia

- **Dados de oferta:** auditoria de pipeline de 2026-11-12 sobre a base de produção
  (7 dias, qualificados, por cidade/ofício). O staging tem apenas 4 leads + 14 preventivos
  de demonstração, pelo que não serve para volumetria.
- **Código/config:** `backend/main.py` (`_scrape_worker`), `config.py`, `trade_grid.py`,
  `freshness`/`control_tower`, Docker/Railway.
- **Carga:** teste read-only contra o backend de staging (`127.0.0.1:8010`), com token real,
  10/25/50/100 concorrentes, mix de endpoints do dashboard.
- **Exclusividade:** testes de `PROPERTY_LOCKED`, quota e locks já executados; análise do
  fluxo transacional.

## 3. Cobertura e volumetria por cidade

Stock qualificado dos últimos 7 dias (auditoria de produção de 12/11):

| Cidade | Sinais/7d | Média/dia | % do total | Utilizadores a 10/dia | Utilizadores a 50% |
|---|---:|---:|---:|---:|---:|
| NYC | 5.923 | 846 | 61,6% | 84,6 | 169,2 |
| Chicago | 2.505 | 358 | 26,0% | 35,8 | 71,6 |
| Dallas | 769 | 110 | 8,0% | 11,0 | 22,0 |
| Boston | 423 | 60 | 4,4% | 6,0 | 12,1 |
| **Total** | **9.620** | **1.374** | 100% | **137,4** | **274,9** |

Ofícios com ≥10 sinais/7d: NYC 13, Chicago 10, Boston 11, Dallas 6. A tabela completa
mostra concentração extrema: NYC Plumbing 1.492/7d e Heating 1.314/7d; Dallas depende de
Structure (211) e Electrical (169); Boston tem volumes residuais em quase todos os ofícios.

### Teto por ofício/cidade (utilizadores a 10/dia)

| Cidade | Ofícios relevantes (7d → users@10/dia) |
|---|---|
| NYC | Plumbing 1.492 → 21,3 · Heating 1.314 → 18,8 · Unsanitary 686 → 9,8 · Door_Window 514 → 7,3 · Paint 445 → 6,4 · Rodent 438 → 6,3 · Debris 436 → 6,2 · Elevator 170 → 2,4 · Electrical 167 → 2,4 · Structure 103 → 1,5 · Roof 10 → 0,1 |
| Chicago | Rodent 800 → 11,4 · Debris 566 → 8,1 · Plumbing 388 → 5,5 · Paint 358 → 5,1 · Electrical 123 → 1,8 · Structure 96 → 1,4 |
| Dallas | Structure 211 → 3,0 · Electrical 169 → 2,4 · Plumbing 132 → 1,9 · Gas 116 → 1,7 · Heating 82 → 1,2 |
| Boston | Rodent 119 → 1,7 · Debris 96 → 1,4 · Electrical 56 → 0,8 · Plumbing 10 → 0,1 |

**Leitura:** 100 empreiteiros da mesma especialidade na mesma cidade não cabem com quota
de 10/dia. Ex.: 50 canalizadores em NYC precisariam de 500/dia; a oferta é 213/dia (2,3×
acima). 20 telhadores em NYC seriam impossíveis (1,4/dia).

## 4. Frescura e robustez das 4 cidades

### Cadência e garantias

- Scheduler interno a cada **6 h** (4 runs/dia), run máximo **3 h**, retry **30 min**,
  watchdog **30 min**, stale **36 h**.
- Frescura: **warn 10,5 h / fail 15 h** (intervalo 6 h × 1,75 / 2,5).
- Watermarks só avançam depois dos inserts; falha a meio repete a janela (idempotente).
- Circuit breaker por cidade + DLQ + `city_health` + alertas (Control Tower/digest).
- Produção: `SCRAPER_SELF_SCHEDULED=true` por defeito; staging corre com schedulers off.

### Fontes por cidade

| Cidade | Fontes no pipeline | Janela | Observações |
|---|---|---|---|
| NYC | 311 (`erm2-nwe9`), HPD Violations (`wvxf-dwi5`), DOB Violations (`3h2n-5cm9`), DOB Permits | 48–120 h | maior volume; HPD Complaints (`ygpa-z7cr`) **não ingerido** |
| Chicago | 311 (`v6vf-nfxy`), Building Permits (`ydr8-5enu`) | 48 h / 720 h | Building Violations (`22u3-xenr`) **não ingerido** |
| Dallas | 311 (`d7e7-envw`), Building Permits | 48 h / 168 h | 311 muito ruidoso; 1.884 “Code Concern”/7d descartados; permits são a oferta útil |
| Boston | 311 CKAN (`254adca6…` + legado `1a0b420d…`), Permits CKAN (`6ddcd912…`) | 72 h / 7 d | risco de rotação de recursos CKAN; stale dedicado 36/48 h |

### Saúde medida (auditoria de 12/11)

- Run manual `6b696a3a110d`: **success**, **793 inseridos** de **58.197 raw**, 4/4 cidades.
- `city_health`: **0 falhas, 0 circuit breakers**.
- `ingestion_failures`: **0**.
- 4 runs com erro em 3 dias, todos “run interrompido” em deploys, recuperados.

### Riscos de frescura

1. **Variação sazonal:** NYC Grass 1/7d, Gas 9/7d, Mold 39/7d; Boston não tem Grass/Lead/
   Mold/Elevator. Não prometer “todos os ofícios em todas as cidades”.
2. **Boston CKAN:** mudança de recurso ativo já tratada com dual-read e alertas; ainda é o
   ponto mais frágil.
3. **Dallas 311:** maioria ruído; a cobertura depende de permits.
4. **Schema drift** nas APIs públicas: o watcher de frescura e o `SCRAPER_SOURCE_SCHEMA`
   alertam, mas a correção é manual.
5. **Deploys:** runs interrompidos; retomada automática, mas há janela de até 6 h.

## 5. Teste de carga (staging, read-only)

Mix de endpoints do dashboard (`auth/me`, `opportunities`, `insights`, `leads/today`,
`daily-stats`), token real, uma ronda por nível:

| Concorrentes | p50 | p95 | máx | erros |
|---:|---:|---:|---:|---:|
| 10 | 451 ms | 476 ms | 476 ms | 0 |
| 25 | 1.483 ms | 1.534 ms | 1.538 ms | 0 |
| 50 | 2.587 ms | 2.786 ms | 2.790 ms | 0 |
| 100 | 5.601 ms | 5.984 ms | 5.999 ms | 0 |

Burst de 100 workers × 5 rondas: 500 pedidos em 31 s, **≈16 req/s**, p50 5,8 s, p95 10,1 s,
110 falhas de ligação do cliente (saturação de sockets/burst, servidor sem erros 5xx).

**Diagnóstico:** a latência cresce linearmente com a concorrência e o throughput estabiliza
em ~16–17 req/s — assinatura de **processamento serializado**, não de CPU. Causas:
- `railway.json` arranca `uvicorn` **sem `--workers`** (1 processo);
- endpoints `/api/opportunities` e `/api/opportunities/insights` chamam SQLite **síncrono**
  dentro de `async def`, bloqueando o event loop;
- cada utilizador do dashboard faz ~6–9 pedidos/min (polling de 60 s). 100 utilizadores
  ≈10–15 req/s — no limite do teto medido, com picos acima.

**Caveat:** o staging tem 4 leads; as queries de produção são mais pesadas. O teste mede a
arquitetura de concorrência, não o custo real da BD de produção.

## 6. Capacidade para 100+ utilizadores

### Reativo (dados atuais)

- 100 utilizadores × 10 revelações = **1.000/dia** = **73%** da oferta (1.374/dia);
  folga de 374/dia.
- A 70% de utilização: 700/dia (51% da oferta). A 50%: 500/dia (36%).
- Teto agregado: **137 utilizadores** a quota cheia; **196** a 70%; **274** a 50%.
- **Distribuição uniforme falha:** 25 users/cidade → Boston precisa 250/dia (oferta 60),
  Dallas 250 (oferta 110).
- **Alocação proporcional** (NYC 62, Chicago 26, Dallas 8, Boston 4) cabe a 100 users a
  quota cheia, mas continua frágil por ofício.

### Preventivo (dados atuais vs. potencial)

- **Hoje:** 0 preventivos reais; 14 de seed. Capacidade preventiva de produção = **0**.
- **Potencial não ingerido:** HPD Complaints 15.321/7d (**2.189/dia**), deadlines HPD
  61.712/30d (≈2.057/dia), Chicago failed inspections 10.470/90d (≈116/dia), ECB active
  11.997/90d (≈133/dia). Somando HPD + Chicago + ECB: **≈2.400/dia** → **≈240 users** a
  10/dia, mas com forte concentração em NYC e nos ofícios Heating/Plumbing/Unsanitary.
- Mesmo com essa ingestão, Roof/Structure não sustentam 100 users: Roof NYC 1,4/dia.

### Exclusividade e concorrência

- `property_locks` tem chave única e a reserva é transacional: **1 imóvel = 1 reserva por
  vez**. O perdedor recebe **409 PROPERTY_LOCKED** e a quota é **estornada** (testado).
- Quota diária atómica (`reserve_daily_quota`); 10/dia por utilizador.
- Após 1 h sem contacto, a oportunidade volta ao pool e pode ser reservada por outro —
  a oferta “serve” sequencialmente, mas não em simultâneo.
- 1.000 reservas/dia = **0,7/min** em média; trivial. Picos de 100 reservas no mesmo minuto
  são o cenário a testar: SQLite tem **um writer** por vez; com 1 worker, os writes entram
  na mesma fila do event loop.
- Conclusão: a atomicidade está correta; a **escala de escrita** e a **escassez por nicho**
  são os riscos, não a corrida.

## 7. Recomendações

### P0 — antes de 100 utilizadores

1. **Ingestão preventiva real:** HPD Complaints (`ygpa-z7cr`) + deadlines (`wvxf-dwi5`) +
   Chicago Building Violations (`22u3-xenr`) + ECB (`6bgk-3dad`), com dedupe por
   complaint/building e agendamento do adaptador preventivo após cada run.
2. **Escalar o backend:** `uvicorn --workers 4` no `railway.json`; mover as chamadas
   síncronas de `/api/opportunities*` para `anyio.to_thread`; cache de 15–30 s para
   list/insights (o dashboard faz polling de 60 s).
3. **Teste de carga com BD do tamanho de produção** e rajada de escritas (reservas), não só
   leituras; medir p95 de reserva e `database is locked`.

### P1 — proteger a exclusividade

4. **Onboarding por cidade/ofício:** máximo de utilizadores =
   `floor(0,7 × oferta_diária / 10)`. A 70%: NYC ~59, Chicago ~25, Dallas ~7, Boston ~4;
   por ofício, NYC Plumbing ~15, Heating ~13, Roof 0.
5. **Quota dinâmica** por ofício/cidade (10 global, menos nos nichos) ou lista de espera;
   comunicar “10/dia” como teto, não garantia.
6. **Foco comercial:** NYC e Chicago; Boston/Dallas exigem expansão de fontes ou limites
   mais baixos.
7. **Cadência:** 2–3 h em NYC/Chicago no pico; 6 h nas restantes.

### P2 — escala e monitorização

8. Postgres (ou réplica de leitura) quando >200 utilizadores ativos ou writes sustentados;
   SQLite/WAL serve o volume atual, mas não múltiplos writers.
9. Painel de capacidade: novos/dia por cidade/ofício, utilizadores ativos, revelações/dia,
   conflitos 409, profundidade de fila, p95 de reserva.
10. Sazonalidade: não prometer Grass/Gas/Mold no inverno; ajustar expectativas por cidade.

## 8. Veredicto

- **Cobertura:** contínua nas 4 cidades, com volumes muito desiguais; fresh 4×/dia com
  alertas e recuperação.
- **100 utilizadores:** o **stock reativo agregado** chega (1.374/dia vs 1.000/dia a quota
  cheia), mas **não** com distribuição uniforme nem em nichos; o **preventivo real** ainda
  não existe; o **backend de 1 worker** satura perto de 16–17 req/s.
- **Exclusividade:** modelo atómico e correto; a escassez é de oferta e de arquitetura, não
  de corrida.
- **Recomendação:** não abrir para 100 utilizadores antes dos P0. Com P0 + onboarding
  proporcional, 100 é viável; 200+ exige Postgres e mais ingestão.

Produção continua em `master` `3b53962`, intocada e isolada.
