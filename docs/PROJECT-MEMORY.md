# Memória do Projeto — Magic Leads / Garimpador Leads

> Documento canónico de contexto. **Ler antes de qualquer alteração de código.**
> Última atualização: 2026-10-29 (UTC). Números medidos em produção (`/data/leads.db`).

---

## 1. Objetivo do produto

Vender a empreiteiros licenciados (EUA) **oportunidades imobiliárias preditivas** com o
telefone do proprietário, a partir de registos públicos (311, violações HPD/DOB, permits),
sem ESP externo (SMTP próprio: Contabo VPS + Google Workspace).

Promessa da landing: "oportunidade + telefone do proprietário". O produto tem de a cumprir
com margem — não basta ter a infraestrutura.

---

## 2. Invariantes mandatórios (NÃO QUEBRAR)

### 2.1 Outreach e privacidade
1. **WhatsApp/SMS são SEMPRE em inglês.** `OUTREACH_DEFAULT_LANG = "en"` é intencional.
   Não passar `lang` do locale para `buildOutreachMessage`.
2. **Proibição absoluta** de incluir nas mensagens automáticas: morada, número de porta,
   `311`, `complaint`, `violation`, `report`, `case`, `denúncia` ou qualquer referência ao
   registo que originou o lead. A abordagem é **serviço local + avaliação gratuita**.
3. O contexto preditivo vive **apenas no briefing interno da dashboard** ("Porquê Agora").
   Nunca é interpolado no payload de outreach.
4. Testes de guarda obrigatórios: idioma EN + ausência dos termos acima em todas as
   mensagens geradas (PT/EN/ES podem existir no dicionário, mas o default é EN).

### 2.2 Sinal preditivo
5. `signal_type` ∈ `legal_obligation | authorized_work | open_request`.
6. `signal_status` ∈ `open | closed | unknown`.
7. **311 nunca pertence a `legal_obligation`.** O filtro "Obrigação legal" é só
   violações/multas (HPD, DOB, ECB/OATH, equivalentes Chicago/Boston).
8. Leads com `signal_status = 'closed'` **saem do feed por defeito** (o toggle
   "incluir fechados" pode mostrá-los).
9. Badges do cartão derivam de `signal_type`, nunca de `source_type` cru.
10. Briefing interno usa apenas dados públicos; nunca citar códigos legais crus
    (`§27-2005…`) na UI.

### 2.3 Frescura (P1)
11. Job diário de re-verificação de violações abertas (HPD/DOB) por `external_id`,
    em lotes, para eliminar registos "zumbis". Uma violação resolvida não pode
    continuar a ser apresentada como obrigação.

### 2.4 Ingestão
12. Paginação SoQL por `$offset` + `watermark` por dataset; sobreposição mínima de 6h;
    `max_pages` com tecto duro; timeout por página e retry com backoff.
13. **WAL já está ativo** (`backend/services/db.py:875-878`) e o backup já usa a API
    `sqlite3.Connection.backup` (WAL-safe, `control_tower.py:364-380`). **Não reimplementar.**
14. `leads` tem 1 linha por endereço/cidade (`UNIQUE(address, city)`): a reincidência
    tem de ser guardada em `lead_case_history` (uma linha por ocorrência), senão perde-se.

### 2.5 Telefone e economia
15. O clique **nunca** chama a Searchbug. Telefone vem de cache em BD.
16. `phone_lookups` com TTL 90 dias para hits, 7 dias para misses; entrega em 0 ms no clique.
17. Placeholders (`UNAVAILABLE OWNER`, `TAXPAYER OF`, `RAILROAD`, `* CITY OF`, variantes
    OCR) vão para `guard_skipped` — custo zero, nunca são pesquisados.
18. Pré-enriquecimento noturno por `priority_score`, agrupado por `owner_key`.

### 2.5.1 Proteção de caixa (on-demand, sem pré-enriquecimento)

25. **Não existe job noturno de telefone.** O único caminho pago de telefone é o clique
    do utilizador. `ENRICH_MAX_CALLS_PER_DAY = 0` é o default permanente e bloqueia
    qualquer job de lote futuro (hoje o parâmetro ainda não existe no código — criar).
26. **Ponto único de chamada paga** (`PhoneLookupService.lookup_phone`) exige um
    `trigger` explícito (`user_click` | `admin_manual` | `batch`). Sem `trigger` não
    compila/corre — impede que um caller novo gaste dinheiro por esquecimento.
27. **Ordem obrigatória no clique**: (1) cache persistente → (2) guards gratuitos
    (endereço, placeholder, institucional, corporativo) → (3) só então Searchbug.
28. **Só se chama quando o lead pode ser cobrado**: `will_charge_if_phone_found(lead)`
    (tem `owner_name`, não é institucional/corporativo, endereço resolvível) **e** o
    utilizador tem subscrição ativa **e** cota diária disponível. Lead grátis nunca
    gera chamada paga.
