# Estudo de Viabilidade v2 — Collision Innovation

**Data:** 2026-11-06  
**Natureza:** análise estratégica isolada. **Zero código, zero deploy, zero alteração ao produto principal.**  
**Documento anterior:** `docs/COLLISION-LEADS-FEASIBILITY.md` (DPPA e acesso a relatórios).

---

## 1. Sumário executivo

**Tese:** o espaço não é "mais um marketplace de leads". É **infraestrutura do momento zero** — detetar, decidir e orquestrar assistência nos primeiros 120 segundos — e **inteligência de demanda out-of-pocket** para prestadores. O consumidor não procura "leads"; procura alguém que resolva o problema antes de ele pensar em procurar.

Três apostas, sequenciadas:

| Aposta | O que é | Prazo | Capital | Porquê |
|---|---|---|---|---|
| **A. Provider Demand Intelligence** | SaaS B2B que prevê demanda de reparação out-of-pocket por H3/hora para body shops e reboques | **0–6 meses** | baixo | Receita mais rápida; usa open data; sem PII de consumidor; cria o data moat |
| **B. Moment-Zero SDK** | SDK/API embebido em apps de frotas, dashcams, estacionamento e mecânicas; deteta o sinistro e oferece ajuda pré-aprovada | **6–18 meses** | médio | Distribuição via parceiros; dados proprietários do evento; maior ceiling |
| **C. Driver-Owned Crash Record + Near-Miss Network** | Dossiê de sinistro assinado e partilhável pelo condutor + rede agregada de quase-acidentes | **12–24 meses** | médio | Moat de longo prazo; dados que ninguém tem; vendável a frotas, seguradoras e cidades |

**O que não fazer agora:** marketplace web de consumidor, IoT urbano como primeiro produto, V2X/RSU, seguro paramétrico. São bons mercados, mas com ciclos de venda longos e capital intensivo.

### Reality check — quatro correções que mudam o desenho

1. **Waze e Google Maps não são APIs comerciais de acidentes.** O Waze for Cities é uma parceria com governos e operadores de vias; o Google Maps expõe trânsito, não um feed de colisões. Para incidentes comerciais: **TomTom/HERE**, **511/WZDx** e **CAD público**.
2. **Web Push + geofencing não acorda no local do acidente em iOS.** Se o browser/PWA está fechado, não há geofence em background. O gatilho tem de ser **app nativa/SDK** (idealmente Apple SafetyKit) ou um link SMS.
3. **"Precisão de interseção/hora" é cientificamente frágil.** O produto deve vender **probabilidade e alocação de capacidade**, não profecia. Um lift de 1,8–2,5× no topo do ranking já é excelente.
4. **"Ninguém aplicou" é quase sempre falso.** Os componentes existem (CMT, Sfara, Samsara, Nexar, CCC, RepairPal). O que não existe em escala é a **combinação**: out-of-pocket + zero-PII + orquestração cross-provider + dossiê do condutor.

---

## 2. O que está realmente disponível

| Fonte | O que dá | Latência | Acesso | Veredicto |
|---|---|---|---|---|
| **Waze for Cities** | incidentes, lentidão, obras | ~2 min | **governos/operadores de vias** | não é via comercial; usar como benchmark ou via cidade |
| **Google Maps Platform** | trânsito, rotas, ETA | segundos | comercial | não expõe feed de colisões |
| **TomTom Traffic Incidents** | incidentes, closures, flow | segundos–minutos | comercial | **viável** |
| **HERE Traffic API v7** | incidentes e flow | segundos–minutos | comercial | **viável** |
| **511 / WZDx** | obras, closures, incidentes | 1–5 min | grátis/estadual | **viável**, cobertura irregular |
| **CAD público** | dispatch policial/bombeiros | 1–10 min | cidade a cidade | **viável em praças selecionadas** |
| **PulsePoint** | dispatch fire/EMS | ~1 min | agência opt-in | parceria, não self-serve |
| **Sensores urbanos** (Miovision, Iteris, NoTraffic) | contagens, conflitos, filas | segundos | cidade | **B2G**, ciclo 6–18 meses |
| **Telemática de frota** (Samsara, Geotab, Motive) | crash events, harsh braking, GPS | 10–60 s | API/marketplace | **viável via parceiro** |
| **Dashcams** (Nexar, Samsara, Motive) | vídeo, crash, near-miss | 5–30 s | parceria | **viável**, hardware-dependente |
| **Apple SafetyKit** | Crash Detection para apps autorizadas | ~10–30 s | entitlement Apple | **viável em iOS**, só crashes severos |
| **Android** | sem API pública equivalente | — | — | **gap**; usar SDK de sensor fusion (CMT/Sfara/Damoov) |
| **Smartcar / connected car** | estado, localização, odómetro | segundos | comercial | crash events dependem do OEM |
| **NOAA / Tomorrow.io** | clima, precipitação, visibilidade | minutos | grátis/comercial | **viável** |
| **Open crash data** | agregado, sem PII | diária/anual | grátis | **viável** para o modelo preditivo |

