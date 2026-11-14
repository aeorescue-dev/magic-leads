# Parecer técnico de prontidão para produção — MagicLeads / Fase 1

Data: 2026-11-13
Branch auditada: `staging/opportunity-foundation` → head **`3e7bd5e`**
Produção de referência: `master` → **`3b53962`**
Âmbito: staging (dashboard preventiva, ingestão, schedulers, visualização, landing e isolamento).

## 1. Veredito executivo

**Go condicional. O código está verde, mas o pacote de release ainda não está pronto para um merge cego na `master`.**

Não encontrei bug funcional ou visual bloqueante nas rotinas principais do staging. Os testes passam, a integridade de dados está limpa e os schedulers correm sem erros. Porém, o branch de staging **não é um patch de 4 commits da Fase 1**: está **30 commits à frente da `master`**, com 53 ficheiros e ~8.951 linhas, incluindo uma alteração funcional à landing (`LandingShell.tsx`) e correções de acentuação em copy da landing. Isso conflita com a regra de “landing congelada” e aumenta o risco de regressão.

**Recomendação:** criar um branch de release a partir da `master`, decidir explicitamente o escopo (o release train completo ou apenas a Fase 1), remover/reverter as alterações de landing e seguir o checklist da secção 9 antes do merge.

## 2. Escopo e método

Foram auditados:

- testes backend e frontend;
- build de produção Next.js;
- integridade da base SQLite de staging;
- contrato da API (`/api/opportunities`, insights, view, filtros, paginação);
- schedulers da Fase 1 e logs;
- jornada de visualização por utilizador;
- landing page e isolamento do repositório de produção;
- privacidade e termos proibidos.

## 3. Repositório e isolamento

| Item | Resultado |
|---|---|
| Branch staging | `staging/opportunity-foundation` |
| Head staging | `3e7bd5e` |
| `master` no repo de staging | `3b53962` |
| Commits à frente da `master` | **30** |
| Commits atrás da `master` | 0 |
| Ficheiros alterados vs `master` | **53** |
| Linhas | **+8.951 / -271** |
| Repo de produção `garimpador-leads` | `master` **`3b53962`**, intocada |
| Alterações não commitadas no staging | **0** |

O repositório de produção tem apenas ficheiros não rastreados pré-existentes (`deploy_voice_tts_cache.log`, `voice_start_monitor.log`, `frontend/AGENTS.md`, `reports/`). Nada foi alterado em produção.

### Achado bloqueante de escopo

O branch de staging inclui muito mais do que a Fase 1:

- `frontend/components/landing/LandingShell.tsx` — alteração funcional ao seletor de idioma da landing (passa a fazer `router.replace` para o path com locale);
- `frontend/lib/i18n/{en,es,pt}.ts` — inclui correções de acentuação em chaves `landing.*` (ES/PT);
- `frontend/lib/i18n.tsx` — novo `pathWithLocale`;
- `frontend/components/AuthForm.tsx`, `NavbarNew.tsx`, `ui/ReserveGuideModal.tsx`, `backend/models/schemas.py`, `backend/services/enrichment.py`, `backend/services/privacy.py`, testes de quota;
- scripts e relatórios de staging (`seed_staging_opportunities.py`, `ingest_phase1_staging.py`, `reclassify_staging_opportunities.py`, `create_beta_tester.py`, relatórios);
- `frontend/AGENTS.md` (ficheiro gerado pelo `next dev`).

**Conclusão:** um merge direto do branch levaria todo esse pacote para produção. Isso não é um merge “só da Fase 1” e não cumpre a regra de landing intocada.

## 4. Testes e qualidade

