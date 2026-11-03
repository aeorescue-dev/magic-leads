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

### Segurança — A1 + A2 (2026-10-30)

- **A1 anti-raspagem**: `/api/leads`, `/api/leads/today`, `/api/leads/search` e
  `/api/leads/{id}` passaram a exigir conta (`_get_current_user`) e rate limit de
  120/min. Antes o feed era anónimo, sem limite e com `offset` livre: 85.873 leads
  percorríveis em ~425 pedidos; o detalhe permitia enumerar IDs sequenciais e a busca
  varria a base com `per_page`. `/api/leads/recent` continua público (montra da
  landing), mas limitado a 20 itens, 30/min e com o dono mascarado. `per_page` da lista
  é fixado a 200 na resposta (não só no SQL).
- **A2 TTL de sessão**: coluna `user_sessions.expires_at` (migração + backfill de 30 d
  para as sessões antigas, que eram eternas). `SESSION_TTL_DAYS=30` com expiração
  **deslizante** (cada uso renova; o limite real é inatividade). Token expirado é
  apagado, devolve 401 `session_expired` e o frontend limpa a sessão/redireciona.
  `prune_expired_sessions()` no arranque. Cookie alinhado ao TTL.
- **860 testes** (8 TTL + 7 anti-raspagem novos), 15 e2e, tsc/build/ruff limpos.
- **Verificado em produção (30/10)**: anónimo → 401 em `/api/leads`, `/api/leads/today`,
  `/api/leads/search` e `/api/leads/{id}`; `recent` → 200 com `per_page=20` e dono
  mascarado; sessão autenticada → 200 e `expires_at` a 30 dias; sessão forçada a expirar
  → 401 `session_expired`; 11/11 sessões antigas ficaram com `expires_at` no backfill.
- **Fora de âmbito (próximo bloco)**: gate de acesso em `contact/negotiate/convert`,
  trial de 3 dias (função existe e nunca é chamada), coerência 402 vs 403.

### UI — cota diária na sidebar (2026-10-30)

- O cartão inferior esquerdo mostrava **“SALDO DE CRÉDITOS / 0 créditos disponíveis”**, o
  que sugere venda de créditos — o modelo é passe semanal de $120. Além disso lia o
  ledger (`consume_reveal.count`), que não regista consumos, e por isso ficava sempre 0.
- Passou a **“Revelações diárias”** com o consumo real de `dailyStats`:
  `10 / 10`, `usadas hoje`, barra de progresso e aviso de renovação à meia-noite quando
  esgota. Fonte única: `/api/users/{id}/daily-stats` (a mesma da trava de 10/dia).
- Removidos `credit_balance`/`credits_available`/`today_used` (só existiam em PT; EN/ES
  mostravam o fallback em português) e a chamada periódica a `/credit-balance`.
- Novas chaves em PT/EN/ES. Guard: `tests/test_sidebar_quota_copy.py` (4) + e2e da
  sidebar. **865 testes**, 16 e2e.

### Segurança — A5 + sessões + onboarding (2026-10-30)

- **Gate A5**: `_require_active_access(user)` devolve **402** com
  `{error: subscription_required, action: REDIRECT_TO_CHECKOUT}`. Aplicado a
  reservar, revelar, contactar, negociar e converter. Antes, contactar/negociar/
  converter não tinham gate e reservar/revelar respondiam 403 (que não comunica
  "renove"). O frontend já trata 402 como checkout.
- **Sessões no Admin**: `GET /api/admin/sessions`, `DELETE /api/admin/sessions/{id}`
  e `DELETE /api/admin/users/{id}/sessions`. A listagem lê `user_sessions.expires_at`
  (TTL 30 d) e a revogação apaga a linha — o dispositivo perde acesso no pedido
  seguinte (401). UI na Torre de Controlo ("Sessões ativas").
- **Onboarding Wizard** (`/[locale]/onboarding`): passo 1 ofícios + cidades,
  passo 2 valor do push antes da permissão nativa, depois grava e abre o dashboard.
  Endpoints novos: `GET/PUT /api/users/me/interests` e
  `GET/POST /api/users/me/onboarding` (este recusa lista vazia).
- **Gate de ativação**: o dashboard deixou de auto-persistir as 16 categorias
  quando o servidor devolvia vazio (isso marcava o utilizador como "configurado"
  com escolhas que ele nunca fez). Sem ofícios → `router.replace('/onboarding')`
  antes do feed. `/onboarding` entrou em `PROTECTED_PATHS`.
- Seed E2E: `e2e-token-novo` (sem interesses) para o wizard; `e2e-token-ciclo`
  ganhou 'Roof' para não ser redireccionado. **876 pytest**, 19 e2e, 74 vitest.

### Outbound — fila resiliente e diagnóstico (2026-10-31)

- **Sintoma**: 2 mensagens de Chicago presas 51 h com `queue_age=fail`; caixas
  em warm-up dia 2 com cap 1/dia.
- **Causa raiz estrutural**: dois `break` no tick. (1) cidade com
  `send_enabled=0` parava o tick inteiro (head-of-line blocking); (2) cidade
  cujas caixas esgotavam o cap parava tudo, mesmo com caixas de outras cidades
  vazias. O digest mostrava só o cap global, nunca o motivo real.
- **Motor**: `_pick_mailbox` passou a fazer duas passagens — caixa da cidade
  primeiro, depois **spillover** para qualquer caixa com folga. O tick continua
  para outras cidades quando uma está desligada/sem cap, com janela de scan de
  200 linhas (mensagens bloqueadas não escondem as de trás). Envio com exceção
  da Gmail marca `failed` e o tick continua; o reaper de `sending` corre também
  com `send_enabled=0`.
- **Diagnóstico**: `process_queue` devolve `blocked_reason`/`blocked_detail`/
  `retry_at`; `/outbound/status` expõe `queue_blocker`, `queue_oldest_*`,
  `mailbox_remaining_today`; a Torre de Controlo mostra o banner "Fila parada ·
  limite de caixa (0/2 hoje, warm-up dia 2) — retoma à meia-noite UTC".
- **Control Tower**: `queue_age` deixa de ser `fail` cego. Sem capacidade →
  `warn` com o motivo (cap/quiet hours/cidade desligada). Com capacidade e
  fila velha → `fail` "há capacidade mas a fila não avança" (stall real).
  O digest mostra `hoje x/cap` e `CAPACIDADE restam N`.
- Testes: `tests/test_outbound_queue_resilience.py` (8).

### Admin — Concessão manual de acesso (cortesia) (2026-10-31)

- **Fonte única**: a concessão escreve `users.subscription_status='active'` e
  `users.plan_until` — os mesmos campos que o Stripe. `is_access_active` passa a
  devolver `can_access=True` e o gate A5 (402) abre sem ramos novos.
- **Semântica**: soma dias a `max(agora, plan_until)`; **nunca encurta nem
  reinicia** um plano pago. `BEGIN IMMEDIATE` evita perder uma renovação
  concorrente do webhook.
- **Auditoria**: tabela nova `admin_audit_log` (append-only) com admin, alvo,
  dias, motivo, nota, `before_json`/`after_json`, IP e `idempotency_key`.
  Não usa `credit_ledger` (razão de créditos) nem `system_alerts` (anomalias);
  só concessões sensíveis (admin alvo ou >90 dias) geram `system_alert`
  `ADMIN_ACCESS_GRANT`.
- **API**: `GET /api/admin/users/lookup`, `POST /api/admin/access/grant`
  (30/h), `POST /api/admin/access/revoke`, `GET /api/admin/access/audit`.
- **Undo seguro**: restaura o `before` apenas se `plan_until` ainda for igual ao
  `after` da concessão; se houve pagamento posterior devolve **409**.
- **Copy**: `get_user_subscription_status` devolve `"Acesso ativo até dd/mm/aaaa"`
  quando a expiração em vigor veio de um grant (derivado da auditoria) e
  `"Plano ativo. Renova em Nd"` quando veio de assinatura. Depois de uma
  renovação Stripe, a origem volta a `subscription` sozinha.
- **UI**: `AccessGrantPanel` na Torre de Controlo, imediatamente acima de
  "Sessões ativas". Fluxo em 3 passos (procurar → duração/motivo → confirmar),
  preview do antes/depois, dupla confirmação para admins e tabela de auditoria
  com botão Reverter.
- Testes: `tests/test_admin_access_grant.py` (12) — soma, validação,
  idempotência, revogação segura, gate A5 e copy.

### Fase B — Segurança, CORS, headers e inglês no checkout (2026-10-31)

- **Endpoints dormentes**: `/api/scraper/enrich` e `/api/leads/{id}/enrich`
  passaram de “qualquer sessão” para `_require_admin_user` + limite (5/h e 10/h).
  Eram um vetor de abuso (até 500 consultas externas por request, sem uso na UI).
  `enrichLeads()` morto removido do cliente.
- **CORS**: removido o wildcard `project-*`/`-git-*` que aceitava
  `magicleads-oficial-evil.vercel.app` com credenciais. Agora só allowlist exata
  e domínio base Vercel exato; previews exigem entrada explícita.
- **Headers**: middleware backend + `next.config.js` com `X-Content-Type-Options`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` e CSP mínima
  (`frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'`).
- **Inglês no checkout**: `pickLang()` (novo) resolve
  localStorage → cookie → browser → **EN**. Copy EN do modal/página reescrita
  (“Start your 7-day access”, “Reactivate your access”, “We couldn't start
  checkout…”). Teste unitário do default + e2e `/en` com 402.
- Testes: 907 pytest (+11 de segurança), 22 e2e (+2), 83 vitest (+4).

### Fase C — Alerta de frescura de ingestão (2026-10-31)

- **Problema**: a Control Tower vigiava worker/fila/backup/VPS/tokens/Searchbug/
  push, mas **não** a ingestão. Uma fonte a mudar de schema podia parar o scraper
  com o sistema “verde”.
- **`_check_ingestion_freshness()`**: último run concluído (`success`/`partial`)
  com limiares derivados de `SCRAPER_INTERVAL_HOURS` (default 6 h → warn 10,5 h,
  fail 15 h; override por env). `error` posterior ao último sucesso → **fail**;
  `running` >2 h → **warn** (preso); sem data → warn.
- **Digest**: nova linha `INGESTAO` com estado/idade/inseridos e leads em 24 h.
- **Testes**: `tests/test_ingestion_freshness.py` (8) + digest com motivo;
  **916 pytest**, 22 e2e, 83 vitest.

### Fase E — polimento e hardening estrutural (2026-10-31)

- **Next 16.4.3** (React 18 mantido): `npm audit --omit=dev` = **0 vulnerabilidades**
  (antes 1 critical, 2 high). `viewport`/`themeColor` movidos para o export
  `viewport`; `middleware.ts` migrado para **`proxy.ts`** (convenção Next 16),
  com redirect 307 confirmado em produção para `/dashboard` sem cookie.
- **Índices**: `lead_reveals(user_id, revealed_at)`, `(lead_id)`, `(revealed_date)`,
  `(refunded, revealed_date)` e `notifications(user_id, read, created_at)`.
- **Cidades canónicas**: `canonical_served_cities()` dedupa `CHICAGO`/`Chicago`;
  `/api/metrics/public` passou de `cities_count: 5` para **4** em produção.
- **Higiene**: removido `_SESSIONS` (dict morto sem leitura); `_scrape_runs` podado
  a 50; `mark_stale_scraper_runs()` fecha runs presos em `running` no arranque.
- **Custo**: falhas em `record_outbound_enrichment_call` (Snov/ELV) agora geram
  `logger.warning` em vez de `pass`.