**Conclusão:** há matéria-prima suficiente para um produto real em 2–3 praças, desde que a arquitetura seja **multi-fonte com fusão**, não dependente de uma única API.

---

## 3. A tese de inovação

### 3.1 As quatro camadas

```text
SENSE  →  DECIDE  →  MATCH  →  LEARN
```

| Camada | Pergunta | Tecnologia |
|---|---|---|
| **Sense** | Houve um sinistro? Onde, quando, quão grave? | fusão de 511/WZDx, TomTom/HERE, CAD, telemática, dashcam, SafetyKit |
| **Decide** | É drivável? Precisa de reboque, oficina, vidro, advogado? | regras + ML de severidade + confirmação humana |
| **Match** | Quem resolve, com que SLA e preço? | leilão cego, capacidade em tempo real, geofence H3 |
| **Learn** | O que aconteceu? Quanto custou? Onde repetir? | feedback loop, demanda out-of-pocket, near-miss |

### 3.2 O white space

1. **Out-of-pocket, não insurance claim.** 39% dos condutores segurados já pagam reparações do próprio bolso; 59% acham o dano demasiado pequeno; 44% têm deductible acima do custo; 42% receiam subida de prémio. O mercado de claims está saturado; o de **private-pay** está desinstrumentalizado.
2. **Zero-PII matchmaking.** Os marketplaces atuais pedem nome/telefone/email antes de qualquer orçamento. Um leilão cego, com revelação só no aceite, é diferenciador e reduz fricção.
3. **Orquestração cross-provider.** Ninguém junta reboque + oficina + vidro + aluguer + apoio jurídico num único evento. Cada um otimiza o seu silo.
4. **Dossiê do condutor.** O evento é capturado pelo condutor, não vendido a partir de um relatório policial. É dele; ele partilha se quiser.

---

## 4. Deep dive 1 — Deteção preditiva em tempo real

### 4.1 Arquitetura de fusão

```text
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ 511 / WZDx   │  │ TomTom/HERE  │  │  CAD público │  │  Telemática  │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │                 │
       └────────────┬────┴────────┬────────┴────────┬────────┘
                    ▼             ▼                 ▼
              ┌─────────────────────────────────────────┐
              │  Normalizer + Idempotency (event_id)    │
              └──────────────────┬──────────────────────┘
                                 ▼
              ┌─────────────────────────────────────────┐
              │  Spatio-temporal dedupe (150 m / 10 min)│
              └──────────────────┬──────────────────────┘
                                 ▼
              ┌─────────────────────────────────────────┐
              │  Evidence graph + confidence scoring    │
              │  confirmed | probable | possible        │
              └──────────────────┬──────────────────────┘
                                 ▼
              ┌─────────────────────────────────────────┐
              │  H3 index (res 8) + Redis geofence      │
              └───────┬──────────────────┬──────────────┘
                      ▼                  ▼
             ┌────────────────┐  ┌────────────────────┐
             │ Moment-Zero API│  │ Demand forecast     │
             │ (webhook/push) │  │ (batch + nowcast)   │
             └────────────────┘  └────────────────────┘
```

### 4.2 Confiança e falsos positivos

Não disparar com uma única fonte fraca. Modelo de evidência:

| Sinal | Peso | Nota |
|---|---|---|
| Telemetria de frota com queda brusca de velocidade + impacto | alto | confirmation por voz do condutor |
| Apple SafetyKit / crash detection | alto | só crashes severos |
| CAD com código de colisão | alto | varia por cidade |
| 511/WZDx com incidente | médio | pode ser obra |
| Waze/TomTom/HERE | médio | reportado por utilizadores, atraso |
| Áudio (dashcam) | médio | ruído, falso positivo |
| Cluster de hard-braking de vários veículos | médio | near-miss, não crash |

Regras:

```text
confirmed  = telemetria alta OU SafetyKit OU (CAD + 1 fonte independente)
probable   = 2 fontes médias concordantes em 150 m / 10 min
possible   = 1 fonte média
```

