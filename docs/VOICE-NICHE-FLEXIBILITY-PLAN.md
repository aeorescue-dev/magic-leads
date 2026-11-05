# Plano técnico — flexibilização de nichos da voz (pós-P0)

**Data:** 2026-11-05  
**Âmbito:** campanhas #7–#11, classificação de empresas, guardrail de showcase e distribuição por nicho.  
**Pré-requisito:** P0 de 05/11 às 20:00 ET concluído. Nenhuma alteração antes disso.

---

## 1. Diagnóstico

### 1.1 O que realmente aconteceu na #5

A #5 não ficou em dois nichos por causa do `showcase_guard`. Ficou em **25 HVAC + 25 Remodeling** por um bug do auto-dialer: o primeiro trade do `trade_plan` consumia o lote inteiro. O bug está corrigido no commit `732356b` (worktree `p0-hotfixes`).

A #6 já tem um plano de **10 nichos**:

```text
hvac 8 · remodeling 25 · painting 8 · roofing 4 · cleaning 2
landscaping 4 · windows 3 · electrical 1 · plumbing 1 · remediation 4
```

Portanto, a diversificação já começou. O que falta é **profundidade** em cada nicho e **classificação correta** das empresas.

### 1.2 O guard não é o único bloqueio

O `showcase_guard` é estrito de propósito: só fala uma contagem de um trade se existirem pelo menos 5 itens exatos e o inventário tiver ≤72 h. Isto evita prometer “45 roofing opportunities” quando existem 0.

O problema real é a montante:

| Facto medido | Valor |
|---|---:|
| Empresas NYC | 8.534 |
| `general_contractor` + `remodeling` | 7.480 |
| Com telefone válido | 8.534 (100%) |
| Com nome que revela ofício | **126 / 7.480 (1,7%)** |
| Sem qualquer sinal de ofício no nome | **7.354 / 7.480 (98,3%)** |
| Elegíveis com showcase exato | 3.437 (40,3%) |

**Conclusão:** ampliar sinónimos no nome resolve, no máximo, ~126 empresas. Os 4.850 GC são um “saco” de classificação, não um nicho. Para os destravar é preciso **cruzar licenças, permits, websites e OSM**, não apenas alargar a lista de palavras.

### 1.3 Nichos que nenhum sinónimo resolve

| Nicho | Oportunidades 30 d | Empresas na base |
|---|---:|---:|
| Elevators | 349 | 0 |
| Rodents & Pests | 1.109 | 0 |
| Debris & Trash | 1.052 | 0 |
| Construction & Permits | 0 (760 sem mapeamento) | 0 |

Sem enriquecimento de empresas, estes nichos continuam a 0 chamadas. Nenhuma alteração de sinónimos cria empresas.

---

## 2. Arquitetura proposta

### 2.1 Taxonomia expandida

Novo módulo puro `backend/services/voice_taxonomy.py`:

- 16 categorias canónicas ↔ trades de voz.
- Aliases de mercado:
  - `plumbing`: plumber, plumbing & heating, sewer, drain, rooter.
  - `electrical`: electrician, electrical contracting, lighting.
  - `hvac`: heating, HVAC/R, mechanical, boiler, oil burner, air conditioning.
  - `roofing`: roofer, roofing & waterproofing, shingle.
  - `painting`: painter, painting & plastering.
  - `windows`: window & door, glazing, glass, storefront.
  - `landscaping`: landscaping & grounds, lawn, garden, tree service.
  - `cleaning`: janitorial, maid, commercial cleaning.
  - `pest_control`: exterminating, pest control, rodent.
  - `debris_removal`: junk removal, rubbish, carting, waste.
  - `elevator`: elevator, lift.
  - `remediation`: restoration, water damage, mold remediation.
- Mapa de `license_type` → trade:
  - `MASTER PLUMBER` → plumbing
  - `ELECTRICAL FIRM` / `ELECTRICAL CONTRACTOR` → electrical
  - `ELEVATOR AGENCY / INSPECTOR` → elevator
  - `OIL BURNER INSTALLER` → hvac
  - `SIGN HANGER` → signage
- Regras negativas: “supply”, “distributor”, “showroom”, “rental”, “school” não são empreiteiros.
- Normalização de acentos, sufixos legais, `&`/`and`, abreviaturas.

**Não** usar tokens genéricos como `construction`, `contracting`, `services` como sinal positivo: são a causa dos 4.850 GC.

### 2.2 Classificação multi-label

Nova tabela:

```sql
CREATE TABLE company_trades (
  company_id INTEGER NOT NULL REFERENCES prospect_companies(id) ON DELETE CASCADE,
  trade_code TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  source TEXT NOT NULL,
  is_primary INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (company_id, trade_code)
);
```