- **Admin**: painel “Saúde do motor” (checks + digest), cartão “Funil de checkout”
  e “marcar resposta” manual por contacto (trava a sequência). `fmtDt` trata UTC
  naive como UTC.
- **Segurança**: demo login fail-closed sem `DEMO_PASSWORD` e cookie `SameSite=Lax`;
  HMAC de clique exige `PUSH_CLICK_SECRET`/`CRON_SECRET` (fallback hardcoded
  removido); gate de onboarding cobre falha de `/interests`.
- **Qualidade**: ESLint 9 flat config (`npm run lint` = 0 erros), `pytest-cov`
  (baseline **66%** do backend), e2e do Admin com conta isolada
  `e2e-admin@magicleads.app` (grant → auditoria → revoke). **23 e2e**, 83 vitest,
  **928 pytest**, Ruff global limpo (23 avisos antigos de testes resolvidos,
  incluindo um teste duplicado `F811` que nunca corria).

### Passkeys / Face ID (WebAuthn) — MVP (2026-10-31)

- **Fluxo de retorno primeiro** (`ee12cb5`): `proxy.ts` deixou de perder o
  destino. Sessão ausente em `/pt/dashboard?lead=42` → `/pt/auth?next=…`; o
  `AuthForm` valida `next` (só caminho relativo) e regressa lá depois do login.
  Corrigido também o redirect de bloqueio (`//checkout` → `/{locale}/checkout`).
- **Zero custo externo**: a biometria nunca sai do dispositivo. O servidor
  guarda só a chave **pública** (`webauthn_credentials`), o challenge de uso
  único (`webauthn_challenges`, 5 min, consumo atómico com `BEGIN IMMEDIATE`)
  e metadados (transports, aaguid, label do dispositivo). `py_webauthn 2.8`.
- **Sessão igual à A2**: login por passkey emite `garimpador_token` +
  `user_sessions` com o mesmo TTL deslizante de 30 d. Sem segundo sistema de
  autenticação, sem JWT novo, sem serviço pago.
- **Segurança**: `rp_id` = `WEBAUTHN_RP_ID` (default `magicleads.app`),
  `user_verification=required`, `authenticator_attachment=platform`,
  `exclude_credentials` no registo e `allow_credentials` no login (descoberta
  por e-mail opcional, sem enumerar contas). `sign_count` regressivo gera
  `system_alert` `WEBAUTHN_CLONED_SIGNAL`.
- **UI**: botão “Entrar com Face ID” no ecrã de auth apenas quando o browser
  suporta WebAuthn **e** já há uma passkey neste dispositivo (hint local);
  painel “Segurança de acesso” nas Definições para ativar/remover; erros
  distintos para não suportado, sem passkey, cancelado e falha. A palavra-passe
  continua sempre disponível.
- **E2E real**: `e2e/passkey.spec.ts` usa o *virtual authenticator* do Chromium
  (CDP `WebAuthn.addVirtualAuthenticator`) — regista, limpa a sessão local e
  entra sem palavra-passe. RP ID em E2E = `localhost` (WebAuthn rejeita IPs).
- Testes: **937 pytest** (+6), **26 e2e** (+3 desde a Fase E), 83 vitest,
  Ruff/tsc/ESLint limpos (0 erros, 34 avisos antigos).

### Incidente — ativação de Face ID falhava em preview (2026-10-31)

- **Sintoma**: "Ativar Face ID neste dispositivo" devolvia sempre o genérico
  “Não foi possível ativar o Face ID. Tente novamente” em
  `magicleads-oficial.vercel.app` (report com screenshot).
- **Causa raiz**: o RP ID era fixo (`WEBAUTHN_RP_ID=magicleads.app`). O browser
  valida `rp.id` contra o host **antes** de chamar a rede:
  `magicleads.app` não é sufixo de `magicleads-oficial.vercel.app` →
  `SecurityError` em `navigator.credentials.create`. Nenhum pedido chegava ao
  `/verify`; o cliente convertia tudo em "failed" genérico. Não era CORS nem
  backend em baixo.
- **Correção (servidor)**: `_wa_rp_id(origin)` deriva o RP ID por pedido —
  `magicleads.app`/`*.magicleads.app` → canónico; outras origens só se estiverem
  na allowlist exata e usam o próprio host (sem wildcards). `rp_id`/`origin`
  ficam gravados no challenge e o `/verify` usa **esses** valores
  (`_wa_verify_context`). Erros passam a devolver código estável
  (`origin_not_allowed`, `verification_failed`, `challenge_invalid`,
  `credential_exists`, `passkey_not_recognized`).
- **Correção (cliente)**: `passkeyErrorFromException` mapeia o erro real do
  browser (`SecurityError`→domínio, `InvalidStateError`→já registado,
  `NotAllowedError`/`AbortError`→cancelado, `NotSupportedError`→sem suporte);
  pré-check `rp.id` vs `window.location.hostname` falha antes do autenticador;
  a UI mostra a mensagem certa **e** um “Detalhe técnico” com o erro original
  (para suporte). A palavra-passe continua na mesma linha.
- **Registo**: cada passkey fica ligada ao RP onde foi criada — uma passkey
  criada no preview não serve no domínio oficial (limite do WebAuthn, não bug).
- **Testes**: 5 pytest novos (RP oficial/www, preview Vercel, origem recusada
  com 403, verify a usar o RP gravado) e 7 vitest de mapeamento de erros;
  e2e de passkey continua verde em `localhost` (origem não-canónica real).

### Incidente — Android: “Face ID” e NotReadableError (2026-10-31)

- **Sintoma**: no Android o botão dizia “Entrar com Face ID” e a ativação
  falhava com `NotReadableError: An unknown error occurred while talking to
  the credential manager`.
- **Causa raiz (rótulo)**: copy fixa em “Face ID”, vocabulário só da Apple.
- **Causa raiz (erro)**: o registo pedia `authenticatorAttachment=platform` +
  `residentKey=preferred`. No Android isso encaminha o Chrome para o **FIDO
  API** (chave presa ao dispositivo); o desbloqueio pelo bloqueio de ecrã pode
  expirar e o Chromium mapeia o `UNKNOWN_ERROR` do Credential Manager para
  `NotReadableError`. Além disso o `user.name` ia como `user-32` porque
  `_get_current_user` só devolve o id — daí o Google Password Manager mostrar
  “user-32” e oferecer “Usar chave de acesso salva?” para uma credencial órfã.
- **Correção**:
  - Registo pede `residentKey=required` + `requireResidentKey`, sem forçar
    attachment → caminho do Credential Manager (passkeys sincronizadas).
  - `user.name` = e-mail e `displayName` = empresa (perfil carregado no options).
  - Handle do utilizador passou a **v2** (`sha256("…:v2:<id>")`) para não
    colidir com credenciais órfãs deixadas por registos que falharam no verify.
    O login resolve a conta pelo `credential_id`, por isso nada quebrou.
  - Rótulos/descrições por plataforma (Apple/Android/Windows/outro) em PT/EN/ES.
  - `NotReadableError`/`UnknownError` → código `unreadable` com instruções
    (desbloquear o ecrã, confirmar o gestor de senhas, repetir). O erro real
    continua no “Detalhe técnico”.
  - Resiliência: `attemptRef` ignora resultados atrasados de tentativas
    canceladas; `passkey_not_recognized` limpa o hint local (o botão deixa de
    aparecer até haver registo válido).
- **Testes**: pytest do options (e-mail, `residentKey=required`, sem
  attachment); vitest de `NotReadableError`/`UnknownError` e deteção de
  plataforma; e2e novo com UA Android garante “impressão digital” e ausência de
  “Face ID”. **942 pytest**, **92 vitest**, **27 e2e**.

### Incidente — Android: NotAllowedError com credencial existente (2026-10-31)

- **Sintoma**: já existia uma credencial “Android · Nunca usado”; clicar em
  “Ativar impressão digital” devolvia `NotAllowedError: The operation either
  timed out or was not allowed` e a UI dizia “Ativação cancelada”.
- **Causa raiz**: a UI oferecia **registo duplicado** no mesmo dispositivo. A
  credencial existente ia em `excludeCredentials`; no Android/Chrome esse
  caminho não devolve o `InvalidStateError` previsto — fica à espera e termina
  em `NotAllowedError`/timeout. O cliente ainda mapeava `NotAllowedError` para
  “cancelado”, mesmo quando o utilizador não cancelou nada.
- **Bug latente encontrado no caminho**: `_wa_descriptors` passava strings em
  `transports`; `options_to_json` faz `transport.value` e rebentava (500)
  quando a credencial tinha transports (ex.: `["internal"]`). Corrigido para
  `AuthenticatorTransport(...)`.
- **Correção**:
  - `device_id` opaco por browser (localStorage) gravado em
    `webauthn_credentials.device_id`; fallback pelo label para linhas antigas.
  - Se já há chave neste dispositivo: “Chave de acesso ativa neste dispositivo”
    + botão **Substituir** (em vez de “Ativar”).
  - Substituição envia `replace_credential_id`; o servidor **exclui** essa
    credencial de `excludeCredentials`, cria a nova e só depois a antiga é
    apagada (se o registo falhar, a antiga continua válida).
  - `NotAllowedError` com “timed out” → código `timeout` com instruções
    (desbloquear o ecrã, manter aberto), separado de “cancelado”.
- **Testes**: pytest (device_id sanitizado, substituição fora do exclude,
  transports serializáveis), vitest do `timeout`, e2e de substituição garante
  **1** credencial com id novo. **944 pytest**, **93 vitest**, **28 e2e**.

### UX — cancelamento e chave antiga (2026-10-31)

- **Cancelar ≠ timeout**: o Chrome devolve sempre `NotAllowedError` com
  “timed out or was not allowed”, mesmo quando o utilizador fecha a caixa
  nativa. A distinção passou a ser pelo tempo até à rejeição: <25 s →
  `cancelled` (“Login por biometria cancelado”, curto); ≥25 s → `timeout` com
  instruções. O detalhe técnico continua disponível.
- **Chave antiga (`user-32`)**: ao escolher no Google Password Manager uma
  credencial que o servidor não conhece, o `/verify` devolve
  `passkey_not_recognized`; a UI explica que a chave não pertence à conta,
  manda entrar com a palavra-passe e ativar uma nova, e limpa o hint local.
  O bloco de erro passou para **fora** do bloco do botão — antes, limpar o hint
  desmontava o botão e a explicação desaparecia com ele.
- **Testes**: e2e novo simula exatamente isso (regista, apaga só no servidor,
  escolhe a órfã, confirma a mensagem e que o botão desaparece mas o detalhe
  fica); vitest cobre a distinção por tempo. **944 pytest**, **93 vitest**,
  **29 e2e**.

### Incidente — cap de caixa e quiet hours (2026-10-31)

- **Auditoria de produção** (read-only, Railway/SQLite): 8 e-mails aceites pela
  Gmail API (Pamela 5, Pedro 3), 0 falhas, 0 stale, 1 bounce suprimido. O motor
  estava **vivo** (tick 60 s, inbox sync e backup OK) mas **subaproveitado**:
  10 contactos, todos de Chicago, `enrich_enabled=0`.
- **P0-1 — cap violado no mesmo tick**: em `995007d`, `_pick_mailbox` passou a
  devolver `dict(pool[0])` (cópia). O incremento de `sent_today` em
  `process_queue` alterava a cópia, não o snapshot; a mesma caixa voltava a ser
  escolhida. Prova real: Pamela com `daily_cap=1` enviou **2** a 31/10
  (`sent: 2` no log). Corrigido para devolver a **referência** ao snapshot;
  regressão coberta por dois testes (cap 1 + 2 mensagens → 1 envio; duas caixas
  cap 1 → 1 cada).
