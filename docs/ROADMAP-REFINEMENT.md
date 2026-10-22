# Roadmap de Refinamento — Magic Leads

> Diagnóstico de dono (2026-10-21), feito por auditoria de código com medições
> reais (frontend + backend). **Nada disto foi implementado** — é o mapa de
> decisão. Actualiza-se à medida que cada item é fechado.
>
> Como ler: **Impacto** = dano se não for corrigido · **Esforço** = P (<½ dia) /
> M (1-3 dias) / G (>1 semana) · **Risco** = incidente vs. ganho de performance.

---

## 0. Decisões de negócio — NÃO tocar (anotado de propósito)

Estas coisas **parecem** bugs e **não são**. Estão aqui para ninguém as "corrigir" por engano.

| Item | Decisão | Porquê |
|---|---|---|
| **Mensagem de WhatsApp/SMS/email em inglês** | **Manter 100% em inglês** | Decisão de negócio: o contacto final é sempre o proprietário americano do imóvel nos EUA. A UI continua na língua do utilizador; **só o texto enviado ao dono é em inglês** (parâmetro `lang` do `buildOutreachMessage`). |
| **"Novas oportunidades" = real + 1500** | Manter (decisão comercial de prova social) | Mas **expor as duas partes separadamente** (real e margem) no admin, para o número ser reconciliável com a base. Ver §6-H10. |
| **Preço $120/semana · 300 leads** | Em revisão via posicionamento nichado | A mudança para "50 leads do meu ofício" é o movimento que resolve o travão de inventário (§5). Decisão em aberto. |
| **Conta Stripe BR** | Manter para o lançamento | A entidade americana é um movimento posterior, não um bloqueador. |
| **Qualificação por SQL com LIKEs** | Migrar, mas **preservar a semântica** exacta | A regra é o moat de qualidade. O problema é a *implementação* (performance), não o critério. |

---

## 1. 🏁 SPRINT 1 — "Parar de perder dinheiro" (prioridade absoluta)

**Objectivo:** o contractor nunca é enganado, nunca paga o que não deve, e o sistema nunca perde dinheiro em silêncio.
**Quando:** depois da sessão de Workspace + rotação de chaves (fim de semana).
**Como:** **um único commit + um único deploy** (o pipeline de build da Railway está instável; cada deploy custa tempo).

### 1.1 Falha de API apresentada como "zero oportunidades" 🔴
- **Onde:** `frontend/app/[locale]/(dashboard)/dashboard/page.tsx:536-549` — `fetchTodayLeads(...).catch(() => ({leads: [], total: 0, ...}))`, e o mesmo padrão em `fetchDashboardSummary` / `fetchScraperStatus` / `fetchPublicMetrics`.
- **Efeito:** o `.catch` devolve lista vazia → `loadingLeads=false` → o render entra em `filteredLeads.length === 0` (`:2385`) e mostra *"Nenhuma oportunidade nas categorias ativas"* + *"Ative mais categorias ao lado para ver mais."* (`i18n.tsx:537-538`).
- **Impacto:** o cliente **paga e vê "zero obras"**, e é instruído a mexer nos filtros. Churn + pedidos de reembolso.
- **Proposta:** distinguir `erro` de `vazio`. `useState<"idle"|"loading"|"ready"|"error">`; em `error` → banner persistente com "Não conseguimos carregar. A tua cidade pode ter obras — tente novamente" + botão **Repetir**. Nunca mostrar o estado vazio por falha.
- **Aceite:** com a API a falhar, o ecrã mostra erro explícito e **nunca** "0 oportunidades".
- **Esforço:** P · **Risco:** incidente (churn)

