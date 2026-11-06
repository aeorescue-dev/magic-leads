# Estudo de Viabilidade — Collision & Accident Leads Platform

**Data:** 2026-11-06  
**Natureza:** avaliação estratégica paralela. **Zero código, zero deploy, zero alteração ao produto principal.**  
**Mercados analisados:** TX, NY, FL, IL, MA (com foco nas praças atuais: NYC, Dallas, Chicago, Boston).

---

## 1. Sumário executivo

**Veredicto: NO-GO para o modelo como descrito.** A captura contínua de relatórios de acidente com PII e a venda fracionada de contactos a body shops, reboques e advogados não é viável de forma lícita nos estados-alvo. O bloqueio não é técnico; é legal e de acesso aos dados.

O que **é** viável, com o engine atual:

1. **Crash Intelligence agregada** — hotspots, volume, gravidade, tipo de dano, ZIP/corredor, sem PII, vendida por assinatura a body shops, reboques e seguradoras.
2. **Marketplace inbound** — o consumidor pede ajuda (landing/chat), dá consentimento e é encaminhado para 1–3 prestadores locais. É o modelo de lead gen que sobrevive a DPPA/TCPA.

| Dimensão | Avaliação |
|---|---|
| Acesso a relatórios com PII em bulk | **Vermelho** — não existe feed público; acesso restrito a partes/lesados/seguradoras |
| Venda de PII para body shops/reboques | **Vermelho** — fora dos permissible uses da DPPA e, em FL/TX/IL, proibida por estatuto próprio |
| Captura de dados agregados (sem PII) | **Verde** — open data diário/semanal em NYC, Chicago, Boston, Dallas, Austin, etc. |
| Reutilização do pipeline | **Amarelo** — ingestão, geocoding, segmentos e admin reaproveitam-se; voz/DNC/enriquecimento de telefone **não** |
| Liquidez dos compradores | **Amarelo** — PI lawyers pagam mais, mas têm o maior risco de solicitação; body shops são o meio; towing é o mais fraco |
| Time-to-market do pivot agregado | **3–4 semanas** para MVP em 2 praças |
| Time-to-market do marketplace inbound | **6–8 semanas**, dependente do chat/inbox |

**Recomendação:** parar o modelo de "venda de relatórios" e aprovar uma **discovery de 2 semanas** para o pivot agregado + inbound, com parecer de advogado US antes de qualquer linha de código.

---

## 2. O conceito e a hipótese central

Hipótese do negócio:

```text
Acidente → relatório policial público → extrair proprietário/telefone
→ segmentar por ZIP/raio → vender a body shops, reboques e PI lawyers
```

Três premissas precisam de ser verdadeiras:

1. **Quase todos os acidentes geram relatório.** Falso para "fender benders": os limiares de reporte excluem danos pequenos.
2. **O relatório é público e obtível em bulk.** Falso: é público com restrições, muitas vezes pago, e a PII é redigida ou reservada às partes.
3. **É lícito vender a PII a prestadores.** Falso: não é um permissible use da DPPA e vários estados proíbem explicitamente a solicitação comercial.

### O problema de seleção mais grave

Os limiares típicos de reporte:

| Estado | Limiar de reporte |
|---|---|
| TX | Injury/death ou danos ≥ **$1.000** por pessoa |
| NY | Injury/death ou danos > **$1.000** |
| FL | Injury, reboque, veículo comercial ou violação específica |
| MA | Injury/death ou danos > **$1.000** |
| IL | Injury/death ou danos acima do limiar estadual |

O cliente que "não quer acionar o seguro para não subir o prémio" é exatamente quem **não** tem incentivo para reportar um dano pequeno. O inventário disponível está enviesado para acidentes com lesão, reboque ou danos materiais relevantes — ou seja, o segmento **PI/lesão**, não o pequeno reparo de lataria. A tese de produto e a fonte de dados apontam para públicos diferentes.

---

## 3. Fontes de dados: o que existe de facto

### 3.1 Dados abertos agregados (sem PII) — viável

