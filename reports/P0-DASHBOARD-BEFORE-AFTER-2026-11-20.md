# P0 da dashboard — antes/depois nas 4 cidades

**Data:** 2026-11-20 · **Estado:** implementado e testado localmente; **backfill não aplicado em produção**; nenhum deploy.
**Âmbito:** classificação `source_kind`, janelas de prazo/multa, contagens das abas, mapa. `VOICE_FREEZE=1` e frente BR intactos.

> **Nota de leitura:** o “depois” é a projeção sobre os dados atuais usando a classificação por `signal_type` e as novas janelas. O backfill só será executado depois da sua validação; nada em produção foi alterado.

---

## 1. O que mudou

| # | Mudança | Ficheiro |
|---|---|---|
| P0.1 | `source_kind` passa a seguir `signal_type` (`legal_obligation→reactive`, `authorized_work→permit`, `open_request→preventive`) | `backend/services/phase1_enrichment.py` (`source_kind_for_signal`, `build_candidates`) |
| P0.1b | Backfill idempotente, dry-run por defeito | `backend/scripts/backfill_source_kind.py` |
| P0.2 | `insights`: `received_at` só governa “novas”; prazos/multas são risco aberto (inclui vencidos). Novo `totals.overdue`. | `backend/services/opportunity_workflow.py` |
| P0.3 | Contagens por tipo no mesmo WHERE do feed (`signal_counts`) | `backend/services/db.py`, `backend/models/schemas.py`, `backend/main.py` |
| P0.3b | Abas da Pré-inspeção filtram o feed de **oportunidades** (all/preventive/reactive/permit); abas da lista de leads filtram **leads** | `frontend/.../page.tsx`, `PreventiveFeed.tsx`, `NeighborhoodPanel.tsx` |
| P0.4 | Mapa da Pré-inspeção passa de 30d para **7d**, alinhado com feed/KPI; segue o `kind` ativo | `NeighborhoodPanel.tsx` |
| P0.4b | “Reativos” deixa de ser “tudo o que não é obra” e passa a `legal_obligation`; “Preventivos” = `open_request` | `backend/services/db.py` (`_leads_feed_where`), `page.tsx` |
| — | Seletor de cidade passa a explicitar “contagens: leads dos últimos 7 dias” | `CityPicker.tsx`, i18n |

**Ajuste conjunto pedido:** as multas/prazos de NYC não desaparecem. Passam a aparecer no separador correto:
- `Preventivos`: 7 multas (open_request);
- `Reativos`: 98 multas (legal_obligation);
- `Todos`: 105 multas / $478.900.
O total mantém-se; só a etiqueta muda.

---

## 2. Antes/depois — Pré-inspeção (oportunidades, 7d)

### 2.1 Contagens por separador

**Antes (print):**

| Cidade | Todos | Reativos | Preventivos | Obras |
|---|---:|---:|---:|---:|
| NYC | 2.941 | 2.941 | 469 | 0 |
| Chicago | 2.963 | 2.963 | 96 | 0 |
| Dallas | 3.466 | 2.918 | 545 | 41 |

**Depois (dados reais por `signal_type`, 7d):**

| Cidade | Todos | Reativos | Preventivos | Obras |
|---|---:|---:|---:|---:|
| NYC | **469** | **150** | **319** | **0** |
| Chicago | **96** | **96** | **0** | **0** |
| Dallas | **545** | **0** | **41** | **504** |
| Boston | **548** | **0** | **336** | **212** |

**Leitura:** em Dallas os números estavam **invertidos** — os 545 “preventivos” eram 504 obras + 41 preventivos; o “Obras 41” era, na verdade, o preventivo. Em Chicago os 96 são **reativos** (violações), não preventivos. Em NYC, 319 preventivos + 150 reativos.

### 2.2 Leads (aba Oportunidades, 7d qualificados)

| Cidade | Todos | Reativos | Preventivos | Obras |
|---|---:|---:|---:|---:|
| NYC | 7.869 | 1.000 | 6.862 | 7 |
| Chicago | 2.329 | 0 | 1.925 | 404 |
| Dallas | 1.058 | 0 | 28 | 1.030 |
| Boston | 836 | 0 | 344 | 492 |

Estes são os 7d qualificados de produção. O feed do utilizador aplica interesses, readiness e estado; os contadores acompanham **o mesmo WHERE** da lista. O seletor de cidade está rotulado “leads 7d” para não ser confundido com oportunidades.

---

## 3. Antes/depois — Prazos e multas