### 1.2 Mostrar a urgência no painel 🔴
- **Onde:** `urgency_level` existe em `api-client.ts:61`, é filtrável (`:1206`, `:1814`) e **não é renderizado em nenhum cartão, modal ou histórico**. As traduções `dashboard.feed.urgency.high` (`i18n.tsx:530-535`) existem e só são usadas nas `<option>` do filtro.
- **Impacto:** a landing promete *"endereço, tipo de reparo, **urgência** e a mensagem pronta"* (`i18n.tsx:926`) e *"com endereço, categoria e **urgência**"* (`i18n.tsx:1390`). **O cliente paga por um campo que o produto não entrega.**
- **Proposta:** badge no cartão + no modal de detalhe, **em linguagem simples** (não "HIGH/MEDIUM"): "Sem aquecimento há 3 dias" / "Obra urgente" / "Manutenção de rotina". Reaproveitar `_infer_urgency` (backend) como referência, mas a fonte é o `urgency_level` que já vem no payload.
- **Aceite:** a urgência é visível no cartão **e** no modal, com texto legível.
- **Esforço:** P · **Risco:** promessa não cumprida

### 1.3 Uma só fonte de verdade para as 16 categorias 🔴
- **Onde (frontend):** `dashboard/page.tsx:87-118` — `CATEGORIES` com keywords sobrepostas e `find()` (primeiro que casa):
  - `Roof` contém `"structure"`, `"foundation"`, `"collaps"` → **todo o estrutural é rotulado "Telhado & Estrutura"**;
  - `Grass` (posição 9) contém `"garbage"`, `"trash"`, `"debris"`, `"unsanitary"`, `"rodent"` → **Debris / Unsanitary / Rodent nunca são atingidos**;
  - `Paint` (posição 5) contém `"lead"` e vem antes de `Lead` → **chumbo é rotulado "Pintura"**.
  - O `matchCategory` (`:110-113`) faz `hay.includes(k)` sobre `issue_category + issue_description + case_title + descriptor + department`.
- **Onde (backend):** o filtro usa o enum canónico (`backend/main.py:800-804`, `issue_category IN (...)`).
- **Impacto:** **servidor e cliente discordam.** Filtrar por "Estrutura" devolve linhas cujo badge diz "Telhado & Estrutura". E o contractor não sabe em que categoria está a olhar.
- **Proposta (duas partes):**
  1. **O frontend deixa de re-derivar a categoria.** A API devolve `issue_category` canónico + um `label`/`label_key` já traduzido; o frontend usa-o. A lista de keywords (para *matching* de texto livre) fica só no backend, onde a inferência já vive (`socrata_311.py:_infer_category`).
  2. **O enum não vaza para o ecrã.** `dashboard/page.tsx:2731` (badge do modal de detalhe) e `:3117` (modal de consentimento) mostram `Permit_Rejected` / `Door_Window` cru — **exatamente nos modais onde o utilizador decide gastar crédito**. Passar pelo tradutor (`catOfLead`/`t(labelKey)`).
- **Aceite:** (a) o badge e o filtro usam a mesma categoria em 100% dos casos; (b) zero valores crus de enum visíveis.
- **Esforço:** M · **Risco:** confiança (o Contractor julga o produto, não a ferramenta)

### 1.4 Ordem de liberação no webhook Stripe 🔴
- **Onde:** `backend/main.py:4207-4224` — `record_stripe_event(event_id, ...)` (grava o evento) **antes** de `extend_access(user_id, days=7)`.
- **Falha:** se `extend_access` lançar (DB busy, exceção) → a rota devolve 500 → o Stripe retenta → mas `has_stripe_event(event_id)` é agora `True` (`:4190`) → devolve `{"idempotent": True}` **sem conceder acesso**.
- **Impacto:** **o cliente pagou e não recebe acesso.** Perda de dinheiro + ticket de suporte + desconfiança.
- **Proposta:** só marcar o evento como processado **depois** de o acesso ser concedido. Se o `extend_access` falhar, o evento fica por processar e o retry do Stripe volta a tentar. Ideal: um estado intermédio (`processing`/`done`) para distinguir "já vi, mas falhei" de "já tratei".
- **Aceite:** um webhook que falha no `extend_access` **volta a conceder acesso** no retry.
- **Esforço:** M · **Risco:** incidente (dinheiro)