| Fonte | Conteúdo | PII | Atualização |
|---|---|---|---|
| NYC Open Data — Motor Vehicle Collisions: Crashes (`h9gi-nx95`), Vehicles (`bm4k-52h4`), Person (`f55k-p6yu`) | data/hora, borough, ZIP, rua, lat/lng, tipo de veículo, lesões, fatores | **Não** (sem nomes/telefones) | diária/semanal |
| Chicago — Traffic Crashes: Crashes (`85ca-t3if`), Vehicles (`68nd-jvt3`), People (`u6pd-qa9d`) | crash, veículos, pessoas (tipo/lesão), geocode | **Não** — o portal exclui PII explicitamente | diária |
| Boston — Vision Zero Crash Records (Analyze Boston) | data/hora, local, tipo, gravidade | **Não** | periódica |
| Dallas — Crash Data / Dallas Open Data | crash, local, gravidade | **Não** | periódica |
| Austin — Traffic Crashes | crash, local, lesões | **Não** | periódica |
| LA / Seattle / Philadelphia | datasets equivalentes | **Não** | periódica |
| TxDOT CRIS — extract files | crash statistics estaduais | **Não** (agregado) | anual/periodica |
| IDOT / MassDOT / FLHSMV dashboards | estatísticas e mapas | **Não** | periódica |

**Conclusão:** dá para construir um produto de inteligência de sinistralidade com dados gratuitos, atualização diária e cobertura nas quatro praças atuais. Não dá para contactar vítimas com estes dados.

### 3.2 Relatórios de acidente com PII — inviável para lead gen

| Estado | Acesso | PII | Restrição crítica |
|---|---|---|---|
| **TX** | CR-3, **$6**; relatório **redigido** para qualquer pessoa; completo só para "person directly concerned or having a proper interest" | Nome, morada, DL, DOB, placa, telefone | A lista legal de destinatários não inclui lead vendors; o relatório redigido remove precisamente os campos necessários |
| **FL** | Long form; confidencial **60 dias**; depois, só para entidades elegíveis ou permissible uses da DPPA | Nome, morada, telefone, seguro | **Sworn statement obrigatório** de que não será usado para "commercial solicitation of accident victims"; violação = **felony de 3.º grau** + $2.500 de danos liquidados |
| **NY** | MV-198C; "proper interest"; FOIL para registos DMV | Nome, morada, DL, DOB | Acesso a registos de outra pessoa exige certificação de permissible use DPPA; FOIL tem exceções de privacidade |
| **IL** | IDOT/State Police; relatórios confidenciais (625 ILCS 5/11-412) | Nome, morada, lesões | Uso admitido para fins **estatísticos/analíticos**; não para solicitação comercial |
| **MA** | RMV; **$20** de search fee por relatório | Nome, morada, lesões | Categorias de "permitted use" no formulário; não é feed aberto |

**Conclusão:** não existe um feed legal, em bulk, de relatórios com PII para revenda. Onde o relatório é obtível, o destinatário tem de ser parte/lesado/seguradora/advogado com propósito legítimo — e a revenda a body shops/reboques não é um propósito legítimo.

### 3.3 O telefone do proprietário

Mesmo com o relatório, o telefone nem sempre existe. Quando não existe, o enriquecimento teria de vir de:

- skip trace / credit header (FCRA/GLBA/DPPA);
- registos DMV (DPPA);
- dados de seguradoras (contrato, não scraping).

O `phone_enrichment.py` atual (crawl de websites de empresas) **não serve** para consumidores: não há website pessoal com telefone. Isto elimina a principal vantagem técnica que o pipeline atual oferece no B2B.

---

## 4. Conformidade legal

### 4.1 DPPA — 18 U.S.C. § 2721

A DPPA protege "personal information" obtida em motor vehicle records: nome, morada, telefone, DL, SSN, foto. Os permissible uses incluem governo, segurança, emissões, seguradoras, investigação de litígios, investigação licenciada, pesquisa estatística e marketing em bulk **com consentimento expresso**.

O que **não** existe na lista:

- vender contactos de acidentes a body shops;
- vender contactos a reboques;
- vender leads a advogados por conta própria;
- usar dados para solicitação comercial sem consentimento.

Regras de revenda: um destinatário autorizado só pode revender para usos permitidos; tem de manter registos durante 5 anos. Pesquisa estatística (b)(5) não pode ser usada para contactar indivíduos.

**Penalidades civis:** mínimo de **$2.500 por pessoa** em danos liquidados, mais danos punitivos e honorários. **Penalidade criminal:** multa até **$5.000**. Uma base com 10.000 vítimas é uma exposição de **$25 milhões** em liquidated damages, antes de punitive e fees.

### 4.2 Estatutos estaduais

- **FL:** 316.066(2)(d) exige sworn statement contra "commercial solicitation of accident victims"; 316.066(3)(d) classifica a violação como felony de 3.º grau; 316.066(3)(e) acrescenta a ação civil DPPA. É o estado mais hostil ao modelo.
- **TX:** 550.065 limita o relatório completo a partes com "proper interest"; 550.065(c-1) cria a versão redigida para o público. Penal Code § 38.12 (barratry) e a regra disciplinar 7.03 proíbem solicitação direta de vítimas; a comunicação escrita tem janela de 30 dias.
- **NY:** DMV exige certificação DPPA para registos de terceiros; FOIL não garante PII. A solicitação de vítimas por agentes é escrutinada pelas regras de publicidade/advocacia.
- **IL:** 625 ILCS 5/11-412 trata os relatórios como confidenciais; o uso é estatístico/analítico.
- **MA:** RMV só liberta mediante categorias de permitted use e cobra $20 por pesquisa.

### 4.3 Solicitação por advogados

Mesmo que os dados fossem lícitos, o comprador PI tem regras próprias:

- **TX:** barratry; proibição de contacto direto e de mail nos 30 dias seguintes;
- **FL:** Rule 4-7.18; proibição de contacto direto e de mail nos 30 dias;
- **NY/IL/MA:** regras equivalentes de solicitação e publicidade.

Um lead vendor que aborda a vítima em nome do escritório pode ser tratado como agente do advogado. O escritório responde disciplinarmente; o vendor perde o cliente e o contrato.

### 4.4 TCPA e telemarketing

- Chamadas/textos automáticos para consumidores exigem consentimento prévio expresso; o DNC nacional aplica-se.
- O motor atual (`b2b_voice`) é **B2B**: `entity_type == business`, `PIPELINE_STATES`, DNC com bypass `staging_clear`, 9–20 local, 50/dia por DID. Não é um motor de consumer outreach.
- O `staging_clear` é aceitável para prospeção B2B em staging, **não** é consentimento TCPA para consumidores.
- States mini-TCPAs (FL, OK, WA, etc.) acrescentam requisitos.

### 4.5 Publicidade e ética

- Advogados não podem partilhar honorários com não-advogados; o modelo tem de ser fee-for-advertising/lead, não percentagem de honorários.
- Body shops e reboques têm regras estaduais sobre "runners", "capping" e solicitação no local do acidente.
- Vender a mesma vítima a vários compradores agrava o dano e a exposição.

---

## 5. Viabilidade técnica e reutilização do engine

### 5.1 O que se reutiliza bem

| Capacidade | Módulo atual | Reuso | Gap |
|---|---|---|---|
| Ingestão multi-fonte | `discovery_engine`, `contractor_ingest`, `b2b_voice.sync_source` | padrão de fetch, normalização, idempotência | adapters Socrata/ArcGIS/CSV; sem licenças |
| Dedupe / entity resolution | `entity_bridge` | conceito de chave externa | chave passa a `source:crash_id`, não e-mail |
| Geocoding | `geo_lookup` | cache hit/miss e resiliência | NYC BBL/PLUTO não serve; usar Census/TIGER/OSM |
| Segmentos | `b2b_voice.rebuild_segments`, `segments` | agregação por cidade/nicho | novo `collision_segments` por ZIP/corredor/raio |
| Admin | `/admin/voice` + polling 30 s | shell, cards, liquidez, live | nova página `/admin/collision` |
| Voz | `auto_dialer`, `telnyx_voice`, `voice_scripts` | chamadas a **buyers** B2B | não usar para vítimas |
| E-mail | `outbound_engine` | prospeção de buyers | não usar para vítimas |
| Vitrine | `showcase.py` | páginas públicas de procura agregada | sem PII; k-anonimato |
| Push/chat | roadmap `CHAT-INBOX-ROADMAP.md` | canal inbound do marketplace | ainda não implementado |
| Billing | Stripe | assinatura/lead fees | novos produtos |

