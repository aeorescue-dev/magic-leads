# Auditoria NYC — 16 nichos

**Data:** 2026-11-05  
**Snapshot:** 17:00 UTC / 12:00 ET  
**Âmbito:** NYC (`city='NYC'`, `state='NY'`)  
**Objetivo:** inventário real por nicho do dropdown, telefones acionáveis, oportunidades e chamadas elegíveis sob a guardrail de showcase exato.

---

## 1. Método

Fontes lidas em modo read-only:

| Fonte | Uso |
|---|---|
| `/data/leads.db` → `leads` | oportunidades por `issue_category` |
| `/data/voice.db` → `prospect_companies`, `dnc_checks`, `voice_suppressions`, `voice_calls` | empresas, telefones, elegibilidade e chamadas recentes |
| `/data/showcase.db` → `market_inventory` | inventário exato por cidade/nicho |
| `voice_scripts.showcase_guard()` | gate real de disparo: nicho exato, mínimo 5 itens, inventário ≤72 h |

Regras aplicadas:

- Oportunidade = `signal_status='open'`, `signal_type IN ('open_request','authorized_work')`, `is_junk=0`.
- Janela principal = 30 dias; coluna separada para 72 h.
- Elegível = passa em `b2b_voice._eligibility()` **e** o trade tem showcase exato com ≥5 itens.
- **Não há fallback city-wide para voz.** `general_contractor` e `signage` têm 0 itens exatos e são bloqueados pelo `showcase_guard`, mesmo que `include_fallback=1`.

---

## 2. Mapeamento label do dropdown → categoria → trade

Os labels do dropdown são os 16 interesses canónicos (`frontend/lib/categories.ts`). O motor de voz usa um vocabulário menor de trades (`showcase.TRADE_MAP`).

| # | Label no dropdown | Categoria canónica | Trade(s) de voz | Nota |
|---:|---|---|---|---|
| 1 | Roofing & Structure | `Roof` | `roofing` | — |
| 2 | Structure | `Structure` | `remodeling`, `general_contractor` | Só `remodeling` tem showcase exato; `general_contractor` é bloqueado |
| 3 | Plumbing | `Plumbing` | `plumbing` | — |
| 4 | Grass & Debris / “Yard & Debris” | `Grass` | `landscaping` | `Debris` é o nicho 16, separado |
| 5 | Painting | `Paint` | `painting` | Partilha trade com `Lead` |
| 6 | Construction & Permits / “Jobs & Permits” | `Permit_Rejected` | — | **Sem trade mapping**; 760 leads não entram na vitrine |
| 7 | Heating & Hot Water | `Heating` | `hvac` | Partilha trade com `Gas` |
| 8 | Electrical | `Electrical` | `electrical` | — |
| 9 | Elevators | `Elevator` | `elevator` | Sem empresas na base de voz |
| 10 | Gas & Leaks | `Gas` | `hvac` | Sem showcase específico de gás; usa o de HVAC |
| 11 | Rodents & Pests | `Rodent` | `pest_control` | Sem empresas na base de voz |
| 12 | Mold & Moisture | `Mold` | `remediation` | — |
| 13 | Lead & Paint | `Lead` | `painting` | Sem showcase específico de lead; usa o de Painting |
| 14 | Unsanitary & Sewage / “Unsanitary & Sewer” | `Unsanitary` | `cleaning` | — |
| 15 | Doors & Windows | `Door_Window` | `windows` | — |
| 16 | Debris & Trash | `Debris` | `debris_removal` | Sem empresas na base de voz |

Aliases legados ainda presentes em `leads.issue_category` (todos fechados, 37 linhas): `General Contractors` (21), `Heating & HVAC` (9), `Restoration & Cleanup` (4), `Remodeling & Renovation` (2), `Landscaping & Grounds` (1).

---

## 3. Tabela de inventário

