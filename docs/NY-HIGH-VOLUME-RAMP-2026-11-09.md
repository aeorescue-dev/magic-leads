# Plano de rampa NY alto volume — 09–13/11/2026

**Estado:** proposta. Nada foi aplicado em produção.  
**Âmbito:** campanhas 7–11 (`New York`), DIDs, DNC, tetos de volume e orçamento.  
**Campanha #12 (Dallas):** não é tocada.

---

## 0. Decisão pendente: 2.050 ou 2.125 chamadas?

A soma dos dias indicados é:

```text
300 + 350 + 400 + 450 + 550 = 2.050
```

O total declarado de **2.125** tem **+75 chamadas** que não estão atribuídas a nenhum dia. Há duas opções:

| Opção | Dias | Total | Pico | DIDs necessários |
|---|---|---:|---:|---:|
| **A — usar os dias indicados** | 300 / 350 / 400 / 450 / 550 | **2.050** | 550 | **11** (10 novos + 929 atual) |
| **B — honrar 2.125** | 315 / 365 / 415 / 465 / 565 (+15/dia) | **2.125** | 565 | **12** (11 novos + 929 atual) |

O resto deste documento usa a **Opção A** (2.050), porque os valores diários foram explícitos. A Opção B está na secção 5.

---

## 1. Matriz de nichos — Opção A (2.050)

Distribuição proporcional ao inventário **exact verified** de NY (total 8.671). Arredondamento por maior resto; cada coluna soma exatamente o dia.

| Nicho | Seg 300 | Ter 350 | Qua 400 | Qui 450 | Sex 550 | **Total** |
|---|---:|---:|---:|---:|---:|---:|
| Structure / Remodeling | 188 | 219 | 251 | 282 | 345 | **1.285** |
| Plumbing | 34 | 39 | 45 | 51 | 62 | **231** |
| Electrical | 32 | 38 | 43 | 49 | 59 | **221** |
| Heating & Hot Water | 10 | 11 | 13 | 14 | 17 | **65** |
| Mold & Moisture | 9 | 11 | 12 | 14 | 17 | **63** |
| Painting | 8 | 9 | 11 | 12 | 15 | **55** |
| Grass & Debris | 6 | 8 | 9 | 10 | 12 | **45** |
| Doors & Windows | 6 | 7 | 8 | 9 | 11 | **41** |
| Roofing & Structure | 4 | 5 | 5 | 6 | 7 | **27** |
| Long tail* | 3 | 3 | 3 | 3 | 5 | **17** |
| **Total** | **300** | **350** | **400** | **450** | **550** | **2.050** |

\* Long tail semanal: Unsanitary & Sewage 11, Debris & Trash 5, Elevators 1, Rodents & Pests 0.  
Se quisermos chamar pests, é preciso tirar 1–2 chamadas de Structure numa das pontas.

### Validação de cobertura

A matriz usa ~24% do inventário exact de cada nicho:

| Nicho | Exact verified | Necessário na semana | Cobertura |
|---|---:|---:|---:|
| Structure/Remodeling | 5.438 | 1.285 | 4,2× |
| Plumbing | 975 | 231 | 4,2× |
| Electrical | 938 | 221 | 4,2× |
| Heating | 274 | 65 | 4,2× |
| Mold | 270 | 63 | 4,3× |
| Painting | 229 | 55 | 4,2× |
| Grass | 187 | 45 | 4,2× |
| Windows | 173 | 41 | 4,2× |
| Roofing | 114 | 27 | 4,2× |

Há folga para absorver DNC listed e bloqueios sem quebrar a quota diária.

---

## 2. DIDs

### 2.1 Quantidade

Com `VOICE_DID_DAILY_CAP=50`:

```text
550 / 50 = 11 DIDs no pico
11 − 1 (929 atual) = 10 novos DIDs
```

- **Mínimo matemático: 10 novos** (total 11). Capacidade exacta de 550/dia, **sem margem**.
- **Recomendado: 11 novos** (total 12). Capacidade 600/dia, 50 chamadas de folga para falhas/retries.
- Custo Telnyx confirmado: **$1 upfront + $1/mês por número**. 10 novos = $10 + $10/mês; 11 novos = $11 + $11/mês.

### 2.2 Lista exacta — números 929 disponíveis em 07/11 06:xx UTC

Todos são **929 / NEW YORK CITY**, voice + SMS + emergency, $1/mês. Excluí um 13.º resultado da consulta que estava a $2/mês.