Só `confirmed` e `probable` acionam assistência. `possible` entra no mapa e no modelo.

### 4.3 Latência e SLOs

| Etapa | Orçamento |
|---|---|
| Ingestão | < 5 s |
| Dedupe/fusão | < 2 s |
| Notificação ao parceiro | < 10 s |
| Primeiro bid de oficina | < 10 min |
| **p95 total (deteção → oferta)** | **< 30 s** |

### 4.4 O que é viável em 90 dias

**Sim:**

- 511/WZDx + TomTom/HERE + CAD de 1–2 cidades.
- Fusão, dedupe e confidence scoring.
- Mapa de risco em tempo real e webhook para parceiros.
- 1 parceiro de frota/dashcam para telemetria.

**Não:**

- Cobertura nacional.
- Deteção de todos os fender benders (não reportados).
- Substituir 911 ou dispatch oficial.

### 4.5 Produto

**Moment-Zero API** para parceiros:

```text
POST /v1/incidents/detect     # evento normalizado
GET  /v1/incidents/{id}       # estado + confiança
POST /v1/assistance/request   # pedido de ajuda pré-aprovado
WS   /v1/stream               # stream de eventos por geofence
```

Métricas: precision, recall, time-to-detect, false-dispatch rate, cobertura por H3.

---

## 5. Deep dive 2 — Micro-widget / SDK B2B embebido

### 5.1 Porque é a via certa

O consumidor não vai instalar mais uma app. Mas já tem apps abertas:

| Categoria | Exemplos | Sinal | Valor |
|---|---|---|---|
| Gestão de frotas | Samsara, Geotab, Motive | crash event, GPS, velocidade | alto |
| Dashcams | Nexar, Samsara, Motive | vídeo, impacto, near-miss | alto |
| Estacionamento | SpotHero, ParkMobile | localização, sessão | médio |
| Mecânicas | RepairPal, CarAdvise | veículo, histórico | médio |
| Ride-hail / entrega | apps de motoristas | crash, GPS | alto |
| Auto finance / seguro | apps de seguradoras | apólice, veículo | alto |

### 5.2 Padrões de integração

```text
Opção 1 — Web SDK (iframe/JS)      → integração em horas, baixo controlo
Opção 2 — React Native / Flutter   → 1–3 semanas, bom equilíbrio
Opção 3 — REST + webhook           → 2–6 semanas, controlo total
Opção 4 — SDK nativo (iOS/Android) → 6–10 semanas, acesso a sensores
```

MVP recomendado: **REST + webhook + widget white-label**, com SDK nativo só no parceiro âncora.

### 5.3 Stack de deteção

| Plataforma | Mecanismo | Nota |
|---|---|---|
| iOS | **SafetyKit Crash Detection** | requer autorização Apple; crashes severos; iPhone 14+ |
| Android | sensor fusion (acelerómetro + giroscópio + GPS + áudio) via SDK próprio ou CMT/Sfara | fragmentação; calibrar por dispositivo |
| Frota | evento de crash do fornecedor (Samsara/Geotab/Motive) | mais fiável, mas só frotas |
| Dashcam | impacto + vídeo + áudio | prova visual; near-miss |
| OBD-II | airbag/impacto | após-market, nicho |

### 5.4 Ajuda pré-aprovada

No onboarding do parceiro, o utilizador opta por:

- veículo (YMM, matrícula opcional);
- preferências (oficina, reboque, vidro, aluguer);
- método de pagamento / seguro;
- contacto de emergência;
- raio de assistência.

No evento, um toque → pedido com localização, fotos e severidade. **Sem PII para os prestadores até ao aceite.**

### 5.5 GTM e moat

- Entrar por **marketplaces** (Samsara, Geotab) e **revenda** (seguradoras, associações de oficinas).
- Revenue share 10–20% ou fee por evento.
- Moat: distribuição + dados proprietários + confiança da marca, não o modelo.
- Integração: 2–6 semanas por parceiro; security review; contrato de dados.

### 5.6 Riscos

| Risco | Mitigação |
|---|---|
| Apple não aprovar o entitlement | começar por frota/dashcam; iOS como fase 2 |
| Android fragmentado | SDK comercial (CMT/Sfara) no arranque |
| Falsos positivos | confirmação do condutor + fusão + histerese |
| Parceiro não prioriza | começar com 1 âncora e revenue share |
| Responsabilidade se a ajuda falhar | SLA, seguro, disclaimers, fallback 911 |

---

## 6. Deep dive 3 — Motor preditivo para prestadores (B2B SaaS)

