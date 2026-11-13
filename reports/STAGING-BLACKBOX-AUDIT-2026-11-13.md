# Auditoria "caixa preta" — Pré-inspeção / Feed (staging)

Data: 2026-11-13
Branch: `staging/opportunity-foundation`
Produção: `master` em `3b53962` — **intocada** (sem deploy, sem migração, sem commit).
Base de staging: `C:\Users\Fabio\AppData\Local\Temp\opencode\staging-opportunity\leads.db`
Backend: `127.0.0.1:8010` (schedulers desligados) · Frontend: `localhost:3000`

Método: inventário estático (BD → API → tipos → componentes), 6 testes unitários novos,
simulação de erros com duas contas reais, troca rápida de abas e execução em 4 fusos.

---

## 1. Enriquecimento de dados (backend → API → interface)

### 1.1 Matriz de campos

| Campo em `opportunity_workflow` | API | Card | Drawer | Situação |
|---|---|---|---|---|
| `address`, `city`, `state`, `zip_code` | sim | sim | sim | OK |
| `category` | sim | sim | sim | OK |
| `severity` | sim | sim | sim | OK |
| `compliance_deadline` | sim | sim | sim | OK (dias de calendário) |
| `description` | sim | sim | sim | OK |
| `owner_name` | sim | sim | sim | OK |
| `owner_type` | sim | — | **sim** | **corrigido nesta auditoria** |
| `inspection_status` | sim | — | sim | OK |
| `received_at` | sim | — | sim | OK |
| `tags_json` → `tags` | sim | — | **sim** | **corrigido nesta auditoria** |
| `timeline_json` → `timeline` | sim | — | **sim** | **corrigido nesta auditoria** |
| `job_value` | sim | — | **sim** | **corrigido nesta auditoria** |
| `status` | sim | timeline | sim | OK |
| `source_type` | sim | badge | sim | OK (mapeado, nunca cru) |
| `signal_type` | sim | passo “Chamado aberto” | idem | OK (implícito) |
| `reserved_until`, `stage_expires_at` | sim | — | — | no guia 1h/48h/48h e no detalhe do lead |
| `bbl`, `bin` | sim | — | — | interno (regra de privacidade) |
| `property_key`, `source_record_id`, `source_kind` | sim | — | — | interno |
| `contacted_at`, `negotiated_at`, `converted_at`, `created_at`, `updated_at` | sim | — | — | auditoria/ciclo de vida |
| `source_payload` | **não** | — | — | **removido da resposta pública** (ver 1.2) |

Ficheiros alterados para fechar os cortes: `OpportunityDrawer.tsx`, `PreventiveFeed.tsx`,
`opportunity-format.ts`, `seed_staging_opportunities.py` (+ `opportunity-format.test.ts`).

### 1.2 Achados

1. **`source_payload` era devolvido ao cliente.** O `_public()` devolvia o payload bruto da
   fonte, o que podia expor termos/datasets proibidos pela regra de privacidade. Passou a ser
   removido da resposta (fica só na BD). Verificado: a resposta já não contém a chave.
2. **`job_value`, `owner_type`, `tags` e `timeline` existiam na API mas não eram exibidos.**
   Agora aparecem no drawer: valor estimado (moeda localizada), tipo de proprietário, tags
   traduzidas e datas da timeline vindas do backend.
3. **Timeline usava apenas o estado, não os metadados.** Passou a usar `timeline_json` para
   data/rótulo, mantendo o estado calculado em tempo real (reserva/contacto/negociação).
4. **Seed não preenchia `tags_json`/`timeline_json`.** Passou a preencher (inclui
   `deadline_soon` apenas para prazos ≤ 7 dias).

### 1.3 O que ainda NÃO chega à interface (bloqueio de pipeline, não de UI)

- **Managing Agent do HPD (LLC / CorporateOwner).**
  `backend/services/hpd_agent.py` resolve o agente via `tesw-yqqr` + `feu5-w2e2` e
  `enrichment.py:328-340` anexa `managing_agent` ao resultado **apenas** com
  `HPD_AGENT_ENRICHMENT_ENABLED` (default `False`). Porém:
  - não existe coluna em `leads` para o persistir;
  - os chamadores só gravam `owner_name` e `mailing_address` (`main.py:4709`, `8866`);
  - não existe campo na API nem na UI.
  **Conclusão:** o dado é calculado e descartado. Para produção, é preciso coluna + persistência
  + exposição (e depois mostrar no detalhe do lead/drawer).
