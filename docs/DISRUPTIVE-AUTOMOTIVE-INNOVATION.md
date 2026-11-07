# Estudo de Viabilidade v3 — Inovação Disruptiva Automóvel

**Data:** 2026-11-06  
**Natureza:** documento estratégico isolado. **Zero código, zero deploy, zero alteração ao Magic Leads, motor de voz ou infraestrutura atual.**  
**Critérios:** 60 dias, B2B, sem dependência de telemática/seguradoras/DMS, sem PII de consumidor, alto ROI imediato.

---

## 1. Sumário executivo

**Tese:** o maior "boom" B2B de 60 dias não está em detetar acidentes — está em **recuperar o dinheiro que as oficinas já ganharam mas não documentaram**. O mercado americano de colisão perde **~$1.023 por estimativa** em operações omitidas; 63% das reparações exigem supplement. As oficinas sabem que perdem, mas não têm um sistema que audite, documente e cobre.

Três conceitos, sequenciados:

| # | Conceito | Comprador | Receita | 60 dias? | Moat |
|---|---|---|---|---|---|
| **1** | **Claim Completeness AI** — auditoria e supplement automático por OEM | Body shops, MSOs, dealers | 15–20% do recuperado ou $399–$799/mês | **Sim** | Dados de gaps + outcomes + benchmark de seguradoras |
| **2** | **Calibration & Sublet Exchange** — rede de calibração ADAS e sublet especializado | Body/glass shops, dealers | 15–20% take rate + SaaS | **Sim** | Densidade da rede + certificação + documentação |
| **3** | **Collision Repair Data Cooperative** — benchmark anónimo de reparações e comportamento de seguradoras | Associações, distribuidores, PE, oficinas | $2k–$10k/mês por comprador | **Sim** | Rede de dados + confiança + índice proprietário |

**Recomendação:** lançar o **#1** em 60 dias. É o único que gera receita na primeira semana, com prova de ROI em 48 horas e um comprador que já sente a dor. O #2 é o cross-sell natural para os mesmos compradores. O #3 é a camada de moat que se constrói com os dados do #1 e #2.

---

## 2. Porque os estudos anteriores não chegaram lá

| Estudo | Problema |
|---|---|
| v1 (relatórios de acidente) | Dependia de PII e acesso legal inexistente |
| v2 (telemática/SDK) | Dependia de Samsara/CMT/Waze e de distribuição de terceiros |

O v3 inverte a lógica:

```text
Não procurar o acidente.
Procurar o dinheiro que já está na oficina e não é cobrado.
```

É um mercado **B2B**, com comprador identificável, dor quantificável e ROI em dias — não em meses.

---

## 3. O conceito #1 — Claim Completeness AI

### 3.1 A dor

Uma estimativa de colisão é construída pelo software (CCC, Mitchell, Audatex), mas o software **não cruza automaticamente** com os procedimentos OEM do veículo específico. O resultado é estrutural:

- **63%** das reparações de colisão exigem supplement (dados CCC).
- Em **257 repair orders** auditadas, a média foi **$1.023 por estimativa** em operações omitidas; **4.078 operações** e **$262.818** encontrados.
- As quatro categorias que explicam a maioria:

| Categoria | Exemplo |
|---|---|
| **ADAS** | recalibração de radar/câmara exigida pelo OEM e ausente |
| **Fasteners** | parafusos/componentes de uso único não identificados |
| **Refinish** | operações "not-included" executadas e não cobradas |
| **OEM procedures** | proteção anticorrosiva, seam sealer, masking, etc. |

Uma oficina com 30 jobs/mês deixa **~$30.690/mês** na mesa. **$368k/ano.** Não porque o trabalho não foi feito — porque não foi documentado.

### 3.2 O produto

```text
Upload da estimativa / repair order / fotos
        ↓
OCR + extração LLM (linhas, operações, peças, veículo)
        ↓
Motor de regras OEM (procedimentos, ADAS, fasteners, refinish)
        ↓
Lista de gaps + evidência + pacote de supplement
        ↓
Oficina revê e aprova
        ↓
Submissão à seguradora (email/portal) + tracking
        ↓
Dashboard: $ recuperado, taxa de aprovação, ciclo
```

