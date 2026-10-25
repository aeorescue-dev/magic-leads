# Automação Total da Descoberta e Enriquecimento de E-mails

**Estado:** PROPOSTA — STOP & REVIEW. Nenhum código de produção foi escrito, alterado ou commitado nesta fase.
**Data:** 2026-10-25
**Âmbito:** NYC, CHICAGO, DALLAS, BOSTON (`SERVED_CITIES`, `db.py:824`)
**Requer:** validação explícima do cliente antes de qualquer implementação.

---

## 0. Resumo executivo

Hoje o motor só sabe enviar para quem já tem e-mail em `outbound_contacts`, e essa tabela só
é preenchida por (a) import manual B2B ou (b) verificação de um e-mail que já existia no lead.
Nas bases públicas o `owner_email` é `None` por construção (`main.py:2212`, `main.py:2795`),
e a verificação (`EmailListVerify.find_and_verify`) nunca recebe `domain` a partir do
`enqueue_batch` — logo, **sem import manual, `queued = 0`**.

A lacuna real é uma etapa que não existe: **nome da empresa + praça → domínio oficial**.
Tudo o resto (resolver e-mail a partir do domínio, validar, enfileirar) já está construído.

Proposta: um **pipeline de descoberta em background**, com 3 camadas de custo decrescente,
orçamentos rígidos, cache agressivo e feedback loops. Custo modelado:

| Cenário | Volume | Custo estimado | E-mails enviáveis |
|---|---|---|---|
| Backfill NYC (21.122 qualificados) | ~11.600 com nome | **~US$ 250–350** | ~4.500–6.500 |
| Backfill 4 praças | ~60.000 qualificados | **~US$ 700–1.100** | ~25.000–33.000 |
| Operação contínua (zero toque) | ~400 envios/dia | **~US$ 250–400/mês** | 12.000/mês |

Custo derivado: **≈ US$ 0,02 por lead processado, ≈ US$ 0,05 por e-mail enviável.**
*Todas as percentagens de sucesso são hipóteses a validar no Fase 0 (spike de medição).*

**Aviso de gargalo:** o volume descoberto nunca será o limite — o limite é o teto de envio
(`daily_send_cap=100` por praça + warmup). Descobrir 27.000 e-mails significa ~67 dias de
envio a 400/dia. O pipeline deve ser **dimensionado à procura, não ao inventário**.

---

## 1. Diagnóstico do que bloqueia a automação (com referências de código)

| # | Bloqueio | Evidência |
|---|---|---|
| 1 | Nenhuma etapa nome+praça → domínio existe | `enqueue_batch` chama `find_and_verify(owner_email, company_name, contact_name, city)` **sem `domain`** (`outbound_engine.py:234`) |
| 2 | `find_and_verify` deriva domínio **apenas** de `owner_email` | `clean_domain = (domain or "") or email_domain(clean_email)` (`enrichment_emaillistverify.py:312`). Sem `owner_email` → `outcome="no_domain"`, 0 créditos, 0 resultado |
| 3 | Enriquecimento só corre dentro do envio | único `find_and_verify` chamado em `enqueue_batch`; não há job de descoberta |
| 4 | Import B2B é a única fonte com `email_source='import'` | `import_b2b_lead` (`db.py:2273`) |
| 5 | Cobertura de `owner_name` desconhecida | **nunca medida** — é a variável #1 do custo |
| 6 | KPI "Com e-mail" ≠ gate de envio | `count_outbound_recipients` ignora `email_status` e não filtra nicho (`db.py:1932`) |
| 7 | Sem loop de resposta | `replied_at` é marcado **manualmente** no painel (`main.py:1771`, `outbound_engine.py:366`) |
| 8 | Opt-out só por reply-text | rodapé `To stop receiving these emails, reply "unsubscribe"` (`outbound_templates.py:143`); **sem header `List-Unsubscribe`** |

Os pontos 7 e 8 são pré-requisitos de compliance antes de escalar volume (secção 6).

---

## 2. Objetivos e não-objetivos

**Objetivos**
- O1: um lead novo que entre por scrape passa a `sendable` sem toque humano.
- O2: KPI "Com e-mail" > 0 por omissão em qualquer praça com inventário.
- O3: custo por e-mail enviável auditável e limitado por dia.
- O4: nenhuma dependência de fonte pública sem e-mail (311/Socrata) para o endereço de destino.

