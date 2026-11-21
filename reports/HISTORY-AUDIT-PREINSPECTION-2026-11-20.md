# Pente fino de histórico — Pré-inspeção, KPIs, contagens e telefone

**Data:** 2026-11-20 · **Modo:** leitura (`git log`, `git show`, pickaxe). Nenhum `--apply`, nenhum deploy, nenhuma escrita em produção.

> **Correção (ver `reports/PRODUCTION-EVIDENCE-2026-11-20.md`):** a afirmação de que Boston não tem fonte de multa estava incompleta. O dataset ingerido (`800a2663`) tem `value="N/A"`, mas o dataset **Code Enforcement Violations** (`90ed3816-5e70-443c-803d-9a71f44470be`) tem `value` com multas reais (25/100/50…) e **não foi ingerido**. Em Chicago, `6br9-quuz` (`imposed_fine`) e `kc9i-wq85` (`total_fines`) também existem e não foram ingeridos.
**HEAD auditado:** `73ad46d` (master). Working tree contém o P0 ainda **não commitado/deployado**.

---

## 1. Linha temporal relevante

| Data | Commit | O que entrou |
|---|---|---|
| 2026-09-30 | `4bdee2c` | Cache de telefone **em memória** (30 d hit / 24 h miss). Nunca houve `phone_lookups` em BD. |
| 2026-11-13 | `b8d7a19` | Criou `phase1_enrichment.py`: NYC HPD/ECB, Chicago violations, PLUTO. **`source_kind="preventive"` para tudo** desde o nascimento. Chicago violations sem prazo/multa. |
| 2026-11-13 | `4123700` | Fila de 7 dias. Introduziu `window_days` no `insights`: **a janela de `received_at` passou a filtrar também prazos e multas**. |
| 2026-11-13 | `fc408e6` | Barra de abas unificada com `realTotalLeads - permitCount` (leads + página + oportunidades). Antes não existia esta barra. |
| 2026-11-13 | `8047f25` | **Release de produção** do phase1/dashboard: levou os três pontos acima juntos. |
| 2026-11-14 | `010ef51` | Boston/Dallas: prazos de 311 (`target_close_date`, `overall_service_request_due_date`), **sem multas**; Boston violations sem prazo. |
| 2026-11-17 | `9446d5d` | Revelação de telefone por subscrição: `verified=(provider != "mock")`. |
| 2026-11-17 | `5b38255` | Quota de telefone para números em cache. |
| 2026-11-19 | `0294448` | **KPIs passam a respeitar cidade/filtros**. Antes, o KPI era **global**. |
| 2026-11-20 | `c6c15a3` | Chicago: watermark de violações, **novas oportunidades de alvará** e ZIPs. |

---

## 2. O que “parecia funcionar” e por quê

### 2.1 O KPI era global até 19/11

Antes de `0294448`, o call era:

```ts
fetchOpportunityInsights("preventive")   // sem cidade, sem filtros
```

O endpoint devolvia os agregados de **todas as cidades**. Ou seja: ao selecionar Chicago ou Dallas, o cartão “Multas em risco”/“Prazos ≤ 7 dias” mostrava os números **globais**, dominados por NYC. Isso explica a memória de “valores presentes” em cidades que hoje dão zero: não eram valores daquela cidade.

`0294448` mudou para:

```ts
fetchOpportunityInsights("preventive", 7, {
  city: insightsCity, category, severity, zips,
  deadline_within, with_fines,
})
```

A partir daí o KPI é **por cidade**. Os zeros de Chicago/Dallas deixaram de ser mascarados pelos valores de NYC.

Nota: antes de `0294448`, o fetch estava ainda condicionado a `isActiveWeekly`; planos pro/enterprise **nem pediam** insights e viam zeros. O commit corrigiu também esse gate (`hasAccess`). Portanto, o “global” descrito aplica-se sobretudo a contas weekly.

**Veredito:** não é regressão; é a correção que **expôs** a falta de dados locais.

### 2.2 A janela de 7 dias foi aplicada ao campo errado desde 13/11

`4123700` adicionou ao `insights`:

```python
if window_days:
    clause_parts.append("date(COALESCE(received_at, created_at)) >= date('now', ?)")
```