**Não é um "auditor" passivo.** É um **sistema operativo de receita** que transforma cada estimativa num claim completo antes de sair da oficina.

### 3.3 Porque ninguém o faz em escala

| Player | O que faz | Porque não resolve |
|---|---|---|
| CCC / Mitchell / Solera | estimating + claims | alinhados com a seguradora, não com o shop; não auditam contra OEM para o shop |
| Estimate Optimizer | auditoria manual/AI de estimates | serviço fragmentado; não é o fluxo completo nem o benchmark |
| Consultores de supplement | revisão humana | caro, lento, não escala |
| Software de shop | DMS/CRM | passivo; não cruza OEM procedures |

**White space:** ninguém combina **auditoria automática + geração de supplement + tracking de recuperação + benchmark de seguradora** num produto de performance para o shop. O incumbente está do lado errado da mesa.

### 3.4 Comprador e liquidez

| Perfil | Tamanho | Dor | Capacidade de pagar |
|---|---|---|---|
| Body shop independente | ~31.350 firms (EUA) | 10–50 ROs/mês; margem apertada | **alta** — paga % do recuperado |
| MSO / multi-loja | consolidadores | padronização e receita | **muito alta** |
| Dealer body shop | ~18k dealers | processos e auditoria | alta |
| Associações | estaduais/nacionais | ferramenta para membros | alta (canal) |

**Economia por shop:**

```text
30 ROs/mês × $1.023 = $30.690 encontrados
15% de fee = $4.603/mês por shop
10 shops = $46k MRR
50 shops = $230k MRR
```

Mesmo com recuperação de 50%, o ROI é evidente. O fee por performance remove a objeção de preço.

### 3.5 Prova de conceito em 60 dias

| Semana | Entrega |
|---|---|
| 1 | 10 design partners; 50 repair orders; contratação de expert de colisão |
| 2 | OCR + extração; regras v1 (ADAS, fasteners, refinish, OEM) |
| 3 | Gerador de supplement; dashboard; Stripe |
| 4 | Piloto em 5 shops; medir $ encontrado por estimativa |
| 5 | Case study; outbound a 300 shops com auditoria gratuita |
| 6 | 10 shops pagantes; 50 auditorias |
| 7 | Tracking de resposta da seguradora; automação |
| 8 | 20 shops pagantes; 100 auditorias; benchmark inicial |

**Equipa:** 2 engenheiros, 1 expert de colisão (contrato), 1 sales/ops.  
**Custo:** $40k–$80k (expert, LLM/OCR, cloud, vendas).  
**Stack:** FastAPI, Postgres, S3, OCR (Textract/Tesseract), LLM (DeepSeek/GLM), regras em Python/JSON, Stripe.

**Reutilização do engine atual:**

| Capacidade | Uso |
|---|---|
| `prospect_companies` / `contractor_entities` | base de body shops e MSOs |
| `phone_enrichment` | telefones de decisores |
| `b2b_voice` / `outbound_engine` | outbound para shops |
| Admin | dashboard de contas, auditorias e recuperação |
| Stripe | fee por performance |
| Geocoding | agrupamento por mercado/seguradora |

**Novo:** upload/OCR, extração, motor de regras OEM, gerador de PDF, tracking.

### 3.6 Métricas e kill criteria

| Métrica | Meta |
|---|---|
| $ encontrado por estimativa | > $700 |
| Precisão das linhas | > 90% |
| Taxa de aprovação do supplement | > 60% |
| Tempo até supplement | < 30 min |
| Payback do shop | < 30 dias |
| CAC | < $1.500 |
| Churn | < 5%/mês |

**Kill:** < $500/estimativa; < 3 shops dispostos a pagar; precisão < 85%; recuperação < 30%.

### 3.7 Riscos