29. **Cota individual, não tecto global**: 10 revelações reais/utilizador/dia, gate
    atómico. **Não existe nem deve ser criado um tecto global diário/mensal
    bloqueante** — com 10 ou 50 assinantes, um cap fixo impediria clientes pagantes
    de usar a cota. O gasto global é observabilidade/alerta, nunca travão.
    Anti-abuso é por utilizador: orçamento de tentativas (30/dia) + rajada (3/min).
30. **Contabilidade real**: cada tentativa grava `cost_usd` com
    `SEARCHBUG_PRICE_PER_CALL_USD = 0.20` (tarifa real da fatura, confirmada 2026-10)
    — `credit_ledger.amount=0` já não serve como auditoria.
31. **`no_results` não é garantia de não-cobrança.** O código assume `Status=NORESULTS`
    como não cobrado e `Status=ERROR` como cobrado. A fatura é a única autoridade;
    reconciliar semanalmente e nunca repetir uma chave com negativo válido.
32. **Cache persistente**: `phone_lookups` com TTL 90 d (hit), 7 d (miss), 1 h (erro
    transitório); o dicionário em memória (`_phone_cache`) é só L1 e morre em cada deploy.
33. **ZIP**: 4 dígitos é rejeitado pela Searchbug ("Please enter 5-digit ZIP Code").
    Normalizar com `zfill(5)` antes de qualquer chamada (Boston: 7.966 leads).
34. **Ordem do nome**: a inversão LAST FIRST ganhou 5–3 bruto / 3–1 validado (n=10).
    Aplicar só em nomes registry-style (3+ tokens com inicial final; 2 tokens em
    NYC/Boston/Dallas) e **sempre** com `name_match`; não é flip global.
35. **L3 sem nome**: 1/10. Não entra no badge de alta probabilidade; só "sob consulta".
36. **Resposta não-JSON** (47,5% no experimento) não é `success` nem `no_results`:
    classificar como `transport_error`, **não faturar**, retry 1× com backoff e
    circuit breaker (3 consecutivos → pausa 60 s + alerta).
37. **`PHONE_TYPE`/`CARRIER`/`IS_CONNECTED` não vêm** na resposta `api_nape`. A
    validação é só `name_match` + NANP; "verificado" exige `name_match ≥ 0,6`.
38. **Falsos positivos são frequentes** (4/10 dos sucessos brutos do P0-0 eram outra
    pessoa). Nunca contar "sucesso bruto" como telefone entregue.

### 2.5.2 Orçamento e cotas (tarifa real $0,20/chamada)

**Modelo comercial: cota individual por utilizador.** Cada utilizador com acesso
ativo tem **10 revelações reais/dia** (qualquer cidade/nicho). O custo de $0,20 é
amortizado pela assinatura individual.

**Não existe (nem deve ser criado) um tecto global diário de gasto.** Com 10 ou 50
assinantes ativos, um cap fixo bloquearia clientes pagantes no meio do dia. O gasto
global é uma métrica de painel/alerta, não um gate.

| Parâmetro | Valor | Papel |
|---|---|---|
| `SEARCHBUG_PRICE_PER_CALL_USD` | **0.20** | tarifa da fatura |
| Cota de revelações | **10/utilizador/dia** | gate comercial (atómico) |
| Orçamento de tentativas pagas | **30/utilizador/dia** (3× a cota) | anti-abuso, por utilizador |
| Rajada | **3 tentativas/min/utilizador** | anti-bot |
| Gasto global | **sem cap bloqueante** | só alerta a 80% do previsto |
| Teste A/B (60 chamadas) | one-off | **$12,00** |

Custo por telefone (9 sucessos em 25 tentativas): **$0,42** sobre as 19 chamadas
faturáveis (ou **$0,56** se se imputarem as 25 tentativas).
Com cache: ~$0,36. Com portfólio: ~$0,31.

**C2 (custo observável):** `searchbug_calls.cost_usd` = `0.20` quando `billed=1`,
`0` caso contrário; backfill histórico `billed=1 -> 0.20`. Painel admin: custo 7d/hoje,
custo/telefone, ghost charges, `transport_errors`, `name_mismatches`, custo por cidade.
Alerta no Control Tower (`searchbug_cost`): custo/hora > max($1, 3× média 24h) → warn;
`transport_error` > 50% em 15 min (≥5 chamadas) → fail; ghost > 30% das pagas em 24h
(≥10) → warn; `name_mismatch` > 50% dos resolvidos (≥10) → warn. Sem cap global.

### 2.6 Preservação funcional
19. Ciclo de vida: reserva **60 min**, contacto **48 h**, negociação **48 h**, conversão
    terminal. Watchdog em processo a cada 15 min.
20. Bugs conhecidos a corrigir (não esquecer): reveals órfãos quando `expire_holds` corre
    antes de `check_reveal_watchdogs`; 5 leads legados com `stage_expires_at NULL`.
21. O cartão tem de chamar `recordContact(lead.id, "whatsapp"|"sms")` antes de abrir o link.
22. `lat/lng` preservados em `leads` (74.455/81.469 = 91,4%); o mapa usa `address` + `city`,
    mas as coordenadas não podem ser removidas nem substituídas por `owners`.