- **P0-2 — quiet hours em UTC**: os envios saíam às 03:00 ET porque a janela
  22:00–07:00 era comparada em UTC. Passou a comparar em
  `America/New_York` (com DST via `zoneinfo`); `quiet_hours_end_iso` converte
  o fim de volta para UTC. Testes de verão/inverno e `retry_at`.
- **P2 — observabilidade**: log por envio
  (`[OUTBOUND] Enviado msg=… caixa=… provider=…`) e por falha; o
  `/outbound/status` passou a trazer `last_send_at`, `sent_48h`, `failed_48h`,
  `skipped_48h` e `last_error` por caixa; novo
  `GET /api/admin/outbound/mailbox-health?hours=48`; o painel Admin mostra
  “48 h (env/falha)”, “Último envio” e o último erro na tabela de caixas.
- **Testes**: **950 pytest** (+6), tsc/ESLint/Ruff limpos (34 avisos antigos).

### Fase 1 — Auto-Ramp, disjuntor e Admin segmentado (2026-10-31)

- **Auto-Ramp** (`backend/services/auto_ramp.py`): escada 1→75, teto
  `auto_ramp_max` (default 75, máx. 100), avaliação 1×/dia. Abaixo de 25 sobe
  por warm-up; a partir de 25 exige ≥200 envios/30 d, bounce <1%, complaint
  <0.1% e zero auth errors. Auditoria em `mailbox_ramp_log`; `hold_reason`
  visível no Admin. Ao ligar a rampa, parte do cap efetivo atual (nunca salta
  para 25).
- **Disjuntor** (`mailbox_guard.py`): pausa com bounce >2% (≥20 envios),
  2 bounces consecutivos, complaint >0.1% ou 401/403/invalid_grant; alerta
  `MAILBOX_PAUSED`; retoma manual. Bounces passam a ser registados por caixa
  (`mailbox_bounce_events`) no inbox sync.
- **Admin**: cartão “Prontos para enviar” por cidade+nicho; switches
  `send_enabled`/`enrich_enabled` **por cidade**; editor de `daily_cap`,
  Auto-Ramp e teto por caixa; pausar/retomar. Endpoints `readiness`,
  `mailboxes/{id}/controls|pause|resume|ramp-log`.
- **Segurança**: `auth_ref` encriptado em repouso com `MAILBOX_SECRET_KEY`
  (Fernet); migração re-encripta no arranque.
- **Testes**: 18 pytest novos (auto-ramp, disjuntor, readiness/controles,
  encriptação); suite **971 pytest**, 29 e2e, 34 avisos ESLint antigos.

### Fase 2.1 — Grafo de empreiteiros e resolver OSM (2026-10-31)

- **Tabelas**: `contractor_entities` (empresa, licença, cidade/estado, papel,
  domínio, nicho, e-mail, estado), `contractor_entity_sources` (proveniência
  idempotente por fonte+registo) e `city_enrichment_state` (cursor/quota).
- **Normalização**: remove sufixos legais (`LLC`, `INC`, `CORP`, …), acentos e
  pontuação; `entity_key = sha256(nome+estado)`. Dedupe por **licença** quando
  existe (chave forte) e por nome normalizado caso contrário. Placeholders
  (`UNAVAILABLE OWNER`, `N/A`, …) nunca criam entidade.
- **Ciclo**: `new → domain → ready` ou `quarantined` (e-mail `catch_all` ou
  sem site). Fontes idempotentes (`UNIQUE(source, external_id, role)`).
- **Resolver** (`domain_resolver.py`): Overpass por nome+cidade, tags
  `website`/`contact:website`, `registrable_domain`, corroboração Jaccard
  ≥0.5. Sem correspondência → `None` (quarentena), nunca adivinha.
- **Testes**: 12 (normalização/dedupe/licença/fontes/ciclo + resolver/query).
  Suite **984 pytest**.
- **Ainda por ligar**: extração nos ingestores (NYC `applicant_*`, Chicago
  `contact_*`, fontes de Dallas/Boston), estágio de e-mail, scheduler 24/7 e
  UI de entidades.

### Fase 2.2 — Ingestão de entidades NYC/Chicago/Boston (2026-10-31)

- **Extratores** (`contractor_ingest.py`), funções puras:
  - NYC: `applicant_business_name` + `applicant_license` (novo no select do DOB),
    papel contractor; `job_filing_number~work_permit` como fonte idempotente.
  - Chicago: leitura dedicada de `contact_N_type/name` (o fetch genérico não
    os traz); só `CONTRACTOR-*` e `MASON*`; prefixo de licença
    (`PL058130279-`) separado do nome.
  - Boston: o 311 não tem empreiteiro; passa a ler o dataset público
    **Approved Building Permits** e só aceita `applicant` com indicador
    empresarial (pessoa não vira entidade).
  - Owners/architects ficam fora (não são alvo comercial).
- **Proteção do scrape**: `_record_contractor_entities` deduplica antes da BD,
  limita a 2000 registos/run e nunca propaga exceção para o scrape.
- **Dry-run real (amostras de 200 linhas, sem escrita)**:
  - NYC: 200 linhas → **195 entidades / 111 únicas**.
  - Chicago: 200 → **147 / 117 únicas**.
  - Boston: 200 → **5 / 4 únicas** (fonte é maioritariamente pessoa, como
    esperado).
- **Testes**: 4 novos (extratores + dedupe na BD); suite **988 pytest**.
- Dallas continua pausada até haver fonte pública de permits.

### Fase 3 — Scheduler autónomo de enriquecimento (2026-10-31)

- **`enrichment_scheduler.py`**: loop 24/7 em processo (60 s), concorrência
  global 4, quota **300/cidade/dia** (`ENRICH_ENTITIES_PER_CITY_DAY`), cidades
  `NYC,CHICAGO,BOSTON` (`ENRICH_ENTITY_CITIES`); Dallas fora até haver fonte.
  Só atua com `enrich_enabled=1` na cidade; nunca envia e-mail.
- **Estágios**: `new` → OSM/Overpass (throttle ~1,1 s) → `domain` → SMTP RCPT
  com prova de catch-all → `ready`; sem site/catch-all/sem e-mail após 2
  tentativas → `quarantined` com `quarantine_reason`.
- **Persistência**: `domain_checked_at/attempts`, `email_checked_at/attempts`,
  `quarantine_reason`; cursor/quota em `city_enrichment_state`.
- **Admin**: bloco “Entidades” com `new/domain/ready/quarantined`, quota do dia
  e botão “Correr enriquecimento”; endpoints `/api/admin/contractors/stats|run|
  entities`.
- **Reconciliação**: `contractor_release_tracking/penalties/metrics` são
  métricas operacionais de liberação/penalidade (45/0/5 linhas), **não**
  identidade; não foram fundidas em `contractor_entities` para não misturar
  conceitos. Ficam como histórico operacional.
- **Testes**: 5 scheduler (domain→email→ready, sem domínio 2×→quarentena,
  catch-all, cidade desligada, quota) + 1 stats. Suite **994 pytest**.

### Fase 3.1 — Ponte `ready → outbound_contacts` (2026-10-31)

- `entity_bridge.py`: entidade `ready` passa por `niche_classifier.classify`;
  só com `confirmed` cria lead `import_b2b` + `outbound_contacts`
  (`email_source='import'`, `niche_status='confirmed'`) e marca
  `bridged_at/outbound_contact_id/outbound_lead_id`. Sem nicho confirmado →
  `quarantined` (`niche_unconfirmed`), sem contacto. Idempotente por e-mail.
- O scheduler faz a ponte logo após o e-mail validado e também drena entidades
  `ready` antigas (`list_entities_for_bridge`). Nunca envia e-mail.
- UI “Prontos para enviar” passa a refletir o inventário real do robô, porque
  a contagem é de `outbound_contacts`.
- Testes: 2 novos (bridge cria contacto/lead e readiness=1; nicho não
  confirmado não cria contacto). Suite **995 pytest**.

### Fase 3.2 — Snippet do site no nicho (2026-10-31)

- O `DomainResult` passa a devolver `snippet` (texto da homepage) e o
  scheduler guarda-o em `contractor_entities.site_snippet`.
- A ponte classifica com `name + domínio + texto do site`; quando falta o
  snippet, descarrega a homepage uma vez e persiste-a. Um único token no nome
  vale 2.0 (limiar 3.0), por isso o texto do site é o que confirma
  `general_contractors`, `plumbing`, `hvac`, etc.
- No ensaio real isto recupera e-mails válidos que antes caíam em
  `niche_unconfirmed` (Formlinea, Nomis, Star Tuckpointing, RAM Mechanical…).
- Testes: snippet guardado e ponte a confirmar nicho pelo site; suite
  **1000 pytest**.

### Fase 3.3 — Anti-falso-positivo de domínio (2026-10-31)

- O ensaio apanhou um erro grave: `OZ CONTRACTING`, `P B CONTRACTING` e
  `D.R. CONTRACTING` resolveram todos para `contractingnyc.com` (diretório),
  porque só a palavra genérica CONTRACTING coincidia com o título.
- `identity_ok()`: o site tem de conter um token **distintivo** do nome (no
  domínio ou no título); nomes só com termos genéricos exigem o nome completo.
- Domínio partilhado por duas empresas → `quarantined/shared_domain` (é
  diretório, nunca o site de cada uma).
- `pipe\w*` do nicho plumbing deixou de casar “pipe scaffolding” (falso
  plumbing); `scaffold/masonry/tuckpoint/signs/signage` passam a contar para
  general contractors.
- Testes: identidade, diretório e domínio partilhado; suite **1002 pytest**.

### Fase 4 — Copy v2, rampa acelerada e Brave (2026-11-01)

- **Copy v2** (aprovada pelo owner): exclusividade real ("one contractor at a
  time - first come, first served"), "property details" em vez de homeowner,
  saudação com o nome da empresa (`Hi Kelso-Burnett Co. team,`), assinatura
  Pamela, morada postal `110-33 64th Rd, Forest Hills, NY 11375` e
  `Unsubscribe: <link assinado>` + `reply "unsubscribe"`.
- **Passo 2**: `{count}` dinâmico (fim do "300" fixo), categoria derivada do
  nicho (nunca "construction" para um canalizador) e "one closed job covers
  the week".
- **Opt-out**: token HMAC `base64url(email).sig`, `GET/POST /unsubscribe`,
  `List-Unsubscribe` + `List-Unsubscribe-Post` no envio. Sem segredo o link
  cai para a página genérica (fail-closed) e o opt-out por resposta mantém-se.
- **Inventário**: `import_b2b` deixou de contar como "oportunidade" no
  `{count}` e na mistura de categorias — é destinatário, nunca projeto.
- **Auto-Ramp**: `STEP_INTERVAL_DAYS` (2 dias até 8, 3 até 25, 4–7 acima) em
  vez de 7 dias fixos; gates de amostra/bounce/complaint/auth mantidos.
  Ligado nas duas caixas (max 75, `per_mailbox_daily_cap=75`); primeira
  avaliação subiu 1 → 2/dia em ambas.
- **Brave Search**: `brave_search.py` com candidatos → verificação
  DNS/HTTP + `identity_ok` + cidade, cache de 30 dias (negativo incluído) e
  orçamento diário em `system_kv` (450 queries). Quota de enriquecimento
  750/cidade/dia (default do scheduler). Inerte até `BRAVE_SEARCH_API_KEY`.
- **Admin**: `/api/admin/outbound/capacity` + cartão "Capacidade vs
  inventário" (prontos agora, produzidos/dia, envio/dia, cobertura, por
  cidade). Primeira leitura: 22 prontos, 3,7/dia produzidos, 4/dia de
  capacidade, 5,5 dias de cobertura.