| Risco | Mitigação |
|---|---|
| Falso positivo / linha inválida | revisão humana; evidência OEM; não prometer valor |
| Seguradora rejeita | packet com citação OEM; histórico de aprovação |
| Licenciamento de procedimentos OEM | usar fontes públicas/OEM position statements; parceria com editor |
| Concorrência | velocidade, performance pricing, dados de outcome |
| Responsabilidade | contrato B2B; shop aprova; sem garantia de pagamento |

---

## 4. O conceito #2 — Calibration & Sublet Exchange

### 4.1 A dor

A complexidade do veículo explodiu. **68% dos veículos com ADAS exigem recalibração após substituição de para-brisas**; o mesmo acontece após colisão, alinhamento ou suspensão. As body shops não têm equipamento nem espaço para calibrar tudo. O processo atual é arcaico:

```text
telefonar a 5 fornecedores → preços diferentes → sem documentação
→ atraso de 2–5 dias → risco de comeback e responsabilidade
```

O mercado global de serviços de calibração ADAS foi **$8,4 mil milhões em 2025**, com CAGR ~11,3%. É recorrente, não é um evento único.

### 4.2 O produto

Uma **exchange B2B** que liga quem precisa a quem executa:

```text
Body/glass shop cria pedido (VIN, dano, localização, prazo)
        ↓
Match com provedores verificados num raio (H3)
        ↓
Bid/aceitação com preço, ETA, garantia
        ↓
Agendamento + recolha/entrega
        ↓
Provedor upload de pré/pós-scan + certificado
        ↓
Verificação AI + fatura + histórico
```

Cobre não só ADAS, mas **sublet especializado**: calibração, alumínio, frame, vidro, pintura móvel, diagnósticos.

### 4.3 Porque ninguém o faz

- **Fabricantes de equipamento** (Autel, Hunter) vendem hardware, não orquestração.
- **Provedores móveis** são locais e fragmentados; não têm marca nacional nem SLA.
- **Seguradoras** têm redes DRP, mas não um exchange neutro para o shop.
- **Software de shop** não gere sublet nem documentação.

**White space:** uma camada de confiança e documentação — o "Stripe Atlas" do sublet de colisão.

### 4.4 Comprador e liquidez

| Lado | Perfil | Porque paga |
|---|---|---|
| Demanda | body shops, glass shops, dealers | reduzir atraso, comeback e responsabilidade |
| Oferta | mobile calibration techs, speciality shops | acesso a procura previsível |

**Economia:**

```text
Calibração média: $250
Take rate 18% = $45 por job
500 jobs/mês = $22.5k
+ SaaS $199/mês × 100 shops = $19.9k MRR
```

### 4.5 Prova de conceito em 60 dias

| Semana | Entrega |
|---|---|
| 1–2 | 20 provedores em Dallas; 30 shops; tabela de preços/SLA |
| 3–4 | Formulário de pedido, matching, agendamento, upload de certificado |
| 5–6 | 50 jobs piloto; verificação; tempo médio |
| 7–8 | Lançamento em Dallas + NYC; 100 jobs |

**Reutilização:** diretório de empresas, phone enrichment, outbound, admin, Stripe Connect, geocoding.

### 4.6 Riscos

| Risco | Mitigação |
|---|---|
| Densidade de oferta | começar numa metro; recrutar 20 provedores |
| Qualidade/no-show | verificação, seguro, score, depósito |
| Preço commoditizado | garantia, documentação, SLA |
| Responsabilidade | contrato, seguro, certificado assinado |

---

## 5. O conceito #3 — Collision Repair Data Cooperative

### 5.1 A dor

As oficinas não sabem se estão a ser pagas de forma justa. As seguradoras sabem tudo; as oficinas têm anedotas. Os surveys de labor rate são manuais, anuais e opacos. Não existe um **índice contínuo** de comportamento de seguradora por mercado, tipo de dano e veículo.

### 5.2 O produto

Uma cooperativa de dados anónimos:

```text
Shop upload de repair orders (PDF/CSV)
        ↓
Anonimização (shop, cliente, VIN)
        ↓
Normalização (linhas, operações, peças, tempos)
        ↓
Agregação com k ≥ 10
        ↓
Dashboard: labor rate, margem de peças, ciclo, negação,
underpayment, supplement recovery por seguradora/ZIP
```

**Produto:** benchmark mensal + relatórios + API. As oficinas recebem o benchmark gratuitamente; distribuidores, PE, associações e lenders pagam.

### 5.3 Porque ninguém o faz

- **Surveys** (LaborRateHero, Crash Network) são pontuais e declared, não observados.
- **CCC/Verisk** têm dados, mas vendem a seguradoras — não ao shop.
- **Associações** fazem surveys manuais, sem granularidade.
- **Shops** receiam partilhar dados; falta um aggregator neutro com valor imediato.

**White space:** um **Bloomberg da reparação** — observado, anónimo, contínuo.

### 5.4 Comprador e liquidez

| Comprador | Uso | Disposição a pagar |
|---|---|---|
| Oficinas | benchmark + negociação | baixa (freemium) |
| Associações | ferramenta para membros | média |
| Distribuidores de peças | alocação de inventário | **alta** ($2k–$10k/mês) |
| PE / consolidadores | due diligence e market map | **muito alta** |
| Seguradoras | benchmark de mercado | alta (mas conflito) |

### 5.5 Prova de conceito em 60 dias

| Semana | Entrega |
|---|---|
| 1–2 | 20 shops; acordo de dados; 500 ROs |
| 3–4 | Anonimização, normalização, dashboard |
| 5–6 | Relatório benchmark; 10 entrevistas a compradores |
| 7–8 | 3 pilotos pagos (distribuidor/PE/associação) |

**Reutilização:** admin, segmentação, reporting, Stripe.

### 5.6 Riscos

| Risco | Mitigação |
|---|---|
| Shops não partilham | benchmark grátis + recovery; opt-in; transparência |
| Amostra pequena | k ≥ 10; agregar por mercado |
| Reidentificação | hash, supressão, contrato |
| Concorrência | velocidade + rede + confiança |

---

## 6. Comparação e recomendação

| Critério | #1 Claim AI | #2 Calibration | #3 Data Coop |
|---|---|---|---|
| Time to MVP | **6–8 semanas** | 6–8 semanas | 8 semanas |
| Time to first revenue | **1–2 semanas** | 3–6 semanas | 6–10 semanas |
| ACV | **$3k–$6k/mês** | $200–$500/mês + take | $2k–$10k/mês |
| Nº de compradores | **31k body shops** | 31k + glass/dealers | 20–50 grandes |
| Sales cycle | **1–4 semanas** | 2–6 semanas | 1–3 meses |
| Prova de ROI | **imediata ($)** | imediata (tempo) | média |
| Moat | **dados de gap/outcome** | rede | dados + confiança |
| Risco regulatório | baixo (B2B) | baixo (B2B) | baixo (agregado) |
| "Boom" | **muito alto** | alto | médio |

**Sequência recomendada:**

```text
#1 Claim Completeness AI (0–60 dias)
        ↓ cross-sell
#2 Calibration & Sublet Exchange (60–120 dias)
        ↓ data layer
#3 Collision Repair Data Cooperative (6–12 meses)
```

O #1 dá cash e acesso aos shops. O #2 aumenta o ticket e a frequência. O #3 transforma os dados em moat e em receita de alto ACV.

---

## 7. Arquitetura comum

### 7.1 Stack

| Camada | Escolha |
|---|---|
| API | FastAPI |
| OLTP | PostgreSQL |
| Ficheiros | S3 (PDFs, fotos, certificados) |
| OCR/LLM | Textract/Tesseract + DeepSeek/GLM |
| Regras | Python + JSON (OEM procedures) |
| Pagamentos | Stripe / Stripe Connect |
| Admin | React/Next (padrão atual) |
| Observabilidade | OpenTelemetry + Grafana |
| Anonimização | hash + k-anonymity |