23. Contrato de API estável: `lead.owner_phone` (topo do objeto) e `res.owner.phone`
    (resposta do reveal). Se mudarem, quebram WhatsApp/SMS/tel/mailto.
24. `leads.address`, `city`, `state`, `zip_code`, `lat`, `lng` são a fonte de localização.
    `owners`/`address_key` servem para agrupar, **nunca** para substituir a morada de exibição.

---

## 3. Estado medido (2026-10-29)

| Métrica | Valor |
|---|---|
| Leads totais | 81.469 |
| Endereços distintos | 81.469 (1 lead por endereço) |
| Com `owner_name` | 56.939 |
| Com `owner_phone` | 19 |
| Com geo (`lat/lng`) | 74.455 |
| Com `mailing_address` | 577 |
| `lead_case_history` | 34.280 linhas / 1.472 leads (1,8%) |
| Testes | 698 passed, 1 skipped; ruff + tsc limpos |

### Fontes por cidade

| Cidade | 311 | HPD | DOB viol. | Permits | Outros |
|---|---:|---:|---:|---:|---:|
| NYC | 18.759 | 5.427 | 5.410 | 94 | — |
| Chicago | 23.382 | — | — | 2.685 | 10 B2B |
| Boston | 9.875 | — | — | 0 | — |
| Dallas | 15.827 | — | — | 0 | — |

### Defeitos de sinal confirmados
- 4.829/5.427 HPD com `case_status NULL` (89%) — `violationstatus`/`currentstatus` não mapeados.
- 2.685/2.685 Chicago permits com `case_status NULL` — `permit_status` não mapeado.
- 5.410/5.410 DOB com `case_status="Open"` gravado à mão; idade média 365 d, máx. 836 d.
- NYC DOB entra **sem BBL e sem lat/lng** (o select especial não os pede).
- Filtro "Obrigação legal" inclui `311` → devolve 29.596/29.690 em NYC.
- "Chamado aberto" devolve ~21% já fechados + 5,8% sem estado.
- Fallback de categoria: descrição legal sem ofício vira `Permit_Rejected` (522 HPD).
- `/api/leads` não aplica `_qualified_where` → lista e KPIs divergem.

---

## 4. P0 — escopo e critérios de aceitação

| Bloco | Entrega | Aceitação |
|---|---|---|
| **P0-C Custos e cotas** | (1) choke point único com `trigger` obrigatório e `will_charge_if_phone_found`; (2) **cota atómica + pré-verificação antes da Searchbug**; (3) **orçamento de tentativas por utilizador (30/dia, 3/min) + rate limit**; (4) remoção do fluxo legado pago sem consentimento; (5) unificação das duas implementações de cota; (6) placeholders em falta; (7) `cost_usd` + painel | 0 chamadas `batch`; 0 chamadas acima da cota; 0 chamadas para lead não cobrável; 30 tentativas/dia e 3/min por utilizador; falha não consome cota; 20 pedidos concorrentes com 9/10 terminam em 10, nunca 11 |
| P0-A Ingestão | `$offset` + watermark + max_pages nos 4 caminhos (genérico, DOB viol., DOB permits, Boston CKAN) | NYC ≥ 18.000/ciclo sem timeout; 2.ª execução não duplica; p95 do feed < 300 ms |
| P0-A Índices | índice do feed + `EXPLAIN QUERY PLAN` | plano usa índice; sem `database is locked` |
| P0-B Contadores | `/api/leads` com total real + alinhamento com KPI | total da lista == SQL COUNT; KPI == lista em "Todas" |
| P0-B Semântica | `signal_type`/`signal_status` + migração/backfill + API + badges + frontend | 0 linhas 311 em `legal_obligation`; fechados fora do default; badges coerentes |

### P0-0 — experimento de telefone ($10 = 50 chamadas no máximo)

**Antes do C1**, um harness standalone (fora do caminho de produção, sem alterar a app)
corre 40–50 chamadas no coorte limpo, com hard cap, `trigger=admin_manual` e log por
chamada (`lead_id`, `owner_class`, `layer`, ordem do nome, ZIP, `name_match`, `phone_type`,
`billed`, custo):

| Braço | Chamadas | Hipótese |
|---|---:|---|
| L2 ordem atual (FIRST LAST) | 10 | baseline |
| L2 invertida (LAST FIRST) | 10 | +15–25 p.p. em NYC/Boston/Dallas |
| Boston ZIP `2114` vs `02114` | 10 | ZIP de 4 dígitos invalida o match |
| L3 sem nome, com `name_match` | 10 | desbloquear 23.017 leads |

Custo: **$8 (40 chamadas)** a **$10 (50 chamadas)**. O harness aborta em 429/saldo
insuficiente e nunca escreve em `leads`. **Não prova 70–80%** (amostra pequena, IC largo):
escolhe o braço vencedor e mede a direção. A prova de 70–80% vem dos primeiros 100
reveals de produção com instrumentação.