| Verificação | Resultado |
|---|---|
| `pytest tests -q` | **1718 passed, 1 skipped** |
| Motivo do skip | `test_e2e_checkout.py` exige `E2E_API_URL` (E2E de checkout não executado) |
| `npm test` | **126 passed** |
| `npx tsc --noEmit` | limpo |
| `npm run build` | **sucesso** (todas as rotas geradas) |
| `ruff check backend tests --select=E,F,W,I --ignore=E501` | limpo |
| ESLint | **0 erros**, 101 warnings |
| `npm audit --omit=dev` | **0 vulnerabilities** |

Os warnings de ESLint são de regras `react-hooks/set-state-in-effect` e `exhaustive-deps` já presentes no projeto; não há erros. O skip do checkout é esperado sem a env de E2E.

**Resposta à pergunta 2:** todas as suites passaram; há **1 skip esperado** e **101 warnings não bloqueantes**. Não é correto dizer “zero alertas”, mas não há falhas.

## 5. Integridade de dados

Base auditada: SQLite de staging.

| Métrica | Resultado |
|---|---|
| Preventivos totais | 408 |
| Preventivos na janela de 7 dias | 402 |
| Preventivos em 30 dias | 408 |
| Linhas com mais de 90 dias | 0 |
| `category` vazia / `Unclassified` | **0** |
| `source_kind + source_record_id` duplicados | 0 |
| Imóveis com mais de um ciclo ativo | 0 |
| Locks órfãos | 0 |
| Views órfãs | 0 |
| Histórico/propriedade JSON inválidos | 0 |
| Datas inválidas (`received_at`, `compliance_deadline`) | 0 |
| Multas negativas | 0 |
| `fine_paid > fine_imposed` | 0 |
| `fine_balance > fine_imposed` | 0 |

### Estado da fila

| Métrica | Valor |
|---|---|
| Multas reais em aberto | 39 |
| Saldo de multas em risco | **US$ 304.300** |
| Prazos ≤ 7 dias | 44 |
| Prazos ≤ 3 dias | 18 |
| Valor de obra | 42 (32 de alvará) |
| Dossiê de imóvel | 67 |
| Histórico | 390 |

Distribuição por ofício na janela: Heating 173, Rodent 72, Structure 32, Plumbing 25, Elevator 20, Electrical 19, Paint 13, Roof 12, Unsanitary 10, Door_Window 8, Mold 6, Permit_Rejected 5, Gas 4, Debris 2, Lead 1.

## 6. API e privacidade

| Verificação | Resultado |
|---|---|
| `GET /api/opportunities?kind=preventive&limit=50&days=7` | 200, 50 linhas, `total=402`, `has_more=true` |
| Filtro `with_fines=true` | 39 |
| Filtro `deadline_within=3` | 18 |
| Insights | `count=402`, `fines_at_risk=304300`, `fines_count=39` |
| `source_payload` na resposta pública | **ausente** |
| Termos proibidos em descrições/histórico/propriedade | **0 leaks** |

A API devolve `viewed_at` apenas para o utilizador autenticado. O endpoint de visualização foi testado: regista a abertura, não consome cota e não vaza a marcação para outro utilizador.

## 7. Jornada de visualização

| Regra | Estado |
|---|---|
| Persistência por `(user_id, opportunity_id)` | `opportunity_views` |
| Abrir o drawer marca a visualização | `POST /api/opportunities/{id}/view` |
| Nunca vistos primeiro | validado (ordenação por `last_viewed_at IS NULL`) |
| Visto hoje | selo **“Visto hoje”** |
| Visto ontem / há 2 dias | **“Visto ontem” / “Visto há 2 dias”** |
| 3+ dias | **opacidade 70%** + **“Visto a DD/MM”** |
| Isolamento entre utilizadores | validado por teste |
| Consumo de cota | nenhum |

Validação manual no browser:
- `1320 W Fullerton Ave` passou a “Visto hoje” ao abrir;
- `564 W Randolph St` com visualização de 4 dias atrás ficou com opacidade 0.70 e “Visto a 09/11”;
- cartões nunca abertos continuam sem selo e à frente;
- sem erros de consola no dashboard.