**Não-objetivos**
- N1: substituir o Gmail API como canal de envio (não faz parte desta proposta).
- N2: scraping de diretórios de terceiros (Yelp/BBB/Yellow Pages) — ver secção 5.7.
- N3: expansion geográfica para fora de `SERVED_CITIES`.

---

## 3. Estratégia de descoberta: opções analisadas

### 3.1 Matriz de fontes

| # | Fonte | Fornece | Custo unitário | Risco / ToS | Papel |
|---|---|---|---|---|---|
| L1a | **Heurística própria**: slug do nome + verificação DNS (A/MX) + fetch HTTP + fuzzy match do título/telefone | domínio | **US$ 0** | nenhum (DNS/HTTP públicos) | primeira tentativa |
| L1b | **Pattern guessing** (`info@`, `contact@`, `office@`, `firstname@`, `first.last@`) + verificação | e-mail candidato | só o custo da verificação | nenhum | primeira tentativa |
| L2 | **Brave Search API** — Web Search e Place Search (200M POIs: nome, **URL**, endereço, telefone, **e-mail**) | domínio/site e por vezes e-mail | **US$ 5 / 1.000** (US$ 5 grátis/mês) | API licenciada, índice próprio, 50 QPS | fallback da L1 |
| L3a | **EmailListVerify** (já contratado): `verifyEmail` 1 crédito; `findContact` nome 5 créditos / domínio 10 créditos | e-mail + validação | 1 crédito = **US$ 0,0027** (10k) → verify ≈ $0,003; find nome ≈ $0,014; find domínio ≈ $0,027 | já integrado, fail-soft | validação + fallback |
| L3b | **Hunter** — Domain Search 1 crédito/e-mail encontrado; **Bulk Domain Search 1 crédito = até 10 e-mails**; verificação 0,5 crédito | domínio → e-mails em massa | Starter $49 → 2.000 créditos; Growth $149 → 10.000 créditos (≈ $0,0015–0,005/e-mail) | API oficial, ToS permite uso em pipelines | **candidato a substituir L3a em volume** (testar na Fase 0) |
| L3c | **Snov.io** — já tem módulo `snov.py` e credenciais em `config.py`; Domain Search aceita **nome de empresa** | nome → domínio → e-mail | Starter $39 → 1.000 créditos; Pro M $189 → 5.000 créditos (créditos partilhados finder/verifier) | já integrado | alternativa/comparação de preço |
| — | **Google Places API (New)** | website (sem e-mail) | **US$ 32–35 / 1.000** (crédito universal de $200 removido) | API oficial | reserva (6–7× mais caro que Brave) |
| — | **Registos públicos estaduais/municipais** (NY DOB, NY DOS, juntas de licenças) | só nome de empresa/endereço/telefone — **raramente website** | $0 | licença aberta com atribuição | já explorado: **não resolve domínio** |
| — | **SEC EDGAR / skip_trace atual** | só corporativo, devolve `None` na prática | $0 | ok | sem papel |
| — | **Google Custom Search JSON API** | — | — | fecha a novos clientes e **encerra 2027-01-01** | **excluído** |
| — | **Bing Search APIs** | — | — | **descontinuadas** | **excluído** |
| — | **Apollo / RocketReach / Clay / Dropcontact / FullEnrich** | enriquecimento pronto | dezenas de US$/mês + créditos | ok | fora de budget inicial |
| — | **Scraping de Yelp / BBB / Yellow Pages / Angi / Houzz** | website + telefone | $0 | **ToS proíbem uso para captação em massa; anti-bot; litígio Google↔scrapers** | **desaconselhado** |

### 3.2 Porquê que a camada "nome + praça → domínio" é o verdadeiro trabalho

Um permit/licença pública dá: endereço, categoria, empresa/proprietário, telefone. **Nunca
website.** Por isso a decisão de arquitetura é:

1. **L1 heurística (grátis)** — para empreiteiros americanos, o padrão `nome-empresa.com` /
   `nomeempresa.com` / `nome-empresa-nyc.com` tem adesão alta. Pipeline: slug → `A`+`MX` →
   `GET /` com timeout curto → título/telefone correspondem ao lead? Aceita-se só com
   **corroboração** (semântica ≥ 0,8 OU telefone igual ao `owner_phone` do lead).
