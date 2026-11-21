# Enriquecimento de telefone no clique "Reservar 1 Hora" — SearchBug vs Bright Data

**Data:** 2026-11-20 · **Modo:** estritamente read-only (código, logs, SQL `mode=ro`, fontes públicas). Nenhuma linha de código, configuração, base de dados ou produção foi alterada.

---

## 1. O que acontece hoje no clique

### 1.1 Frontend

1. O cartão do lead mostra o botão **“Reservar 1 Hora”** (`dashboard.action.reserve_1h`, `OpportunityCard.tsx:331`).
2. O clique **não chama a API ainda**: `handleQuickReserve` (`page.tsx:1354`) abre o modal de consentimento (`revealTarget`).
3. Ao confirmar o consentimento, `confirmReveal` (`page.tsx:1429`) chama:
   - `POST /api/leads/{id}/reserve` com `{ minutes: 60, consent: true, idempotency: "u<user>:l<lead>:<data>" }`.
4. Existe também o botão separado **“Revelar Telefone”** (`OpportunityCard.tsx:347`), que chama `revealPhoneForLead` → endpoint de reveal de telefone (mesmo caminho SearchBug).

**O pedido HTTP não envia nome, empresa, endereço, documento, e-mail ou telefone.** Envia apenas o ID do lead, 60 minutos, consentimento e uma chave de idempotência. O backend carrega o resto.

### 1.2 Backend `/api/leads/{id}/reserve`

Ordem real (`main.py:9218-9460`):

1. Gate de assinatura (`_require_active_access`).
2. `precheck_reveal` (lead, posse, estado).
3. Consome **1 carta/visita da cota diária** (10/dia).
4. `owner_enrichment.enrich(address, city, bbl)` — fontes públicas Socrata/CKAN; devolve **owner_name** e **mailing_address** (sem telefone). Persiste no lead.
5. `subscription_reveals.reveal_phone(...)`:
   - verifica `phone_eligible`/`phone_ready`/telefone existente;
   - consome a **cota de telefone do plano** (2–20/dia; 14–140/semana);
   - aplica o orçamento antiabuso `phone_attempts` (30/dia, 3/min);
   - se não houver telefone em cache, chama a **SearchBug**;
   - em sucesso, grava `owner_phone`; em falha, devolve a unidade da cota.
6. `reveal_lead` cria a reserva de 60 minutos.

### 1.3 O que a SearchBug recebe

`searchbug.py:886-900` → `POST https://data.searchbug.com/api/search.aspx` (form):

| Campo | Conteúdo |
|---|---|
| `CO_CODE` / `PASS` | credenciais da conta |
| `TYPE` | `api_nape` (o mais barato; não usa `api_ppl` nem `api_contact`) |
| `FORMAT` | `JSON` |
| `ADDRESS` | morada limpa (cidade/estado/ZIP removidos do texto) |
| `CITY`, `STATE` | cidade/estado |
| `ZIP` | 5 dígitos (normaliza `2114` → `02114`) |
| `FNAME`, `LNAME` | **só** quando o proprietário é pessoa física; nomes corporativos/institucionais são omitidos |

**Não envia:** CPF/documento, e-mail, telefone, nome da empresa como campo separado, cargo, LinkedIn, dados de decisor.

### 1.4 O que o sistema lê e como valida

Resposta esperada `Data.RECORD[]`; lê `FNAME`, `LNAME`, `PHONE`, `PHONE_TYPE`, `CARRIER`, `IS_CONNECTED`.

Validações/descarte:

- `name_match` = sobreposição de tokens do nome do dono com o nome devolvido; **mínimo 0,6** (`PHONE_NAME_MATCH_MIN`). Abaixo: `name_mismatch`, telefone não entregue.
- Telefone normalizado para **E.164** (`+1XXXXXXXXXX`) e formatado na UI.
- ZIP normalizado para 5 dígitos antes da chamada paga.
- Endereço não resolvível, owner ausente/placeholder ou entidade institucional: **nem chama** (`guard_skipped`, custo zero).
- Nome corporativo: não usa FNAME/LNAME; faz **L3 address-only**, sem selo de verificação.
- L3 sem nome (`PHONE_L3_UNNAMED_ENABLED`) está **desligado** por defeito.
- Cache em memória: 30 dias para positivo, 24 h para negativo; **não há tabela `phone_lookups` em produção** — reinícios perdem a cache.
- Timeout 10 s (connect 5 s); 1 retry em erro de transporte; circuit breaker após 3 falhas (60 s).
- `no_results` não é cobrado; erros HTTP/transporte não são cobrados.