E o mesmo filtro passou a valer para `compliance_deadline` e `fine_*`. Antes de `4123700`, o `insights` não tinha janela: contava **todas** as linhas. Dallas tem 6.855 prazos ≤7d, mas 6.789 vencidos e antigos; com a janela de entrada, só 2 entravam. NYC tinha todas as linhas recentes, por isso continuou a parecer correto.

**Veredito:** a regressão real é de `4123700`/`8047f25` (13/11), não do P0. O P0 separa as janelas.

### 2.3 Tudo é `preventive` desde o primeiro commit

`b8d7a19` nasceu com:

```python
target["source_kind"] = "preventive"
target["source_type"] = "pre_inspection"
```

Nunca existiram linhas `reactive`/`permit` em `opportunity_workflow`. As abas “Reativos/Obras” sempre foram alimentadas por **leads**, não por oportunidades. `8047f25` levou isso para produção. `c6c15a3` adicionou alvarás de Chicago como oportunidades, mas continuaram gravados como `preventive`.

**Veredito:** não houve regressão de uma classificação correta; a classificação correta **nunca existiu**.

### 2.4 A barra de abas misturou três universos em 13/11

`fc408e6` introduziu:

```ts
const permitCount = leads.filter((lead) => lead.signal_type === "authorized_work").length;
const feedTabs = [
  { key: "all", count: realTotalLeads },
  { key: "reactive", count: realTotalLeads - permitCount },
  { key: "preventive", count: preventiveInsights?.totals.count ?? 0 },
  { key: "permit", count: permitCount },
];
```

Antes de `fc408e6`, a UI tinha botões separados “Preventivos/Reativos” dentro do feed; não havia uma barra única a prometer contagens coerentes. O “Todos 2.941 / Reativos 2.941” nasceu aqui: `realTotalLeads` é de leads, `permitCount` é da página atual e `preventiveCount` é de oportunidades.

**Veredito:** regressão de UX em `fc408e6` (13/11), não do P0.

### 2.5 O mapa sempre foi 30d

`7b2a0fd` introduziu o mapa com `days: 30`, enquanto o feed/KPI usavam 7d. A divergência 587 × 469 é essa janela. `c6c15a3` mexeu em ZIPs/escopos, mas não alinhou a janela. O P0 alinhou para 7d.

### 2.6 Chicago: o que mudou em 20/11

`c6c15a3`:
- trocou o fetch de violações de `since=90d` + `$order=violation_date` por **watermark** em `coalesce(violation_last_modified_date, violation_date)`, com paginação;
- criou `fetch_chicago_permits` como oportunidades `authorized_work`;
- adicionou ZIPs/centroides.

Efeito: o conjunto Chicago mudou. Os **96** atuais são violações `legal_obligation` gravadas como `preventive`; os **504** alvarás também estão como `preventive`. Antes de `c6c15a3`, não havia oportunidades de alvará em Chicago e o conjunto de violações era outro. O “Obras 0” de Chicago era correto antes; agora há 504 obras, mas a aba ainda lia a página de leads.

**Veredito:** a inversão Dallas/Chicago não é regressão de código; é a classificação `preventive` + a contagem de obras por página de leads.

### 2.7 Boston/Dallas: prazos sim, multas não (por fonte)

`010ef51` adicionou:
- Boston 311 → `target_close_date` (prazo);
- Dallas 311 → `overall_service_request_due_date` (prazo);
- **nenhuma multa** em Boston/Dallas;
- Boston violations → `compliance_deadline=None` (a fonte só tem `status_dttm`, que é mudança de estado).

**Veredito:** o zero de multas em Boston/Dallas é ausência de fonte, não código. O zero de prazo em Chicago é ausência de campo no dataset `22u3-xenr`.

---

## 3. Telefone: o que o histórico mostra