2. **L2 Brave Place Search / Web Search (US$ 0,005/query)** — query
   `"Nome da Empresa" <city> <trade>`; confirmação por telefone (`owner_phone` já existe em
   `leads`) ou similaridade de nome. Place Search devolve URL **e** e-mail em resultado único.
3. **L3 EmailListVerify / Hunter / Snov** — resolve o e-mail a partir do domínio.

Regra de ouro: **nunca aceitar um domínio sem corroboração** (telefone OU nome similar).
Um domínio errado envia marketing a um terceiro — é o único erro com consequências legais.

---

## 4. Modelação de custos

### 4.1 Custos unitários verificados (2026-10-25)

| Operação | Fonte | Custo |
|---|---|---|
| Query de busca / place | Brave Search API | $0,005 |
| Verificação de e-mail | EmailListVerify (pay-as-you-go 10k = $27) | $0,0027 |
| Encontrar por nome (nome+domínio) | EmailListVerify, 5 créditos | $0,0135 |
| Encontrar por domínio (só domínio) | EmailListVerify, 10 créditos | $0,027 |
| Domínio → 10 e-mails | Hunter Bulk Domain Search, 1 crédito | $0,0015–0,005/e-mail |
| Slug + DNS + fetch próprio | — | ~$0 |
| Nota | `EMAILLISTVERIFY_PER_CREDIT_USD = 0.00699` em `config.py:198` está **desatualizado** (era o preço de 2024, $6,99/1.000) | corrigir numa fase de código |

### 4.2 Cenário NYC (21.122 qualificados)

Hipóteses (validar na Fase 0): 55% têm `owner_name` utilizável → 11.600 leads; yield de
e-mail enviável 40–55%.

| Etapa | Volume | Custo |
|---|---|---|
| Heurística de domínio (L1) | 11.600 | $0 |
| Brave fallback (L2), 50% de falhas | 5.800 × $0,005 | $29 |
| Pattern + verificação (L1b), 3 candidatos/lead | 11.600 × 3 × $0,0027 | $94 |
| `findContact` domínio (L3a), 40% de falhas | 4.600 × $0,027 | $124 |
| **Total NYC** | | **≈ $247** → **4.600–6.400 e-mails enviáveis** |

Custo por e-mail enviável: **≈ $0,04–0,055**.

### 4.3 Escala 4 praças e operação contínua

- Backfill (~60k qualificados): **≈ $700–1.100** one-shot (ou mais barato se Hunter bulk
  se confirmar na Fase 0 → potencialmente −40%).
- Operação contínua: 4 praças × `daily_send_cap` 100 = 400 envios/dia; com yield 45% é
  preciso processar ~900 leads/dia. Custo ≈ **$19/dia ≈ $580/mês** em regime de burn total.
- **Recomendação**: descoberta *just-in-time* com buffer de 3 dias de envio (~1.200
  enviáveis) → **~450 leads/dia → ≈ US$ 10/dia → ≈ US$ 300/mês**, com folga para queda de yield.

### 4.4 Gatilhos de corte (fail-closed de orçamento)

- `daily_discovery_cap` (leads processados/dia) por praça.
- `max_spend_discovery_usd` diário global; contador reutiliza `outbound_counters`
  (`enriched`, `spend_usd`) já existente.
- Teto mensal absoluto (env variável); ao atingir → `outcome="budget_exhausted"`, sem exceção.
- Circuit breaker: 5× `429`/`5xx` consecutivos → suspender fornecedor e degradar para L1.

---

## 5. Arquitetura do pipeline (desenho — sem código)

### 5.1 Diagrama