### 1.5 Reaper das mensagens presas em `sending` 🔴
- **Onde:** `backend/services/outbound_engine.py:517` faz o claim atómico (`queued → sending`, `db.py:1794-1812`) **antes** do envio. `list_queued_outbound_messages` (`db.py:2134`) só lê `status='queued'` e **não existe nenhum `UPDATE ... WHERE status='sending' AND <antigo>`** (grep confirmou: `'sending'` só aparece em `db.py:1277`, `1803`, `1928`, `2017` e `main.py:1872/1890`).
- **Falha:** se o processo morrer entre o claim e o `status='sent'` (deploy, OOM, restart), a mensagem fica **`sending` para sempre**.
- **Impacto:** **crédito de enriquecimento gasto, lead reservado, e-mail nunca enviado — e nenhum aviso.**
- **Proposta:** no watchdog (ou no worker), reaper que reenfileira mensagens `sending` com `updated_at`/claim mais antigo que X (ex.: 10 min), registando o evento em telemetria. Complementar: `claimed_at` explícito para saber há quanto tempo está presa.
- **Aceite:** uma mensagem presa em `sending` > 10 min volta a `queued` (e é registado).
- **Esforço:** M · **Risco:** incidente (crédito perdido)

### 1.6 Itens adicionais de baixo custo que entram no mesmo Sprint 1
| Item | Onde | Impacto | Esforço |
|---|---|---|---|
| **Correcção da estimativa de custo do painel** (Snov $0.015 → EmailListVerify 5-10 créditos = $0.035-0.070) | `backend/main.py:1559-1560` | O painel **subestima o custo 2,3×-4,7×** → decisões de orçamento erradas | **P** |
| **`/api/scraper/enrich` → exigir admin + rate limit** | `backend/main.py:3264-3309` (hoje `_get_current_user`) | Qualquer utilizador autenticado dispara enriquecimento de 500 leads (DOS das APIs upstream + writes) | **P** |
| **Rate limit nas rotas que gastam dinheiro** (`/reserve`, `/reveal-phone` → Searchbug) | `main.py:4395`, `main.py:4753` | Custo por abuse | **P** |
| **`/health` real** (`SELECT 1` + `PRAGMA quick_check`) | `backend/main.py:655-657` + `railway.json:9` | O Railway dá por saudável **mesmo com a base corrompida** | **P** |
| **Headers de segurança** (HSTS, `X-Content-Type-Options`, `X-Frame-Options`, CSP) | backend + `frontend/middleware.ts` | hygiene | **P** |
| **Verificar se a conta demo está activa em produção** | `main.py:3805` (`DEMO_PASSWORD`) | Entrada pública com password conhecida | **P** |
| **Limpar `/pricing` inexistente** e `example.com` na rota morta | `(public)/checkout/page.tsx:44`; `app/api/stripe/checkout/route.ts:21-22` | Dead-end no funil de pagamento | **P** |
| **`/icon-192.png` e `/icon-512.png` em falta** (só existe `.svg`) | `public/manifest.json:10-19`; `layout.tsx:44` | 404 → **o prompt "Instalar app" pode não aparecer**; ícone iOS default | **P** |

---

## 2. ⚙️ SPRINT 2 — "Remover o muro de escala"

**Objectivo:** o motor e a API aguentar 50 clientes com polling de 30 s.
**Estado actual (medido, 46k leads local):**

| Query | 46k | 66k (prod, extrapolado) |
|---|---:|---:|
| `count_qualified_contractors_in_city` | 859 ms | ~1,24 s |
| `get_outbound_sample_lead` | 840 ms | ~1,21 s |
| `/api/leads/recent` (público) | 830 ms | ~1,20 s |
| `cities_with_counts_filtered` | 805 ms | ~1,16 s |
| `/api/leads/today` (COUNT + página) | 547 ms | ~0,79 s |
| `get_connection()` (abrir ligação) | 1,64 ms | × 198 sítios |