## 8. Schedulers da Fase 1

| Item | Resultado |
|---|---|
| Processo backend | ativo em `127.0.0.1:8010` |
| Scheduler Fase 1 | ativo: operacional 6h, alvarás 24h, fila 7d |
| Último run diário | 381 candidatos, 0 criados, 381 enriquecidos |
| Erros/tracebacks no log | **0** |
| Purga de 90 dias | ativa, sem linhas antigas |
| Default em produção | `PHASE1_SCHEDULER_ENABLED=False` (seguro) |
| Staging | ligado por env |

Riscos operacionais:

- os timers são **em memória**; um restart com `PHASE1_RUN_ON_START=1` dispara novo run diário. É idempotente, mas gera carga extra em cada deploy;
- não há teste E2E do loop do scheduler, apenas dos serviços de ingestão/retenção;
- Socrata sem app token tem throttling; monitorizar 429;
- o volume de produção esperado (~20 mil registos na janela de 7 dias) não foi testado; o staging tem 408.

## 9. Landing page

| Verificação | Resultado |
|---|---|
| Working tree atual vs HEAD em `frontend/app/[locale]/(marketing)` | 0 |
| Working tree atual vs HEAD em `frontend/components/landing` | 0 |
| Branch vs `master` em `frontend/app/[locale]/(marketing)` | 0 |
| Branch vs `master` em `frontend/components/landing` | **1 ficheiro: `LandingShell.tsx`** |
| Chaves `landing.*` alteradas vs `master` | **correções de acentuação em ES/PT** |

**Achado bloqueante:** a landing não está “zero-diff” contra a `master`. O merge do branch altera o comportamento do seletor de idioma e copy com acentos. É necessária uma decisão explícita:

1. reverter `LandingShell.tsx` e as chaves `landing.*` no branch de release; ou
2. aprovar formalmente essa alteração e retirar a regra de “landing congelada” para este release.

## 10. Checklist obrigatório antes do merge

1. **Criar branch de release a partir da `master`**; não fazer merge direto do staging.
2. **Decidir o escopo:** o release train de 30 commits ou apenas os commits da Fase 1 (a Fase 1 depende da fundação de dashboard/oportunidades, pelo que o corte não é trivial).
3. **Remover/reverter landing:** `frontend/components/landing/LandingShell.tsx` e chaves `landing.*` alteradas; ou exceção escrita.
4. **Excluir scripts/relatórios de staging** que não devem ir para produção (seed, ingest manual, reclassify, beta tester, relatórios) ou aprová-los explicitamente.
5. **Backup da BD de produção** e execução do `init_db()` para criar `opportunity_workflow`, `opportunity_views`, colunas e índices.
6. **Configurar env de produção:** `PHASE1_SCHEDULER_ENABLED=1`, limites (`PHASE1_OPERATIONAL_LIMIT`, `PHASE1_ECB_LIMIT`, `PHASE1_DAILY_PERMIT_ROWS`), `PREVENTIVE_*`; decidir `PHASE1_RUN_ON_START`.
7. **Primeiro run controlado:** usar `POST /api/admin/phase1/run` com limites baixos e validar 50/100 cartões, filtros, view e ausência de “Unclassified”.
8. **Monitorizar 24–48h:** logs `[PHASE1]`, erros, 429 da Socrata, crescimento da BD, purga, latência da API.
9. **Rollback:** deploy anterior da `master`, scheduler off; as tabelas novas são aditivas e não alteram `leads`, pelo que o rollback é seguro.

## 11. Respostas diretas

### 1. O sistema está 100% consistente, sem bugs visuais ou de backend nas rotinas principais?

**No staging, sim para o escopo auditado:** não encontrei bug funcional/visual nas rotinas principais (dashboard, filtros, paginação, drawer, multas, prazos, classificação, visualização, scheduler). A integridade de dados está limpa. **Mas o pacote de release não está consistente com a regra de landing intocada**, porque o branch vs `master` altera `LandingShell.tsx` e copy da landing.