```
                    ┌─────────────────────────────────────────────────────┐
 scrape / ingestão  │            DISCOVERY WORKER (background)           │
   leads (nova      │                                                     │
   linha, enrich_   │  P1 company_resolver                                │
   state=pending)──►│    owner_name + city + owner_phone                  │
                    │    → company_directory (cache, dedup)               │
                    │  P2 domain_resolver                                 │
                    │    L1 slug+DNS+fetch  →  L2 Brave place/web         │
                    │    (corroborar por telefone ou similaridade ≥0.8)    │
                    │  P3 email_resolver                                  │
                    │    L1 pattern + ELV verify  →  L3 ELV/Hunter find   │
                    │  P4 persist                                         │
                    │    → outbound_contacts(email_source='auto_*',       │
                    │                          email_status='valid')      │
                    │    → leads.enrich_state = 'sendable'                │
                    └─────────────────────────────────────────────────────┘
                                        │
        count_outbound_recipients > 0   ▼
   painel  ──► Simular lote ──► /outbound/send ──► enqueue_batch ──► fila ──► Gmail
                                        │
                    ┌─────────────────────────────────────────────────────┐
                    │             FEEDBACK LOOP (Fase 4)                  │
                    │  NDR/bounce (Gmail users.watch) → email_status='invalid'
                    │  resposta "unsubscribe" parseada → unsubscribed=1    │
                    │  complaint/spam report → suppress + domínio blacklist│
                    └─────────────────────────────────────────────────────┘
```

### 5.2 Estado por lead

`leads.enrich_state` (coluna nova, proposta):

```
pending ──► name_missing (sem owner_name → reintenta quando enrichment de nome correr)
        ──► domain_ok ──► email_ok ──► sendable   (o KPI passa a contar aqui)
        ──► domain_fail (negativo, TTL 30–90 dias)
        ──► email_fail  (negativo, TTL 30 dias)
        ──► suppressed  (bounce/opt-out → nunca mais)
```

**Caches negativos são obrigatórios:** 60k × re-lookup diário é como gastar orçamento
à toa. `domain_fail`/`email_fail` guardam `outcome`, `attempts` e `retry_at`.

### 5.3 Tabelas propostas (desenho)

1. **`company_directory`** — dedup de resolução de empresa (evita refazer trabalho por lead):
   `norm_key UNIQUE` (nome normalizado + cidade), `company_name`, `city`, `phone`,
   `domain`, `website_url`, `source` (`heuristic|brave_place|brave_web|snov|hunter`),
   `confidence`, `verified_at`, `attempts`, `last_error`.
   `UNIQUE(lower(domain))` para partilhar um domínio entre N leads.
2. **`email_candidates`** — memória do que já se tentou por lead/domínio (positivo e
   negativo): `email`, `source`, `status`, `credits_spent`, `outcome`, `checked_at`.
   Também serve de funil para o painel.
3. **`outbound_contacts`** — alargue mínimo proposto: novos valores de `email_source`
   `auto_pattern`, `auto_provider`, `auto_search` + coluna `confidence`.
   ⚠️ `TRUSTED_EMAIL_SOURCES = ('import','manual')` (`db.py:80`) tem de ser alargado,
   senão o gate `is_sendable_contact` rejeita tudo o que a automação produzir.
4. **`outbound_enrichment_calls`** (já existe) — reutilizar com `provider` =
   `brave_search`, `domain_heuristic`, `snov_find`, mantendo a telemetria existente.

### 5.4 Worker e agendamento

Reutilizar os padrões já no processo (`main.py:2987` `_lifespan`):

- **`_discovery_loop`** — task asyncio com chunk pequeno (10–25 leads/tick), sleep
  entre fornecedores, token-bucket por fornecedor, idêntico em posture ao
  `_outbound_task` (fail-soft por dentro, `discovery_enabled=0` = no-op).
- **Corre também antes do envio**: `enqueue_batch` passa a tratar a descoberta como
  *fallback* (se `is_sendable_contact` falso → chamar descoberta síncrona com orçamento
  restante) em vez de único ponto.
- Nunca bloquear o `POST /send`: enfileirar o que já está pronto; o resto fica para o
  próximo tick.

### 5.5 Mitigação de rate limits (por fornecedor)

| Fornecedor | Limite conhecido | Medida |
|---|---|---|
| Brave Search API | 50 QPS no plano Search; créditos pré-pagos | token bucket 10–20 QPS, jitter, `Retry-After` |
| EmailListVerify | >100k verificações/hora | 5–10 req/s, backoff exponencial (2ⁿ + jitter) |
| Hunter | limites por plano (minuto/hora) | configurar à mão por plano; testar na Fase 0 |
| Snov | limites de API por plano | idem |
| HTTP próprio (fetch de site candidato) | cortesia do alvo | timeout 5s, 1 req/dominio, user-agent identificativo, `robots.txt` respeitado para crawl próprio |

Geral: **circuit breaker** (5 falhas consecutivas → pausa 15 min + log), métricas de
`429/5xx` por fornecedor, e o fornecedor nunca é único ponto de falha (L1 continua a
funcionar).