### 7.2 Modelo de dados (#1)

```sql
shops (id, name, city, state, phone, email, status, plan);

repair_orders (
  id, shop_id, vehicle_ymm, vin_hash, insurer, estimate_total_cents,
  status, uploaded_at, audited_at
);

line_items (
  id, repair_order_id, operation_code, description,
  labor_cents, parts_cents, source, confidence
);

gaps (
  id, repair_order_id, category, operation_code, description,
  evidence, estimated_cents, status
);

supplements (
  id, repair_order_id, total_cents, pdf_path,
  submitted_at, response, recovered_cents
);
```

### 7.3 Modelo de dados (#2)

```sql
providers (id, name, kind, h3_r8, services, certs, insurance, rating);

sublet_requests (
  id, shop_id, vehicle_ymm, service, h3_r8, deadline, status
);

bids (id, request_id, provider_id, price_cents, eta_min, warranty_days);

certificates (id, request_id, provider_id, pre_scan, post_scan, pdf_path);
```

### 7.4 Modelo de dados (#3)

```sql
ro_facts (
  id, market, insurer, vehicle_class, labor_rate_cents,
  parts_margin_pct, cycle_days, denied_cents, recovered_cents,
  period, k_anon_bucket
);

benchmarks (
  id, market, insurer, period, metric, value, sample_size
);
```

### 7.5 Segurança

- B2B apenas; sem PII de consumidor.
- VIN e cliente hashed; PDFs em S3 com KMS.
- Acesso por shop; audit log.
- k ≥ 10 em benchmarks; sem células pequenas.
- Contratos de dados e opt-in para a cooperativa.

---

## 8. Plano de 60 dias do #1 (detalhado)

### 8.1 Semanas 1–2 — Descoberta e regras

- 10 design partners (body shops em Dallas/NYC).
- 50 repair orders reais (PDF) com autorização.
- Contratar 1 expert de colisão (20h/semana).
- Definir as 4 categorias de gap e as regras v1.
- Escolher 2 seguradoras para o piloto.

**Gate:** 5 shops comprometem-se com piloto; 50 ROs recebidos.

### 8.2 Semanas 3–4 — MVP

- Upload + OCR + extração LLM.
- Motor de regras v1.
- Gerador de supplement em PDF.
- Dashboard simples (ROs, gaps, $).
- Stripe (fee por performance).

**Gate:** 5 auditorias manuais com $ encontrado > $700.

### 8.3 Semanas 5–6 — Piloto

- 5 shops; 50 auditorias.
- Medir precisão, aprovação, tempo.
- Case study com $ recuperado.
- Outbound a 300 shops com auditoria gratuita.

**Gate:** 3 shops pagantes; aprovação > 50%.

### 8.4 Semanas 7–8 — Escala inicial

- Automação de tracking de resposta.
- 10–20 shops pagantes.
- 100 auditorias.
- Primeiro benchmark de seguradora.

**Gate:** $10k MRR; CAC < $1.500; churn < 5%.

### 8.5 Equipa e custo

| Item | Custo |
|---|---|
| 2 engenheiros (8 semanas) | $40k–$70k |
| Expert de colisão (contrato) | $8k–$15k |
| LLM/OCR/cloud | $2k–$5k |
| Vendas/ops | $5k–$10k |
| **Total** | **$55k–$100k** |

---

## 9. Unit economics (#1)

| Item | Valor |
|---|---|
| Fee | 15% do recuperado |
| Média encontrada/shop/mês | $30.690 |
| Receita/shop/mês | $4.603 |
| 10 shops | $46k MRR |
| 50 shops | $230k MRR |
| Custo variável (LLM/OCR/support) | 15–20% |
| Margem bruta | 80–85% |
| CAC | $1.000–$1.500 |
| Payback | < 1 mês |

**Pressupostos:** 30 ROs/mês, $1.023/RO, recuperação de 60–80%. Números conservadores devem usar 50% de recuperação.