Valores únicos por cidade. Onde dois nichos partilham o mesmo trade, a coluna de empresas repete o pool e está marcada com “mesmo pool”; o total único está no fim.

| # | Nicho | Categoria | Trade(s) | Oport. total | Oport. 30 d | Oport. 72 h | Empresas | Telefone válido | Chamáveis | Elegíveis c/ showcase exato | Itens no showcase exato |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | Roofing & Structure | Roof | roofing | 1.463 | 60 | 9 | 82 | 82 | 82 | 82 | 45 |
| 2 | Structure | Structure | remodeling + general_contractor | 11.196 | 95 | 0 | 7.480 | 7.480 | 7.480 | **2.630** | 107 (só remodeling) |
| 3 | Plumbing | Plumbing | plumbing | 8.386 | 3.366 | 428 | 9 | 9 | 9 | 9 | 3.050 |
| 4 | Grass & Debris | Grass | landscaping | 1.801 | 635 | 52 | 68 | 68 | 68 | 68 | 635 |
| 5 | Painting | Paint | painting | 3.100 | 1.036 | 80 | 172 | 172 | 172 | 172 | 1.460 |
| 6 | Construction & Permits | Permit_Rejected | — | 760 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 7 | Heating & Hot Water | Heating | hvac | 5.152 | 2.867 | 404 | 118 | 118 | 117 | 117 | 2.676 |
| 8 | Electrical | Electrical | electrical | 1.426 | 392 | 50 | 33 | 33 | 33 | 33 | 398 |
| 9 | Elevators | Elevator | elevator | 4.948 | 349 | 45 | 0 | 0 | 0 | 0 | 330 |
| 10 | Gas & Leaks | Gas | hvac | 597 | 0 | 0 | 118 (mesmo pool) | 118 | 117 | 117* | 0 específico |
| 11 | Rodents & Pests | Rodent | pest_control | 4.488 | 1.109 | 119 | 0 | 0 | 0 | 0 | 1.017 |
| 12 | Mold & Moisture | Mold | remediation | 586 | 17 | 2 | 205 | 205 | 205 | 205 | 15 |
| 13 | Lead & Paint | Lead | painting | 986 | 370 | 0 | 172 (mesmo pool) | 172 | 172 | 172* | 1.460 (Paint) |
| 14 | Unsanitary & Sewage | Unsanitary | cleaning | 2.921 | 1.811 | 266 | 34 | 34 | 34 | 34 | 1.672 |
| 15 | Doors & Windows | Door_Window | windows | 4.362 | 615 | 66 | 87 | 87 | 87 | 87 | 624 |
| 16 | Debris & Trash | Debris | debris_removal | 1.710 | 1.052 | 200 | 0 | 0 | 0 | 0 | 777 |

`*` O guard passa porque o trade é partilhado (HVAC/Painting), mas a linha falada não é específica de gás/lead. Não é atribuição semântica correta.

### Totais únicos

| Métrica | Valor |
|---|---:|
| Oportunidades canónicas (todas) | 53.882 |
| Aliases legados (fechados) | 37 |
| Oportunidades totais NYC | **53.919** |
| Oportunidades com showcase (30 d) | **13.774** |
| Oportunidades com showcase (72 h) | **1.721** |
| Empresas NYC | **8.534** |
| Telefone E.164 válido | **8.534 (100%)** |
| Chamáveis (DNC/supressão/estado) | **8.533** |
| Elegíveis com showcase exato | **3.437 (40,3%)** |
| Chamáveis mas bloqueados pelo guard | **5.096** (4.850 GC + 246 signage) |
| Bloqueio individual | 1: Radant Plumbing & Heating (`do_not_call` + suprimido) |
| Chamadas telnyx nos últimos 7 d | **83** (48 remodeling + 35 hvac) |
| Elegíveis imediatos hoje | **3.354** (3.437 − 83) |