**Resultado (2026-10-29):** 40 chamadas, **$6,80 assumidos** (34 linhas `billed=1`;
fatura por confirmar). ZIP 4→5 confirmado (5/5 rejeições: "Please enter 5-digit ZIP Code").
Inversão +2 validados (B 3 vs A 1; n=10, não conclusivo). L3 1/10. **19/40 respostas
não-JSON** (~150 ms) marcadas como pagas — falha de transporte/faturação a corrigir.
4/10 sucessos brutos eram outra pessoa. Relatório:
`docs/experiments/2026-10-29-p0-phone-report.md`.

### P0-C — ordem de execução (aprovada 2026-10-29)

**C1 — amanhã, ~9 h (núcleo de segurança e custo)**
1. Choke point `trigger` + `will_charge_if_phone_found` + kill-switch — 2,0 h
2. Cota atómica (`UPDATE … WHERE used < limit`) + pré-verificação antes da chamada + unificar `increment_daily_leads` — 2,5 h
3. Orçamento de tentativas por utilizador (30/dia, 3/min) + rate limit nos endpoints — 2,0 h
4. Remover o caminho legado pago sem consentimento + placeholders em falta + **implementar a regra vencedora do P0-0** (ordem do nome / ZIP) — 1,0 h
5. Testes de aceitação (7 casos da auditoria de cotas) — 1,5 h
6. Deploy + smoke (10 revelações, 0 chamadas indevidas, 0 locks) — 1,0 h

**C2 — dia seguinte, ~4 h (observabilidade)**
- `cost_usd` em `searchbug_calls` + painel de reconciliação (`billed × 0.20`)
- Tabela de placeholders alargada + testes de dados reais
- Load test de 10 utilizadores × 10 revelações (100 chamadas, sem cap global)

**Fora do P0-C:** decisão de produto sobre cobrar cota em L3 (telefone sem nome).
Bloqueia o P1 (desbloquear 23.017 leads sem nome), não o C1.

**Estado C1-A+B (2026-10-29, deployado `c73e33f`):** ZIP `zfill(5)`;
`transport_error` não faturado + retry 1× + circuit breaker; `name_match >= 0.6`
com `phone_verified`; inversão condicional LAST FIRST; L3 atrás de
`PHONE_L3_UNNAMED_ENABLED=0`; telemetria `lead_id/owner_class/layer/name_match/
transport_error`; placeholders `UNAVAILABLE/TAXPAYER/CITY OF` em guard;
**cota atómica** (`UPDATE … WHERE leads_used < leads_limit` + `BEGIN IMMEDIATE`),
pré-verificação antes da Searchbug (cota esgotada entrega sem telefone),
orçamento de tentativas 30/dia + 3/min (`phone_attempts`), fluxo `consent=False`
sem chamada paga, rate limit 20/min. **719 testes verdes**, ruff limpo.
**Deploy 2026-10-29:** commit `c73e33f`, Railway SUCCESS, `/health` ok,
backup pré-deploy verificado (82.560 leads), smoke: `phone_verified` +
5 colunas de telemetria + `phone_attempts`; 0 chamadas Searchbug novas.
**C2 (2026-10-29):** `cost_usd` real + painel + alerta `searchbug_cost`;
**727 testes verdes**; commit/deploy de C2 no mesmo dia.
Pendente: P0-A (paginação/watermark) → P0-B → UI/UX.

### P0-A — paginação e watermark (implementado 2026-10-29)

- `_fetch_soql(offset=...)` e `_fetch_all_pages` com `page_size`, `max_pages`,
  `truncated` e `max_date`. NYC/Chicago/Dallas usam o caminho genérico; DOB
  violações/permits e Boston CKAN também paginam.
- Tabela `scraper_watermarks (key, last_date)`; `fetch_from_dataset` aceita
  `watermark` e usa `watermark - 6 h` em vez da janela fixa. O watermark **não
  avança** quando a paginação é truncada.
- Índice `idx_leads_feed (city, lead_status, date_reported DESC)`.
- Teste live NYC 96 h: **34.915 linhas em 7 páginas, 28,9 s, 34.128 leads**
  (antes: 5.000). Testes: **733 verdes**.
- **Deploy P0-A:** commits `e3a4f1f` + `ff90220`; `/health` ok; `scraper_watermarks`
  e `idx_leads_feed` criados.
- **Correção crítica:** a primeira versão avançava o watermark no fetch. Se o run
  caísse antes dos inserts, a janela era saltada. Agora os watermarks ficam em
  `pending_watermarks` e só são aplicados **depois** de todos os inserts; os 5
  watermarks foram resetados para 2026-10-26 e o run `c7a24e5528d0` confirmou que
  não avançam durante o fetch.
- **Smoke:** leads 82.560 → **84.026** (+1.466) com o run em curso; feed NYC
  `limit=20` **p50 1,2 ms / p95 1,5 ms / max 1,7 ms**.
- **Nota de modelo:** `leads` tem `UNIQUE(address, city)`. A paginação recupera
  muitos registos, mas a maioria atualiza moradas já existentes; o crescimento
  visível é menor. Histórico/portfólio por ocorrência é P0-B/P1.