- **Testes**: 1017 pytest (1 skip), Ruff limpo, tsc limpo, ESLint 0 erros.

### Fase 5 — Fontes orgânicas gratuitas (2026-11-01)

- **NYC DCWP**: `licensing_sources.py` ingere `Home Improvement Contractor`
  ativos (Socrata `w7w3-xahh`), com telefone e licença. Backfill: **13.385
  linhas → 13.383 entidades**, 9.855 novas (as restantes já existiam). O
  telefone alimenta o `corroborate()`, que usa `phone_match` como sinal forte.
- **OSM (salta a Brave)**: `osm_extract.py` descarrega extracts BBBike,
  filtra `craft=*`/`office=construction_company` por bbox e grava o domínio do
  website diretamente. Medido: NYC 251 (70 com site), Chicago 53 (25), Dallas
  30 (25). Boston removido (311 MB/19 min para 15 empresas).
- **Fila por intenção**: `list_entities_for_domain|email` ordena por telefone,
  depois licença, depois id.
- **Incidente e recuperação**: o backfill levou o WAL a 257 MB num volume de
  434 MB e encheu `/data` (disk I/O error). Recuperado com checkpoint+VACUUM de
  uma cópia e swap do ficheiro; **13.395 entidades e 17 mensagens intactas**.
  Guardas: `journal_size_limit=64 MB`, checkpoint a cada 30 ticks, checkpoint
  após cada ingestão e bloqueio de ingestão com <120 MB livres.
- **Testes**: 1033 pytest.

### Fase 6 — TDLR, OSINT do dono e check pós-deploy (2026-11-01)

- **TDLR (Texas)**: 4 CSVs públicos (A/C, eletricistas, sign, elevadores)
  filtrados ao metro de Dallas (cidade **ou** condado de Dallas). Resultado:
  **3.630 entidades** em 4,9 s, com telefone e licença. Dallas passou de 30
  para **4.468 entidades**.
- **Owner-email OSINT**: crawl de `/about`, `/team`, `/about-us`, `/contact`;
  extrai nome + cargo, gera padrões (`first@`, `first.last@`, `f.last@`,
  `jsmith@`, …) e valida por RCPT no worker VPS. Catch-all nunca é aceite.
  Primeiro achado real: `springscaffolding.com → tony.halasz@…`.
- **Pós-deploy**: `post_deploy_check.py` corre antes do uvicorn, valida
  `quick_check`, WAL, espaço e escrita real; grava em `system_kv`. Primeira
  execução: `status ok, 265 MB livres, integrity ok, writable true`.
- **Testes**: 1039 pytest.

### Fase 7 — Licenças de Chicago e diretórios de associações (2026-11-01)

- **IL IDFPR** (`data.illinois.gov/pzzh-kp68`): a única base estadual com
  contractor de construção é `ROOFING CONTRACTOR`. Filtrado a Chicago ativo:
  **1.238 entidades** (1.265 linhas) com licença e zip, em 16 s.
- **Chicago Business Licenses** (`uupf-x98q`): poucos ofícios (plumbing 0,
  electrical 16; a licença de ofício é estadual). Filtro construção/contratação/
  elétrica rendeu **216 entidades**.
- Chicago passou de 1.967 para **3.387 entidades**.
- **Associações: sem parser viável.** Testados AGC Chicago (sem diretório),
  AGC NYS (só info), Texas Builders (403), BRAGB (Wix/JS), BXNet (lista de
  associações, não de empresas), Dallas Builders (`/member-directory` e
  `web.dallasbuilders.org` atrás de Cloudflare 403); três domínios já não
  resolvem. Contornar 403/Cloudflare está fora de questão.
- **Testes**: 1041 pytest.

### Fase 8 — Chicago elétrico e KPI de origem do e-mail (2026-11-01)

- **Filtro de Chicago corrigido**: exigia prefixo `CONTRACTOR` e perdia
  `ELECTRICAL CONTRACTOR` (261.787 registos no dataset). Agora aceita qualquer
  tipo com `CONTRACTOR` (exceto `OWNER AS GENERAL CONTRACTOR`) e mantém
  `MASON`. Dry-run em 10.000 permits: **18.023 entidades → 4.184 únicas**;
  Chicago passou de 3.387 para **5.493**.
- **Origem do e-mail rastreada**: `contractor_entities.email_source`
  (`smtp_pattern` vs `owner_osint`) propaga-se ao contacto via
  `import_b2b_lead(email_source=...)`. `/outbound/metrics` ganhou
  `by_email_source` (contactos, respostas, positivas, taxas) e o cartão do
  Admin mostra a linha “Por origem do e-mail”.
- **IDFPR sem plumbing/electric**: confirmado por consulta direta — só existe
  `ROOFING CONTRACTOR`. Os datasets de eletricistas do catálogo federado são
  de Vermont, Louisiana, Buffalo, Montgomery e Delaware.
- **Volume**: ainda 263 MB livres no `/data` (resize para 2 GB pendente do
  lado do Railway).
- **Testes**: 1041 pytest.

### Fase 9 — Backfill de Chicago, volume 1 GB e avaliação de Boston (2026-11-01)

- **Backfill de Chicago**: 85.000 permits antigos (offsets 10k–95k) em 17
  páginas, **384 s**; ~150k registos extraídos, **49.470 upserts**. Chicago
  passou de 5.493 para **11.887 entidades** (+6.394).
- **Volume**: resize para 1 GB aplicado — **700 MB livres** no `/data`.
- **KPI por origem**: `/outbound/metrics` devolve `by_email_source`; nesta
  janela só há 8 contactos antigos (`import`), 0 respostas. A comparação
  `owner_osint` vs `smtp_pattern` começa a encher com os próximos bridges.
- **Massachusetts**: sem dados em massa. `data.mass.gov` é um hub Next.js sem
  API de catálogo; `mass.gov/.../check-a-license` devolve 403 e o eLicensing
  recusa ligação. Boston fica com OSM (8 domínios) + permits até haver
  exportação/parceria.
- **Testes**: 1041 pytest.

### Fase 10 — Brave 2.000/dia, quota corrigida e ramp (2026-11-01)

- **Brave**: `BRAVE_DAILY_QUERIES=2000` na Railway (≈$10/dia no pico) e
  disjuntor para 401/402/429: se a Brave recusar por quota/plano, o dia fica
  marcado em `system_kv` e o provider para de consumir. No primeiro check:
  758 usadas de 2.000.
- **Quota por cidade corrigida**: `bump_city_enrichment_state` sobrescrevia
  `jobs_today` com o valor do último ciclo (mostrava "hoje 4/750" e nunca
  bloqueava). Agora acumula no mesmo dia e reseta à meia-noite; teste cobre.
- **Ramp**: as duas caixas mantêm 2/dia e o avaliador devolve `hold: interval`
  — a subida para 3/dia acontece na janela de 03/11, como desenhado (2 dias
  por degrau). Bounce 0,0% e complaint 0,0% em 30 dias.
- **Testes**: 1043 pytest.

### Fase 11 — Monitorização da ramp e orçamento Brave real (2026-11-01)

- **Ramp log** visível no Admin: `auto_ramp_last_step_at` na linha de cada
  caixa. Histórico confirma 1→2 em 01/11 00:43 (`healthy`), próxima subida
  em 03/11 (intervalo de 2 dias para cap 2). Bounce/complaint 0/0.
- **Quota por cidade** a acumular corretamente: NYC 19, Chicago 15, Dallas 8
  no mesmo dia (antes ficava sempre em 4-5).
- **Orçamento Brave**: o saldo de $6,13 ≈ 1.226 queries a $5/1.000. A
  2.000/dia isso dura **menos de um dia** (~$10/dia); a 250/dia dura ~5 dias
  (~$1,25/dia). Limite reduzido para **250/dia** por proteção até haver
  recarga; o disjuntor 401/402/429 continua a travar em caso de saldo zero.
- **Capacidade vs orçamento**: 250 queries/dia ≈ 60 prontos/dia (suporta
  ~60 envios/dia); 750/dia ≈ 190 prontos (150+ envios); 2.000/dia ≈ 500.
- **Testes**: 1043 pytest.

### Fase 12 — Fila 50/50 por origem do e-mail (2026-11-01)

- `list_queued_outbound_messages_balanced` intercala `owner_osint` e
  `smtp_pattern` 1:1, começando pela origem com menos envios nas últimas
  24 h; sem as duas origens mantém FIFO. O motor usa esta lista, o que
  duplica a velocidade de acumulação da amostra sem enviesar o KPI.
- Brave mantido em **250/dia** por decisão de custo; o contador de hoje
  (780, da janela anterior de 2.000) fecha o dia e volta a 0 às 00:00 UTC.
- Ramp: ambas as caixas em 2/dia, `hold: interval`, última subida 01/11
  00:43 — próxima a 03/11.
- **Testes**: 1045 pytest.

### Fase 13 — Upgrade OSINT dos prontos (2026-11-01)

- `upgrade_contact_email` troca o e-mail genérico por um nominal comprovado
  (contacto + lead B2B + entidade na mesma transação), com guardas: nunca com
  mensagem ativa, nunca colide com e-mail existente.
- Script `upgrade_ready_osint`: **147 prontos analisados → 12 atualizados**
  (8,2%). Exemplos reais: `tom.graham@airoom.com`, `jake@purevoltage.com`,
  `tony.halasz@springscaffolding.com`, `dlong@bigskyconstruction.com`.
- Pool pronto: 136 `import`, 5 `smtp_pattern`, **12 `owner_osint`**.
- Bug do script corrigido: `list_contractor_entities` tem limite 200 e
  escondia os prontos; passou a filtrar `status="ready"` no SQL.
- **Gap operacional identificado**: a fila só recebe lotes quando o Admin
  clica “Enviar lote real”; não há criação automática de lote. Com 1 mensagem
  na fila, o envio para quando ela sair.
- **Testes**: 1048 pytest.

### Fase 14 — Auto-lote (2026-11-01)

- Loop no worker (60 s) chama `auto_batch.maybe_create_batch()`: se
  `send_enabled=1`, fora das quiet hours, fila <3, capacidade do dia >0,
  cooldown de 10 min e cidade/nicho ligados, cria um lote com
  `min(prontos, capacidade, 8)` e chama `enqueue_batch` (nunca envia).
- Escolha do par (cidade, nicho) maximiza `owner_osint` **e** `generic` no
  mesmo lote — primeiro Dallas/GC (2 osint + 5 generic), para o 1:1 arrancar.
- Verificado em produção: com 4/4 já enviados hoje devolve `no_capacity`
  (guarda correta). O primeiro lote automático sai quando o contador UTC
  reinicia (00:00 UTC = 20:00 EDT) e depois às 11:00 UTC.
- Quirk conhecido: o cap diário usa o dia **UTC** (reinicia às 20:00 EDT),
  não a meia-noite de Nova Iorque.
- **Testes**: 1055 pytest.

### Fase 15 — Dia operacional em Nova Iorque (2026-11-01)

- `timeutil.py`: `day_key`/`day_start_utc`/`next_day_start_utc` com
  `ZoneInfo("America/New_York")` e fallback UTC. O cap diário, o contador por
  cidade, o eval do Auto-Ramp e o `retry_at` passam a cortar à meia-noite de
  NY (antes 00:00 UTC = 20:00 EDT).
- `count_mailbox_sent_today` compara `sent_at` com o início do dia NY
  convertido para UTC (DST tratado). Em produção: dia `2026-11-01`, início
  `04:00 UTC`, próxima meia-noite `2026-11-02 05:00 UTC`.
- Copy do bloqueio corrigida para “meia-noite de Nova Iorque”.
- **Testes**: 1055 pytest.