| # | Número | Usar |
|---:|---|---|
| 1 | +1 929 448 0511 | novo |
| 2 | +1 929 357 1376 | novo |
| 3 | +1 929 357 1378 | novo |
| 4 | +1 929 556 7262 | novo |
| 5 | +1 929 628 0134 | novo |
| 6 | +1 929 475 8963 | novo |
| 7 | +1 929 732 2404 | novo |
| 8 | +1 929 488 1845 | novo |
| 9 | +1 929 610 8321 | novo |
| 10 | +1 929 379 9532 | novo |
| 11 | +1 929 379 9704 | novo (recomendado, dá a 12.ª linha) |
| 12 | +1 929 401 0892 | backup |
| — | +1 929 256 2550 | **já existe** (primário atual) |

**Não usar** `+1 929 379 9555` (mensalidade $2).  
**917:** a consulta estrita por NYC não devolveu números; os 929 acima são a via limpa.

> Disponibilidade confirmada por consulta read-only à Telnyx. Os números podem ser tomados por terceiros; reservar no GO.

### 2.3 Variável e roteamento

O parser atual de `VOICE_DID_BY_CITY` aceita **um DID por cidade** (`dallas=+14699607326`); não aceita lista. Para um pool, a alteração mínima é uma nova variável:

```env
VOICE_DID_BY_CITY=dallas=+14699607326
VOICE_DID_POOL_BY_CITY={"new york":["+19292562550","+19294480511","+19293571376","+19293571378","+19295567262","+19296280134","+19294758963","+19297322404","+19294881845","+19296108321","+19293799532","+19293799704"]}
VOICE_DID_DAILY_CAP=50
```

- O pool tem 12 números: 1 existente + 11 novos.
- `VOICE_DID_POOL_BY_CITY` tem precedência sobre `VOICE_DID_BY_CITY` para NY.
- **Não colocar o 518 no pool.** Se o pool esgotar, a campanha pausa com `did_capacity_reached`; nunca transborda para 518.
- Alternativa de variável única: estender `VOICE_DID_BY_CITY` para aceitar arrays JSON (`{"dallas":"+1...","new york":["+1...",...]}`). É mais invasivo e quebra compatibilidade; recomendo a variável separada.

### 2.4 Alterações de código necessárias

1. `config.py`: adicionar `VOICE_DID_POOL_BY_CITY: str = ""`.
2. `auto_dialer.py`:
   - `_did_pool_for_city(city)` — parse JSON, valida `+1` com 12 dígitos, dedupe.
   - `_reserve_did(city, day)` — escolhe o DID menos usado abaixo de 50/dia; reserva atomicamente.
   - Substituir `city_did or (secondary if calls >= did_cap else "")` por `_reserve_did(...)`.
   - Se não houver DID disponível: `paused` + `next_batch_at` seguinte + `error='did_capacity_reached'`; **não usar 518**.
3. `b2b_voice.py`:
   - `_ensure_columns`: adicionar `from_number TEXT` a `voice_calls`.
   - `create_voice_call(..., from_number="")` e gravar o número.
   - Tabela `voice_did_usage (day, did, calls)` com reserva atómica (`BEGIN IMMEDIATE` + upsert).
   - `did_capacity_status(city, day)` para preflight.
4. `telnyx_voice.py`: passar `from_number` ao `create_voice_call` e usá-lo no payload `from`.
5. `main.py`: `GET /api/admin/voice/did-capacity?city=New%20York` para mostrar uso/cap por DID.
6. Testes: parsing do pool, cap 50/DID/dia, rotação, ausência de 518 para NY, migração idempotente.

**Roteamento recomendado:** usar o pool inteiro todos os dias com seleção “least-used”, em vez de usar só 6 DIDs na segunda. Isso dá:

| Dia | Chamadas | DIDs ativos | Média/DID |
|---|---:|---:|---:|
| Seg | 300 | 12 | 25 |
| Ter | 350 | 12 | 29 |
| Qua | 400 | 12 | 33 |
| Qui | 450 | 12 | 38 |
| Sex | 550 | 12 | 46 |

É uma rampa suave para os 11 números novos e mantém todos abaixo de 50.

---

## 3. DNC scrub oficial

### 3.1 O bloqueio actual

- Os 2.050 candidatos (e toda a base NY) só têm `dnc_checks.source='staging'` de 03/11 **ou nenhum check**. **0 com scrub oficial.** Simulação da fila: **1.638 staging + 412 sem check + 0 oficial**.
- O endpoint existente `POST /api/admin/voice/dnc/scrub` aceita `text` até **5 MB** e aplica a lista a **toda a base**. A registry nacional completa é muito maior do que 5 MB; o parser também carrega a lista inteira em memória.
- Portanto, **não é possível garantir o scrub oficial só com o endpoint actual**. É preciso um adaptador por lote/fila.