### P0-B — semântica, contadores e histórico (2026-10-29)

- `signal_type` (`legal_obligation` / `authorized_work` / `open_request`) e
  `signal_status` (`open` / `closed` / `unknown`) + backfill dos 84k+ leads.
  311 nunca é obrigação legal; `closed` sai do feed por defeito; HPD
  `violationstatus`/`currentstatus` passa a ser mapeado para `case_status`.
- `/api/leads` e `/api/leads/today` usam `get_leads_feed` (SQL): filtros, busy,
  paginação e **total real** no mesmo WHERE; o resumo do dashboard usa a mesma
  janela (`date_reported` 7d) e o mesmo `_qualified_where`.
- `lead_case_history` recebe uma ocorrência por registo no ingest (UNIQUE
  lead_id+external_id); `lead_history` calcula `repeat_365`, `open_cases`,
  `oldest_open_days`, `last_case_at` e o feed expõe esses campos.
- Testes: **739 verdes**; tsc limpo. Frontend: filtro "Tipo" usa `signal_type`;
  badges por sinal; `include_closed` no toggle.
- **Deploy `4770046` + `d2e7984`; smoke:** `legal_obligation` + 311 = **0**;
  51.488 `open_request/open`, 16.182 `closed`, 6.220 `legal/open`;
  `/api/leads/today?type=legal_obligation` total **1.325**; feed legal NYC
  **p95 169 ms**; `lead_history` backfill 1.445 leads; run `9eeb1268961b`
  a acrescentar ocorrências (+7.500) com watermarks parados em 26 (deferral ok).

### P1 — frescura e confiança (2026-10-29)

- `backend/services/freshness.py`: re-verifica HPD (`wvxf-dwi5`) e DOB
  (`3h2n-5cm9`) por `external_id` em lotes de 200, atualiza
  `case_status`/`signal_status`; fechados saem do feed. Registo em `freshness_runs`.
- Loop diário (`FRESHNESS_ENABLED`, atraso inicial 30 min, cada 24 h) +
  `POST /api/cron/freshness` com `X-Cron-Secret`.
- Consolidação `lead_history` (repeat_365/open_cases/oldest_open_days/last_case_at)
  no fim de cada run de frescura.
- `phone_confidence` (verified/high/medium/none) exposto no `LeadResponse`;
  cartão mostra selo "Telefone verificado"/"Alta probabilidade" e a linha
  "Porquê agora" (reincidência/idade do aberto).
- **741 testes**, tsc limpo.

### P1 — fixes de produto (2026-10-29, mesmo dia)

- `recordContact` ligado aos CTAs de WhatsApp/SMS do cartão (os 2 layouts) e do
  modal: `POST /api/leads/{id}/contact` passa a marcar `contact_count` e a parar
  o watchdog de reveals que ainda notificava o empreiteiro.
- `/api/users/{id}/daily-stats` expira holds ANTES de correr
  `check_reveal_watchdogs` (reveals órfãos deixam de ser notificados como vivos).
- Reparação de migração: leads em `reserved`/`contacted`/`in_negotiation` com
  `stage_expires_at NULL` passam a ter prazo (reserved = `reserved_until`, resto
  = max(updated_at+48h, now+24h)); deixa de haver leads presos para sempre.
- `LeadResponse` passa a expor `state`, `zip_code`, `lat`, `lng` (fonte do mapa,
  invariante 7).
- Cidade case-insensitive: filtros `COLLATE NOCASE`, import B2B reutiliza a
  grafia existente e `get_cities*` funde "CHICAGO"+"Chicago" (count somado,
  grafia da variante com mais leads).
- L3 sem nome: não consome cota (entrega incompleta), mas consome o orçamento de
  tentativas via `lead_rules.will_call_provider` — com a flag ligada não há
  chamadas pagas ilimitadas.
- **744 testes**, tsc limpo.

### Sprint UI/UX (2026-10-29)

- **Tokens de tema**: `panel`, `subtle`, `track`, `chipActive`, `ghost`,
  `ghostDanger`, `divider`; `data-theme` no root do dashboard. `color-scheme`
  e anel de foco próprios no modo claro; overrides `text-*-400 → -700` e
  `text2 = slate-600` (AA sobre branco).
- **Bug de persistência do tema**: o efeito de gravação corria com o estado
  inicial ("dark") e apagava a escolha guardada (visível com StrictMode). Passa
  a gravar só depois da leitura (`themeLoaded`).
- **6 classes hardcoded** substituídas por tokens (`page.tsx` nav badge,
  divisor, barra de limite, track, chip "incluir encerrados", chip de período).
- **Hierarquia de CTA**: removido o "Reservar" duplicado no topo do cartão; o
  CTA principal passa a `indigo-600` maior com sombra e anel de foco;
  "Revelar telefone" fica outline violeta (não compete).