`classify_company(company)` devolve trades ordenados por confiança, com fontes:

1. `license_type` (DOB) — peso mais alto.
2. `license`/`phone` match com fonte externa.
3. Nome normalizado — peso médio.
4. `site_snippet` / OSM tags — peso médio.
5. Histórico de permits (work type) — peso médio.

Regras:

- `confidence >= 0.80` para entrar em campanha.
- `prospect_companies.trade` continua a ser o primário (compatibilidade).
- `campaign_candidates` passa a consultar `company_trades` quando existe; fallback para o campo antigo.
- A exclusão global de 7 dias por `company_id` impede chamar a mesma empresa duas vezes por trades diferentes.

### 2.3 Guard com três âmbitos

`voice_scripts.showcase_guard()` passa a devolver `scope`:

| Scope | Condição | Linha falada | Uso |
|---|---|---|---|
| `exact` | `exact_count >= 5`, fresco | “45 active roofing opportunities in New York this week” | default; todos os trades com página exata |
| `bundle` | soma de ≥2 trades exatos, cada um ≥5, total ≥25 | “over 5,000 active home-service opportunities in New York this week” | GC/handyman multi-trade |
| `city` | `city_total >= 5,000`, fresco | “over 12,800 active property opportunities in New York this week” | GC sem trade confirmado; piloto máximo 10% |
| `none` | resto | — | bloqueia |

Invariantes:

- Nenhum scope inventa uma contagem por trade.
- `bundle` só soma trades com inventário exato; nunca inclui um trade a 0.
- `city` só é permitido se existir página city-wide e o link abrir nessa página.
- O mínimo de 5 itens **não** desce.
- `voice_calls` ganha `script_scope` e `bundle_code` para atribuição.

Flags:

```text
VOICE_GUARD_SCOPES=exact              # default; sem mudança de comportamento
VOICE_GUARD_SCOPES=exact,bundle
VOICE_GUARD_SCOPES=exact,bundle,city
VOICE_CITY_SCOPE_MAX_PCT=10
```

### 2.4 Inventário por categoria (fase 2)

Para separar `Lead` de `Painting` e `Gas` de `Heating`, criar:

```sql
CREATE TABLE market_categories (
  city_slug TEXT NOT NULL,
  category_slug TEXT NOT NULL,
  city TEXT NOT NULL,
  state TEXT NOT NULL,
  category TEXT NOT NULL,
  item_count INTEGER NOT NULL DEFAULT 0,
  built_at TEXT NOT NULL,
  PRIMARY KEY (city_slug, category_slug)
);
```

- `Lead` tem 370 oportunidades/30 d; pode ser um nicho próprio.
- `Gas` tem 0/30 d; fica fora.
- `Permit_Rejected` tem 0 com sinal permitido; fica fora até haver mapeamento.
- A página de showcase tem de ser construída por categoria; sem página, o guard não autoriza.

### 2.5 Plano de campanha por categoria

Substituir o `trade_plan` por `category_plan` (compatível com o formato atual):

```json
[
  {"category": "Plumbing", "trade": "plumbing", "quota": 3},
  {"category": "Electrical", "trade": "electrical", "quota": 5}
]
```

Alocador:

1. Calcula `eligible_now` por categoria (classifier + DNC + exclusão de 7 dias).
2. Limita a quota ao stock disponível.
3. Impõe teto por categoria (ex.: 35–40% do lote).
4. Redistribui categorias sem stock.
5. Nunca agenda uma categoria com 0 empresas.

---

## 3. Plano de dados e correlação

| Fonte | O que resolve | Telefone | Estado |
|---|---|---:|---|
| NYC DOB License Info `t8hj-ruu2` | 1.129 master plumbers, 950 electrical firms, 7 elevators, 104 oil burner, 42 sign hangers | Sim | a implementar |
| NYC DCWP `w7w3-xahh` | 18.931 home improvement; 13.383 já ingeridos | Sim | existe |
| DSNY/BIC `867j-5pgi` | 89 debris haulers ativos em NYC | Sim | a implementar |
| NYS DEC `h8u2-6ejg` | 442 pest businesses | Não | a enriquecer |
| OSM / Brave | website/phone para confirmar trade | Por confirmar | existe |
| DOB permits | work type para inferir trade | Não | a integrar |

Estratégia:

1. **Importar diretamente** os trades com licença explícita (DOB): plumbing, electrical, elevator, HVAC, signage.
2. **Correlacionar** as 4.850 GC existentes com DOB/DCWP/OSM por telefone, licença e nome+ZIP. Só marcar trade quando a confiança for ≥0,80.
3. **Piloto de precisão:** 100 empresas classificadas manualmente; exigir ≥95% de precisão antes de campanha.
4. **DNC:** as 8.534 empresas existentes já têm `dnc_checks` fresco; reclassificar não exige novo DNC. Novos imports exigem scrub.
5. **Sem duplicar contactos:** o telefone é único; a tabela `company_trades` permite vários trades sem duplicar a empresa.

