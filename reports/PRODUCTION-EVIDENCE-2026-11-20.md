# Evidências de produção e fontes — Pré-inspeção (read-only)

**Data:** 2026-11-20 · **Modo:** leitura. Nenhum `--apply`, nenhum deploy, nenhuma escrita em produção.
**HEAD local:** `73ad46d` · **Working tree:** P0 não commitado (não está em produção).

---

## 1. O que está realmente rodando

### 1.1 Backend (Railway)

Runtime do serviço `magic-leads`, ambiente `production`:

```
RAILWAY_GIT_BRANCH=master
RAILWAY_GIT_COMMIT_SHA=73ad46daa3fe27a27e34848971dae21aae730b80
RAILWAY_GIT_COMMIT_MESSAGE=fix(chicago): backfill ZIPs from violation history coordinates
```

### 1.2 Frontend (Vercel)

Projeto de produção: `magic-leads-frontend-final` → `https://www.magicleads.app`.

| Deployment | Criado (UTC) | SHA | Branch |
|---|---|---|---|
| `magic-leads-frontend-final-quxbcu57j` (atual) | 2026-11-20 13:34:05 | `73ad46daa3fe27a27e34848971dae21aae730b80` | master |
| `magic-leads-frontend-final-k1iuk1std` | 2026-11-20 03:33:19 | `029444809d84a7ba5d39f9a487892bc8193a4fb3` | master |
| `magic-leads-frontend-final-qn43tbkth` | 2026-11-18 16:08:48 | `172dee6aac2d6fedb4bcd901dc3a26c60bdb16ed` | master |

### 1.3 Comparação

| Ambiente | SHA |
|---|---|
| Railway produção | `73ad46d` |
| Vercel produção | `73ad46d` |
| `master` local | `73ad46d` |
| Working tree local | `73ad46d` + alterações P0 não commitadas |

**Conclusão:** produção e `master` estão sincronizados em `73ad46d`. O P0 (classificação por `signal_type`, janelas separadas, contagens unificadas, mapa 7d) **não está em produção**.

**Prova temporal do “antes”:** até 2026-11-20 03:33, a produção era `172dee6` (18/11) — **antes** do commit `0294448` que passou o KPI a filtrar por cidade. A partir de 03:33, `0294448`. Isto confirma que os valores “que pareciam presentes” antes eram os do KPI global.

---

## 2. Histórico completo (all branches, tags, stashes)

- **Tags:** nenhuma.
- **Stashes:** apenas `data/leads.db` (binário). Não há código de Pré-inspeção escondido em stash.
- **Branches relevantes:** `fix/dashboard-preinspection` (`0294448`, em master), `feat/preventive-boston-dallas` (`d103aac`), `feat/territory-view-preview` (`7b2a0fd`), `release/phase1-production` (`8047f25`), `staging/opportunity-foundation`, `feat/preview-kpi-proposal` (`764e64e`).

### 2.1 Protótipos anteriores a 13/11

| Data | Commit | O que era |
|---|---|---|
| 2026-11-09 | `3b37e23` | `OpportunityCard` + drawer. É um cartão de **leads** (owner, telefone, data); **não** tem prazo/multa de oportunidade. |
| 2026-11-11 | `764e64e` | Proposta de KPI “active-scope” com **snapshot estático 12/11/2026 03:05Z**; mostra oportunidades ativas, owners, urgentes e cobertura. **Não** tem prazos/multas. Apagou o `preview/dashboard` antigo. |
| 2026-11-13 | `49419e5` | Primeiro `opportunity_workflow.py` (schema e ciclo). |
| 2026-11-13 | `b8d7a19` | Primeiro `phase1_enrichment.py` com **prazos/multas reais** (NYC HPD/ECB; Chicago violations sem prazo/multa). |
| 2026-11-13 | `4123700` | Fila 7d; `window_days` passou a filtrar prazos/multas. |
| 2026-11-13 | `fc408e6` | Barra de abas unificada (leads + página + oportunidades). |
| 2026-11-13 | `8047f25` | Release de produção. |

**Conclusão:** **não existiu** uma versão anterior a 13/11 com prazos/multas de oportunidade “a funcionar de outra forma” que tenha sido perdida. Os protótipos de 09/11 e 11/11 eram leads/KPI estático. A camada de oportunidades só nasceu em 13/11 — já com `source_kind="preventive"` para tudo e com a janela de 7d aplicada a prazos/multas.

---

## 3. Prova bruta das fontes

### 3.1 Campos reais devolvidos pelas APIs