- **Mobile**: gaveta de filtros (sheet) com contagem de filtros ativos,
  focus trap, `Escape`, scroll lock e devolução de foco; topbar deixa de
  rebentar (mensagem de push compacta + CTA `whitespace-nowrap`).
- **Skeletons** no feed (4 cartões com a altura real, `aria-busy`).
- **Teclado**: cartões do feed e do histórico com `role=button`, `tabIndex`,
  Enter/Espaço, `aria-label` e ring de foco; modais de reveal e detalhe com
  `role=dialog`/`aria-modal`, foco inicial e fecho por `Escape`.
- **Testes**: 746 backend, 73 vitest, tsc limpo; 10 e2e (3 novos em
  `e2e/ui-ux.spec.ts`; corrigido o label "Ver fluxo completo" no lifecycle).

### Verificação visual em produção (2026-10-29)

- **Tokens `muted` no claro:** `--muted`, `--border`, `--card` e `--foreground`
  só existiam na paleta escura. Os blocos "Detalhes da ocorrência"/"Detalhes do
  chamado" ficavam cinzentos com texto cinzento. Passam a ter equivalentes
  claros em `[data-theme="light"]`.
- **Texto quase invisível:** eventos do histórico em `text-slate-300` (1,4:1) e
  KPI em `text-*-500` (2,1–3,7:1). Os overrides de contraste passam a apanhar
  `-300/-400/-500/-600` e variantes com opacidade.
- **404 em cada poll:** `/api/users/{id}/credit-balance` e `/credit-ledger` não
  existiam (só a versão admin). Adicionados com verificação de posse; a resposta
  inclui `counts` (nome que o frontend já usava).
- **Botão "Salvar"** das notas com estado disabled legível (`bg-slate-200
  text-slate-600` no claro) em vez de opacidade 50%.
- Auditoria de contraste no browser (WCAG por elemento): sem falhas de texto
  normal; só os números KPI grandes, agora acima de 3:1.
- **KPIs**: as cores vinham em `style={{ color: "#f59e0b" }}` (inline), imunes a
  overrides CSS. Passam a escolher `-700` no claro.
- **CTAs coloridos**: "Contactar" era branco sobre `sky-500` (3:1) → `sky-700`;
  "Negociar" branco sobre âmbar (2:1) → texto `slate-950`; chips de cidade e
  botões indigo passam a `indigo-600` (6,3:1 com branco).

### P2 — percentagem de confiança (2026-10-29)

- `get_phone_success_stats(city, owner_class, 90d)` em `db.py`: denominador =
  `success`/`no_results`/`name_mismatch`; cache, guard e erros de transporte
  ficam fora (não são tentativas reais).
- `_phone_confidence_stats` em `main.py`: hierarquia (cidade, classe) →
  (classe, todas as cidades); **só devolve percentagem com ≥30 amostras**;
  cache em memória de 10 min por segmento (o feed repete o mesmo segmento).
- `LeadResponse.phone_success_pct` + `phone_sample_size`; o cartão mostra
  "Alta probabilidade · 72%" com tooltip "n consultas"; sem amostras suficientes
  não há número inventado — o selo qualitativo mantém-se.
- **752 testes**, tsc limpo, build ok.
- **Painel admin** "Calibração da confiança": `/api/admin/phone-sample-progress`
  (`days=90`) devolve, por (cidade, classe) e por classe global, amostras,
  sucessos, `pct` (só quando pronto), `needed` e `ready`; a UI mostra barra de
  progresso até 30 com estado pronto/pendente. É o mesmo denominador do cartão.
- **Smoke em produção:** `/api/leads/today` devolve `phone_success_pct=50` e
  `phone_sample_size=38` no segmento `unknown` (311 sem nome, onde a amostra já
  passa de 30). Para leads com nome a amostra ainda é 0: os 65 registos
  históricos de `searchbug_calls` têm `owner_class NULL` e `lead_id 0` (anteriores
  à telemetria P0-C1). A percentagem aparece quando houver ≥30 consultas novas do
  segmento; até lá o selo fica qualitativo, sem número inventado.

### Alert Engine v2 — Fase A (2026-10-29)

- **Gate semântico**: o planner deixou de usar o dict do insert e passou a
  buscar `get_leads_for_alert` (signal_type/status, owner, phone, repeat_365,
  coords). Exclui `closed`, institucional, morada não resolvível e leads com
  mais de 48 h sem reincidência.
- **Nicho estrito**: `get_users_interested_in(..., strict=True)` no planner.
  Sem interesses gravados = sem alerta individual (o onboarding in-app já
  existe). Fim do fallback "sem interesses = todas".
- **Quiet hours**: 21:00–08:00 `America/New_York`; 311/obra suprimidos (in-app
  criado na mesma), `legal_obligation` passa sempre. Digest não é criado no
  silêncio (o primeiro run da manhã cria e envia).
- **Distância**: informativa e critério de ordenação (sinal > estado >
  frescura > distância). **Nunca filtra**: o default é toda a cidade, sem raio.
  Base do utilizador: GPS/manual (mostra "a X mi") ou centroide da cidade
  (mostra "na sua cidade"). Haversine local, zero APIs pagas.