### 3.2 Processo proposto

1. Exportar os **2.050 telefones** da fila (deduplicados) para `ny_queue_phones.csv`.
2. Obter a registry oficial (FTC National DNC ou provedor licenciado) e fazer matching offline contra os 2.050 telefones. O ficheiro completo não entra na app.
3. Novo `scrub_queue_with_dnc_matches(phones, matches, source='official')`:
   - `dnc_checks.listed=1` para os que estão na registry;
   - `listed=0` para os restantes;
   - `source='official'`, `expires_at=now+31d`.
4. Alternativa: provedor com lookup por telefone; 2.050 chamadas de lookup, registadas com `check_dnc(..., source='official', provider=...)`.
5. Verificação obrigatória:
   - `2.050/2.050` com `source='official'` e `expires_at > now`;
   - listar quantos `listed=1`;
   - revalidar a matriz por nicho (quota diária vs `dnc_clear`);
   - dry-run de 10 chamadas por nicho antes do GO.

**Dependência:** a registry oficial. Sem ela, o plano fica em `NO-GO` regulatório, mesmo com DIDs e budget prontos.

---

## 4. Tetos globais e financeiros

### 4.1 Variáveis

| Variável | Hoje | Opção A (2.050, pico 550) | Opção B (2.125, pico 565) |
|---|---:|---:|---:|
| `VOICE_MAX_CALLS_PER_DAY` | 100 | **650** | **700** |
| `VOICE_MAX_DAILY_BUDGET_USD` | 5 | **150** | **175** |
| `VOICE_ESTIMATED_CALL_COST_CENTS` | 25 | 25 | 25 |
| `VOICE_DID_DAILY_CAP` | 50 | 50 | 50 |

O limite de $150/dia é a reserva conservadora: 550 × $0.25 = $137.50 + 9% de folga. O custo real recente é ~$0.019/chamada; 550 chamadas custaram ~$10, não $137.50. O teto é uma proteção, não o gasto esperado.

### 4.2 Orçamento por campanha

As campanhas 7–11 têm hoje `budget_total_usd=20` e `budget_daily_usd=5`. **É obrigatório subir**, senão a campanha bloqueia a meio.

| Campanha | Chamadas | `budget_daily_usd` | `budget_total_usd` |
|---|---:|---:|---:|
| 7 | 300 | 75,00 | 75,00 |
| 8 | 350 | 87,50 | 87,50 |
| 9 | 400 | 100,00 | 100,00 |
| 10 | 450 | 112,50 | 112,50 |
| 11 | 550 | 137,50 | 137,50 |

Custo real esperado da semana: **~$38** (2.050 × $0.0186). A reserva de $512,50 é apenas o teto.

Para a Opção B (+15/dia): 78,75 / 91,25 / 103,75 / 116,25 / 141,25.

---

## 5. Opção B — 2.125 chamadas (+15/dia)

| Dia | Chamadas | DIDs |
|---|---:|---:|
| Seg | 315 | 12 |
| Ter | 365 | 12 |
| Qua | 415 | 12 |
| Qui | 465 | 12 |
| Sex | 565 | 12 |

Matriz de nichos (mesmos pesos):

| Nicho | Seg 315 | Ter 365 | Qua 415 | Qui 465 | Sex 565 | Total |
|---|---:|---:|---:|---:|---:|---:|
| Structure/Remodeling | 198 | 229 | 260 | 292 | 354 | 1.333 |
| Plumbing | 35 | 41 | 47 | 52 | 64 | 239 |
| Electrical | 34 | 39 | 45 | 50 | 61 | 229 |
| Heating | 10 | 12 | 13 | 15 | 18 | 68 |
| Mold | 10 | 11 | 13 | 15 | 18 | 67 |
| Painting | 8 | 10 | 11 | 12 | 15 | 56 |
| Grass | 7 | 8 | 9 | 10 | 12 | 46 |
| Windows | 6 | 7 | 8 | 9 | 11 | 41 |
| Roofing | 4 | 5 | 6 | 6 | 7 | 28 |
| Long tail | 3 | 3 | 3 | 4 | 5 | 18 |
| **Total** | **315** | **365** | **415** | **465** | **565** | **2.125** |

---

## 6. Checklist de GO