### 6.1 O que prever (e o que não prever)

**Não:** "vai haver um acidente no cruzamento X às 17:42".

**Sim:** "espera-se 1,8–2,4× mais procura de reparação out-of-pocket nas células H3 A, B, C entre 16:00–19:00 de sexta".

O alvo é **demanda de reparação private-pay**, não todos os sinistros. Isso exclui lesão grave, veículo total e claims segurados — e é exatamente o que as plataformas de claims não modelam.

### 6.2 Dados e features

| Grupo | Exemplos |
|---|---|
| Histórico de sinistros | open crash data por H3/hora, gravidade, tipo |
| Trânsito | volume AADT, velocidade, congestionamento |
| Clima | chuva, neve, gelo, visibilidade, temperatura |
| Via | geometria, nº de faixas, curvatura, tipo de interseção, obras (WZDx) |
| Contexto | bares, escolas, retail, eventos, feriados, jogos |
| Veículo | idade média, valor, mix por ZIP |
| Capacidade | oficinas/reboques por raio, slots, preços |
| Feedback | jobs reais aceites por H3/hora (ground truth) |

### 6.3 Modelos

1. **Baseline:** Poisson/negative binomial por H3/hora, com sazonalidade.
2. **Produção:** LightGBM/XGBoost com target Poisson, features espaciais e temporais.
3. **Fase 2:** GNN espaço-temporal (PyTorch Geometric) para dependências entre células.
4. **Incerteza:** conformal prediction / quantis; nunca um número sem intervalo.

### 6.4 Validação

- **Rolling-origin backtesting** (treinar até T, testar T+1…T+n).
- **Métricas:** MAE, Poisson deviance, calibration, precision@k, lift no top decil.
- **Meta realista:** AUC 0,65–0,75 por segmento; **lift 1,8–2,5×** no top 10%; erro de calibração < 20%.
- **Sem leakage:** nunca usar o outcome do período de teste; validar por cidade.

### 6.5 Produto

| Superfície | Utilizador | Valor |
|---|---|---|
| Weekly Demand Forecast | dono de body shop | staffing, compras, capacidade |
| Daily Risk Map | gestor de reboques | posicionamento de viaturas |
| Capacity Planner | multi-loja | alocação de técnicos e bays |
| Marketing Allocator | marketing | onde gastar Google Ads/local |
| API | software de gestão | embedded forecast |

**Preço:** $199–$499/mês por loja; $999+ multi-loja; $99–$299 para reboques; API custom.

### 6.6 Moat

- Dados de intake reais dos parceiros (ground truth que ninguém tem).
- Calibração local por cidade/corredor.
- Integrações no workflow da oficina.
- Marca e confiança na vertical.

### 6.7 Riscos

- **Viés de reporte:** acidentes pequenos não entram nos dados policiais. Corrigir com dados de oficinas.
- **Amostra pequena:** H3 × hora é esparso; agregar para H3 × dia ou corredor × hora.
- **Drift:** obras, clima, economia, novos padrões. Retreinar semanalmente; monitorizar.
- **Overfitting:** validação temporal e por cidade, não aleatória.
- **Expectativa:** vender probabilidade, não certeza.

---

## 7. Deep dive 4 — Zero-PII matchmaking

### 7.1 A correção do gatilho

O pedido original assumia "Web Push / geofencing no local". Em iOS:

- Web Push só funciona em **PWA instalada** e com permissão;
- não há geofencing em background para web;
- o browser fechado não recebe o evento.

**Gatilhos reais:**

1. App nativa do parceiro com SDK (melhor).
2. Apple SafetyKit (crash severo).
3. Link SMS enviado pelo parceiro/telemetria.
4. QR code no carro / carta de assistência.
5. Botão "Preciso de ajuda" no widget.

### 7.2 Fluxo anónimo

```text
1. Trigger (SDK/SafetyKit/SMS)
2. Criar pedido anónimo:
   { request_token, h3_r8, damage_photos, YMM, drivable, time_window }
3. PII vault: nome/telefone/email cifrados; só token no pedido
4. Broadcast a oficinas verificadas num raio (push/email/SMS)
5. Leilão cego: preço, ETA, garantia, slot
6. Condutor compara 3–5 bids e aceita
7. Revelação única: localização exata + contacto; escrow
8. Conclusão, rating, libertação do pagamento
9. Apagar PII após N dias (salvo obrigação legal)
```

### 7.3 Privacidade técnica