**Causa raiz:** `_qualified_where()` = **~75 `LIKE`s por linha** (`db.py:59-154` + `lead_rules.py:380-396`), usado em ~15 rotas. O único filtro sargable do sistema é `issue_category`.

**Ordem de custo (a 50 clientes, 1 poll/30 s):** 1,67 req/s × ~0,9 s ≈ **1,5 core de CPU** num único processo uvicorn, pool de 40 threads.

| # | Item | Onde | Impacto | Esforço |
|---|---|---|---|---|
| 2.1 | **Full scan por email no worker** → 1 query por lote | `outbound_engine.py:427-559` (`_render_message` → `count_qualified_contractors_in_city`) | 10 emails/tick = **12 s de CPU por minuto** a contar o mesmo número | **P** |
| 2.2 | **Request autenticado toma o write lock** → `last_active_at` só de 5 em 5 min | `db.py:3506-3527` | 1,67 transações de escrita/s a competir com o scraper | **P** |
| 2.3 | **"database is locked" visível** (contador + log) em vez de `except Exception: return False` | ~40 sítios (`db.py:2336-2342`, `2377-2379`, `2103-2105`, `2124-2125`, …) | Hoje o sintoma (leads em falta) **não tem rasto** | **M** |
| 2.4 | **Índices que faltam**: `leads(updated_at)`, `leads(created_at)`, `leads(city, issue_category, date_reported DESC)`, `leads(city, lead_status)` | `db.py` | 253-859 ms → ~20-60 ms | **P** |
| 2.5 | **Índices a remover**: `idx_leads_source`, `idx_leads_lead_status`; e **3 índices para a mesma `status`** em `outbound_messages` | `db.py` | escreve amplification | **P** |
| 2.6 | **`PRAGMA optimize` / `ANALYZE` + `cache_size` + `foreign_keys=ON`** | `db.py:811-826` | Stats do planner desatualizadas após cada scrape; base de 126 MB com cache de 2 MB | **P** |
| 2.7 | **Pool de ligações** (ou `threading.local`) | `get_connection()` (198 sítios) | 1,64 ms × 198; no scrape: 3 ligações/lead ≈ 25 s de setup | **M** |
| 2.8 | **`BEGIN IMMEDIATE` nas escritas críticas** (reveal, reserve, insert_lead, claim, record_stripe_event, extend_access) | `db.py` | Classe clássica de "database is locked" intermitente | **M** |
| 2.9 | **`dashboard_summary` agregado em SQL** (hoje traz 7.915 linhas e agrupa em Python, com 2 regex/linha) | `db.py:5319-5501` | 253 ms → ~20 ms | **M** |
| 2.10 | **`/api/leads/today` não executa o filtro pesado 2×** (COUNT + página) | `main.py:814` | 267+280 ms → ~280 ms | **P** |
| 2.11 | **`ORDER BY` sargable** (hoje `COALESCE(date_reported,'')` → temp B-tree) | `db.py:1883`, `db.py:2019` | 840 ms → ~10 ms | **M** |
| 2.12 | **Materializar a contagem qualificada** (muda 1×/6 h, não por email) | novo | Elimina o full scan do `{count}` e de várias rotas | **M** |
| 2.13 | **Stripe SDK síncrono dentro de `async def`** → `anyio.to_thread.run_sync` | `main.py:3987`, `4029` | Uma API lenta **bloqueia o event loop inteiro** (todos os pedidos + os 4 jobs) | **P** |
| 2.14 | **Retry só para 5xx/timeout** (hoje retenta 4xx permanentes) | `socrata_311.py:91-126` | 4 tentativas × backoff por dataset morto | **P** |
| 2.15 | **Retry no EmailListVerify** (pago por crédito!) | `enrichment_emaillistverify.py:206-235` | Falha transitória perde o lookup **e o dinheiro do crédito** | **P** |
| 2.16 | **Bug `data` não reinicializado** entre queries no enrichment | `enrichment.py:417` | **O proprietário de outro edifício pode ser atribuído ao lead** — integridade do core | **P** |
| 2.17 | **Reaper de `sending`** (também no Sprint 1) | `outbound_engine.py:517` | (ver 1.5) | **M** |
| 2.18 | **Guard "already_running" persistente** (lease na BD) | `main.py:1333-1339` | Não sobrevive a restart; com 2 réplicas deixa passar 2 scrapers | **M** |
| 2.19 | **Cancelar `_checkout_recovery_task` no shutdown** | `main.py:3003-3015` | Fuga de task a cada deploy | **P** |
| 2.20 | **`lead_case_history`: 258.903 linhas, código morto, sem TTL** | `db.py:4797-4820`, `4845-4865` | Parte dos 77 MB; risco de crescer sem limite | **P** |