---

## 4. Distribuição #7–#11

### 4.1 Regras

- Nenhuma campanha com mais de **35–40%** num único nicho.
- Mínimo de **8 nichos** por campanha, quando houver stock.
- Respeitar o stock semanal: plumbing tem 9 empresas; não pode levar 9 em todas as campanhas.
- A exclusão global de 7 dias transforma o stock numa **dotação semanal**, não diária.
- Categorias com 0 empresas não entram.

### 4.2 Exemplo de #7 (50 chamadas, 10 nichos)

| Categoria | Quota exemplo | Stock atual |
|---|---:|---:|
| Remodeling | 12 | 2.582 |
| HVAC | 7 | 82 |
| Painting | 7 | 172 |
| Electrical | 5 | 33 |
| Windows & Doors | 5 | 87 |
| Roofing | 4 | 82 |
| Plumbing | 3 | 9 |
| Landscaping | 2 | 68 |
| Cleaning | 2 | 34 |
| Remediation | 3 | 205 |
| **Total** | **50** | — |

As quotas reais são calculadas pelo alocador; a tabela é ilustrativa.

### 4.3 O que muda em cada campanha

| Campanha | Nichos | Observação |
|---|---|---|
| #6 (sex 06/11) | 10 | mantém o plano atual; não mexer |
| #7 (seg 09/11) | 10 | `exact` + `category_plan`; sem bundle/city |
| #8 (ter 10/11) | 10–11 | piloto `bundle` em 10% dos GC, após 20:00 ET |
| #9 (qua 11/11) | 10–12 | `Lead` se a página por categoria estiver pronta |
| #10 (qui 12/11) | 10–12 | `city` em 10% dos GC, se o piloto estiver limpo |
| #11 (sex 13/11) | 10–12 | consolidar; sem novos scopes |

### 4.4 O que não é possível já na #7

- Elevators, Rodents e Debris: 0 empresas. Só após enriquecimento.
- Construction & Permits: 0 oportunidades com sinal permitido e sem trade.
- Gas: 0 oportunidades/30 d. Não vale a pena forçar.
- 16 nichos completos na #7: não. 10 agora, 12 após a fase 2, 14 após enriquecimento.

---

## 5. Sequência de execução

| Quando | O quê | Deploy |
|---|---|---|
| Hoje 20:00 ET | P0: gmail_tokens + multi-trade + re-armar #6 | sim |
| Sex 06/11 20:00 | Fase 1: taxonomia + classifier + guard scopes (flag `exact`) | sim, sem mudança de comportamento |
| Sáb 07/11 | Reclassificação offline + auditoria de 100 empresas | não |
| Dom 08/11 20:00 | Ativar `exact` para reclassificadas + `category_plan`; dry-run | sim |
| Seg 09/11 09:00 | #7 com 10 nichos `exact` | campanha |
| Ter 10/11 20:00 | Ativar `bundle` em 10% dos GC | sim |
| Qua 11/11 20:00 | Ativar `city` em 10% dos GC, se piloto limpo | sim |
| Qui–Sex | #10/#11 com o mix validado | campanha |
| Fim de semana | Enriquecimento DOB/DSNY/NYS DEC para elevator/debris/pest | sim, após 20:00 |

Nenhum deploy entre 09:00 e 20:00 ET. Nenhuma alteração ao fluxo de voz estável fora da flag.

---

## 6. Gates e rollback

| Gate | Critério |
|---|---|
| Precisão do classifier | ≥95% numa amostra manual de 100 |
| Exact | Mesmas chamadas de hoje; zero regressão |
| Bundle | Answer rate não cai >5 p.p. vs exact; opt-out ≤3% |
| City | Answer rate não cai >10 p.p.; opt-out ≤3%; zero queixas |
| DNC | 100% dos contactos com check fresco |
| Showcase | `built_at` ≤72 h; `ready=true` por trade |
| Stock | Nenhuma categoria acima do stock semanal |
| Rollback | `VOICE_GUARD_SCOPES=exact` e `category_plan` antigo |

---

## 7. Decisões que precisam de aprovação

1. Autorizar os scopes `bundle` e `city`, com `city` limitado a 10% e apenas para GC.
2. Autorizar a tabela `company_trades` e a classificação multi-label.
3. Autorizar o uso de DOB/DSNY/NYS DEC como fontes públicas.
4. Aceitar que 4 nichos só entram depois de enriquecimento; não há sinónimo que resolva 0 empresas.
5. Confirmar que a prioridade é **diversificar com verdade**, não baixar o mínimo de 5 itens nem inventar contagens.