| Elemento | Técnica |
|---|---|
| Localização | H3 res 8 (~0,74 km²) até ao aceite; exata só depois |
| Fotos | blur on-device de rostos/matrículas; EXIF strip; sem VIN |
| Identidade | token efémero; PII em vault separado (KMS, field-level encryption) |
| Comunicação | chat in-app; chamada mascarada |
| Pagamento | Stripe Connect escrow; sem dados de cartão no nosso lado |
| Auditoria | log imutável de acessos à PII |
| Retenção | 30–90 dias; eliminação automática |

### 7.4 Leilão cego

- Oficinas vêem: H3, fotos, YMM, drivability, prazo.
- Não vêem: nome, telefone, morada exata, matrícula.
- Bids com preço, ETA, garantia, slot, rating.
- Score de qualidade + preço; evitar race to the bottom.
- Limite de 5 bids; timeout 15 min; fallback para reboque/guincho.

### 7.5 Pagamento e confiança

- Depósito/escrow no aceite; libertação na conclusão.
- Garantia mínima (ex.: 90 dias) e disputa.
- Verificação de oficina: licença, seguro, reviews, capacidade.
- SLA: resposta < 15 min; penalização por no-show.

### 7.6 Métricas

| Métrica | Meta |
|---|---|
| Time-to-first-bid | < 10 min |
| Bid coverage | > 60% dos pedidos |
| Accept rate | > 25% |
| Job completion | > 90% |
| PII leak | 0 |
| NPS pós-reparação | > 50 |

### 7.7 Riscos

- **Poucos bids** em cidades pequenas → começar denso (1 bairro/cidade).
- **Race to the bottom** → score de qualidade e garantia.
- **Pedidos falsos** → OTP, device fingerprint, rate limit.
- **Responsabilidade** → contrato com oficinas, seguro, disclaimers.
- **Fotos más** → guia de captura no app; triagem por CV.

---

## 8. Vectores adicionais (o que ninguém está a juntar)

| # | Vector | Novidade | Viabilidade | Prazo | Veredicto |
|---|---|---|---|---|---|
| 1 | **Near-Miss Network** — dashcams/frotas agregam quase-acidentes; mapa de risco para cidades/seguradoras | alta | média | 12–18 m | **aposta C** |
| 2 | **Driver-Owned Crash Record** — dossiê assinado (fotos, telemetria, testemunhas, timestamp) partilhável pelo condutor | alta | média | 9–12 m | **aposta C** |
| 3 | **Damage Triage API** — foto → severidade, estimativa, drivability, routing | média | alta | 6 m | embed na aposta B |
| 4 | **Fleet FNOL Automation** — crash → claim → repair booking → rental, para frotas pequenas | média | alta | 6 m | **quick win B2B** |
| 5 | **Towing Capacity Orchestration** — oferta em tempo real + rotação municipal | média | média | 9 m | B2G/B2B |
| 6 | **Municipal Vision Zero Twin** — digital twin + previsão de risco para cidades | média | baixa | 18 m | B2G, longo |
| 7 | **Parametric Micro-Cover** — pagamento fixo para danos < deductible | alta | baixa | 18–24 m | exige MGA/seguradora |
| 8 | **V2X / Roadside Units** — comunicação veículo-infraestrutura | alta | baixa | 24 m+ | não agora |
| 9 | **Roadside Assistance API** — botão "ajuda" white-label em apps de parceiros | baixa | alta | 3 m | feature da aposta B |
| 10 | **Crash Evidence Marketplace** — perícias/laudos anonimizados para litígios | média | média | 12 m | só com consentimento |

### 8.1 Near-Miss Network

Dashcams e frotas já detetam hard-braking, almost-collisions e eventos de proximidade. Agregados por H3/hora, valem mais que crash data para prever risco: são **mais frequentes, mais recentes e menos enviesados por reporte**.

- Produto: heatmap de risco + alertas para cidades, seguradoras e frotas.
- Privacidade: sem vídeo, sem matrícula, sem localização exata; só evento agregado.
- Moat: rede de dashcams/frotas; efeito de rede.
- Receita: assinatura municipal/seguradora; API.

### 8.2 Driver-Owned Crash Record

No momento do sinistro, a app captura:

- timestamp assinado, GPS, velocidade, acelerómetro;
- fotos com blur de PII;
- áudio curto (opcional);
- testemunhas via QR/link;
- condições meteorológicas e estado da via.

O condutor é o dono; pode partilhar com oficina, seguradora ou advogado. Não é vendido. É um **cofre de prova** que reduz fraude e acelera o processo.