### Fase 16 — Primeiro lote 100% autónomo e export de copy (2026-11-01)

- O auto-lote criou sozinho o lote `auto-20261101-1646-dallas-general_contractors`
  (Dallas/GC): **4 mensagens enfileiradas, 3 enviadas** (limite de capacidade
  do dia) e 1 em fila. Primeiro envio sem clique humano.
- A mudança para o dia NY (início 04:00 UTC) reclassificou os 4 envios das
  00:00 UTC para o dia anterior, libertando capacidade — efeito único da
  transição, sem violar o cap por dia NY.
- `docs/OUTBOUND-COPY.md`: export completo dos textos em produção (passo 1,
  passo 2, variáveis por nicho, exemplos reais, conformidade) e estado do A/B:
  **não existem variantes de copy**; o 1:1 atual é por origem do e-mail.
  Três variantes propostas para aprovação.
- **Testes**: 1055 pytest.

### Fase 17 — Landing: painel de amostra localizado e fim do flash de zeros (2026-11-01)

- O painel de amostra da landing tinha os 12 leads hardcoded em português
  (categoria, gravidade e descrição) e aparecia em PT na versão `/en`. Passou a
  ler `landing.sampleLeads` (bloco `id|ofício|gravidade|descrição`) + as chaves
  `landing.badge.*`, com tradução EN/PT/ES. Rua, bairro, nome e telefone
  continuam na base (são iguais nos três idiomas).
- **Flash de zeros**: o hero arrancava com `EMPTY_PUBLIC_METRICS` e mostrava
  “0 jobs in the bank right now”, “0+ leads”, “0+ with owner”. O estado passou a
  ser `null` até a API responder: o kicker mostra `landing.heroLoading`, os
  dois números mostram “—” e a linha “· N new opportunities” só aparece com
  dados reais. Cidades mantém 4 (é um facto conhecido, não uma métrica).
- **Testes**: 1055 pytest · 93 vitest · tsc limpo · ESLint 0 erros.

### Fase 18 — A/B de texto do passo 1 com gate de volume (2026-11-01)

- Três variantes novas do primeiro e-mail, traduzidas da landing: `five_crews`
  (concorrência/margem), `owner_asked` (velocidade e contacto direto) e
  `limited_spots` (escassez por área). `control` mantém a copy atual com CTA
  “reply send”, como base de comparação.
- **Gate**: `OUTBOUND_COPY_VARIANT_MIN_SENDS` (default **20** envios no dia de
  Nova Iorque) e `OUTBOUND_COPY_VARIANTS_ENABLED`. Abaixo do limiar tudo sai em
  `control`; acima, rotação **1:1:1:1** por lote. O A/B nunca divide uma amostra
  pequena.
- Atribuição persistida em `outbound_messages.copy_variant` (nova coluna, com
  migração `ALTER TABLE`); linhas antigas e passo 2 são lidas como `control`.
  `outbound_metrics` passa a devolver `by_copy_variant` e o estado do gate,
  mostrados no cartão de métricas do Admin.
- Duas frases ajustadas para não prometer o que a landing não promete:
  `owner_asked` diz “the phone number **when we find it**”; `limited_spots` diz
  “one contractor **at a time**” (a exclusividade real é a reserva de 1 hora;
  “once taken, it is gone” exigiria venda única permanente).
- `docs/OUTBOUND-COPY.md` reescrito: os dois eixos de teste (origem do e-mail e
  texto), os quatro braços, o gate e a amostra necessária (≥300 envios/braço).
- **Testes**: 1064 pytest · 97 vitest · tsc limpo · ESLint 0 erros.

### Fase 19 — Teto e número do dia vêm das mensagens (2026-11-01)

- O `/outbound/status` somava `outbound_daily_counters.sent` por cidade e o
  tick usava esse contador para o `daily_send_cap`. Após o restauro da BD o
  contador ficou acima da realidade (**8** no cartão para **4** mensagens
  enviadas), o que inflacionava o número mostrado ao dono e podia bloquear uma
  cidade cedo demais.
- Agora `count_outbound_sent_today(day, city=None)` lê `outbound_messages`
  (`status='sent' AND sent_at >= 00:00 NY`), com filtro opcional de cidade. É a
  mesma fonte usada pelo gate do A/B de texto.
- O tick guarda o contador por cidade em cache e incrementa-o no próprio tick
  após cada envio, para o teto ver a folga gasta de imediato.
- **Testes**: 1066 pytest (2 novos) · 97 vitest · tsc limpo · Ruff limpo.

### Fase 20 — Auditoria preditiva do cruzeiro (2026-11-01)

- **Rampa:** o intervalo era comparado ao segundo, mas a avaliação é 1x/dia com
  jitter de até 60 s; um degrau podia escorregar um dia inteiro (`hold:
  interval` com a marca diária já escrita). `INTERVAL_TOLERANCE = 1 h` absorve
  o jitter. Simulação com os valores reais: 03/11 `2→3`, 05/11 `3→5`; nunca
  sobe dois dias seguidos nem salta degraus.
- **Fuso:** teste fixa a mudança de hora (`01/11` começa 04:00 UTC em EDT;
  `02/11` começa 05:00 UTC em EST) e o dia operacional.
- **Links:** `sequence_url` passou a usar `urlencode` (tokens crus com `&` ou
  espaço nunca partem o redirect). 64 combinações cidade×nicho×passo
  verificadas com `parse_qs`; 8 URLs reais devolvem 200; cada variante tem um
  único link de campanha.
- **Disjuntor:** testes novos para complaint >0,1%, limites exatos (2,0% e
  0,1% não pausam) e para a garantia de que o Auto-Ramp nunca retoma uma caixa
  pausada. Auth, 2 bounces consecutivos e bounce >2% já estavam cobertos.
- **Produção (read-only):** `integrity_check`/`quick_check` ok, WAL 0,1 MB,
  693 MB livres, 0 mensagens presas, 0 duplicadas, 0 falhas 7 d, 0 erros nos
  logs, RSS 53 MB, 2 threads.
- **Dívida encontrada:** `PRAGMA foreign_keys=0` deixou 1.058 linhas órfãs em
  tabelas de dashboard (`lead_case_history` 912, `credit_ledger` 52, …); o
  domínio de envio tem **0** órfãos. Limpeza fica para tarefa separada.
- Relatório completo: `docs/PREDICTIVE-AUDIT.md`.
- **Testes**: 1077 pytest (11 novos) · Ruff limpo.

### Fase 21 — Consistência de nicho entre fila e envio (2026-11-01)

- O enfileiramento escrevia copy e URL com o nicho do **destinatário**
  (`contact.niche_key` confirmado), mas o re-render de envio usava o nicho do
  **lote**. Num lead de categoria partilhada (`Roof` em `general_contractors` e
  em `roofing`; `Paint` em GC/remodeling; `Gas` em electrical/hvac) o e-mail
  podia sair com texto de um nicho e link de outro.
- `_recipient_niche(contact, batch_niche)` centraliza a regra: nicho do
  contacto quando `niche_status="confirmed"`, senão o do lote. Aplicado em
  `_render_message` (passos 1 e 2) e em `schedule_next_steps`.
- Teste novo captura o corpo no enfileiramento (gate A/B forçado aberto), faz o
  re-render de envio e exige que a URL seja **exatamente igual**; teste unitário
  cobre o fallback sem nicho confirmado.
- **Testes**: 1079 pytest · Ruff limpo.

### Fase 22 — Performance do dashboard: qualificação materializada (2026-11-01)

- **Causa medida**: `get_leads_feed` custava **555 ms** (258 ms `COUNT` + 297 ms
  página) e **3 074 ms** a frio. O filtro de ruído faz 20 `LIKE '%…%'` sobre 5
  colunas; o planner usava `idx_leads_category` + `TEMP B-TREE FOR ORDER BY`
  sobre 13 mil linhas. Todo o resto do dashboard estava abaixo de 130 ms.
- Colunas materializadas `is_junk`, `is_feed_ok` e `is_qualified`, recalculadas
  na escrita (`insert_lead`, `update_lead_historical`, `update_lead_freshness`)
  e no backfill de arranque (só linhas NULL, ~2 s medidos numa cópia).
- Índices `(is_feed_ok, date_reported DESC, id DESC)`,
  `(is_qualified, date_reported DESC, id DESC)` e
  `(is_qualified, city, issue_category)`.
- `get_leads_feed`, `count_qualified_contractors_in_city` e
  `get_dashboard_summary` leem as colunas. Benchmark na cópia: **13 ms** count e
  **0,4 ms** página (de 258/297).
- Cache in-process de 60 s em `get_stats` e `get_public_metrics`, invalidado no
  fim de cada run de ingestão (`record_scrape_run`).
- `/daily-stats` deixa de correr `expire_holds`/`check_reveal_watchdogs`
  (escritas a cada poll de 60 s); ficam no watchdog de 15 min e no cron.
- **Paridade**: teste compara nos dois sentidos os ids das colunas com
  `_qualified_where`/`_feed_where`, cobre lixo/morada curta/categoria/fechado/
  legado e verifica o recálculo na escrita. Relatório em
  `docs/PERFORMANCE-AUDIT.md`.
- **Testes**: 1084 pytest · Ruff limpo.

### Fase 23 — Frontend: SWR, AuthProvider e ondas (2026-11-01)

- **AuthProvider** no layout do locale: `/me` + `/subscription-status` deixam de
  repetir-se a cada página montada (eram 2 chamadas por transição). Login
  password/passkey/demo atualizam o provider (o demo passou a chamar
  `updateUser`).
- **SWR 2.5.1** (`frontend/package.json`) com `SWRConfig` no layout do
  dashboard: cache persiste entre rotas, `stale-while-revalidate`,
  `keepPreviousData`, dedupe de 5 s e polling pausado com a aba oculta.
- Ondas: o feed é a única chamada que bloqueia a lista; stats/resumo/scraper/
  métricas públicas entram depois, com keys fixas (mudar filtros refaz só o
  feed). Interests, notificações, métricas de penalidade e quota diária também
  passaram a SWR.
- Links de Configurações/voltar levam o locale e fazem `router.prefetch()` no
  hover/focus.
- **Medição no browser (demo, produção, 3 ciclos):** Dashboard → Configurações
  **733 → 78 ms**; Configurações → Dashboard **522 → 55 ms** (shell) e
  **1 227 → 118 ms** (dados prontos). LCP **~1 140 → 428 ms** (mediana),
  CLS **0,013 → 0,001**. 0 chamadas de `/me`/subscription nas transições.
- Sem erros de consola em landing/dashboard/settings/auth; `npm audit
  --omit=dev` com 0 vulnerabilidades; build e `tsc` limpos.
- **Testes**: 1084 pytest · 97 vitest · ESLint 0 erros · Ruff limpo.

### Fase 24 — Web Push: distância, iOS e ícones (2026-11-01)

- **Distância**: `source='city'` passou a renderizar distância aproximada com o
  nome da cidade da base (`~11,0 mi do centro de Chicago`); GPS/manual usam o
  texto do mockup (`a 2,3 mi de si`). Sem base, o segmento continua omitido.
  Leads com coordenadas: 114/114 alertas recentes.
- **iOS**: `send_to_user` aceita `ios_payload` e escolhe por `user_agent` da
  subscription. A variante iOS remove `actions`/`requireInteraction`/`vibrate`
  e acrescenta a CTA no corpo (`Toque para abrir o lead.`).