- **Payload v2**: labels PT/EN/ES, "Porquê agora", confiança (≥30 amostras ou
  "sob consulta"), ações "Ver lead"/"Dispensar", `timestamp` epoch,
  `renotify`, vibração, `requireInteraction` em legal.
- **Entrega**: TTL 4 h (lead) / 12 h (digest) — antes era 0; `Urgency` high em
  legal e normal nos restantes; broadcast admin respeita `push_enabled`.
- **Privacidade**: `show_address_in_push` (default ligado) + toggle em
  Definições; API `PUT/DELETE /api/users/{id}/base-location` e
  `PATCH /api/users/{id}/push-preferences`.
- **Observabilidade**: `push_health` no Control Tower (VAPID em falta, 0
  entregas com subs, explosão de subs mortas).
- **766 testes**, 11 e2e, tsc limpo.
- **Limitação assumida**: Web Push não suporta som personalizado por ficheiro;
  usam-se padrões de vibração + (fase B) um chime in-app quando a app está
  aberta. DOB de NYC não tem lat/lng no dataset → sem distância até ao
  enriquecimento BIN→PLUTO (gratuito).

### Sprint B1 — clique, coalescência e higiene (2026-10-29)

- **Telemetria de clique**: payload leva `nid` + `sig` (HMAC de
  `push_click.sign_click`). O SW regista `GET /api/push/click` antes de
  navegar; o deep link leva os mesmos campos como fallback (dashboard).
  `notifications.clicked_at` + `push_deliveries.clicked_at`; painel admin
  mostra **Cliques** e **CTR**.
- **Coalescência**: 1 push por execução. 1 lead → push individual; ≥2 →
  resumo (“2 novas oportunidades — Chicago · 1 obrigação legal · 2 chamados”),
  com “Ver oportunidades”. O digest não envia push no mesmo run de um lote.
- **Min-gap**: 30 min por utilizador (lido antes de criar os in-app deste run;
  senão o próprio alerta contava como anterior). In-app é criado sempre.
- **Higiene de dispositivos**: máx. 5 ativos (`disabled_at`), `last_seen_at`,
  `last_success_at`, `device_label` (UA), poda de inativos >90 d mantendo
  sempre um; broadcast respeita `push_enabled` e só usa subs ativas.
- **777 testes**, 11 e2e, tsc limpo.
- **Lição de migração**: SQLite não aceita `DEFAULT CURRENT_TIMESTAMP` num `ALTER TABLE`
  (“Cannot add a column with non-constant default”). `last_seen_at` nasce `TEXT` e é
  preenchida com `created_at`; o erro foi detetado no smoke de produção e corrigido
  no mesmo dia (`3f00916`). Migrações novas devem usar defaults constantes + backfill.

### Sprint B2 — preferências, onboarding e lifecycle (2026-10-29)

- **Push por ofício**: `user_interests.push_enabled` (default 1) + sino nas Definições.
  Desligar remove só o push desse nicho; o **in-app fica completo**. Editar a seleção
  de ofícios preserva o estado dos sinos (antes um `DELETE`+`INSERT` reiniciava tudo).
  Endpoints: `GET /api/users/{id}/interests/push`, `PATCH .../{category}/push`.
- **Digest**: `users.digest_enabled` default **1**, toggle nas Definições. O digest do
  excedente continua a ser 1/dia; **novo**: quem não tem ofícios recebe um digest diário
  genérico (`dispatch_unconfigured_digest`) — antes 101/122 utilizadores ficavam sem
  qualquer sinal, porque a audiência estrita nunca os incluía.
- **Onboarding**: `dispatch_interests_onboarding` envia **um** push instructivo
  (“Escolha os seus ofícios”) a quem tem push ativo, subscrição viva, acesso vigente e
  zero interesses. Uma vez por utilizador (`notifications.interests_onboarding`), fora
  do orçamento e nunca no silêncio.
- **Lifecycle**: `users.lifecycle_push_enabled` default **0**. `lifecycle_push.py` promove
  `reveal_followup/reveal_urgent/stage_warning/stage_urgent` (<45 min) a push, com
  `pushed_at` para idempotência. O `reveal_urgent` (15 min para perder a reserva) é o
  **único** que fura as quiet hours; `urgency=high` + `requireInteraction`.
  Corre no watchdog de 15 min e em `/api/cron/expire-holds`.
- **794 testes**, 13 e2e, tsc limpo, build ok.

### Sprint B3 — geo BBL→PLUTO, chime e A/B (2026-10-29)