- Receita: assinatura premium, fee por partilha, licença para frotas.
- Moat: confiança + integrações + cadeia de custódia.

### 8.3 Damage Triage API

Foto → classificação de dano, drivability, faixa de custo, peças prováveis. Integra no SDK e no matchmaking.

- Não competir com CCC/Tractable no estimate insurers; competir no **private-pay triage**.
- Modelo: CNN/ViT + dados de oficinas parceiras; começar com 5 classes.
- Saída: "provável $800–$1.500; drivável; 2 dias de oficina".

### 8.4 Fleet FNOL Automation

Frotas pequenas (5–50 veículos) não têm workflow de sinistro. Integração com telemetria:

```text
crash event → confirmação do condutor → fotos → FNOL → oficina/reboque → aluguer → custo
```

- Receita: $2–$5/veículo/mês + fee por evento.
- Vantagem: o evento já vem com telemetria e vídeo.
- GTM: parceiros de frota, associações, seguradoras.

---

## 9. Competitive landscape

| Player | O que faz | O que falta |
|---|---|---|
| **Cambridge Mobile Telematics / Sfara** | crash detection SDK para seguradoras | não fazem matchmaking nem out-of-pocket |
| **Samsara / Geotab / Motive** | telemetria, crash detection, marketplace | ecossistema fechado; não servem consumidor |
| **Nexar** | rede de 350k dashcams, dataset e crash prediction | hardware-centric; não orquestram reparação |
| **Waze / Google** | incidentes/trânsito | não é feed comercial de colisões; não despacham |
| **TomTom / HERE** | trânsito e incidentes | dados, não assistência |
| **CCC / Mitchell / Solera** | estimating e claims, dominam DRP | centrados em seguradora; não private-pay |
| **RepairPal / CarAdvise / Openbay** | quotes de reparação | PII upfront; não momento zero; não zero-PII |
| **Tractable / Solera AI** | damage estimation | insurer-centric |
| **Life360 / OnStar** | crash detection/emergência | não marketplace local |
| **Lead vendors de relatórios** | leads de acidente | risco legal; sem tecnologia |

**White space real:** ninguém junta **evento em tempo real + private-pay + leilão cego + orquestração cross-provider + dossiê do condutor**. É aí que a inovação vive.

---

## 10. Portfólio recomendado

### Aposta A — Provider Demand Intelligence (0–6 meses)

**Porquê primeiro:** receita, sem PII de consumidor, usa open data, cria o dataset de demanda que alimenta tudo o resto.

**Entregáveis:**

1. Ingestão NYC + Chicago + Dallas + Boston.
2. Modelo de demanda por H3/hora com validação temporal.
3. Dashboard + API para body shops e reboques.
4. 10 pilotos pagos.

**Gate:** lift ≥ 1,8× no top decil; 5 LOIs; 3 pilotos pagos.

### Aposta B — Moment-Zero SDK (6–18 meses)

**Porquê segundo:** distribuição via parceiros; dados proprietários; maior ceiling.

**Entregáveis:**

1. REST + webhook + widget white-label.
2. iOS SafetyKit (se aprovado) + Android sensor fusion.
3. Ajuda pré-aprovada + zero-PII matchmaking.
4. 1 parceiro âncora (frota/dashcam/estacionamento).

**Gate:** 2 parceiros com LOI; 100 eventos reais; precision ≥ 70%; bid coverage ≥ 60%.

### Aposta C — Crash Record + Near-Miss (12–24 meses)

**Porquê terceiro:** moat de longo prazo; depende da rede da aposta B.

**Entregáveis:**

1. Dossiê assinado e partilhável.
2. Near-miss network agregada.
3. Produto para cidades/seguradoras.

**Gate:** 3 clientes pagos (cidade, seguradora ou frota); 1M eventos agregados.

---

## 11. Arquitetura de referência

### 11.1 Stack

| Camada | Escolha | Nota |
|---|---|---|
| API | FastAPI (Python) | mesma linguagem do engine atual |
| OLTP | PostgreSQL + PostGIS | pedidos, oficinas, bids |
| Time-series | TimescaleDB | eventos, métricas |
| Cache/geofence | Redis | H3 cells, presença, rate limit |
| Event bus | Redpanda/Kafka (fase 2); Redis Streams no MVP | ingestão multi-fonte |
| Lake | S3 + Parquet | raw, treino, backtest |
| Analytics | DuckDB | exploração rápida |
| ML | LightGBM + PyTorch; ONNX Runtime | batch + serving |
| MLOps | MLflow + cron | versionamento, drift |
| Pagamentos | Stripe Connect | escrow/marketplace |
| Observabilidade | OpenTelemetry + Grafana | SLOs, alertas |
| Segredos | KMS + vault | PII encriptada |