### 5.6 Dedup e reutilização

- Um **domínio** descoberto serve todos os leads da mesma empresa (coloque/matrícula).
- Um **`findContact` por domínio** por janela de 30 dias (hoje o cache in-process de
  `EmailListVerifyService` morre no restart → passar a cache para a BD).
- Leads com o mesmo `owner_name` normalizado + cidade colapsam para `company_directory`.

### 5.7 Por que não fazer scraping de diretórios

Yelp/BBB/Yellow Pages/Angi/Houzz proíem (nos respetivos ToS) o uso dos dados para
contacto/marketing em massa, usam anti-bot e as consequências vão de bloqueio a ação
judicial (caso Google vs. fornecedores de scraping, citado pela própria Brave). Alternativas
com o mesmo resultado e risco muito menor: **API licenciada (Brave/Google)** e **dados
abertos com atribuição** (NYC Open Data Terms of Use). Manter o scraping de dados públicos
de governo (Socrata/CKAN) como está — é aí que nasce a *oportunidade*, não o e-mail.

---

## 6. Enquadramento jurídico e de entregabilidade

### 6.1 CAN-SPAM (EUA — NYC/Chicago/Dallas/Boston)

Aplica-se também a e-mails B2B. **Não exige consentimento prévio**, exige:

1. cabeçalho `From`/`Reply-To` e assunto verdadeiros (o template já é en-US e não engana);
2. identificação clara de conteúdo comercial;
3. **endereço postal físico válido** na mensagem — ⚠️ **verificar que existe no template**
   (não confirmado nesta auditoria: o rodapé só mostra o opt-out por reply);
4. opt-out claro, válido ≥30 dias, honrado em ≤10 dias — ⚠️ sem canal automático (ponto 7);
5. responsabilidade de quem subcontrata envio.

### 6.2 Requisitos de bulk senders Google/Yahoo (>2.000/dia por domínio/remetente)

SPF/DKIM/DMARC (documentado em `docs/OUTBOUND-DOMAIN-AND-MAILBOXES.md`), taxa de spam
<0,3%, e **one-click unsubscribe (RFC 8058, header `List-Unsubscribe-Post`)**. O template
atual só tem `reply "unsubscribe"` — **é bloqueante acima do teto atual**. Abaixo de
2.000/dia não bloqueia, mas convém resolver antes de subir `daily_send_cap`.

### 6.3 Outras

- **GDPR/LGPD:** leads são empresas nos EUA, dado profissional de empresa, fonte pública;
  risco baixo. Registar base legal (interesse legítimo) caso haja expansão para a UE.
- **Custo legal real:** reclamações de spam → queima de reputação do domínio, não tribunal.
  Daí a regra de **nunca aceitar domínio sem corroboração** e o bounce feedback loop.
- **Termos de fornecedores:** ELV/Hunter/Snov/Brave permitem uso programático nos seus
  respetivos planos de API; ler antes de ativar bulk.

---

## 7. O que já existe e será reutilizado (sem reescrita)

| Componente | Ficheiro | Uso |
|---|---|---|
| Cliente ELV completo + telemetria | `enrichment_emaillistverify.py` | verificação e `findContact` |
| Cliente Snov legado | `snov.py` | candidato a `domain search` por nome |
| Gate de envio | `is_sendable_contact` (`outbound_engine.py:51`) | mantém-se; alargar `TRUSTED_EMAIL_SOURCES` |
| Contadores/diário | `outbound_counters` + `daily_enrich_cap` + `max_spend_per_batch_usd` | orçamentos |
| Telemetria de chamadas | `outbound_enrichment_calls` | observabilidade por fornecedor |
| Loop de processos | `_scheduler_loop`, `_outbound_task`, `_lifespan` | novo `_discovery_loop` |
| Diagnóstico do funil | `GET /api/admin/outbound/diagnostics` | acrescentar etapas da descoberta |
| Padrão fail-soft/fail-closed | config + worker | `discovery_enabled=0` por omissão |

**Correções que devem acompanhar a implementação** (pendentes de aprovação):
KPI alinhado com o gate real e por nicho; `sendable_recipients` devolvido também no
`/preview`; `domain` passado ao `find_and_verify`; preço por crédito ELV corrigido;
estimador de custo do painel deixa de usar `_SNOV_PER_EMAIL_USD = 0,015` (`main.py:1559`).