- **Ícones**: payload, lifecycle e broadcast passam a usar
  `/icons/push-icon-192.png` e `/icons/push-badge-72.png` (PNG). O badge foi
  regenerado a 72×72 como silhueta branca (era duplicado do ícone).
  `manifest.json` e `apple-touch-icon` apontam para ficheiros existentes
  (antes `/icon-192.png` devolvia HTML); `push-icon-512` foi gerado a partir
  da marca.
- **Cliques**: `PUSH_CLICK_SECRET` definido em produção (48 bytes aleatórios,
  via stdin, sem exposição em logs). `nid`/`sig` passam a ser assinados e
  `push_deliveries.clicked_at` a ser preenchido.
- Novo `docs/WEB-PUSH.md` com regras de conteúdo e matriz de validação em
  dispositivo.
- **Testes**: 1093 pytest (9 novos) · 97 vitest · tsc/build/lint limpos.

### Fase 25 — i18n estrita do Web Push (2026-11-01)

- `push_subscriptions.locale`: novo campo com backfill de `users.locale`,
  preenchido no registo (fallback SQL) e **propagado** por `update_user_locale`
  a todos os dispositivos. Landing e navbar também persistem a troca de idioma
  na conta (antes só mudavam a UI).
- Envio resolve o idioma **por subscription** (`subscription.locale` →
  `users.locale` → `en`); o mesmo utilizador pode ter Android em EN e iPhone em
  ES. Nunca há fallback PT por omissão.
- Alertas, batch, digest, onboarding e ciclo de vida constroem payloads nos 3
  idiomas (`SUPPORTED`) e `send_to_user` escolhe por dispositivo. `digest`
  deixou de ter ações hardcoded em PT.
- Avisos de ciclo de vida (`reveal_*`, `stage_*`) deixaram de gravar texto PT:
  passam a gravar `msg_key` + `msg_params` (render no locale do destinatário,
  in-app e push). Linhas antigas sem chave usam fallback genérico localizado.
- **Testes**: `tests/test_push_i18n.py` (9) valida EN/ES sem vocabulário PT,
  distância nos 3 idiomas, CTA iOS, propagação do locale na BD e escolha por
  subscription. Total **1102 pytest** · 97 vitest · tsc/build/lint limpos.

### Fase 26 — P0/P1 da auditoria de garimpagem (2026-11-01)

- **Boston (moradas)**: `clean_boston_location` remove o sufixo duplicado
  `, Boston, MA` e separa rua/ZIP na ingestao; `parcel_match_key` ignora a
  unidade do parcel dataset (`526 COLUMBUS AV 2`); `normalize_street` mapeia
  `AV` -> `AVE`; `_lookup_ckan` usa filtros exactos `ST_NUM`/`ST_NAME` (o `q`
  do CKAN é OR), cobre intervalos (`970` vs `980 970`, `81-83` vs `81 83`) e
  prefere a linha sem unidade. Backfill idempotente
  `backend/scripts/backfill_boston.py`: 7.705 moradas normalizadas e owners
  **4.404 -> 7.798 (77,2%)**; 2.301 sem owner (1.054 interseções + ~1.001
  duplicados cuja linha canónica já tem owner).
  `enrich_enabled=1` para Boston.
  Residual: ~1.000 duplicados do mesmo imovel cujo UPDATE colide com o indice
  unico `address+city`; owner preenchido, fusao segura fica para fase propria.
- **Ingestao**: scheduler interno ancorado ao relogio (ultimo sucesso na BD,
  dispara logo se vencido, retry 30 min) em vez de `sleep(6h)` pos-boot;
  arranque do run persistido; webhook com `trigger` real.
- **Watchdog**: a cada 30 min alerta cidade >24h (`MAX(date_reported)`),
  2 runs com `inserted=0`, anomalia por cidade e run vencido (~10,5h);
  dedupe 6h e recolha forcada com cooldown 3h. Anomalia passou a olhar para
  `inserted`, nao para raw. Primeiro alerta real em producao:
  `SCRAPER_CITY_STALE:BOSTON` (48,4h) as 22:41 UTC.
- **Quotas**: dominio por cidade = `BRAVE_DAILY_QUERIES // cidades_activas`
  (250/4 = 62) e `deferred` sem gastar tentativa quando o orcamento acaba
  (hoje 780/250, ja esgotado). `domain_jobs_today` separa a quota.
- **Owners NULL**: backfill em lote com cursor e quota 200/cidade/dia
  (`owner_backfill.py`), 1 s entre lookups, retry sem abortar o lote.
- **Numeros de producao (23:0x UTC)**: NYC 51.539 (283 factos 24h, owner
  85,9%); Chicago 29.137 (642 factos 24h, owner 74,9%); Dallas 16.341
  (72 factos 24h, owner 60,8%); Boston 10.099 (2 factos 24h, owner 77,2%).
- **Testes**: **1.166 pytest** (+64; 1 skipped) e CI ruff (em `./backend`)
  verde. `docs/INGESTION-HEALTH.md` e o runbook.

### Fase 27 — System Health no Admin (2026-11-02)

- Nova rota **`/admin/system-health`** (read-only) + `GET
  /api/admin/system-health?window=24` (sessao admin, cache 30 s).
- **7 camadas** com score 0-100 e estado: ingestao 20, enriquecimento 15,
  outreach 20, push 10, cotas 10, infra 15, alertas 10. Score global =
  media ponderada; estado global = pior camada. UI com anel/barra por topico.
- **Snapshots** compactos a cada 15 min em `system_health_snapshots`
  (retencao 30 dias, prune diario na Control Tower) e sparkline de 24 h.
- Ingestao olha para `inserted` e frescura por cidade; outreach mostra
  `queue_blocker` (cap/quiet hours nao penalizam); push conta
  `expired`/`rejected_dead`, nao `accepted`; cotas mostram Brave e Searchbug;
  infra usa os checks da Control Tower (worker/backup/disco/tokens); alertas
  criticos >7d pesam como governance (-5), nao como falha atual.
- **Baseline producao (00:09 UTC)**: overall **97 warn** (4 criticos
  historicos); ingest/enrichment/outreach/push/quotas/infra a **100**;
  alertas 66. 165 prontos, 24.433 por enriquecer, Brave 16/250, 21 entregas
  push/24h, 12 dispositivos ativos.
- **Testes**: **1.204 pytest** (+38; 1 skipped) e **103 vitest** (+6);
  tsc/lint limpos; CI verde.
- **Micro-lote 02/11**: `ADMIN_ACCESS_*` deixou de pesar no score (fica no
  feed como auditoria). Alertas 66 -> 78 e overall 97 -> 98; reconhecer os 5
  alertas operacionais leva a 100. Botão **Reconhecer** em cada alerta no
  System Health (`POST /api/admin/alerts/{id}/ack`, sessão de admin, limpa o
  cache do snapshot). Testes: **1.210 pytest**, **104 vitest**.

### Fase 28 — bounce duplicado + queue_age esperado (2026-11-02)

- **Bounce:** 1 endereço real (`info@alliedroofingtexas.com`) devolveu
  `user is over quota` (4,5% = 1/22). Foi suprimido e o contacto ficou
  `unsubscribed=1`. O inbox sync relia o mesmo DSN de 5 em 5 min e criava
  eventos duplicados; o segundo evento disparou
  `consecutive_bounces` e pausou Pedro (falso positivo).
- **Correções:** `inbox_processed_messages` (message-id processado uma vez),
  índice único `(mailbox_id, lower(email), kind)` + migração de dedupe,
  `mailbox_guard` exige 2 e-mails **distintos**, e o score de Outreach usa a
  amostra de **20 envios por caixa** (igual ao disjuntor).
- **queue_age:** blockers `quiet hours` e `limite de caixa` passam a `ok`
  ("retenção esperada"); `send_enabled=0`/cidade desligada continuam `warn`.
- Detalhe do incidente em `docs/INCIDENT-2026-11-02-BOUNCE.md`.
- **Testes:** **1.216 pytest** (+6; 1 skipped); ruff limpo.

### Fase 29 — Web Analytics first-party (2026-11-02)

- **Rota `/admin/analytics`**: saúde do tráfego (volume/engagement/conversão),
  cards com sparkline, origens/UTM, funil, geo cidade, dispositivo/idioma e
  ações recentes. Filtros 24h/7d/30d, SWR 30 s.
- **Coleta**: beacon first-party sem cookies; `POST /api/track` na Vercel
  (same-origin) injeta geo/UA/IP e encaminha com chave para
  `POST /api/analytics/ingest` no Railway. Lote após idle/pagehide;
  `sendBeacon`; zero requests antes do LCP.
- **Privacidade**: sessão em `sessionStorage`; único diário por HMAC com salt
  diário; sem IP/PII em repouso; DNT/GPC respeitados; bot filter; rate limit.
- **BD separada** `analytics.db`: `sessions`, `events` (idempotente por
  `event_uid`), `meta`; retenção 90d eventos / 180d sessões, purge diário na
  Control Tower.
- **UTM no outreach**: `sequence_url()`/`build_context()` acrescentam
  `utm_source=magicleads&utm_medium=outreach&utm_campaign=<cidade>_<nicho>&utm_content=stepN`
  a todos os links; teste de compliance atualizado.
- **Testes**: **1.227 pytest** (+11; 1 skipped), **107 vitest** (+3);
  tsc/lint/ruff limpos.
- **Refinamento (02/11)**: geografia com CTA/forms por cidade, origem com
  `utm_campaign`/`utm_content`, feed de ações com origem e painel
  **E-mail → Lead** (`form_submit` por campanha/step/cidade). Depois:
  **calendário De/Até** (inclusive, UTC, 366d) e **export CSV** long-format.
  Testes: **1.230 pytest**, **109 vitest**.

### Fase 30 — Investor Room 1A (2026-11-02)

- **Gate 0 assinado**: $120/7 dias, normalizacao 52/12 ($520 MRR / $6.240
  ARR por pass). Stripe = cash; `plan_until` = acesso; passes sem cobranca
  mapeada ficam fora do MRR verificado.
- **`investor.db`** separado com snapshots imutaveis (checksum), assumptions
  versionadas, reconciliacao, NDA e access log. Refresh diario na Control
  Tower + refresh manual (60 s).
- **Piso patrimonial**: dados $42k–$127k (84.6k owners), IP $96k–$270k,
  compliance $10k–$25k; faixa total ~$148k–$422k. E custo de substituicao,
  nao valor de mercado.
- **Proof of Performance**: owner 78,4%, frescura 17,1%, operacao 100/100;
  **Phone Truth em remediação** (73 chamadas, 22 success = 30,1%, 24 errors
  cobrados, $11,40); e-mail 22 enviados/1 bounce. Numeros negativos visiveis.
- **Simulador ROI**: N empreiteiros -> WRR/MRR/ARR, COGS, margem bruta/liquida,
  LTV, valuation 2x-8x e EV range com piso.
- **NDA 1 clique + CSV watermark** (viewer/exported_at/doc_id); Print-to-PDF
  com watermark diagonal. Aba Comprador (preview) exige NDA; data room/PDF
  server-side na 1B.
- **Cobertura publicada**: `pytest --cov=backend` = **69,2%** (12.768/18.446);
  doc `docs/TEST-COVERAGE.md`; CI gera/up a artifact `backend-coverage`.
- **Testes**: **1.241 pytest** (+11; 1 skipped), **109 vitest**;
  ruff/tsc/build/lint limpos.
- **Pendente 1B**: reconciliacao Stripe↔utilizador automatica, data room ACL,
  PDF server-side, links externos e remediacao Searchbug.

### Hotfix — ingestao apos deploy (2026-11-02, commit `2a21970`)

- Sintoma: o deploy das 15:50 matou o run `253b3d48b473` a meio; a linha ficou
  `running` para sempre, o scheduler esperou por um processo morto e o workflow
  do GitHub (run 202) falhou as 15:57 com `.active=false`.