### 11.2 APIs

```text
# Ingestão
POST /v1/events                 # evento normalizado de parceiro
POST /v1/events/batch
GET  /v1/incidents/{id}

# Prestadores
GET  /v1/providers?h3=&radius=
POST /v1/requests               # pedido anónimo
POST /v1/requests/{id}/bids
POST /v1/requests/{id}/accept   # revela PII
POST /v1/requests/{id}/complete

# Forecast
GET  /v1/forecast?h3=&from=&to=
GET  /v1/forecast/segments

# Parceiros
POST /v1/partners/{id}/webhook
```

### 11.3 Modelo de dados (resumo)

```sql
events (
  id, source, external_id, type, occurred_at, h3_r8,
  lat, lng, severity, confidence, raw_json,
  UNIQUE(source, external_id)
);

incidents (
  id, event_id, status, confirmed_at, closed_at, h3_r8
);

repair_requests (
  id, request_token, h3_r8, ymm, drivable, damage_json,
  time_window, status, created_at, expires_at
);

bids (
  id, request_id, provider_id, price_cents, eta_min,
  warranty_days, slot_at, status, created_at
);

providers (
  id, name, kind, h3_r8, license, insurance, rating,
  capacity, status
);

pii_vault (
  request_id, encrypted_name, encrypted_phone,
  encrypted_email, encrypted_address, key_version
);

outcomes (
  id, request_id, accepted_bid_id, completed_at,
  final_price_cents, rating, issue
);
```

### 11.4 Segurança e privacidade

- PII em serviço separado, envelope encryption (KMS), acesso auditado.
- Tokens efémeros; sem PII em logs, URLs ou analytics.
- Fotos processadas on-device; blur de rostos/matrículas.
- H3 res 8 antes do aceite; localização exata só no accept.
- Rate limit por dispositivo/IP; deteção de fraude.
- Retenção 30–90 dias; apagação automática.
- Contratos de dados com parceiros; sem revenda.

### 11.5 SLOs

| Métrica | Alvo |
|---|---|
| Ingestão p95 | < 5 s |
| Deteção → oferta p95 | < 30 s |
| Matchmaking time-to-first-bid | < 10 min |
| Uptime | 99,5% |
| Erro de calibração do forecast | < 20% |
| PII leak | 0 |

---

## 12. Unit economics (pressupostos)

### 12.1 Aposta A — SaaS

| Item | Valor |
|---|---|
| Preço body shop | $299/mês |
| 50 lojas | $14.950 MRR |
| CAC | $800–$1.500 |
| Payback | 3–5 meses |
| Infra + dados | $1.500–$4.000/mês |
| Margem bruta | 80–85% |

### 12.2 Aposta B — matchmaking

| Item | Valor |
|---|---|
| Fee por job aceite | $40 (ou 6–8% do ticket) |
| 1.000 jobs/mês | $40.000 |
| Ops/suporte | 15–20% |
| Pagamentos | ~3% |
| Telemetria/SDK | $1–$3/veículo/mês (parceiro) |
| CAC parceiro | $5k–$20k (BD) |

### 12.3 Investimento inicial (6 meses)

| Item | Faixa |
|---|---|
| 2 engenheiros + 1 data scientist + design/PM | $250k–$450k |
| Cloud/APIs | $10k–$30k |
| Legal/contratos/seguros | $15k–$40k |
| Pilotos e aquisição | $20k–$50k |
| **Total** | **$300k–$570k** |

Pressupostos, não orçamento aprovado.

---

## 13. Plano de 90 dias

| Semana | Foco | Entregável |
|---|---|---|
| 1–2 | Data audit 4 cidades, 24 meses | inventário, qualidade, cobertura |
| 2–4 | 15 entrevistas (body shops, reboques, frotas) | dores, preço, LOIs |
| 4–6 | Modelo baseline + backtest | lift, calibration |
| 6–8 | Dashboard piloto | 2 buyers a usar |
| 8–10 | Protótipo zero-PII | 5 oficinas, 50 pedidos sintéticos |
| 10–12 | Parceiro SDK spike | iOS SafetyKit / frota API |
| 12 | Go/No-Go | decisão |

### Critérios de kill

- Lift < 1,5× no top decil.
- < 3 LOIs após 15 entrevistas.
- Bid coverage < 30% em 15 min.
- Nenhum parceiro com LOI em 90 dias.
- False positive > 20% em deteção real.
- PII leak em teste.

