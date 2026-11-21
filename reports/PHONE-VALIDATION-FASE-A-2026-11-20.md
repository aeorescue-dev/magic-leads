# Fase A — validação gratuita do telefone do proprietário (4 cidades)

**Data:** 2026-11-20 · **Custo:** **$0** (nenhuma chamada paga) · **Escrita em produção:** nenhuma.
**Amostra:** 300 leads/cidade extraídos aleatoriamente da produção em modo `mode=ro`; o harness avalia 50/cidade com semente fixa `20261120`.
**Fonte:** `reports/phone-validation/fase-a/phone-validation-20261120-113507.json` (+ CSV homónimo).
**Regras em vigor:** `PHONE_L3_UNNAMED_ENABLED=0`, `PHONE_ENTITY_MODE=address_only`, `SOS_OFFICERS_ENABLED=0`.

---

## 1. Resultado global (200 leads)

| Decisão | Leads | % |
|---|---:|---:|
| `in_progress` (elegível para consulta paga) | **120** | 60% |
| `blocked` | **80** | 40% |
| `ready` (já tinha telefone) | 0 | 0% |
| `no_phone` (sem dono/morada) | 0 | 0% |

**Todos os 80 bloqueios são entidades** (empresa/trust/edifício). **Todas as 120 pessoas passaram** para `in_progress`. Não houve um único bloqueio por falta de dono, morada, registo antigo ou confiança baixa nesta amostra canónica.

---

## 2. Por cidade

| Cidade | Amostra | `in_progress` | `blocked` | Bloqueios por tipo | Confiança efetiva |
|---|---:|---:|---:|---|---|
| **NYC** | 50 | 19 | **31** | 29 company, 1 trust, 1 building | 46 high, 4 medium |
| **Chicago** | 50 | 34 | 16 | 15 company, 1 trust | 38 high, 12 medium |
| **Boston** | 50 | 33 | 17 | 16 company, 1 trust | 28 high, 15 medium, 7 unresolved→medium |
| **Dallas** | 50 | 34 | 16 | 14 company, 2 trust | 49 high, 1 unresolved→medium |

Totais efetivos: **161 high**, **39 medium** (31 resolvidos + 8 sem resolução), **0 low** nesta amostra.

### Leitura por cidade

- **NYC (62% bloqueado):** o PLUTO é dominado por LLCs/co-ops. Sem SOS e com L3 desligado, a maioria dos leads de empresa não tem telefone. É a maior limitação de cobertura do produto hoje.
- **Chicago (32% bloqueado):** 34 pessoas elegíveis; 12 `number_only` (confiança medium) e 22 casos com mailing diferente (absentee) na amostra de 300. O `year` veio **2026** em todos os 50; a regra de >5 anos não foi exercitada **nesta** amostra (numa execução anterior, um registo de 2021 foi corretamente bloqueado por `stale_property_record`).
- **Boston (34% bloqueado):** 33 pessoas elegíveis. **7 leads sem resolução fresca** (a consulta CKAN não casou); a política usou o nome persistido em `medium`, portanto podem ser consultados mas **nunca saem verificados**.
- **Dallas (32% bloqueado):** 34 pessoas, 49/50 `high`; 1 sem resolução. É o caminho mais limpo dos quatro.

---

## 3. Métodos de casamento e camadas

| Método | Leads | Efeito |
|---|---:|---|
| `bbl` (NYC) | 46 | high |
| `exact_address` | 115 | high |
| `number_only` | 16 | medium → L2, **sem selo** |
| `range` | 15 | medium → L2, **sem selo** |
| sem resolução (`None`) | 8 | medium efetivo → L2, **sem selo** |

**Camadas:** 120/120 `in_progress` são **L2** (nome + morada). **Zero L3** — como pedido.
**Mailing-first:** 42 dos 120 usam o `mailing_address` primeiro (39 absentee confirmados); o imóvel só entraria como fallback L3, que está desligado.

---

## 4. O que isto significa para a Fase B

- **Elegíveis para chamada paga:** 120/200 (60%).
- **Entidades:** 0 chamadas (bloqueadas). O braço de $8 **não se aplica** enquanto `PHONE_L3_UNNAMED_ENABLED=0`.
- **Projeção de custo:**
  - Se corrermos os 50/cidade: **120 × $0,20 = $24,00** — bate no teto, mas gasta a verba das entidades em pessoas.
  - **Recomendado:** `--limit 34`/cidade (136 leads; ~80 pessoas) com `--max-calls 80` → **máximo $16,00**, exatamente a verba base aprovada. Total abaixo do teto de $24.
- **Custo real provável:** inferior a $16, porque `no_results` não é faturado; o pior caso continua a ser $16.

---

## 5. Falhas e limites que a Fase A expôs (sem maquilhagem)

1. **Bug corrigido:** Chicago não lia `record_year` (`year_col` só ordenava). Sem a correção, a regra dos 5 anos **nunca** disparava. Já está corrigido e coberto por teste de regressão.
2. **NYC é o ponto fraco de cobertura:** 62% dos leads são entidades. Sem SOS ou L3, não há telefone para elas. É uma limitação estrutural, não um bug.
3. **Boston tem 14% de owners sem resolução fresca.** A política é honesta (medium, sem selo), mas a taxa de acerto desses casos só se mede na Fase B.
4. **8% `number_only` + 7,5% `range`** = casamentos bons mas não canónicos. Vão para L2 sem selo; a Fase B dirá se o nome compensa.
5. **Registo antigo é raro na amostra canónica** (todos 2026), mas o gate existe e foi exercitado numa execução anterior (2021 → bloqueado).
6. **A amostra é de 300/cidade**; os 50/cidade são uma subamostra estratificada. Não é um censo.

---

## 6. Recomendação

**Aprovar a Fase B apenas no braço de pessoas, com 80 chamadas e teto de $16:**

```bash
python -m backend.scripts.phone_validation --city all --limit 34 --seed 20261120 \
  --live --max-calls 80 --output reports/phone-validation/fase-b
```

- Sem braço de entidades (L3 continua desligado; custo $0).
- Paragem imediata se houver anomalia de cobrança, `name_mismatch` entregue ou falha de contrato.
- Revisão manual obrigatória de cada linha do CSV antes de qualquer escala.
- Critérios de go/no-go inalterados: ≥90% dono correto, 0 `verified` errados, 0 `name_mismatch` entregues, ≤5% terceiro/inquilino.

**Não proponho escalar nada com base na Fase A.** Ela prova que a política é conservadora e que o fluxo está pronto; a taxa de acerto real só a Fase B a mede.