- Correcção: `mark_interrupted_scraper_runs()` no arranque fecha **todos** os
  `running` orfaos como `error` (`run interrompido (processo reiniciado)`),
  emite `SCRAPER_INTERRUPTED` com run/trigger/started_at e o `scrape_guard`
  devolve **0 s** quando o ultimo run foi interrompido sem success posterior
  (catch-up imediato). Erros genericos continuam a respeitar o retry de 30 min.
- Verificado em producao: run orfao fechado as 16:07:05, alerta criado, novo
  run `5ecba44b4db6` arrancou no mesmo segundo e `/health` 200.
- Testes: +1 regressao de orfaos, +2 de cadencia -> **1.244 pytest**.
- Nota: `last_run.status=running` continua a ser legitimo enquanto o run esta
  vivo; o workflow so falha se o run final nao for `success` (timeout de poll
  nao falha).

### Polimento executivo + Claims Register (2026-11-02, commit `be7c79a`)

- **Comprador** deixou de ser tabela crua: Executive Tech Summary com código
  (82,4k LOC), 1.353 testes, 4/4 gates CI/CD, portabilidade 5/5, segurança
  (WAL, CSP/CORS, passkeys, TTL, segredos fail-closed, rate limit),
  composição Python/TS e roadmap 30/60/90. Dívida técnica só em due diligence
  colapsada.
- **Premissas** passaram a cartões executivos (receita $120 → $520 → $6.240,
  múltiplos 2×/3,5×/8×, inputs do piso, unit economics, infra e governança),
  sem tabela SQL.
- **Nova aba Comparativo**: matriz Magic Leads vs. Angi em 7 dimensões
  (custo por lead, exclusividade, cobrança sem fecho, transparência,
  fidelização, propriedade do ativo, qualidade/acurácia) + **Claims Register**
  com 10 claims, cada um com URL, data, citação, publisher e estado.
- **Fontes oficiais**: Angi Help Center FAQ, Angi Pro Agreement (06/10/2026)
  e FTC (ordem de $7,2M, 23/01/2023). A faixa $15–$85/lead é estimativa de
  terceiros e está marcada como `estimate`; nenhum preço hardcoded sem fonte.
- Claims e matriz entram no snapshot (`claims_register`, `competitive`) e no
  CSV; testes de contrato garantem URL/data/citação e source_ids válidos.
- **Testes**: **1.246 pytest** (+2), 109 vitest; ruff/tsc/build/lint limpos.

### Fase 31 — Voice B2B Fase 1 (2026-11-02)

- **Âmbito**: prospeção de **pessoas jurídicas** em Massachusetts; zero PII de
  homeowners e zero extração de contas de concorrentes.
- **`voice.db`** isolado: fontes, empresas, checks DNC, supressões e tentativas.
  Dedupe por telefone E.164; reimportação preserva `do_not_call`.
- **Gate `can_call()` fail-closed**: business-only, `+1` válido, MA, sem
  supressão, DNC fresco (31 d), não listado, <3 tentativas/7 d e janela
  08:00–21:00 ET. O endpoint de registo também aplica o gate; outcomes de
  supressão continuam permitidos para documentar opt-out.
- **Importação**: CSV de licenças/permits de MA e CSV DNC (`phone, listed`).
  Template em `/api/admin/voice/template.csv`.
- **Fila + click-to-call** em `/admin/voice`: score ICP, obras, categoria,
  telefone, compliance visível, drawer com gate, DNC manual, supressão e
  disposição (connected/voicemail/callback/meeting/…).
- **Supressão automática** em sem interesse, número errado e não contactar.
- **Limites**: sem dialer preditivo/gravação na Fase 1; DNC por CSV/manual até
  ligar provedor licenciado. Piloto restrito a MA.
- **Testes**: +13 (11 de serviço + 2 de API) → **1.260 pytest**; 109 vitest;
  ruff/tsc/build/lint limpos.

### Fase 32 — Vitrine pública + atribuição (2026-11-02)

- **Fonte**: inventário de `leads.db` (oportunidades abertas, 30 d) separado do
  `voice.db`; estado público em `showcase.db`.
- **Publicação**: ≥3 oportunidades por cidade × trade; fallback cidade →
  trade → 404. Páginas em `/{locale}/{city}/{trade}` (EN default).
- **Mascaramento**: bairro/ZIP parcial, categoria, data e valor (quando
  existir); sem owner, morada exata ou ID externo. Copy neutra “property
  opportunity” porque a base atual é 311/open requests; “approved work” só com
  `authorized_work`.
- **Atribuição**: token opaco por chamada/empresa, `/r/<token>` regista clique
  e 302 para `?vt=<token>`; Stripe Checkout leva `source=voice_showcase`,
  `voice_call_id`, `showcase_link_id`, `company_id`, `user_id`, `city`,
  `trade_code`, `new_user`. Webhook fecha `showcase_checkouts` e, para novos
  users, envia link de acesso.
- **Email**: Resend via `EMAIL_API_KEY`/`EMAIL_FROM`; dry-run sem canal.
- **Telnyx**: adaptador (`/dial`) com gate `can_call`, `client_state` e webhook
  DTMF 1 → cria link + email. Sem chaves, dry-run. Segredo partilhado
  fail-closed.
- **Admin**: `/admin/voice` ganhou stats de vitrine, “Rebuild pages”, “Enviar
  vitrine” e “Ligar Telnyx” no drawer.
- **Build real**: 25 páginas de 26 combinações; Boston landscaping 656,
  Boston city fallback 670. Sem página exata de roofing em Boston (inventário
  <3), pelo que o guião deve usar `available()` antes de prometer.
- **Testes**: +13 (10 showcase + 3 Telnyx) → **1.273 pytest**; cobertura
  backend **69,7%**; 109 vitest; ruff/tsc/build limpos.

### Multi-cidade (2026-11-02)

- **Cobertura de vitrine em produção**: Boston 7 páginas / 865 itens; Chicago
  7 / 16.489; Dallas 5 / 3.863; New York 13 / 12.836. `build_pages()` é
  city-agnostic e publica qualquer combinação com ≥3 oportunidades.
- **Gate de voz multi-estado**: `PILOT_STATES = MA, NY, TX, IL`; timezone por
  estado (`America/New_York` para MA/NY, `America/Chicago` para TX/IL).
- **Normalização de cidade**: `NYC` → `new-york` em `get_page`, `available` e
  `create_link`; links de NYC deixam de cair em fallback.
- **Admin**: filtros de cidade/nicho na fila, cobertura agrupada por cidade e
  nicho, e resumo de campanhas (`campaign_id`, chamadas, vitrines, intents).
- **Limite de dados**: nem todos os trades têm página exata em todas as
  cidades (ex.: Dallas roofing cai no fallback da cidade). O guião deve usar
  `showcase.available(city, trade)`.
- **Testes**: +6 → **1.279 pytest**; cobertura backend **69,8%**;
  ruff/tsc/build limpos.

### Fecho da Fase 2A (2026-11-02)

- **Aprovada** a entrega multi-cidade: 32 páginas de vitrine, 34.053
  oportunidades (NY 12.836; Chicago 16.489; Boston 865; Dallas 3.863),
  filtros de cidade/nicho, fusos EST/CST e Investor Room v2026-11-02.4.
- **Piloto inicial** usa a Fase 2A: operador/click-to-call, gate
  `showcase.available()`, link `/r/<token>` e checkout Stripe.
- **Ativação**: inserir variáveis Telnyx no Railway e importar o primeiro CSV
  B2B + DNC em `/admin/voice`.
- **Fase 2B**: guião falado dinâmico por TTS, conversa multi-turn e otimização
  por trade/cidade.

### Automação da Fase 2A (2026-11-02)

- **Ingestão one-click**: `POST /api/admin/voice/ingest` faz parse/clean/dedupe,
  rebuild de vitrines e devolve segmentos. O botão “Importar e processar” usa
  este fluxo.
- **Segmentos cidade+nicho**: `GET /api/admin/voice/segments` agrupa a fila por
  cidade/estado/nicho e classifica `dedicated`, `city_fallback` ou
  `no_showcase` via `showcase.available()`.
- **Auto-scheduler**: `POST /api/admin/voice/campaigns/start` cria campanha e
  arranca worker em background. O worker consome a fila, aplica `can_call()`,
  dispara Telnyx + vitrine e respeita max_calls, timezone, DNC, supressão e
  tentativas. Sem chaves Telnyx corre em dry-run e envia emails em dry-run.
- **Campanhas**: tabela `voice_campaigns` + `voice_campaign_skips`; status
  running/completed/stopped/error; deploy fecha campanhas interrompidas.
- **Admin**: botão “Iniciar campanha autónoma”, tabela de segmentos com
  “Iniciar” por cidade+nicho, lista de campanhas com contadores e “Parar”.
- **Testes**: +4 (auto-scheduler, segmentos, campanha interrompida, ingest API)
  → **1.284 pytest**; cobertura **69,9%**; `auto_dialer.py` 73,3%.

### Fase 1/2 — Fundação de dados e instrumentação (2026-11-02)

- **Base pré-carregada**: `contractor_entities` (28.098 empresas; ~11.4k com
  telefone em NY/TX/IL/MA) é convertida para `prospect_companies` por
  `bridge_contractor_entities()`, com dedupe, normalização de cidade/estado,
  trade inferido e fonte auditável. Em produção: **9.870 empresas** e **28
  segmentos** cidade+nicho; 0 chamáveis até importar DNC.
- **Fontes**: `voice_sources` + `raw_ingest`; conectores `http_csv` (HTTPS com
  allowlist `VOICE_SOURCE_ALLOWED_HOSTS`) e `contractor_entities`. Sync manual
  ou automático; cada execução regista status/erro/linhas.
- **Segmentos materializados**: `voice_segments` por cidade+nicho com
  `Dedicada`, `Fallback cidade` ou `Sem vitrine`; `cached_segments()` evita
  recalcular em cada request.
- **Cotas**: campanhas com `quota_total` + `batch_size`; worker processa o
  lote, fecha como `completed` ou `paused`, e “Continuar lote” retoma.
- **Instrumentação**: `voice_calls` ganhou `answered_at`, `duration_seconds`,
  `listen_seconds`, `hangup_cause`, `cost_cents`, `showcase_clicked_at`,
  `checkout_session_id`, `revenue_cents`. Webhooks Telnyx/Stripe e `/r/<token>`
  alimentam o funil; `metrics()` devolve Answer Rate, Engagement, CTR,
  Checkout Rate, listen médio, receita/custo/net por cidade+nicho.
- **Admin**: tabs Visão Geral / Campanhas / Segmentos / Fontes; visão executiva
  numérica de 30 dias; fontes com sync; cotas totais/lote; campanhas pausadas
  com retoma.
- **Testes**: **1.289 pytest**; cobertura **69,9%**; `auto_dialer.py` 76,5%,
  `b2b_voice.py` 84,9%, `telnyx_voice.py` 69,5%.

### DNC universal + staging (2026-11-02)

- **Parser universal** (`import_dnc_text`): aceita CSV, TSV, TXT, uma coluna,
  linhas soltas, cabeçalhos arbitrários, números com `+1`, parênteses, hífens e
  extensões. Deteta telefones por regex, deduplica, interpreta
  `clean/clear/no/false/0` como limpo e, em conflito, prevalece “listado”.
- **Normalização**: todos os números ficam em E.164 (`+1XXXXXXXXXX`); linhas
  sem telefone são ignoradas e contabilizadas.
- **Staging mode** (`VOICE_STAGING_MODE=true`): DNC em falta/expirado é
  auto-limpo no gate (`dnc_staging_bypass`), mas números listados continuam
  bloqueados; Telnyx fica forçado em dry-run mesmo com chaves.