> **Correção importante:** o levantamento anterior dizia “0 leads NYC <72 h”. Está errado. A consulta correta devolve **1.721 oportunidades com showcase em 72 h**, incluindo 428 de Plumbing, 404 de Heating e 266 de Unsanitary. A janela de 30 dias não é necessária para NYC.

---

## 4. Leitura por nicho

### 4.1 Prontos para disparo imediato

| Ordem | Nicho | Elegíveis agora | Porquê |
|---:|---|---:|---|
| 1 | Structure (remodeling) | 2.582 | 2.630 − 48 chamadas nos últimos 7 d |
| 2 | Mold & Moisture | 205 | inventário exato 15, acima do mínimo 5 |
| 3 | Painting | 172 | inventário exato 1.460 |
| 4 | Heating & Hot Water | 82 | 117 − 35 chamadas nos últimos 7 d |
| 5 | Doors & Windows | 87 | inventário exato 624 |
| 6 | Roofing & Structure | 82 | inventário exato 45 |
| 7 | Grass & Debris | 68 | inventário exato 635 |
| 8 | Unsanitary & Sewage | 34 | inventário exato 1.672 |
| 9 | Electrical | 33 | inventário exato 398 |
| 10 | Plumbing | 9 | inventário exato 3.050 |

### 4.2 Subaproveitados (procura muito acima da oferta de empresas)

| Nicho | Oport. 30 d | Empresas | Oportunidades por empresa |
|---|---:|---:|---:|
| Plumbing | 3.366 | 9 | **374×** |
| Unsanitary & Sewage | 1.811 | 34 | **53×** |
| Heating & Hot Water | 2.867 | 117 | **25×** |
| Electrical | 392 | 33 | **12×** |
| Grass & Debris | 635 | 68 | **9×** |
| Doors & Windows | 615 | 87 | **7×** |
| Painting | 1.036 | 172 | **6×** |

### 4.3 Procura sem qualquer empresa na base de voz

| Nicho | Oport. 30 d | Oport. 72 h | Showcase exato disponível | Empresas |
|---|---:|---:|---:|---:|
| Rodents & Pests | 1.109 | 119 | 1.017 | **0** |
| Debris & Trash | 1.052 | 200 | 777 | **0** |
| Elevators | 349 | 45 | 330 | **0** |
| Construction & Permits | 0 | 0 | 0 | **0** |

`Construction & Permits` tem 760 leads no total, mas **0 entram na vitrine** porque `Permit_Rejected` não existe em `showcase.TRADE_MAP`. É uma lacuna de mapeamento, não de inventário.

### 4.4 Excesso de empresas sem showcase exato

| Nicho | Empresas | Elegíveis exatas | Bloqueadas |
|---|---:|---:|---:|
| Structure (`general_contractor`) | 4.850 | 0 | 4.850 |
| Signage (fora dos 16) | 246 | 0 | 246 |
| Structure (`remodeling`) | 2.630 | 2.630 | 0 |
| Mold & Moisture | 205 | 205 | 0 |

**4.850 general contractors = 56,8% de toda a base NYC** e são inúteis para a V3 enquanto o guard for estrito. O mesmo para 246 de signage.

### 4.5 Semântica partilhada

- `Gas & Leaks` e `Heating & Hot Water` usam o mesmo trade `hvac`. O guard fala “HVAC opportunities”, não “gas leaks”.
- `Lead & Paint` e `Painting` usam o mesmo trade `painting`. O guard fala “painting opportunities”, não “lead paint”.
- Isto não bloqueia chamadas, mas impede relatar conversão por categoria real. Para atribuição correta seria preciso separar `trade_code` por categoria, não só por trade.

---

## 5. Riscos operacionais identificados