---

## 2. Desempenho real observado da SearchBug

Fonte: tabela `searchbug_calls` em produção, últimos 30 dias (leitura).

| Métrica | Valor |
|---|---:|
| Chamadas totais | 62 |
| Cobradas (`billed=1`) | 50 |
| Sucesso | **15** (24,2% do total; 30,0% das cobradas) |
| Ghost charges (cobradas sem sucesso) | **35** (70% das cobradas) |
| `no_results` (não cobrado) | 8 |
| `name_mismatch` | 3 |
| Erros de autenticação/API | **32** (51,6% das chamadas) |
| Erros de transporte | 2 |
| Custo registado | **$10,00** |
| Custo dos 32 erros de auth | $6,40 |
| Sucesso médio (chamadas legítimas) | **53,6%** (15/28) |
| Sucesso entre cobradas legítimas | **83,3%** (15/18) |
| Latência média | 2,2 s |
| p50 / p90 / p95 / máx | **1,03 s / 4,42 s / 7,05 s / 8,67 s** |
| Sucesso — latência média | 4,18 s |
| Última chamada | **2026-11-13** |
| Chamadas nos últimos 7 dias | **0** |
| Revelações de telefone em `lead_reveals` | **0** |

### Leitura honesta

- **32 das 62 chamadas** foram erros de credenciais (“ACCOUNT NUMBER, PASSWORD OR API KEY IS NOT VALID”), todas marcadas como **cobradas** no código. A fatura é a autoridade; é provável que a SearchBug não cobre autenticação inválida, mas a telemetria regista $6,40 de ghost charges. **Bug de classificação de custo.**
- Excluindo esses 32 erros, o desempenho é **53,6% de sucesso** em chamadas legítimas — abaixo dos 75% médios oficiais do `api_nape` (amostra pequena).
- **O fluxo de clique praticamente não foi exercitado**: 0 chamadas nos últimos 7 dias, 0 revelações de telefone, 0 tentativas hoje. Os 15 sucessos são de testes/backfill, não de clientes.
- **Latência p95 de ~7 s** é o ponto mais crítico para a experiência: o clique espera a SearchBug de forma síncrona; o timeout é 10 s.
- Cache: 0 `cache_hit`/`cache_negative` na telemetria; a cache é em memória, não persistida.

### Universo endereçável

| Cidade | Leads | Elegíveis para telefone (`phone_eligible`) | Com telefone |
|---|---:|---:|---:|
| NYC | 75.631 | 38.689 | 21 |
| Chicago | 40.680 | 14.640 | 2 |
| Dallas | 19.217 | 1.943 | 0 |
| Boston | 18.350 | 2.019 | 2 |

**~57.300 leads elegíveis e apenas 25 telefones.** É o mercado real do clique — e o motivo de a qualidade/custo do provedor importar.

---

## 3. SearchBug vs Bright Data

### 3.1 O que cada uma é

| Dimensão | SearchBug | Bright Data |
|---|---|---|
| Natureza | API de people search/contact append dos EUA | Plataforma de web data: proxies, scrapers, datasets, Business Search |
| Produto para este caso | `api_nape` (75% match), `api_contact`, `api_ppl` (87% match), Property Search | Datasets (LinkedIn/B2B/phone), Contact Details Scraper, Business Search, Deep Lookup |
| Telefone verificado por pessoa | **Sim** — retorna telefone, tipo de linha e carrier; validação por nome | **Não por defeito** — perfis públicos não têm telefone verificado; enrich via RevenueBase/Deep Lookup |
| Busca por endereço/proprietário | **Sim** — nome + endereço/cidade/estado/ZIP; Property Search | **Não diretamente** — é preciso construir/scrapear fontes e fazer matching |
| Cobertura de decisores | Boa para proprietário individual; fraca para cargo/empresa | Boa para perfis B2B (LinkedIn/B2B employees), fraca para proprietário de imóvel |
| Precisão | Name match + line type/DNC opcionais | Sem validação de linha/nome por defeito; risco de homónimo/telefone errado |
| Preço | `api_nape` $0,20–$0,04/hit; `api_contact` $0,22–$0,45; `api_ppl` $0,33–$0,79; sem cobrança se não encontrar | Datasets desde $250/100K registos ($2,50/1K); custom desde $400/mês ou $1.200; Business Search $2/1K buscas; scraper pay-per-result |
| Latência | Síncrona; p95 observado ~7 s | Batch/assíncrona; scraping leva segundos a minutos; não é click-grade |
| Contrato | Prepaid, sem mínimo mensal; anual mínimo $2.400 | Mínimos de $250; compromissos/subscrições; engenharia de integração |