- [ ] Confirmar **2.050** (Opção A) ou **2.125** (Opção B).
- [ ] Autorizar compra de **10 DIDs** (mínimo) ou **11 DIDs** (recomendado).
- [ ] Reservar os 929 da lista; associar à connection `3084801788029699518`.
- [ ] Aplicar o patch de pool/rotação e migrar `voice_calls.from_number`.
- [ ] Definir `VOICE_DID_POOL_BY_CITY` e remover o 518 do caminho de NY.
- [ ] Subir `VOICE_MAX_CALLS_PER_DAY` e `VOICE_MAX_DAILY_BUDGET_USD`.
- [ ] Subir `budget_daily_usd`/`budget_total_usd` das campanhas 7–11.
- [ ] Executar o scrub DNC oficial dos 2.050 candidatos.
- [ ] Revalidar quotas por nicho com `dnc_clear`.
- [ ] Dry-run de 10 chamadas por nicho.
- [ ] Deploy fora da janela de Dallas (depois das 11:00 ET de hoje, ou 08/11).
- [ ] Só então atualizar as quotas/trade_plans das campanhas 7–11.

**NO-GO actual:** sem a registry oficial e sem o patch de DIDs, o plano não cumpre o requisito regulatório nem o limite de 50/DID/dia.

---

## 7. Patch de campanhas (proposto, não aplicado)

Atualizar **in-place** as campanhas 7–11. Manter `city='New York'`, `start_hour_et=9`, `include_fallback=0`, `batch_plan=''`, `plan_index=0`, `max_days=0` e as datas `next_batch_at` atuais.

| Campanha | `quota_total` | `batch_size` | `budget_daily_usd` | `budget_total_usd` |
|---|---:|---:|---:|---:|
| 7 | 300 | 300 | 75,00 | 75,00 |
| 8 | 350 | 350 | 87,50 | 87,50 |
| 9 | 400 | 400 | 100,00 | 100,00 |
| 10 | 450 | 450 | 112,50 | 112,50 |
| 11 | 550 | 550 | 137,50 | 137,50 |

### `trade_plan` — campanha 7 (300)

```json
[{"trade":"remodeling","quota":188},{"trade":"plumbing","quota":34},{"trade":"electrical","quota":32},{"trade":"hvac","quota":10},{"trade":"remediation","quota":9},{"trade":"painting","quota":8},{"trade":"landscaping","quota":6},{"trade":"windows","quota":6},{"trade":"roofing","quota":4},{"trade":"cleaning","quota":2},{"trade":"debris_removal","quota":1}]
```

### `trade_plan` — campanha 8 (350)

```json
[{"trade":"remodeling","quota":219},{"trade":"plumbing","quota":39},{"trade":"electrical","quota":38},{"trade":"hvac","quota":11},{"trade":"remediation","quota":11},{"trade":"painting","quota":9},{"trade":"landscaping","quota":8},{"trade":"windows","quota":7},{"trade":"roofing","quota":5},{"trade":"cleaning","quota":2},{"trade":"debris_removal","quota":1}]
```

### `trade_plan` — campanha 9 (400)

```json
[{"trade":"remodeling","quota":251},{"trade":"plumbing","quota":45},{"trade":"electrical","quota":43},{"trade":"hvac","quota":13},{"trade":"remediation","quota":12},{"trade":"painting","quota":11},{"trade":"landscaping","quota":9},{"trade":"windows","quota":8},{"trade":"roofing","quota":5},{"trade":"cleaning","quota":2},{"trade":"debris_removal","quota":1}]
```

### `trade_plan` — campanha 10 (450)

```json
[{"trade":"remodeling","quota":282},{"trade":"plumbing","quota":51},{"trade":"electrical","quota":49},{"trade":"hvac","quota":14},{"trade":"remediation","quota":14},{"trade":"painting","quota":12},{"trade":"landscaping","quota":10},{"trade":"windows","quota":9},{"trade":"roofing","quota":6},{"trade":"cleaning","quota":2},{"trade":"debris_removal","quota":1}]
```

### `trade_plan` — campanha 11 (550)

```json
[{"trade":"remodeling","quota":345},{"trade":"plumbing","quota":62},{"trade":"electrical","quota":59},{"trade":"hvac","quota":17},{"trade":"remediation","quota":17},{"trade":"painting","quota":15},{"trade":"landscaping","quota":12},{"trade":"windows","quota":11},{"trade":"roofing","quota":7},{"trade":"cleaning","quota":3},{"trade":"debris_removal","quota":1},{"trade":"elevator","quota":1}]
```

Cada `trade_plan` soma exactamente `quota_total`. A soma dos 5 planos é **2.050**.