1. **Inventário a expirar.** O `market_inventory` foi construído em `2026-11-02T21:29Z`. No snapshot tinha **67,5 h**; atinge 72 h às **21:29 UTC / 16:29 ET de hoje**. A partir daí o `showcase_guard` marca `stale_inventory` e bloqueia chamadas até o rebuild. O preflight da #6 (08:45 ET) tem de verificar `showcase_guard()` por trade e forçar rebuild se `fresh=false`.
2. **Guard estrito bloqueia 59,7% da base.** Não é falta de telefone; é falta de showcase exato. Importar mais GC não resolve.
3. **`Permit_Rejected` sem trade.** 760 leads ficam invisíveis para a vitrine e para voz.
4. **DNC nos novos contactos.** Qualquer import novo entra sem `dnc_checks` e fica `dnc_not_checked` até scrub. O scrub é obrigatório antes de qualquer chamada.
5. **#6 cabe no inventário atual.** Precisa de 8 HVAC + 25 remodeling + 8 painting + 4 roofing + 2 cleaning + 4 landscaping + 3 windows + 1 electrical + 1 plumbing + 4 remediation = 60. Há 3.354 elegíveis imediatos. Não é necessário adiar a #6 por falta de contactos.

---

## 6. Plano para nova rodada de enriquecimento

### 6.1 Diagnóstico

O problema **não é telefone**: 8.534/8.534 empresas têm E.164 válido. O problema é:

1. **Cobertura de empresas por nicho** — faltam empresas em pest, debris, elevator, plumbing, electrical.
2. **Classificação de trade** — 4.850 GC e 2.630 remodeling vieram de licenças DCWP “Home Improvement”, que não distinguem ofício. O `_infer_trade()` usa o nome e manda quase tudo para GC/remodeling.

### 6.2 Fontes públicas já identificadas

| Fonte | Dataset | Registos úteis | Telefone | Esforço |
|---|---|---|---:|---|
| NYC DOB License Info | `t8hj-ruu2` | MASTER PLUMBER 1.129; ELECTRICAL FIRM 950; ELEVATOR AGENCY 7; OIL BURNER 104; SIGN HANGER 42; GENERAL CONTRACTOR 9.037 | Sim | 2–3 dias |
| NYC DCWP Home Improvement | `w7w3-xahh` | 18.931 ativos; 13.383 já ingeridos | Sim | já existe |
| DSNY/BIC Trade Waste | `867j-5pgi` | 89 nomes/telefones únicos ativos em NYC | Sim | 1 dia |
| NYS DEC Pesticide Businesses | `h8u2-6ejg` | 442 empresas distintas em NYC | **Não** | 2–3 dias + enriquecimento |
| OSM / Brave | extracts + search | fallback para phone/website | Por confirmar | já existe, mas caro |

Notas de qualidade:

- O DOB tem registos de teste (`GOTHAM CITY`, `DOB TESTER`, `MAKE-BELEIVE ELEVATOR`). É obrigatório filtrar com `is_usable_company_name()` e rejeitar telefones placeholder.
- O DOB só tem 7 elevadores ativos com telefone; após filtro podem sobrar 3–5. Ainda assim é melhor que 0.
- O dataset de trade waste tem 712.782 linhas históricas; é preciso filtrar `expiration_date > hoje` e deduplicar por `bic_number`/telefone.
- O NYS DEC não traz telefone; sem OSM/Brave/website, não serve para voz. É a fonte mais fraca das quatro.

### 6.3 Sequência proposta

| Fase | Trabalho | Resultado esperado | Esforço |
|---|---|---|---|
| **E1** | Extractor DOB + `niche_key` explícito por `license_type` + bridge para `prospect_companies` | +1.129 plumbing, +950 electrical, +7 elevator, +104 HVAC, +42 signage (bruto, antes de dedupe/DNC) | 2–3 dias |
| **E2** | Extractor DSNY/BIC trade waste, ativo + telefone + dedupe | +89 debris removal (bruto) | 1 dia |
| **E3** | Reclassificar entidades DCWP existentes por join com DOB (nome/telefone/licença) | Converter parte dos 4.850 GC em plumbing/electrical/elevator sem importar novos números | 1–2 dias |
| **E4** | NYS DEC pest + enriquecimento de telefone via OSM/Brave | +442 seeds; telefone apenas nos que tiverem site/OSM | 2–3 dias |
| **E5** | DNC scrub, `rebuild_segments`, dry-run e warm-up 25/DID/dia | Contactos passam de `dnc_not_checked` a chamáveis | 1 dia |