### 5.2 O que **não** se reutiliza

- **Enriquecimento de telefone de consumidores.** O crawl de websites encontra telefones de empresas; não encontra telefones pessoais. Skip trace é pago e regulado.
- **Discador de voz para vítimas.** O gate exige `business`, DNC e janela 9–20; falta consentimento, opt-out e architectura de consumer.
- **Tabelas `leads` / `prospect_companies`.** `leads` é 1 linha por morada/cidade com histórico de violações; `prospect_companies` é empresa com telefone único. Misturar vítimas com estas tabelas contamina o produto principal e os guardrails.
- **DNC `staging_clear`.** Não é DNC real nem consentimento.

### 5.3 Modelo de dados proposto (novo, isolado)

```sql
collision_sources (
  id, kind, name, url, state, city, cadence, last_sync_at, enabled
);

collision_events (
  id, source_id, external_id, occurred_at, city, county, state, zip,
  lat, lng, corridor, severity, injuries, fatalities, vehicles,
  raw_json, created_at,
  UNIQUE(source_id, external_id)
);

collision_vehicles (
  id, event_id, vehicle_type, damage_area, towed, occupant_count
);

collision_segments (
  id, city_slug, zip, corridor, period_days, total, injury_count,
  fatality_count, tow_count, demand_index, updated_at
);

collision_buyers (
  id, name, kind, city, state, zip, phone, email, status, plan
);

collision_campaigns (
  id, name, segment_json, status, budget, created_at, sent_at
);
```

Regras:

- **Nenhuma PII** em `collision_events`.
- `collision_segments` com **k ≥ 5** por célula (ZIP × período × tipo); abaixo disso, agregar para cidade/condado.
- Retenção de raw 90 dias; agregados indefinidos.
- `collision_buyers` é B2B e pode reutilizar o pipeline de enriquecimento/outbound existente.

### 5.4 Pipeline de ingestão

```text
Socrata / ArcGIS / CSV
   → fetch incremental ($where updated_at > last_sync, $limit/$offset)
   → normalizar schema (data, local, lat/lng, feridos, reboque)
   → geocodificar (Census/OSM) e mapear ZIP/condado
   → dedupe por source:external_id
   → agregar por ZIP/corredor/período (k ≥ 5)
   → collision_segments
   → dashboard/API de buyers
```

Custo: $0 de dados; apenas compute e engenharia. Cadência diária é suficiente; não há valor em "contínuo" para este produto.

### 5.5 Esforço estimado

| Entrega | Estimativa |
|---|---|
| Adapter NYC + Chicago + Dallas + Boston | 1–2 semanas |
| Geocoding + agregação + k-anonimato | 1 semana |
| Dashboard `/admin/collision` + API | 1–2 semanas |
| Contratos/termos com buyers | 1 semana (jurídico) |
| **MVP agregado** | **3–4 semanas** |
| Marketplace inbound (chat + consent + routing) | +4–6 semanas |

O modelo original de PII não tem estimativa de engenharia porque **não deve ser construído**.

---

## 6. Mercado comprador e liquidez

### 6.1 Comparação

| Comprador | Valor por lead (referência de mercado) | Valor do job | Volume | Risco |
|---|---|---|---|---|
| **PI lawyers** | $100–$1.000+ por lead; $1.500–$8.000 por caso assinado | honorários de $10k–$100k+ | alto em metros | **muito alto**: solicitação, barratry, 30 dias, ética |
| **Body shops** | $20–$75 por lead | reparação $2.500+ | médio | médio: steering, referral, publicidade |
| **Towing** | $13–$40 por lead | ~$180 por serviço | alto e urgente | médio: rotação policial, "predatory towing" |

