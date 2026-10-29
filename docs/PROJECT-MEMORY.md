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

### P1 (dia seguinte)
Re-verificação diária de violações abertas; fechar as resolvidas; remover do feed.

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