### 2. Todos os testes de regressão e suites automatizadas passaram sem alertas?

**Passaram sem falhas:** 1718 backend + 126 frontend, build de produção, `tsc`, `ruff` e `npm audit` 0. Há **1 skip esperado** (E2E checkout sem `E2E_API_URL`) e **101 warnings de ESLint** não bloqueantes. Portanto: sem falhas, mas não “sem alertas”.

### 3. O ambiente está tecnicamente pronto e blindado para subir para produção sem riscos de regressão?

**Ainda não para um merge cego.** O código está verde, mas o release não está blindado: 30 commits, 53 ficheiros, landing alterada e scripts de staging no pacote. **Go condicional** após o checklist da secção 10. Com release scoped, landing revertida/aprovada, migração e monitorização, o risco residual é controlável.

## 12. Evidências principais

- `git status` staging limpo; head `3e7bd5e`.
- `git rev-list --count master..HEAD` = 30.
- `git diff --stat master...HEAD` = 53 ficheiros, +8951/-271.
- `git diff master...HEAD -- frontend/components/landing/LandingShell.tsx` = alteração funcional.
- `pytest`: 1718 passed, 1 skipped.
- `npm test`: 126 passed.
- `npm run build`: sucesso.
- `npm audit --omit=dev`: 0 vulnerabilities.
- API: 50/402, `has_more`, 39 multas, 18 prazos ≤3, `source_payload` ausente.
- Dados: 0 Unclassified, 0 duplicados, 0 JSON/datas inválidas, 0 leaks de privacidade.
- Scheduler: ativo, sem erros, run diário de 381 candidatos.
- Produção `garimpador-leads`: `master` `3b53962`, intocada.

## 13. Atualização — release branch limpo criado

Branch de release: **`release/phase1-production`** (worktree separado, criado a partir da `master` `3b53962`).
Commit: **`8047f25`** — 1 commit à frente da `master`, **25 ficheiros**, +5.484/−186.

Incluído:
- backend da Fase 1 (`opportunity_workflow`, `phase1_enrichment`, `phase1_scheduler`, `hpd_agent`);
- schema/tabelas aditivas (`opportunity_workflow`, `property_locks`, `opportunity_outcomes`, `opportunity_views`);
- endpoints `/api/opportunities` (lista, insights, view, reserve/contact/negotiate/convert/outcome);
- dashboard, filtros, paginação, cartões, drawer/dossiê e KPI;
- i18n apenas com chaves de dashboard/oportunidade.

Excluído:
- `LandingShell.tsx`, `frontend/components/landing/*`, `frontend/app/[locale]/(marketing)/*`;
- `frontend/lib/i18n.tsx`;
- scripts de staging (`seed`, `ingest`, `reclassify`, `beta tester`);
- relatórios, `frontend/AGENTS.md` e testes de staging.

Verificação de landing no release:
- `frontend/components/landing` vs `master`: **0 ficheiros**;
- `frontend/app/[locale]/(marketing)` vs `master`: **0 ficheiros**;
- `frontend/lib/i18n.tsx` vs `master`: **0 alterações**;
- chaves `landing.*` vs `master`: **235/235 idênticas** em EN/PT/ES.

Testes no branch de release:
- `pytest tests -q`: **1668 passed, 1 skipped** (suite da `master`);
- `npm test`: **111 passed**;
- `npx tsc --noEmit`: limpo;
- `npm run build`: **sucesso**;
- `ruff`: limpo; ESLint **0 erros**;
- `npm audit --omit=dev`: **0 vulnerabilities**;
- smoke test de runtime: list/view/filtros/insights OK; scheduler `run_once` OK.

Estado: **branch pronto para revisão e deploy**. A `master` e o repositório de produção continuam em `3b53962`, intocados.