- **Desobstrução auditável**: `POST /api/admin/voice/dnc/staging-clear` grava
  checks `source='staging'` e reconstrói segmentos; recusa 403 fora de staging.
- **Scrub da base**: ao importar a lista oficial completa, o toggle “aplicar à
  base” executa `scrub_prospects_with_dnc_text`: números na lista ficam
  bloqueados; os restantes ficam limpos (`source='dnc_scrub'`). Sem scrub, o
  gate continua fail-closed para números sem check.
- **UI**: card DNC aceita ficheiro ou texto colado, mostra listados/limpos e
  botão “Desobstruir staging” quando ativo; badge “Staging · dry-run” no header.
  Em staging, o email da vitrine também fica em dry-run.
- **Testes**: formatos crus, conflito listado/limpo, staging e bloqueio em
  produção → **1.296 pytest**; cobertura **69,9%**.

### Polimento UI/UX — dropdowns e paginação (2026-11-02)

- **Dropdowns de cidade/nicho** substituídos por componente próprio de alto
  contraste: fundo `#1a1d24`, texto branco, hover, check de seleção e z-index
  correto (sem depender do render nativo do browser).
- **Fila paginada**: 20 itens por página, paginação server-side (`offset`),
  indicador “Mostrando X–Y de Z”, Anterior/Próxima e “Página X de Y”.
- Filtros de cidade/nicho resetam a página para 1.
- Testes: **1.295 pytest**; ruff/tsc/build/lint limpos.

### Fase 2B — Roteiros e Telnyx AI (2026-11-02)

- **15 roteiros default em inglês** com o template oficial aprovado:
  “Hi {{company}}, this is an automated assistant from Magic Leads. On our
  website right now, we have {{showcase_line}}…”. Todos **aprovados** em
  produção (versão 2), com labels Opening/Pitch, Yes/Press 1 e No/Stop. O
  `assistant_id` é preservado em reedições.
- **Variáveis**: `{{company}}`, `{{city}}`, `{{trade}}`, `{{permit_count}}`,
  `{{showcase_line}}`, `{{price_weekly}}`, `{{price_monthly}}`. A
  `showcase_line` é calculada por cidade/nicho e nunca promete o nicho quando
  só existe fallback de cidade.
- **Registry**: `voice_scripts` + `voice_script_versions`; guardar incrementa
  versão e volta a `draft`; aprovar marca `approved` com autor/data.
- **Admin**: tab **Roteiros** com lista por trade, editor, disclosure,
  assistant_id, preview por empresa/cidade, Guardar draft, Aprovar, Aprovar
  Todos e Sync Telnyx.
- **Overrides**: `voice_script_overrides` por `state` ou `city`; resolução
  runtime **cidade > estado > global**. Só overrides `approved` entram em
  produção; drafts ignoram-se e o global continua.
- **Bulk approve**: `approve_all` aprova os 15 e `sync_all` tenta sincronizar
  todos os assistants; sem chaves Telnyx devolve `telnyx_not_configured` sem
  bloquear a aprovação.
- **Telnyx**: `create_call` resolve o roteiro efetivo (com override), guarda
  `assistant_id` e bloqueia chamada real sem roteiro aprovado/assistant. No
  webhook `call.answered`, inicia `ai_assistant_start`; se falhar, desliga a
  chamada para não ficar em silêncio.
- **Teste real controlado**: `POST /api/admin/voice/test-call` exige
  `VOICE_STAGING_MODE=false`, Telnyx configurado, `confirm=true` e telefone em
  `VOICE_TEST_NUMBERS`.
- **Testes**: **1.302 pytest**; cobertura **69,7%**; `voice_scripts.py` 70,2%.

### Fase 2C — Voz nativa Telnyx e tools (2026-11-02)

- **Voz nativa apenas**: `TELNYX_ASSISTANT_VOICE` default
  `Telnyx.Ultra.00a77add-...` (Callie); alternativas documentadas Asher e
  Clara. Sem ElevenLabs/Deepgram
  externos. `TELNYX_ASSISTANT_EXPRESSIVE_MODE` liga expressive mode em Ultra.
- **Script por chamada**: no `call.answered`, o backend renderiza o roteiro
  efetivo (override incluído) e envia `instructions`, `greeting` e
  `voice_settings` no `ai_assistant_start`. O assistant já não fala
  `{{company}}`/`{{showcase_line}}` em bruto.
- **Tools**: `send_showcase_link`, `capture_email` e `remove_from_list`
  registadas no assistant via `sync_to_telnyx`; endpoint
  `/api/voice/telnyx/tools/{tool}` correlaciona
  `x-telnyx-call-control-id` com `voice_calls.provider_call_id`.
- **DTMF**: `disable_dtmf=false`. A tecla 1 só marca `intent=showcase`; o envio
  fica em `capture_email`, evitando email duplicado. O assistant recebe o tom
  como texto e pergunta o email.
- **Webhook Ed25519**: `TELNYX_PUBLIC_KEY` verifica
  `telnyx-signature-ed25519`/`telnyx-timestamp`; o segredo partilhado continua
  a proteger os tool calls.
- **Teste real**: sem `assistant_id` devolve `assistant_missing`; se
  `ai_assistant_start` falhar, a chamada é desligada. Falta apenas configurar
  as chaves Telnyx no Railway, sincronizar e definir `VOICE_TEST_NUMBERS`.
- **Testes**: **1.311 pytest**; cobertura **70,0%**.

### Fase 2D - Email HTML e confirmacao de email (2026-11-02)

- **Email aprovado (Opcao C)**: assunto `Here is your link: {count} active
  {trade} opportunities in {city}`; HTML branded com botao `ACCESS YOUR
  EXCLUSIVE OPPORTUNITIES`, fallback texto, assinatura `Magic Leads Team`,
  morada `100 Main St, Suite 500, Boston, MA 02110` e unsubscribe.
- **Link branded**: `https://www.magicleads.app/r/<token>` via rewrite
  `/r/:path*` no frontend + `SHOWCASE_BASE_URL`.
- **Confirmacao primeiro**: o instructions da chamada inclui o email da ficha.
  O assistant pergunta "Can I send it to <email>?"; so depois chama
  `send_showcase_link`, que exige `confirmed_email` igual ao da ficha.
- **Ditado como fallback**: `capture_email` exige `confirmed=true` (read-back)
  e devolve `email_not_confirmed` se o assistant tentar saltar a confirmacao.
- **Anti-erro**: validacao de sintaxe, normalizacao para lowercase, nunca
  inventar/corrigir email em silencio, e mensagens de erro que pedem repeticao.
- **Testes**: **1.316 pytest**; cobertura **70,0%**.

### Fase 2E - Fuso, remetente e analytics de aceite (2026-11-02)

- **Janela de chamada**: 09:00-20:00 no fuso **do estado** (MA/NY ET,
  TX/IL CT), configuravel por `VOICE_CALL_START_HOUR`/`VOICE_CALL_END_HOUR`.
  Sem ZIP porque os 4 estados do piloto tem um unico fuso.
- **Remetente**: `Magic Leads Team <support@magicleads.app>`.
- **Analytics**: `summary.accepts`, `accept_rate`, `subscription_rate`,
  `revenue_per_accept_usd`; `by_state`, `by_city`, `by_trade` e
  `by_city_trade`. Aceite = `intent='showcase'` (DTMF 1 ou tool de email);
  assinatura = `checkout_session_id` preenchido no Stripe.
- **Admin**: gauges **Voice Accept** e **Assinatura**, funil com passo
  **Aceite (1/Yes)**, tres tabelas por estado/cidade/nicho e colunas de aceite
  na matriz cidade x nicho.
- **Testes**: **1.319 pytest**; cobertura **70,0%**.

### Fase 2F - Credenciais reais e shared assistant (2026-11-03)

- **Variaveis Telnyx**: as chaves foram corrigidas no Railway; quatro nomes
  tinham `:` no fim (`TELNYX_API_KEY:`), por isso o pydantic nao as lia. Ficaram
  `TELNYX_API_KEY`, `TELNYX_CONNECTION_ID`, `TELNYX_FROM_NUMBER`,
  `TELNYX_PUBLIC_KEY` e `VOICE_TEST_NUMBERS`. Validacao real: API 200,
  connection 200, numero existe, chave publica 32 bytes.
- **Voice ID real**: a API rejeitava `Telnyx.Ultra.Callie`; o ID da Callie e
  `Telnyx.Ultra.00a77add-48d5-4ef6-8157-71e5437b282d` (en-US, female).
- **Limite Telnyx**: a conta so permite **10 TeXML Applications**. Foram criados
  10 assistants e o 11.o devolveu `10039`. Solucao: um **shared assistant**
  (`assistant-f688c3cb-...`) para os 15 roteiros, com instructions renderizadas
  por chamada. `TELNYX_SHARED_ASSISTANT_ID` ativa o modo.
- **Bug de sync**: a resposta da API e flat (`{"id": ...}`); o codigo so lia
  `data.id` e nao guardava o ID. Corrigido para aceitar flat e nested.
- **Resultado**: `sync_all` devolve `synced=15`, `shared=true`; os 15 roteiros
  apontam para o assistant unico com voz Callie, DTMF ativo e as 3 tools.
- **Testes**: **1.320 pytest**; cobertura **70,0%**.

### Fase 2G - Cap outbound e digest (2026-11-03)

- **Over-cap real**: a 2026-11-03 12:01 UTC, Pedro enviou **4** com cap **3**.
  Dois ticks sobrepostos tinham snapshots de capacidade independentes. O
  `process_queue` ganhou um `asyncio.Lock` (tick sobreposto devolve
  `tick_in_progress`) e uma re-checagem do cap na BD antes de enviar.
- **Digest**: `hoje` passa a contar `outbound_messages.status='sent'` desde a
  meia-noite de Nova Iorque, em vez do contador legado. O digest ganhou a linha
  **FILA** com o motivo da retencao (quiet hours/cap) para explicar filas
  antigas sem as pintar de vermelho.
- **Janela de e-mail**: `quiet_hours_start=20:00` e `quiet_hours_end=09:00`
  (America/New_York), portanto o outbound so envia entre **09:00 e 20:00 ET**,
  alinhado com a voz. Aplicado em `outbound_config` a 2026-11-03; os 7 envios
  das 07:01 ET foram anteriores a esta mudanca.
- **Testes**: **1.321 pytest**; cobertura **70,0%**.

### Fase 2H - Dictado de email e duracao (2026-11-03)

- **Diagnostico real**: nas calls 9/10 o assistant pediu o email, mas a
  transcricao ouviu "Familyvera dot com", "Fabio. Liveira." e nunca formou um
  endereco valido; `capture_email` nao foi chamada. Nao era a tool, era ASR.
- **Transcricao**: `deepgram/flux` -> `deepgram/nova-3`, `language=en`,
  keyterms para dominios comuns; `noise_suppression=krisp`.
- **Prompt**: pedir primeiro a parte antes do `@`, depois o dominio; soletrar
  se necessario; repetir o endereco completo; nunca adivinhar. Apos duas
  falhas, oferecer tentar mais tarde.
- **Flow**: removida a tool `mark_acceptance` (causava um turno extra e, na
  call 9, o assistant ficou sem resposta). `intent=showcase` passa a ser
  marcado pelo DTMF 1 e pelas tools de email.
- **Duracao**: fallback `answered_at -> hangup` quando a Telnyx nao envia
  `duration_seconds`/`duration_millis`; custo deixa de ficar 0.
- **Testes**: **1.322 pytest**; cobertura **70,0%**.

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