---

## 3. ✨ SPRINT 3 — "A delight" (o que o Contractor recorda)

| # | Item | Onde | Impacto | Esforço |
|---|---|---|---|---|
| 3.1 | **"As 3 melhores oportunidades para ti"** (urgência + telefone disponível + proximidade) | novo | **O onboarding mais eficaz possível**: do registo ao primeiro lead útil em <5 min | **P** |
| 3.2 | **Roteiro de chamada por lead** (3 frases: o que chamar, o que perguntar, como fechar) | novo | O Contractor não sabe o que dizer. **É o que o Angi não dá** | **M** |
| 3.3 | **"Porquê este lead"** (obrigação legal / chamado aberto há X dias) | novo | Justifica a taxa de 80% e **explica o preço** | **P** |
| 3.4 | **Filtros guardados** ("telhado em NYC") | novo | Pré-requisito do posicionamento nichado | **M** |
| 3.5 | **Busca no servidor** (o endpoint `searchLeads` já existe e é ignorado) | `api-client.ts:420-425` | Endereço pesquisado → hoje **zero resultados** | **P** |
| 3.6 | **Contador "N novas" funcional** (`setShown` nunca é chamado) | `dashboard/page.tsx:244` | O valor central do produto está morto | **M** |
| 3.7 | **Checklist de primeira execução** | novo | Ninguém diz o que fazer a seguir (grep: 0 resultados de onboarding/checklist) | **M** |
| 3.8 | **Nudge de interesses que não se destrói** (hoje auto-selecciona as 16 e desaparece) | `dashboard/page.tsx:452-473` | O nudge nunca é cumprido | **M** |
| 3.9 | **Explicar a cota antes de gastar** (10/dia, custo por reserva) | `dashboard/page.tsx:1757-1783` | O Contractor não sabe o que cada reserva custa | **P** |
| 3.10 | **Explicar "Reservar 1 Hora" ANTES do clique irreversível** | `ReserveGuideModal` aparece atrás do consentimento | Máxima primeira impressão | **P** |
| 3.11 | **"Enviar 3 de uma vez"** (reserva em lote) | novo | A cota de 10/dia é atrito | **M** |
| 3.12 | **Download CSV do lote com as mensagens prontas** | novo | O Contractor quer levar a lista para o campo | **P** |
| 3.13 | **E-mail diário com as 5 melhores novas oportunidades** | novo (reusa Resend + alert_planner) | Não obriga a ter o dashboard aberto; **gancho de retenção** | **M** |
| 3.14 | **"Perdeste esta oportunidade" → oferece a seguinte** | novo | Transforma exclusividade (que parece perda) **em fluxo** | **M** |
| 3.15 | **"Parar o meu plano" visível** | novo | A pausa do dia 8 sem fatura não é perceptível | **P** |
| 3.16 | **Partilhar um lead com um colega** | novo | Loop viral sem custo | **M** |
| 3.17 | **Página pública "Pulso do mercado" por cidade** | novo | SEO + linkável, dados que já temos | **M** |

