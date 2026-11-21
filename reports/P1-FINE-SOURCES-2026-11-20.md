# P1 — fontes de multa, Chicago 311, auditabilidade e filtros

**Data:** 2026-11-20 · **Estado:** P1 + P1.1 implementados e testados localmente; **dry-run de produção feito (read-only, 2.199 linhas)**; **sem `--apply`, sem deploy, produção em `73ad46d`**.
`VOICE_FREEZE=1` e `feat/br-environmental-mvp` intactos.

---

## 1. Fontes novas

| Cidade | Fonte | Dataset | Campo de multa | Uso |
|---|---|---|---|---|
| Chicago | Ordinance Violations | `6br9-quuz` | `imposed_fine` | `fine_imposed` + `fine_balance`; `hearing_date` separado |
| Chicago | Vacant/Abandoned | `kc9i-wq85` | `total_fines`, `current_amount_due`, `total_paid` | `fine_imposed`, `fine_balance` (due ≥ 0), `fine_paid` |
| Chicago | 311 aberto | `v6vf-nfxy` | — | `open_request` / pre-inspeção |
| Boston | Code Enforcement Violations | `90ed3816-...` | `value` | `fine_imposed` + `fine_balance` |
| Dallas | — | — | — | `—` / “sem dados de multa” |

**`hearing_date` nunca é `compliance_deadline`.** As multas de Chicago/Boston ficam com `compliance_deadline=None`; a audiência vai para `hearing_date`.

### 1.1 Amostra read-only das fontes (sem escrever na BD)

| Fonte | Itens | Tipo | Multa imposta | Saldo | Com payload | Com hearing | Com deadline |
|---|---:|---|---:|---:|---:|---:|---:|
| Chicago 311 (30d, limite 300) | **77** | open_request | $0 | $0 | 77 | 0 | 0 |
| Chicago multas (limite 500, **após P1.1**) | **205** | legal_obligation | **$832.700** | **$613.719,65** | 205 | 205 | 0 |
| Boston code enforcement (limite 300, **após P1.1**) | **253** | legal_obligation | **$20.895** | **$20.895** | 253 | 0 | 0 |

> **Nota:** Chicago soma `6br9-quuz` + `kc9i-wq85`. Antes da dedupe: $1.193.200 / $974.219,65 em Chicago e $23.245 em Boston. Depois da dedupe P1.1: **$832.700 / $613.719,65** e **$20.895**.

---

## 1.2 P1.1 — dedupe de multas

Regra: uma multa conta **uma vez por imóvel e por chave de notificação**.

| Dataset | Chave de dedupe | Efeito |
|---|---|---|
| `6br9-quuz` | `nov_number` (fallback `id`) | Várias linhas com o mesmo NOV (vários `violation_code`) deixam de somar em duplicado |
| `kc9i-wq85` | `violation_number` → `docket_number` → `id` | Idem para o mesmo processo |
| `90ed3816` (Boston) | `case_no` → `ticket_no` | Uma linha por caso |

- **Conservador onde não há pagamento:** `6br9-quuz` não tem estado de pagamento → `fine_balance = imposed_fine`. Não se inventa `paid`.
- **`kc9i-wq85`:** `fine_balance = max(0, current_amount_due)`, `fine_paid = total_paid` (o `current_amount_due` negativo observado, `-140`, fica em 0).
- **Sem chave natural:** a linha é mantida (nunca se descarta uma multa por falta de identificador).
- **Diferença medida:** Chicago **−$360.500** de multa imposta e **−$360.500** de saldo; Boston **−$2.350**. Nenhum imóvel desapareceu (205 e 253 mantêm-se) — só a soma duplicada.

---

## 2. Antes/depois projetado (4 cidades)

| Cidade | Antes (produção) | Depois (com as novas fontes) |
|---|---|---|
| **NYC** | 469 preventivos 7d; 52 prazos; 105 multas / $478.900 | Sem alteração; multas no separador Reativos/Todos |
| **Chicago** | 96 (7d) **reativos**, 0 preventivos; 0 prazos; 0 multas | +77 preventivos (311, 30d); +205 reativos com multa; **$613.719,65 de saldo** (após dedupe); prazos continuam 0 (311 não tem due date) |
| **Boston** | 548 (7d); 393 prazos; 0 multas | +253 reativos com multa; **$20.895** (após dedupe); prazos inalterados |
| **Dallas** | 545 (7d); 2 prazos na janela (6.855 no total); 0 multas | Sem fonte de multa; **`—` / “sem dados”**; prazos inalterados |