| Fonte | Keys | Campos de prazo/multa encontrados | Amostra |
|---|---:|---|---|
| Chicago `22u3-xenr` Building Violations | 30 | **nenhum** (`violation_date`, `violation_status`, `inspection_status` apenas) | `violation_date=2026-08-24`, `status=OPEN` |
| Chicago `6br9-quuz` Ordinance Violations | 27 | **`imposed_fine`**, **`hearing_date`**, `violation_date`, `case_disposition` | `imposed_fine=1000`, `hearing_date=2022-03-02` |
| Chicago `kc9i-wq85` Vacant/Abandoned | 25 | **`total_fines`**, **`current_amount_due`**, `original_total_amount_due`, `last_hearing_date` | `total_fines=0`, `current_amount_due=0` |
| Chicago `ydr8-5enu` Permits | 53 | `reported_cost` (valor de obra) + taxas (`building_fee_*`) | `reported_cost=500` |
| Dallas `d7e7-envw` 311 | 16 | **`overall_service_request_due_date`** (prazo); sem multa | `due=2024-03-18T17:59` |
| Dallas `e7gq-4sah` Permits | 10 | `value` (valor de obra); sem multa | `value=2796` |
| Dallas `x9pz-kdq9` Code Violations | 16 | **nenhum** | `type=Nuisance` |
| Dallas `xrzj-c8ez` Code Violations | 20 | `civil_cite`, `lien` (flags), sem valor de multa | `lien=0`, `civil_cite=0` |
| Boston `800a2663` Building Violations | 25 | `value` = **"N/A" em 1000/1000**; sem prazo (`status_dttm` é mudança de estado) | `value=N/A` |
| Boston `254adca6` 311 | 29 | **`target_close_date`** (prazo); sem multa | `target_close_date` |
| Boston `6ddcd912` Permits | 25 | `declared_valuation` (valor de obra), `total_fees` (taxas); sem multa | `declared_valuation` |
| Boston `90ed3816` **Code Enforcement Violations** | 24 | **`value` = multa real** (25, 100, 50, 15, 250…; 200/200 não-N/A) | `value=25`, `code=1` |

### 3.2 O que isto prova

- **Chicago:** o dataset ingerido (`22u3-xenr`) **não tem** prazo nem multa. Mas a cidade tem **Ordinance Violations** (`6br9-quuz`, `imposed_fine`) e **Vacant/Abandoned** (`kc9i-wq85`, `total_fines`/`current_amount_due`) — **nunca ingeridos**. O zero de Chicago não é “a fonte não tem”; é “ingerimos a fonte errada”.
- **Boston:** o dataset ingerido (`800a2663`) tem `value` sempre **"N/A"**. Mas **Code Enforcement Violations** (`90ed3816`) tem `value` com multas reais (25/100/50…). O zero de Boston também é **dataset errado**, não ausência de fonte.
- **Dallas:** o 311 tem prazo (`overall_service_request_due_date`), mas não multa. Os datasets de “Code Violations” amostrados têm `civil_cite`/`lien` mas **nenhum valor de multa**. Para Dallas, a multa continua sem fonte identificada; o prazo existe e foi mapeado.
- **Chicago prazo:** não há “compliance deadline” no `22u3-xenr`. O `6br9-quuz` tem `hearing_date` (audiência), que **não é** prazo de correção. Não mapear como `compliance_deadline` sem decisão de produto.

### 3.3 O que está guardado na BD

| Campo | Resultado |
|---|---|
| `opportunity_workflow.source_payload` | **0/10.501** linhas com conteúdo (vazio em NYC, Chicago, Dallas, Boston) |
| `history_json` | apenas entradas normalizadas (`kind`, `label`, `date`, `status`, `id`) — ex.: `chi-violation-7568280` |
| `property_json` | vazio nos samples de Chicago/Dallas/Boston |
| `metadata` | **não existe** como coluna |

**Conclusão:** a ingestão **não guarda o payload bruto** da fonte. A BD não permite provar quais campos foram ignorados; a única prova possível é a leitura direta das APIs — que foi feita acima. Isto é, por si, um P1 de auditabilidade: guardar o payload bruto (ou pelo menos os campos não mapeados) no `source_payload`.

---

## 4. Efeito na verdade do produto

1. **“Prazos/multas zerados” não é um único bug.** É:
   - KPI global até 19/11 (`0294448` passou a filtrar por cidade);
   - janela de 7d aplicada a prazos/multas desde 13/11 (`4123700`);
   - dataset de multa errado/não ingerido em Chicago e Boston;
   - Dallas sem dataset de multa com valor identificado.
2. **Os valores que pareciam funcionar** eram o KPI global (NYC) e/ou a janela antiga (antes de `4123700` no staging). Não havia uma versão perdida com dados locais corretos.
3. **A correção P1 de maior impacto é de fonte, não de UI:** ingerir `6br9-quuz`/`kc9i-wq85` (Chicago) e `90ed3816` (Boston) e mapear `imposed_fine`/`total_fines`/`value` para `fine_imposed`/`fine_paid`. Para Dallas, localizar o dataset de multas/court; até lá, `—`.

---

## 5. Segurança

- Nenhum `--apply`; nenhum deploy; nenhuma escrita em produção.
- `VOICE_FREEZE=1` e `feat/br-environmental-mvp` intactos.
- Provas: `reports/source-fields-scan.json`, `reports/raw-payload-audit*.json`, `reports/HISTORY-AUDIT-PREINSPECTION-2026-11-20.md`.