- **Histórico de infrações na camada preventiva.** Os reativos têm `lead_case_history` e os
  endpoints `/api/leads/{id}/history` e `/occurrences` (exibidos no detalhe do lead). Os
  preventivos usam `timeline_json`; o seed já o preenche, mas **não existe ainda o adaptador de
  ingestão** que o preencha em produção — hoje a camada preventiva é alimentada pelo seed.
- **`owner_type` do seed é um rótulo PT** ("Empresa"). A UI mostra-o como conteúdo (não como
  copy); para produção deve vir do classificador (`private`/`institutional`) ou ser mapeado.

**Veredicto 1:** a UI já exibe todos os campos que a API entrega; o que falta é **persistir e
expor o managing agent** e **ligar a ingestão preventiva**. São bloqueios de dados, não de
componentes.

---

## 2. Casos limites simulados

### 2.1 `PROPERTY_LOCKED` (reserva simultânea)

Cenário real com duas contas: `staging@` reserva a oportunidade #13; `edge-b@` tenta a mesma.

| Passo | Resultado |
|---|---|
| API `POST /opportunities/13/reserve` (A) | `200`, `reserved=true` |
| API `POST /opportunities/13/reserve` (B) | `409 {"detail":"PROPERTY_LOCKED"}` |
| UI (B, PT): drawer → consentimento → reservar | toast **“Este imóvel já está reservado por outro empreiteiro.”** |
| Estado da UI | modal fechado, página funcional, **0 erros de consola** |

O botão de reserva não “congela”: o erro é traduzido por código estável (`api-errors.ts`) e o
`finally` fecha o modal.

### 2.2 `DAILY_LIMIT_REACHED` (cota esgotada)

Conta `edge-limit@` com `user_daily_stats = 10/10` e `remaining=0`.

| Camada | Resultado |
|---|---|
| API `POST /opportunities/14/reserve` | `429 {"detail":"DAILY_LIMIT_REACHED"}` |
| UI PT | alerta **“Limite de 10 leads/dia atingido. Volte amanhã…”**, botão confirmar **disabled** |
| UI EN | **“Daily limit of 10 leads reached…”**, disabled |
| UI ES | **“Límite de 10 leads/día alcanzado…”**, disabled |

**Correção feita:** antes o botão ficava apenas desativado, sem explicação. Agora o modal
mostra um `role="alert"` com a mensagem traduzida e mantém o botão bloqueado.

### 2.3 Fusos horários / datas

O cálculo antigo usava `Date.parse("2026-11-14Z")` (meia-noite UTC) e podia recuar um dia em
fusos negativos. Foi substituído por `deadlineDaysLeft()`: lê `YYYY-MM-DD`, compara com a
meia-noite **local** do utilizador.

- Testes unitários: 6 casos passam em `UTC`, `Asia/Tokyo`, `America/Los_Angeles`,
  `Pacific/Honolulu`.
- Teste no browser (Playwright com `timezoneId`), cartão com prazo `2026-11-14`:

| Fuso | Data local | Ecrã | Esperado |
|---|---|---|---|
| UTC | 13 Nov 18:59 | **Prazo em 1 dia** | 1 |
| Asia/Tokyo | 14 Nov 03:59 | **Prazo hoje** | 0 |
| America/Los_Angeles | 13 Nov 10:59 | **Prazo em 1 dia** | 1 |
| Pacific/Honolulu | 13 Nov 08:59 | **Prazo em 1 dia** | 1 |

Também foi corrigida a pluralização: `0` → “Prazo hoje”, `1` → “Prazo em 1 dia”, `N` →
“Prazo em N dias” (EN/ES equivalentes).

**Veredicto 2:** os três cenários passam; sem desvios de fuso e com mensagens localizadas.

---

## 3. Paridade Reativos vs. Preventivos

- Cidade, especialidade, gravidade, “somente com prazo” e busca vivem **na página** e são
  passados aos dois feeds; trocar de aba não reinicia filtros.