**Total realista:** 5–7 dias úteis para E1+E2+E3+E5; +2–3 dias para pest. Pode correr em paralelo com o chat lab, num worktree separado, sem tocar no fluxo de voz.

### 6.4 Gates obrigatórios

1. Nenhum import novo é chamável sem `dnc_checks` fresco (31 dias).
2. `_eligibility()` tem de devolver `allowed=true` para uma amostra de cada trade.
3. `showcase_guard()` tem de devolver `ready=true` para cada trade importado.
4. Import limitado a 500 contactos/dia para não repetir o incidente de WAL/disco.
5. Dry-run de 10 chamadas por trade antes de campanha real.
6. Deploy apenas após 20:00 ET e fora de campanhas ativas.
7. `pytest`, `ruff` e `tsc` verdes; migração idempotente.

### 6.5 Impacto esperado

Se metade dos registos DOB sobreviver a dedupe + DNC + filtro de qualidade:

| Nicho | Hoje | Potencial | Ganho |
|---|---:|---:|---:|
| Plumbing | 9 | ~570 | ~63× |
| Electrical | 33 | ~500 | ~15× |
| Elevators | 0 | ~3–5 | ∞ |
| Heating & Hot Water | 117 | ~170 | +45% |
| Debris & Trash | 0 | ~45–89 | ∞ |
| Rodents & Pests | 0 | ~50–200 | ∞ (se houver telefone) |

O gargalo deixa de ser a base e passa a ser o ritmo seguro por DID.

---

## 7. Recomendação operacional

1. **Não alterar #6–#11 por causa desta auditoria.** A #6 cabe folgadamente nos 3.354 elegíveis.
2. **Não comprar mais DIDs nem aumentar volume** antes de resolver a cobertura de empresas nos nichos com 0.
3. **Prioridade de enriquecimento:** Plumbing → Electrical → Debris → Elevators → Pest. Cleaning não tem fonte pública de licença; fica para OSM/Brave.
4. **Não importar GENERAL CONTRACTOR em massa.** São 9.037 no DOB e continuam bloqueados pelo guard. Só entram depois de reclassificados para um trade com showcase exato.
5. **Corrigir o mapeamento `Permit_Rejected`** numa fase separada: ou mapeia para `remodeling`/`general_contractor` com um guard próprio, ou continua fora da vitrine. Não misturar com este import.
6. **Preflight #6:** confirmar `showcase_guard()` fresco, DNC, 60 candidatos e distribuição do `trade_plan` antes das 09:00 ET.

---

## 8. Reprodução

Consultas principais:

```sql
-- Oportunidades NYC por categoria (leads.db)
SELECT issue_category, COUNT(*) total, ...
FROM leads
WHERE city='NYC' AND state='NY'
  AND signal_status='open'
  AND signal_type IN ('open_request','authorized_work')
  AND is_junk=0
GROUP BY issue_category;

-- Empresas e telefone (voice.db)
SELECT trade, COUNT(*), ...
FROM prospect_companies
WHERE city='New York' AND state='NY'
GROUP BY trade;

-- Elegibilidade real
-- python -c "from backend.services import b2b_voice as v; ... v._eligibility(...)"

-- Guard de showcase
-- python -c "from backend.services import voice_scripts as v; print(v.showcase_guard('plumbing','New York'))"
```

Este documento é um snapshot. Antes de decidir campanhas, repetir a consulta e confirmar `built_at` do `market_inventory`.