---

## 4. 🌍 SPRINT 4 — "O terreno" (paralelo, com o Workspace)

| # | Item | Esforço | Notas |
|---|---|---|---|
| 4.1 | **Los Angeles** (3 datasets de permits LIVE em Socrata, 5.000+/ciclo) | M | Falta `SERVED_CITIES`, `CITY_DISPLAY/STATE`, `CITY_DATASETS` (owner), 2 testes, frontend/i18n |
| 4.2 | **Conector ArcGIS** (Baltimore 1,08M/ano · Charlotte 3,9M · Nashville 3,5M · Denver 475k/ano · Sacramento 6,2M) | G | Exige adapter + testes; o transportador Socrata não os lê |
| 4.3 | **Tax rolls** (Denver, Austin, Providence, Norfolk, San Diego) | M | O verdadeiro portão de cada cidade |
| 4.4 | **NJ / Tri-State** | G | Via **parcelas**, não 311 (0 datasets no formato certo) |
| 4.5 | **Stripe US / LLC** | — | Decisão de negócio; a entidade BR fica para histórico |
| 4.6 | **Fase 2 do Movimento #1**: backfill com janela de 7 dias (10× produção) | M | Medido: NYC 1.037 → **11.170**; CHI 100 → **1.081**; DAL 8 → **574**; fetch ~50 s |

---

## 5. 🎯 A decisão de produto que desbloqueia os 50 clientes

**O travão não é o nº de cidades — é a produção de oportunidades.**

```
Produção actual:            ~8.200 oportunidades/mês
Consumo (50 clientes × 1.300/mês): 65.000/mês   → falta ~8×
Stock disponível:           43.828 (buffer de ~5 meses a 50 clientes)
```

Três saídas (a推荐 é a 1 + 2 juntas):
1. **Janela de fetch de 7 dias** → 10× a produção com as 4 cidades ✅ medido
2. **Activar as fontes por ofício já validadas** (Chicago Building Permits etc.) ✅ feito
3. **Reposicionar para 50 leads *do meu ofício* por nicho** → queima 6× menos inventário por cliente **e** é mais vendável (um telhadeiro quer 10 obras de telhado, não 300 oportunidades de 16 ofícios) → 6× mais clientes sustentáveis
4. Novas cidades (ArcGIS/LA) → multiplica a produção, com mais esforço

---

## 6. 🧹 Higiene (custo baixo, valor de manutenção)

| # | Item | Onde | Esforço |
|---|---|---|---|
| H1 | Apagar `apply_logging.py` e `fix_indent2.py` (**scripts one-shot que reescrevem `main.py`**) | `backend/` | **P** |
| H2 | Apagar código morto: `services/snov.py` (16 KB), `services/phone_lookup.py` (7,8 KB), `services/geocoder.py` (stub) — 0 importações | `backend/services/` | **P** |
| H3 | Apagar 19 componentes Morton do frontend (~2.000 linhas) e a pasta `src/` (Vite partido: `src/App.tsx` não existe) | `frontend/` | **M** |
| H4 | Eliminar a 2.ª cópia do i18n (`frontend/src/i18n.ts`, 675 linhas, morta) | `frontend/` | **P** |
| H5 | Apagar `_SESSIONS` (dict em memória, escrito em 4 sítios, nunca lido) | `backend/main.py:389` | **P** |
| H6 | `lead_case_history`: 258.903 linhas sem leitor → apagar/migrar | `backend/services/db.py` | **P** |
| H7 | Remover settings de serviços não usados (Supabase, geocoder, truthfinder, gemini, SNOV) | `backend/config.py:16-18,43,45,174-186` | **P** |
| H8 | Unificar a regra de qualificação (SQL vs Python dão números diferentes) | `db.py:59-72` + `lead_rules.py:390-396` | **M** |
| H9 | Trocar `alert()` nativo no reset de password | `frontend/components/AuthForm.tsx:34` | **P** |
| H10 | Expor "novas oportunidades" = real + margem **separadamente** | `backend/services/db.py:5250` | **P** |