### 3.2 Poder de retornar telefones reais

- **SearchBug** é a única das duas que, no clique, recebe nome+endereço e devolve **telefone com tipo de linha**, com validação por nome e opção de DNC/TCPA. Para proprietários individuais e imóveis, é a correspondência mais direta.
- **Bright Data** não é uma API de “telefone do proprietário por endereço”. Entrega perfis públicos (ex.: LinkedIn) e contatos empresariais enriquecidos via parceiro; para chegar ao telefone do proprietário de um imóvel é preciso **construir um pipeline** (scraping de registos/diretórios, matching, validação). Cobertura de telefone é variável e não garantida.

### 3.3 Precisão e erro

- SearchBug: `name_match >= 0,6`, `PHONE_TYPE`, `CARRIER`, `IS_CONNECTED`; pode adicionar Line Type + DNC ($0,10–$0,20). Ainda assim, **L3 address-only** (usado para nomes corporativos) não tem validação de nome e é entregue como “sob consulta”.
- Bright Data: sem validação de linha/nome no produto de dataset; o telefone pode ser de um diretório desatualizado ou de outra pessoa. O risco de falso positivo é maior sem uma camada de verificação.

### 3.4 Custo-benefício no clique

- SearchBug: $0,20 por hit `api_nape` (pode descer a $0,04 com volume), **sem cobrança quando não encontra**. Com 53,6% de sucesso em chamadas legítimas, o custo por telefone útil ronda **$0,37** (mais ghosts de name mismatch). É trivial face aos planos semanais ($25,90–$231).
- Bright Data: $2,50/1K registos é muito barato **em bulk**, mas exige mínimo de $250, pipeline, proxies, matching e validação; para um único clique, o custo total de propriedade é desproporcionado. Além disso, o telefone não vem verificado.

### 3.5 Latência e experiência

- SearchBug: p95 ~7 s; o clique espera. Um timeout de 10 s é o limite; uma falha degrada a experiência.
- Bright Data: batch/assíncrono; não serve para responder no clique. Só faz sentido para **pré-computar** telefones para uma cache.

---

## 4. Veredito da Open Code

**Para o clique “Reservar 1 Hora”, manter a SearchBug — mas corrigir/upgradar o fluxo. Não migrar o clique para a Bright Data.**

Razões:

1. **Fit**: a SearchBug é uma API de contact append/people search; a Bright Data é infraestrutura de dados/scraping, não um telefone verificado por proprietário.
2. **Latência**: SearchBug é síncrona (ainda que p95 ~7 s); Bright Data é batch/scraping, incompatível com o clique.
3. **Custo**: $0,20/hit com “no result free” é mais adequado ao clique do que mínimos de $250 + engenharia.
4. **Precisão**: SearchBug permite validação por nome e tipo de linha; Bright Data não garante que o telefone pertence ao decisor.

**Bright Data faz sentido como camada offline**, não no clique:
- construir uma base própria de decisores/empresas (LinkedIn/B2B employees, diretórios públicos, RevenueBase) e **pré-computar** telefones para os leads de maior valor;
- enriquecer a ficha com cargo/empresa/domínio, que a SearchBug não dá;
- o clique consulta primeiro a cache/DB; só cai para a SearchBug se não houver telefone.

### Estratégia recomendada