---

## 8. Roteiro (fases com entregáveis e critérios de saída)

### Fase 0 — Spike de medição (2–3 dias, **fora do código de produção**)
Objetivo: substituir hipóteses por números. Amostra de ~200 leads por praça.
Mede: (a) % com `owner_name`; (b) sucesso da heurística de domínio; (c) sucesso do
Brave Place Search; (d) yield do pattern+verify; (e) yield/custo do `findContact`.
**Critério de saída:** custo por e-mail enviável medido e decisão entre camada L2 =
Brave, e L3 = ELV vs Hunter vs Snov.
*Requer aprovação explícita: criação de chave Brave pré-paga (US$ 5 grátis/mês) e
execução de scripts num separador de trabalho, sem commit em `master`.*

### Fase 1 — Domínios
`company_directory` + heurística L1 + fallback L2 + caches negativos. Entra com
`discovery_enabled=0`.

### Fase 2 — E-mails
`email_candidates` + pattern+verify + `findContact` fallback + alargamento de
`TRUSTED_EMAIL_SOURCES`. KPI "Com e-mail" passa a refletir o gate real.

### Fase 3 — Worker contínuo + orçamentos + observabilidade
`_discovery_loop`, budgets diários, endpoint de funil no painel
(`pending → domain_ok → email_ok → sendable` por praça), alertas de orçamento.

### Fase 4 — Feedback loops (pré-requisito de escala)
Parse de respostas (opt-out automático), bounce/NDR via Gmail API, marcação de
`suppressed`, header `List-Unsubscribe` + endereço postal no template.

### Fase 5 (opcional) — Reavaliação de fornecedor
Com dados da Fase 0, comparar Hunter bulk vs ELV `findContact` vs Snov e migrar o
provedor dominante se a diferença de custo justificar.

---

## 9. Riscos e incertezas abertos

| Risco | Impacto | Mitigation |
|---|---|---|
| Cobertura de `owner_name` baixa em Chicago/Dallas/Boston | custo sobe, yield cai | medir na Fase 0; ligar enriquecimento de nome (Socrata/DOB) antes da descoberta |
| Domínio errado (falso positivo) | marketing a terceiro → spam complaints | corroboração obrigatória (telefone/similaridade); audit sample manual |
| Catch-all domains → verificação devolve `valid` falso | bounce alto | marcar `confidence=low`, não enviar nas primeiras 2 praças, monitorizar bounce |
| Custo ELV/Hunter muda | orçamento | preço por crédito guardado em config, alerta ao desvio >20% |
| Volume descoberto ≫ teto de envio | dinheiro parado em BD | descoberta just-in-time (buffer 3 dias) |
| Cache de fornecedor só em memória | re-chamadas pagas após restart | cache/`email_candidates` na BD |
| Alteração de ToS/limite de fornecedor | paragem | L1 heurística nunca falha; 2 fornecedores em L2/L3 |

---

## 10. Decisões que pedimos antes de escrever uma linha de código

1. **Aprovar a Fase 0 (spike)** — scripts locais, sem deploy, com relatório de números.
2. **Orçamento** — confirmar US$ 300–500/mês para operação contínua e US$ 700–1.100 de backfill.
3. **E-mails de função** (`info@`, `contact@`, `office@`) são aceites como enviáveis?
   Recomendação: sim (norma em empreiteiros), com `email_source` próprio e prioridade
   inferior a e-mails com nome de pessoa.
4. **Prioridade do backfill** — NYC primeiro ou as 4 praças em paralelo?
5. **Fornecedor L3** — manter ELV, testar Hunter, ou reaproveitar Snov (já credenciado)?
6. **Alinhar o KPI e o `/preview`** (correções descritas em §7) — incluir no lote de trabalho?
7. **Fase 4 (opt-out automático + bounce)** — avançar já em Fase 2 ou esperar?

---

*Referências de preço consultadas em 2026-10-25: emaillistverify.com/pricing, hunter.io/pricing,
snov.io/pricing, brave.com/search/api + blog "Brave Place Search API" (2026-07-08, citando a
tabela oficial de preços do Google Maps Platform). Preços podem mudar; confirmar no contrato
antes de codificar orçamentos.*