---

## 10. Riscos transversais

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Precisão insuficiente | média | alto | human-in-the-loop; regras conservadoras |
| Seguradora rejeita | média | médio | evidência OEM; histórico; não garantir |
| Shops não confiam | média | alto | free audit; performance pricing; case studies |
| Concorrência | alta | médio | velocidade; dados; cross-sell |
| Licenciamento OEM | média | médio | fontes públicas; parcerias |
| Densidade de rede (#2) | alta | alto | 1 metro; 20 providers |
| Dados (#3) | média | médio | opt-in; k-anonymity; benchmark grátis |

---

## 11. Outras faíscas (para o radar)

| Ideia | Novidade | 60 dias | Veredicto |
|---|---|---|---|
| **Fleet Upfit Concierge** — marketplace de upfit para frotas pequenas | média | sim | bom #4; ticket alto, ciclo médio |
| **Parts Demand Radar** — previsão de peças por ZIP para distribuidores | alta | sim | alto ACV, poucos compradores |
| **Hail & Storm Capacity Command** — pré-posicionar PDR/oficinas antes de granizo | alta | sim | sazonal, urgência alta |
| **Shop M&A Marketplace** — compra/venda de oficinas com valuation data-driven | média | sim | ciclo longo, alto valor |
| **Equipment Sharing** — aluguer de ferramentas ADAS/frame entre shops | alta | sim | nicho, risco de ativo |
| **OEM Certification Navigator** — auditar e preparar certificações | média | sim | nicho, consultoria |
| **EV Battery Triage** — diagnóstico e routing de baterias | alta | não | 12–18 meses |
| **Insurer Scorecard** — índice de comportamento de seguradoras | alta | sim | base do #3 |

---

## 12. Decisões necessárias

1. **Aprovar o #1** como aposta de 60 dias.
2. Escolher a metro inicial: **Dallas** (custo, rede) ou **NYC** (densidade, ticket).
3. Contratar o expert de colisão antes de escrever regras.
4. Definir fee: **15%** ou **$499/mês + 10%**.
5. Assinar 10 design partners na semana 1.
6. Comprometer 2 engenheiros e 1 sales/ops.
7. Se o #1 atingir o gate, abrir o #2 em 90–120 dias.

---

## 13. Fontes

- 63% dos reparos exigem supplement; $1.023/estimativa em 257 ROs: https://estimateoptimizer.com/blog/auto-body-shop-insurance-underpayment-pattern-audit-results
- 31.350 firms de body shop, $52,9bn: https://verticaliq.com/product/auto-body-shops/
- IBISWorld body shops: https://www.ibisworld.com/united-states/industry/auto-body-shops/1694/
- 78.600 firms de reparação, 82.500 shops, $55bn: https://www.bvresources.com/docs/default-source/free-downloads/viq_industry_sample_auto_repair_12_12_22.pdf
- 68% dos veículos ADAS exigem recalibração após para-brisas; mercado $8,4bn: https://dataintelo.com/report/adas-calibration-service-market
- Mercado de calibração ADAS: https://www.fortunebusinessinsights.com/adas-calibration-services-market-115495
- 39% pagam reparações do próprio bolso: https://www.autobodynews.com/news/almost-40-of-insured-drivers-paid-for-repairs-out-of-pocket-survey
- CCC average repair $4,818: https://www.cccis.com/reports/crash-course-2025/q2
- Labor rate surveys: https://www.laborratehero.com/

---

## 14. Nota final

O #1 não é "mais um software para oficinas". É um **mecanismo de recuperação de receita** com prova financeira imediata:

```text
Auditoria gratuita → $ encontrado → supplement → dinheiro na conta → fee
```

É B2B, não toca em PII de consumidor, não depende de CCC/Mitchell/Seguradoras/DMS, e pode ser lançado em 60 dias com a infraestrutura que já existe.

**Recomendação final:** GO para o #1; #2 como cross-sell; #3 como moat. O deploy e a operação principal permanecem intocados.