---

## 7. 🔐 Registo de segurança (estado actual)

✅ **Limpo:** gate de admin em **todas** as 28 rotas `/api/admin/*` · **sem IDOR** (12 rotas verificam `user["id"] != user_id`) · **sem SQL injection** (parameter binding; f-strings só com constantes internas) · **CORS** com allowlist e `allow_credentials` seguro · passwords PBKDF2-HMAC-SHA256 100k iterações · tokens de sessão guardados como SHA-256 · `/api/billing/mock-activate` desativado (410) · OpenAPI off em produção.

🔴 **A corrigir:**
| Item | Onde | Esforço |
|---|---|---|
| `/api/scraper/enrich` sem gate de admin nem rate limit | `main.py:3264-3309` | **P** |
| `/api/leads/{id}/enrich` sem rate limit | `main.py:3558-3576` | **P** |
| Rotas que gastam dinheiro sem rate limit (`/reserve`, `/reveal-phone`) | `main.py:4395`, `4753` | **P** |
| Sem headers de segurança (HSTS, nosniff, CSP, X-Frame-Options) | backend + `frontend/middleware.ts` | **P** |
| `/health` estático | `main.py:655-657` | **P** |
| Verificar `DEMO_PASSWORD` em produção | `main.py:3805` | **P** |

---

## 8. 📊 Observabilidade (backlog)

**Já existe e é bom:** telemetria de custo em buffer (nunca bloqueia, com `dropped`/`flush_errors`), `scraper_runs`, `city_health` com circuit breaker, Dead Man's Switch, DLQ de notificações, `credit_ledger` append-only com idempotência.

**Falta:**
| Item | Impacto | Esforço |
|---|---|---|
| **request-id** (correlação pedido ↔ run) | Um erro não se liga à origem | **P** |
| **Log de duração por request** | Não há forma de saber que `/today` demora 800 ms | **P** |
| **Contadores de erro agregados** (500s/hora, erros por rota) | Só se descobre lendo o log linearmente | **M** |
| **Telemetria de envio de email** (hoje só a linha `outbound_messages.error`, que o painel não mostra) | Um email falhado é **invisível** | **M** |
| **Reconciliação de runs `running` órfãos** (morreu a meio → fica `running` para sempre) | O painel mostra um run pendurado | **P** |
| **Endpoint de métricas** (Prometheus) — gauges de fila, profundidade, latência | Sem observabilidade de trend | **M** |
| **Limpar `_scrape_runs`** (cresce sem limite em memória) | Memória | **P** |

---

## 9. 📋 Rastreio

| Sprint | Item | Estado |
|---|---|---|
| 1 | 1.1 Falha de API ≠ "0 oportunidades" | ☐ |
| 1 | 1.2 Urgência visível | ☐ |
| 1 | 1.3 Fonte única de categorias + sem enum cru | ☐ |
| 1 | 1.4 Ordem do webhook Stripe | ☐ |
| 1 | 1.5 Reaper de `sending` | ☐ |
| 1 | 1.6 Custo do painel, gates, rate limits, health, headers, ícones | ☐ |
| 2 | 2.1-2.20 (ver tabela) | ☐ |
| 3 | 3.1-3.17 (ver tabela) | ☐ |
| 4 | 4.1-4.6 (ver tabela) | ☐ |
| — | Limpeza H1-H10 | ☐ |
| — | Segurança (registo) | ☐ |
| — | Observabilidade (backlog) | ☐ |

**Regra de ouro deste roadmap:** um item só passa a "feito" com **teste** + **verificação em produção**. Foi assim que se apanhou o bug do `DEFAULT_SCHEMA` antes do deploy, e é assim que este roadmap se mantém honesto.