### 6.2 Leitura

- **PI lawyers** têm a maior liquidez e o maior ticket, mas são o comprador mais difícil de servir legalmente. Sem consentimento inbound e sem respeitar a janela de 30 dias, o produto é tóxico.
- **Body shops** são o ponto de equilíbrio: ticket alto, lead barato, menos restrições de solicitação do que advogados — mas o fluxo é dominado por seguradoras/DRP e o shop desconfia de leads frios.
- **Towing** é o mais fraco: lead barato, job pequeno, e o dispatch já vem da polícia/rotação. Não sustenta a plataforma sozinho.

**Conclusão:** o único segmento com liquidez real para "lead de acidente" é PI, e é precisamente o mais regulado. O segmento que resta (body shops) compra melhor **inteligência de demanda** do que contactos de vítimas.

---

## 7. Modelo recomendado (pivot)

### Opção A — Crash Intelligence (recomendado)

**Produto:** dashboard/API de sinistralidade agregada por ZIP, corredor e período, com volume, gravidade, tipo de dano, reboque e índice de demanda. Sem PII.

**Compradores:** body shops (planeamento de capacidade), reboques (posicionamento), seguradoras (risco), municípios (Vision Zero).

**Preço:** $99–$499/mês por localização/empresa; relatórios custom.

**Vantagens:** usa open data, zero DPPA, zero TCPA, margem alta, vendável pelo outbound B2B existente.

**Limitação:** não é "lead gen"; é SaaS de dados. O ticket é menor, mas o risco também.

### Opção B — Marketplace inbound de ajuda

**Produto:** landing/chat onde o consumidor pede reboque, reparação ou apoio jurídico; dá consentimento explícito; o sistema encaminha para 1–3 prestadores locais.

**Compradores:** body shops, reboques, advogados — com contrato e regras de conduta.

**Pré-requisitos:** chat/inbox do roadmap, consentimento, opt-out, quiet hours, routing, SLA, preço por lead ou assinatura.

**Vantagens:** intenção real, consentimento, sem DPPA; é o modelo que os vendors "DPPA-compliant" usam na prática.

**Limitação:** exige tráfego e marca; é um negócio de marketing, não só de dados.

### Opção C — Venda de relatórios/PII (rejeitada)

Não avançar. O risco criminal e civil é desproporcionado; o acesso em bulk não existe; e a economia não compensa o custo jurídico.

---

## 8. Riscos e mitigação

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| DPPA class action ($2.500/pessoa) | alta no modelo C | crítico | não usar PII; só agregados |
| FL felony por solicitação | alta no modelo C | crítico | não operar relatórios FL para solicitação |
| Barratry/solicitação TX/FL | alta no modelo C | crítico | inbound consent + janela de 30 dias |
| TCPA/DNC em calls/textos | alta no modelo C | alto | consentimento, opt-out, quiet hours |
| Relatório sem telefone | alta | alto | não prometer contacto; agregar |
| Viés para lesão, não fender bender | alta | alto | reposicionar produto |
| Concorrência de vendors de leads | média | médio | diferenciar por dados/analytics |
| Compradores fragmentados | média | médio | começar por 2 praças e 10 buyers |
| Reidentificação em células pequenas | média | alto | k ≥ 5, agregação temporal |
| Contaminação do produto principal | média | alto | schema isolado (`collision_*`) |

---

## 9. Plano de 30 dias e go/no-go

### Semanas 1–2 — Legal e validação

- Parecer de advogado US sobre DPPA, FL 316.066, TX 550.065/barratry, IL 11-412, MA RMV.
- Confirmar que nenhum dado de vítima será vendido.
- Entrevistar 5 body shops, 3 reboques e 3 advogados PI em NYC/Dallas.
- Definir preço e contrato de buyer.

**Gate:** parecer favorável ao modelo agregado/inbound. Sem parecer, não há código.