---

## 14. Riscos e mitigação

| Risco | Tipo | Mitigação |
|---|---|---|
| Falsos positivos | técnico | fusão, confirmação humana, histerese |
| Cobertura fragmentada | técnico | 2 praças densas, multi-fonte |
| Latência | técnico | edge, streaming, cache H3 |
| Drift do modelo | técnico | retreino semanal, monitorização |
| Apple não aprova | parceiro | frota/dashcam primeiro |
| Android fragmentado | técnico | SDK comercial no arranque |
| Parceiro não prioriza | negócio | 1 âncora + revenue share |
| Chicken-and-egg | negócio | começar por SaaS (A), não marketplace |
| Oficinas desconfiam | negócio | transparência, garantia, reviews |
| Race to the bottom | negócio | score de qualidade, não só preço |
| Responsabilidade | negócio | seguro, SLA, disclaimers, fallback 911 |
| Comoditização | estratégia | dados proprietários + distribuição + marca |

---

## 15. Decisões em aberto

1. Cidade inicial: **NYC** (densidade, open data) ou **Dallas** (menos concorrência, engine atual).
2. Vertical inicial: **body shops** (SaaS) ou **frotas** (SDK).
3. Parceiro âncora: Samsara/Geotab/Nexar/SpotHero — quem tem o evento e a distribuição?
4. Apple SafetyKit: pedir entitlement já ou deixar para fase 2?
5. Modelo de receita: assinatura, fee por job, ou híbrido?
6. Marca: produto separado ou extensão da Magic Leads?
7. Dados de treino: só open data ou comprar dados de oficinas?
8. Responsabilidade: seguro próprio ou cobertura via parceiros?

---

## 16. Fontes

**Tempo real / trânsito**
- Waze for Cities (governos): https://www.waze.com/partners/wazeforcities
- Waze Data Feed (2 min): https://support.google.com/waze/partners/answer/10618035
- TomTom Traffic Incidents: https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/traffic-incidents/traffic-incidents-service
- HERE Traffic API v7: https://docs.here.com/traffic-api/docs/introduction-to-here-traffic-api-v7
- WZDx: https://www.transportation.gov/av/data/wzdx
- CAD open data (Austin): https://data.austintexas.gov/Public-Safety/APD-Computer-Aided-Dispatch-Incidents/22de-7rzg
- NYC EMS dispatch: https://data.cityofnewyork.us/Public-Safety/EMS-Incident-Dispatch-Data/76xm-jjuj

**Deteção / telemática**
- Apple SafetyKit: https://developer.apple.com/documentation/safetykit
- Cambridge Mobile Telematics DriveWell Crash: https://www.cmtelematics.com/drivewell-crash/
- Sfara: https://www.sfara.com/
- Samsara: https://www.samsara.com/
- Geotab Marketplace: https://www.geotab.com/
- Nexar network/dataset: https://www.getnexar.com/
- Smartcar API: https://smartcar.com/docs/api-reference/intro

**Mercado / economia**
- 39% pagam reparações do próprio bolso: https://www.autobodynews.com/news/almost-40-of-insured-drivers-paid-for-repairs-out-of-pocket-survey
- LendingTree survey: https://www.lendingtree.com/insurance/insurance-repairs-survey/
- CCC average repair $4,818: https://www.cccis.com/reports/crash-course-2025/q2
- CCC/Mitchell/Audatex share: https://estimateoptimizer.com/blog/audatex-vs-ccc-one-vs-mitchell

**Dados abertos**
- NYC collisions: https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95
- Chicago crashes: https://data.cityofchicago.org/Transportation/Traffic-Crashes-Crashes/85ca-t3if
- Boston Vision Zero: https://data.boston.gov/dataset/vision-zero-crash-records

---

## 17. Nota final

O produto mais defensável não é "detetar acidentes" — é **ser a camada de decisão entre o evento e o prestador certo**, com dados proprietários, distribuição embebida e privacidade como feature.

A sequência recomendada é deliberadamente conservadora:

```text
A (SaaS de demanda) → B (SDK momento zero) → C (dossiê + near-miss)
```

A aposta A financia e valida a B. A B gera os dados que tornam a C impossível de copiar. Saltar diretamente para B ou C multiplica o risco e o capital.

**Recomendação:** aprovar A para discovery de 90 dias; manter B e C como opções condicionadas aos gates. Nenhuma linha de código antes do parecer jurídico e das LOIs.