**Onde as multas aparecem:** no separador **Reativos** (e em **Todos**), não no **Preventivos**. O KPI segue o separador ativo; o 311 de Chicago alimenta o **Preventivos**.

### 2.1 Dry-run do backfill `source_kind` (produção, read-only)

Executado contra `/data/leads.db` do contentor de produção, com conexão **`mode=ro`** (sem `--apply`):

| Cidade | `signal_type` | → `source_kind` / `source_type` | Linhas |
|---|---|---|---:|
| Chicago | `legal_obligation` | reactive / violation | **561** |
| NYC | `legal_obligation` | reactive / violation | **150** |
| Boston | `authorized_work` | permit / permit | **590** |
| Dallas | `authorized_work` | permit / permit | **898** |
| | | **TOTAL** | **2.199** |

Estado de produção antes: `open_request` 8.302 (preventive), `authorized_work` 1.488 (preventive), `legal_obligation` 711 (preventive).
Depois projetado: **preventive 8.302**, **reactive 711** (Chicago 561 + NYC 150), **permit 1.488** (Boston 590 + Dallas 898). Preventivos sem alterações.
Ficheiro: `reports/backfill-source-kind-dryrun-2026-11-20.txt`.

---

## 3. `source_payload` e auditabilidade

- **Novas oportunidades:** 100% com `source_payload` (lista de `{source, row}`), incluindo as linhas brutas de Chicago 311, Chicago fines e Boston code enforcement.
- **Fontes antigas:** HPD, ECB, Chicago violations, Boston violations/311, Dallas 311/permits também passam a anexar o payload nas próximas execuções.
- **Linhas antigas:** continuam com `source_payload` vazio até serem reingeridas; o P1 não faz backfill de payload.
- **API:** `_public` remove `source_payload` das respostas ao cliente (invariante de privacidade); fica só na BD para auditoria.
- **Teste:** `test_source_payload_is_persisted_in_db` confirma a gravação.

---

## 4. UI: honestidade e filtros

- **Dallas / sem fonte:** KPI “Multas em risco” mostra **`—`** (`noData`), delta “sem dados de multa”; o drawer mostra “sem dados de multa nesta cidade”; o toggle **Com multa** fica **desativado** com tooltip.
- **Chicago/Boston:** `fines_available=true`; quando o separador é Preventivos e não há multa preventiva, o valor é `$0` (verdade do subconjunto); em Reativos/Todos mostra o valor real.
- **LIMPAR:** passa a limpar `selectedCity`, `category`, `severity`, `ownerType`, `type`, `includeClosed`, `onlyDeadline`, `deadlineWindow`, `withFines`, `search`, `leadZone`, **`neighborhoodFilter`**, **`feedLayer`**, **`readiness`** e **`opportunityKind`**.
- **Mapa:** recebe `severity`, `deadline_within`, `with_fines` e `search`; janela **7d** alinhada com feed/KPI. O mapa de leads mantém o mesmo `WHERE` do feed.
- **Janelas:** `received_at` só para “novas”; `compliance_deadline` para prazos; `fine_*` para multas (P0).

---

## 5. Testes

- `tests/test_p1_fine_sources.py` (novo): 8 passed
  - Chicago 311 → open_request + payload;
  - Chicago fines → imposed/balance/hearing, sem deadline;
  - **Chicago dedupe**: mesmo `nov_number` em duas linhas conta uma vez;
  - Boston code → `value` → fine;
  - **Boston dedupe**: mesmo `case_no` conta uma vez;
  - `fines_available` por cidade;
  - `territories` com severity/fines/deadline;
  - `source_payload` persistido.
- Suíte dirigida (phase1, Chicago, territories, P0, P1): **43 passed**.
- `ruff` limpo; `tsc` limpo; `npm run lint` 0 erros.
- **Suíte completa: 1792 passed, 1 skipped, 0 failed** (360 s) — `reports/pytest-p1-dedup-final-2026-11-20.log`.
- Nota: o flake de `showcase_checkouts` era isolamento de schema entre testes; corrigido no `tests/conftest.py` (reset do `_INIT` do showcase).
- **Backfill:** `backend/scripts/backfill_source_kind.py` é autónomo (não importa o backend novo), abre a BD em `mode=ro` no dry-run e agrupa por cidade/tipo; sem a coluna `city` usa `(null)`.

---

## 6. Segurança

- **Sem `--apply`** em produção; **sem deploy**; produção continua em `73ad46d`.
- Nenhuma escrita na base de produção.
- `VOICE_FREEZE=1` e `feat/br-environmental-mvp` intactos.