- **Geolocalização DOB**: os 6.101 leads de NYC DOB não tinham lat/lng (o dataset
  `3h2n-5cm9` só publica `boro`/`block`/`lot`/`bin`). O scraper passou a pedir
  `block`/`lot`, compõe o **BBL** de 10 dígitos (`geo_lookup.compose_bbl`) e resolve no
  **PLUTO** (`64uk-42ks`) via `latitude`/`longitude`. Cache local `bbl_coords` (hit e
  miss; miss expira em 30 d). **Custo zero** (dados abertos, lotes de 200 BBL).
  Os leads antigos recuperam o BBL por `violation_number` (`backfill_dob_bbl_from_source`)
  antes da resolução. Endpoints: `GET /api/admin/geo-coverage`,
  `POST /api/admin/backfill-dob-coords` (idempotente, cursor por id).
  O PLUTO devolve BBL como `3074130059.00000000` — a normalização para 10 dígitos é
  obrigatória, senão nenhuma chave casava.
- **Chime in-app**: `frontend/public/sounds/alert-chime.mp3` (13 KB, sintetizado para a
  Magic Leads: arpejo A5–C#6–E6, sem licenças). O dashboard compara o unread a cada 30 s
  e toca o chime **só quando aumenta** e a app está visível. Autoplay desbloqueado no
  primeiro gesto (`primeAlertChime`). Preferência `users.chime_enabled` (default **1**)
  com toggle nas Definições. O Web Push continua a usar o som do SO.
- **A/B do digest**: bucket determinístico pelo id (`par`=A, `ímpar`=B), gravado no
  primeiro digest do dia em `notifications.ab_variant` (não muda a meio do dia). A usa o
  copy neutro; B usa `digest_b` (“N novas oportunidades perto de si… os melhores leads
  são reservados primeiro”). `GET /api/admin/digest-ab` + cartão no Control Tower com
  CTR por braço; **vencedor só com ≥30 envios com push por braço**.
- **820 testes**, 14 e2e, tsc limpo, build ok.
- **Produção (medido)**: backfill 6.101 leads DOB em 62 s → **6.060 com coordenadas**
  (99,3%); BBL preenchido em 6.092. `bbl_coords` com **4.981 hits / 25 misses**
  (99,5% de acerto no PLUTO). Cobertura global: 1.659 de 85.873 sem coordenadas (1,9%),
  quase tudo 311 sem BBL + 40 permits + 41 DOB fora do PLUTO.
- **A/B — realidade da amostra**: só 2 utilizadores com push e o digest exige
  excedente do teto; chegar a 30 envios com push por braço leva semanas. O cartão
  mostra `n/30` por braço e **não declara vencedor** abaixo disso (evita decidir com
  ruído). Os 135 digests históricos ficam no braço `?` (pré-B3) e não contam.
- **Horário do digest**: medido de forma **observacional** (o run que cria o digest do
  dia), não por mudança de agenda — evitar mexer num cron saudável sem amostra.

### Hotfix de confidencialidade (2026-10-29, pós-B3)

- **Regra de ouro**: nenhum termo da fonte/arquitetura na UI, push, e-mail, sino ou docs de
  cliente. O gatilho foi o cartão “Silêncio noturno” a dizer “chamados 311”.
- `backend/services/privacy.py`: `scrub` (remove `311`, Socrata, CKAN, Open Data, DOB, HPD,
  scraper, dataset, API, BBL/BIN e URLs de portais) + `sanitize_lead` (texto limpo,
  `source`/`department` = `None`, `source_type` neutro). Aplicado em `_to_lead_response`,
  ocorrências, histórico (`detail`) e sino in-app (cobre notificações antigas).
- Frontend: `Origem`/`Source` removidos do cartão/tabela; `department` removido do detalhe
  e da secção de revelação; texto do silêncio reescrito em PT/EN/ES.
- `tests/test_privacy_terms.py` (25 testes) varre i18n, `translations.py`, o sanitizador e a
  resposta de API; novo e2e garante que Definições e detalhe do lead não mostram os termos.
- **845 testes**, 15 e2e, tsc limpo, build ok.
- Nota: o painel `/admin` mantém linguagem técnica (é consola interna, não cliente).

### P1 (a seguir)
- Acumular ≥30 amostras por segmento para a percentagem começar a aparecer.
- Ampliar a amostra com as consultas reais (hoje ~65 chamadas no histórico).

---

## 5. Dívida conhecida / não fazer
- Não reativar `lang` do locale no outreach.
- Não injetar morada/denúncia nas mensagens.
- Não remover `lat/lng` nem mudar o contrato `owner.phone`.
- Não voltar a pôr `311` em "Obrigação legal".
- Não usar códigos legais crus na UI.
- `auth_ref` guarda tokens OAuth em plaintext (dívida de segurança, fora do P0).
- `no_results` da Searchbug aparece com `billed=1` em 10 casos — confirmar fatura.

---

## 6. Operação
- Deploy: Railway, projeto `exemplary-respect`, serviço `magic-leads`, branch **`master`**.
- DB produção: `/data/leads.db` (`DATA_DIR=/data`). DB local é outra — nunca comparar.
- VPS: `184.174.36.43` / `https://184.174.36.43.sslip.io` (TLS Caddy, uvicorn 127.0.0.1:8443).
- Testes: `pytest tests/ -v` (CI), ruff `--select=E,F,W,I --ignore=E501`, `tsc --noEmit`.
- Control Tower: backup diário verificado, health 15 min, digest diário.