| Commit | Facto |
|---|---|
| `4bdee2c` (30/09) | Cache **em memória** 30d/24h; `phone_lookups` em BD **nunca existiu**. |
| `c73e33f` (P0-C1) | `name_match`, L2/L3, transporte, `verified` no `searchbug`. |
| `9446d5d` (17/11) | Fluxo de subscrição: `verified=(provider != "mock")` — o selo passou a ignorar `result.verified`. |
| `5b38255` (17/11) | Quota para números em cache. |
| P0 atual (não commitado) | Primeiro `phone_lookups` persistente, fila assíncrona, clique sem provider, `verified` por prova. |

**Veredito:** não há regressão que tenha “zerado” telefones. A produção teve **0 revelações** e a última chamada SearchBug foi 13/11. O `phone_lookups` documentado no `AGENTS.md` era uma intenção, não código. O P0 de telefone corrige isso; ainda não foi deployado.

---

## 4. Confirmação de regressão/efeito colateral

**Não há uma regressão única e recente que explique tudo.** Há quatro causas históricas que se somam:

1. **`0294448` (19/11)** — KPI deixou de ser global e passou a ser por cidade. Os “bons valores” anteriores eram, em grande parte, de NYC a aparecer em todas as cidades.
2. **`4123700`/`8047f25` (13/11)** — janela de `received_at` aplicada a prazos/multas; Dallas antigo ficou de fora.
3. **`b8d7a19` (13/11)** — `source_kind="preventive"` para tudo; nunca houve reativos/obras nas oportunidades.
4. **`fc408e6` (13/11)** — barra de abas com leads + página + oportunidades; o “Todos/Reativos iguais” nasceu aqui.

O P0 não introduziu estes comportamentos; corrige-os. O único efeito colateral novo é o esperado: **Chicago fica com 0 preventivos** depois do backfill, porque os 96 são violações reativas. Para ter pré-inspeção em Chicago, é preciso ingerir o 311 de Chicago (`open_request`), que hoje não é fonte.

---

## 5. Plano dos P1 (confirmado, sem executar agora)

1. **Rótulo honesto de dado ausente**
   - Chicago/Boston: onde não há prazo, mostrar `—`/“sem dados de prazo”, não `0`.
   - Chicago/Dallas/Boston: onde não há multa, mostrar `—`/“sem dados de multa” e desativar “Com multa”.
   - Aplicar em `insights`/cartões e no `PreventiveCard`.

2. **LIMPAR e filtros**
   - `clearFilters` passa a limpar `neighborhoodFilter`, `leadZone`, `feedLayer`, `readiness`, `opportunityKind`, `deadlineWindow` e `withFines` (hoje só limpa parte).
   - Mapa recebe `severity`, `deadline_within`, `with_fines` e busca **ou** esses filtros ficam desativados no mapa com explicação; nunca ignorados em silêncio.
   - Filtros avançados (`Tipo`/`Proprietário`/`Encerrados`) aplicam-se ao feed de leads e, na Pré-inspeção, ou passam a valer ou ficam ocultos.

3. **Janelas**
   - Feed/KPI/mapa a **7d** (P0 já alinhou o mapa).
   - `received_at` só para “novas”; `compliance_deadline` para prazos; `fine_*` para multas (P0 já separou).
   - Se voltar a haver 30d, mostrar “30d” ao lado do número.

4. **Geo**
   - Centroides por ZIP (Census ZCTA) como fallback; contar `unmapped` também quando falta centroide, não só ZIP.

5. **Fonte**
   - Chicago: ingerir 311/`open_request` para haver pré-inspeção; dataset de multas/audiências.
   - Dallas/Boston: dataset de multas/code compliance.
   - Boston: usar data da violação, não `status_dttm`.

---

## 6. Decisões mantidas

- **Backfill `--apply`:** **não autorizado** até dry-run detalhado e revisão deste histórico.
- **Deploy:** **não autorizado** até validar o impacto em Chicago (0 preventivos sem 311).
- **P1:** plano acima confirmado; execução só depois da sua aprovação.
- **`VOICE_FREEZE=1`** e **`feat/br-environmental-mvp`** intactos. Nenhuma escrita em produção.
- **Nota de deployment:** o histórico acima é do `master` (`73ad46d`). Antes de qualquer `apply`/deploy, confirmar o **SHA efetivamente em produção** no Railway/Vercel; o comportamento observado pode corresponder a um commit anterior a `0294448`/`c6c15a3`.