| Cidade | Prazos ≤7d antes | Prazos ≤7d depois | Vencidos (novo) | Multas antes | Multas depois |
|---|---:|---:|---:|---:|---:|
| NYC | 52 | **52** | 26 | 102 / $475.150 | **105 / $478.900** |
| Chicago | 0 | **0** | 0 | 0 | **0** |
| Dallas | **2** | **6.855** | **6.789** | 0 | **0** |
| Boston | 335 | **393** | 334 | 0 | **0** |

- **Dallas:** o “2” era a interseção “prazo ≤7d **e** entrada ≤7d”. Os 6.789 vencidos já não desaparecem; o cartão mostra “6.789 já vencidos”.
- **NYC:** a diferença 102→105 é a janela de 7 dias de entrada; o risco aberto total é 105/$478.900. Por separador: Preventivos 7, Reativos 98, Todos 105.
- **Chicago/Dallas/Boston:** continuam 0 porque a fonte ingerida **não tem** multa; o correto é mostrar “sem dados”/`—` (P1), não `$0`.

### 3.1 Preenchimento real (não mudou — é limite de fonte)

| Cidade | Tipo | Prazo | Multa | Valor obra |
|---|---|---:|---:|---:|
| Chicago | legal_obligation | 0/561 | 0/561 | 1/561 |
| Dallas | open_request | 6.910/6.910 | 0/6.910 | 0/6.910 |
| Dallas | authorized_work | 2/898 | 0/898 | 0/898 |
| Boston | open_request | 393/955 | 0/955 | 3/955 |
| Boston | authorized_work | 0/590 | 0/590 | 587/590 |
| NYC | open_request | 0/437 | 7/437 | 24/437 |
| NYC | legal_obligation | 52/150 | 98/150 | 38/150 |

**Severidade, categoria e ZIP continuam 100% preenchidos.** O P0 não inventa prazos/multas; passa a mostrá-los no separador e na janela corretos.

---

## 4. Antes/depois — Mapa “Onde está o trabalho”

| Cidade | Antes (30d, tudo preventive) | Depois (7d, separador ativo) |
|---|---:|---:|
| NYC | 587 | **319** (Preventivos) / 469 (Todos) |
| Chicago | 166 | **0** (Preventivos) / 96 (Reativos) |
| Dallas | 1.081 | **41** (Preventivos) / 504 (Obras) |
| Boston | 1.015 | **336** (Preventivos) / 212 (Obras) |

O mapa passou a seguir o **mesmo `kind` e a mesma janela** do feed/KPI. O cabeçalho diz “Oportunidades · 7 dias”.

---

## 5. Comportamento por ecrã (novo)

- **Pré-inspeção:** as quatro abas filtram o feed de oportunidades; o contador, a lista, o mapa e o KPI falam do mesmo `kind`/janela.
- **Oportunidades (leads):** as quatro abas filtram o feed de leads; “Reativos” = `legal_obligation`, “Preventivos” = `open_request`, “Obras” = `authorized_work`; o mapa usa o mesmo `layer`.
- **Seletor de cidade:** contagens de **leads 7d**, agora explícitas. Para ver oportunidades por cidade, usa-se o seletor + a aba/Prevenção.

---

## 6. Testes

- `tests/test_p0_dashboard_metrics.py` (novo): 6 passed
  - classificação por sinal;
  - prazos/multas antigos continuam no risco;
  - filtro de prazo não esconde multas;
  - `territories(kind="all")`;
  - `count_leads_by_signal`;
  - backfill em DB temporária.
- Suíte dirigida: **55 passed** (oportunidades, phase1, Chicago, leads, dashboard summary, P0-B, quota/concurrency).
- `ruff` limpo; `tsc` limpo; `npm run lint` 0 erros.
- **Suíte completa: 1784 passed, 1 skipped, 0 failed** (393 s) — `reports/pytest-p0-dashboard-final-2026-11-20.log`.

---

## 7. O que ainda não está feito (P1, por aprovação)

1. **Backfill em produção** — script testado, dry-run por defeito; não executado.
2. **Multas de Chicago/Dallas/Boston** — ingerir datasets de audiências/code compliance; até lá, `—` em vez de `$0`.
3. **Prazos de Chicago/Boston** — fonte não tem prazo; rotular; Boston usar data da violação, não `status_dttm`.
4. **Geo** — centroides por ZIP (Census ZCTA) e contagem de “sem geo”.
5. **Contagem do seletor por oportunidades** — se o produto quiser o mesmo universo da Pré-inspeção; hoje está rotulado como leads.

**Confirmação:** `VOICE_FREEZE=1` e `feat/br-environmental-mvp` intactos; nenhum deploy ou alteração em produção.