- O rail passou a ser **calculado a partir das linhas filtradas** (antes usava os agregados
  globais na pré-inspeção), garantindo que “Prazos críticos”, “Gravidade da amostra” e “ZIPs
  mais quentes” batem com os cartões visíveis.
- Teste de troca rápida (6 mudanças de aba, 1,2 s entre cada):

| Aba | Cartões | Soma da gravidade no rail |
|---|---|---|
| Todos | 4 | 4 |
| Reativos | 3 | 3 |
| Preventivos | 12 | 12 |
| Obras | 1 | 1 |
| Todos (2.ª) | 4 | 4 |
| Preventivos (2.ª) | 12 | 12 |

0 erros de consola; nenhuma fuga de cartões entre camadas (Obras mostrou apenas Preston Rd).

**Veredicto 3:** paridade confirmada; a matemática do rail fecha com os cartões.

---

## 4. Limpeza de código

- **Logs de depuração:** 0 `console.log`/`debugger`/`TODO`/`FIXME` nos ficheiros novos e nos
  alterados nesta fase.
- **Texto hardcoded:** 0 strings visíveis fora de `t()` nos componentes novos
  (`FeedToolbar`, `FeedRail`, `PreventiveCard`, `OpportunityDrawer`). Restam ocorrências
  **pré-existentes** na página (ex.: “Lead já reservado por você”, “Ocorrência”,
  “Carregando...”) — dívida anterior, não introduzida aqui.
- **Código morto removido:** o `filtersTriggerRef` apontava para um botão que já não existia;
  passou a estar ligado ao botão “Filtros” da nova barra (foco devolvido ao fechar a gaveta).
  Também foram removidos os controlos duplicados de categoria/urgência.
- **Tailwind:** os componentes novos usam cor sólida ou `color-mix` inline em vez de
  `bg-[var(--sd-*)]/NN` (o Tailwind 3 descarta essa combinação). Ficaram **13 ocorrências
  pré-existentes** no resto do frontend (ex.: `components/ui/signal.tsx`) — recomenda-se
  limpeza numa passagem de cosmética, sem impacto funcional.
- **Acessibilidade:** o modal de cota usa `role="alert"`; a barra mantém `aria-pressed` nas
  abas/chips e `aria-label` nos selects e busca.

**Veredicto 4:** código novo limpo; a dívida restante é pré-existente e está listada.

---

## 5. Evidência de testes

| Verificação | Resultado |
|---|---|
| `pytest tests/ -q` | 1676 passed, 1 skipped |
| `npm test -- --run` | 123 passed (16 ficheiros; +6 novos) |
| `npx tsc --noEmit` | limpo |
| `npx eslint . --quiet` | limpo |
| Fusos (4) no Vitest | 6/6 passam em cada |
| Browser 4 fusos | render = esperado em todos |
| `PROPERTY_LOCKED` API/UI | 409 + toast PT, 0 erros |
| `DAILY_LIMIT_REACHED` API/UI | 429 + alerta PT/EN/ES, botão disabled |
| Troca rápida de abas | 4/3/12/1 e rail 4/3/12/1 |

Capturas de evidência: `pt-drawer-enriched.png` (valor, tipo de dono, tags e datas),
`pt-quota-blocked.png` (alerta de cota e botão bloqueado) e as restantes em
`C:\Users\Fabio\AppData\Local\Temp\opencode\staging-opportunity\shots\`.

---

## 6. Veredicto final e bloqueios

**Interface:** aprovada tecnicamente. Campos disponíveis são exibidos, erros têm tradução,
prazos são estáveis por fuso e os dois feeds partilham filtros sem conflito.

**Antes de produção (bloqueios de dados, não de UI):**

1. **Persistir e expor o Managing Agent do HPD** (coluna + escrita + API + UI); hoje é
   calculado e descartado.
2. **Ligar o adaptador de ingestão preventiva** (hoje o `opportunity_workflow` é alimentado
   pelo seed) para preencher `description`, `owner_*`, `job_value`, `tags_json` e
   `timeline_json` a partir da fonte real.
3. **Limpeza cosmética** das 13 ocorrências de opacidade com `var(--sd-*)` e das strings
   hardcoded pré-existentes (não bloqueante).

Produção permanece em `master` `3b53962`, sem alterações, deploys ou migrações.