**Fase 1 — corrigir o que já existe (SearchBug):**
1. Adicionar `SUBTYPE=p` ao `api_nape` para só devolver registos com telefone (evita hits pagos sem telefone).
2. Escalar por valor: `api_nape` para volume; `api_contact`/`api_ppl` para Enterprise/Agency e leads de alto valor (87% match no `api_ppl`).
3. Validar linha e DNC (`api_lnp3` $0,10 ou `api_lnd2` $0,20) antes de mostrar; guardar `phone_type`/`carrier`.
4. Corrigir a classificação de custo: erro de autenticação/validação **não é billed**; o `billed` deve refletir a fatura.
5. Corrigir o selo `verified`: usar `result.verified`/`name_match`, não `provider != "mock"` (hoje L3/corporativo fica “verificado”).
6. Cache persistente em DB (`phone_lookups`) para não repetir chamadas pagas após restart; cache negativo curto.
7. Ligar o telefone ao fluxo de **oportunidades pré-inspeção** (`/api/opportunities/{id}/reserve` hoje não chama a SearchBug; só reserva).
8. Pré-computar em lote os leads elegíveis de maior prioridade; o clique deve acertar na cache.

**Fase 2 — hybrid com Bright Data (offline):**
9. Usar Bright Data para construir/enriquecer a base de decisores B2B (cargo, empresa, LinkedIn, contatos empresariais) e alimentar a cache; nunca chamar no clique.
10. Para proprietários de imóveis, a SearchBug Property Search ($0,50) + `api_ppl` é mais direta que a Bright Data; se o objetivo for telefone de homeowner em escala, avaliar também provedores especializados de property data (ATTOM/BatchData/Trestle), fora do par pedido.

---

## 5. Bugs/riscos encontrados (sem alterações)

1. **Erros de autenticação marcados como `billed=1`** — 32 chamadas, $6,40 de ghost charges na telemetria; a fatura pode não cobrar, mas o painel mente.
2. **`api_nape` sem `SUBTYPE=p`** — pode devolver registos sem telefone e gastar um hit.
3. **Selo `verified` indevido** — `update_owner_phone(verified=(provider != "mock"))` marca L3/corporativo como verificado.
4. **Sem validação de linha/DNC** no clique; `PHONE_TYPE`/`CARRIER`/`IS_CONNECTED` são lidos mas não usados para decidir.
5. **Cache apenas em memória** — reinícios perdem cache positiva/negativa; não existe `phone_lookups` em produção.
6. **`/api/opportunities/{id}/reserve` não busca telefone** — o fluxo de pré-inspeção reserva 60 min mas não enriquece telefone.
7. **Latência p95 ~7 s** no clique, com timeout de 10 s; sem pré-computação.
8. **Última chamada 13/11 e 0 revelações de telefone** — o fluxo de clique não está a ser exercitado em produção; a amostra é pequena e antiga.
9. **32 erros de credenciais em 10/11** — credenciais definidas hoje, mas sem chamada recente que confirme a validade; não foi feito teste pago nesta auditoria.

---

## 6. Fontes

- SearchBug — People Search APIs (api_nape 75%, api_contact, api_ppl 87%, preços): https://www.searchbug.com/api/phone-name-address-email.aspx
- SearchBug — API pricing: https://www.searchbug.com/pricing-api.aspx
- SearchBug — api_nape docs (`SUBTYPE=p`, campos): https://www.searchbug.com/info/api/name-address-phone-and-email-api
- SearchBug — pricing de serviços (Property $0,50; Line Type $0,10; DNC $0,20): https://www.searchbug.com/pricing-searches.aspx
- Bright Data — Phone Number Datasets (custom $400/mês ou $1.200): https://brightdata.com/products/datasets/phone-numbers
- Bright Data — Enrichment Datasets ($250 min, $2,50/1K, 303M registos): https://brightdata.com/products/datasets/enrichment
- Bright Data — Business Search API ($2/1K buscas): https://brightdata.com/products/business-search-api
- Bright Data — Contact Details Scraper (pay-per-result, 5K créditos grátis): https://brightdata.com/products/web-scraper/contact-details-scraper
- Bright Data — Dataset FAQ (LinkedIn sem telefone por defeito; enrich via RevenueBase/Deep Lookup): https://docs.brightdata.com/datasets/marketplace/faqs
- APIbenchmarks — Bright Data (perfis públicos, sem telefones verificados por defeito): https://apibenchmarks.com/enrichment/bright-data