### Semanas 3–4 — Protótipo agregado

- Ingestão NYC + Chicago + Dallas + Boston.
- Geocoding e agregação com k ≥ 5.
- Dashboard `/admin/collision` com 3 visões: volume, gravidade, demanda por ZIP.
- 2 buyers em piloto read-only.

**Gate:** 2 buyers dispostos a pagar $99–$299/mês ou carta de intenção.

### Semanas 5–8 — Marketplace inbound (se gate passou)

- Landing/chat com consentimento.
- Routing para 1–3 buyers.
- Preço por lead e SLA.
- Piloto em 1 cidade, 1 vertical (body shop ou reboque).

**Gate:** 20 leads, 30% de aceitação, zero reclamação.

---

## 10. Decisões necessárias

1. **Confirmar o NO-GO** ao modelo de relatórios com PII.
2. Escolher o pivot: **A (intelligence)** ou **B (inbound marketplace)** — ou A primeiro, B depois.
3. Autorizar parecer jurídico US (estimativa $5k–$15k) antes de qualquer implementação.
4. Escolher 2 praças iniciais (NYC + Dallas são as mais óbvias pelo engine atual).
5. Definir se o produto é vendido como **SaaS** ou **lead fee**; não misturar.
6. Nomear um owner de compliance (DPPA/TCPA) com veto sobre features.

---

## 11. Fontes

**DPPA**
- 18 U.S.C. § 2721 — permissible uses: https://www.law.cornell.edu/uscode/text/18/2721
- 18 U.S.C. § 2724 — civil action, $2.500 liquidated damages: https://www.law.cornell.edu/uscode/text/18/2724

**Estados**
- TX Transportation Code § 550.065 — release, redacted report, $6: https://statutes.capitol.texas.gov/GetStatute.aspx?Code=TN&Value=550.065
- FL Stat. § 316.066 — 60 days, sworn statement, felony: https://www.flsenate.gov/Laws/Statutes/2025/0316.066
- IL 625 ILCS 5/11-412 — crash reports confidential: https://ilga.gov/documents/legislation/ilcs/documents/062500050K11-412.htm
- NY DMV — MV-198C / DPPA permissible use: https://dmv.ny.gov/records/request-another-persons-records
- MA RMV — crash report, $20 search fee, permitted use: https://www.mass.gov/how-to/request-a-copy-of-a-police-crash-report

**Solicitação**
- Texas barratry / solicitation: https://www.texasbar.com/Content/NavigationMenu/ForLawyers/GrievanceandEthics/SolicitationandBarratry/default.htm
- Florida Bar Rule 4-7.18 — 30-day ban: https://floridajustice.com/rule/4-7-18/

**Dados abertos**
- NYC collisions: https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95
- Chicago traffic crashes: https://data.cityofchicago.org/Transportation/Traffic-Crashes-Crashes/85ca-t3if
- Boston Vision Zero: https://data.boston.gov/dataset/vision-zero-crash-records
- Dallas crash data: https://egisdata-dallasgis.hub.arcgis.com/datasets/dallas-crash-data
- TxDOT crash data: https://www.txdot.gov/data-maps/crash-reports-records/crash-data-analysis-statistics.html

**Mercado**
- PI lead pricing 2026: https://cimmp.com/how-much-do-personal-injury-leads-cost/
- Auto body lead pricing: https://adwave.com/resources/auto-body-shop-advertising
- Towing lead economics: https://www.towmarx.com/the-dispatch/tow-company-lead-generation

---

## 12. Nota final

O engine da Magic Leads é valioso para esta vertical, mas não pelo motivo inicialmente pensado. O que transfere é a capacidade de **ingerir dados públicos, normalizar, geocodificar, segmentar e operar um admin** — não a capacidade de contactar vítimas. O produto defensável é **inteligência de sinistralidade + inbound com consentimento**, não a revenda de relatórios.

**Recomendação final:** NO-GO ao modelo proposto; GO condicional a uma discovery de 2 semanas do pivot agregado, com parecer jurídico US como primeiro entregável.
