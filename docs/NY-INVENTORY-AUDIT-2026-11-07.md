# Auditoria de inventário NY — 16 nichos oficiais

**Data:** 2026-11-07, ~06:00 UTC (01:00 ET)  
**Âmbito:** `voice.db` → `prospect_companies`, `company_trades`, `dnc_checks`, `voice_suppressions`  
**Cidade:** `New York` / `state='NY'`  
**Natureza:** read-only. Nenhuma campanha, contacto ou configuração foi alterado.

> **Correção operacional (2026-11-07, 06:15 UTC):** NY **não é greenfield**. O inventário abaixo é a base disponível, mas já existem 9 campanhas NY (IDs 3–11), 143 chamadas executadas e 5 campanhas armadas para 09–13/11 com 350 chamadas planeadas. A leitura inicial “NY sem campanhas” estava errada e fica corrigida nesta secção.

### Campanhas NY já existentes

| ID | Nome | Estado | Próximo lote | Quota | Batch | Feitas |
|---:|---|---|---|---:|---:|---:|
| 3 | Pilot NY Remodeling 2026-11-03 | paused, `next_batch_at=NULL` | não retoma sozinha | 68 | 12 | 23 |
| 4 | Pilot NY HVAC 2026-11-04 | paused, `next_batch_at=NULL` | não retoma sozinha | 45 | 10 | 10 |
| 5 | Piloto V3 50 NY Multi 2026-11-05 | completed | — | 50 | 50 | 50 |
| 6 | Piloto V3 60 NY Multi 2026-11-06 | completed | — | 60 | 60 | 60 |
| 7 | Rampa 50 NY Multi 2026-11-09 | paused | 2026-11-09 14:00Z / 09:00 ET | 50 | 50 | 0 |
| 8 | Rampa 60 NY Multi 2026-11-10 | paused | 2026-11-10 14:00Z / 09:00 ET | 60 | 60 | 0 |
| 9 | Rampa 70 NY Multi 2026-11-11 | paused | 2026-11-11 14:00Z / 09:00 ET | 70 | 70 | 0 |
| 10 | Rampa 80 NY Multi 2026-11-12 | paused | 2026-11-12 14:00Z / 09:00 ET | 80 | 80 | 0 |
| 11 | Rampa 90 NY Multi 2026-11-13 | paused | 2026-11-13 14:00Z / 09:00 ET | 90 | 90 | 0 |

As campanhas 7–11 passam o niche gate e estão armadas para retomar automaticamente. Distribuição planeada dos 350 contactos: remodeling 145, hvac 52, painting 52, roofing 25, landscaping 23, remediation 17, windows 16, cleaning 10, electrical 5, plumbing 5.

### DIDs

`VOICE_DID_BY_CITY='dallas=+14699607326'` — **sem chave NY**. `_did_for_city('New York')` devolve `''`. O dialer não bloqueia: usa `TELNYX_FROM_NUMBER=+19292562550` (929 NYC) nas primeiras 50 chamadas de cada campanha e `TELNYX_FROM_NUMBER_SECONDARY=+15189429910` (518 upstate) a partir da 51.ª. Para 09–13/11: 250 chamadas no 929 e 100 no 518.

O gate de DNC da secção 3 aplica-se aos 350 contactos: todos têm apenas `staging`, nenhum tem scrub oficial.

---

## 1. Definições usadas

| Métrica | Regra |
|---|---|
| **Ready** | `status='ready'`, telefone E.164 `+1` com 12 caracteres, `state='NY'`. Exclui `do_not_call`, `invalid`, `meeting` e telefone vazio. |
| **Verified** | `company_trades.confidence >= 0.80`, `source <> 'primary_unconfirmed'`, e licença preenchida **ou** fonte forte (`license`, `niche_key`, `site_text`). É o mesmo gate de `verified_candidate_count()`. |
| **Exato** | O trade do prospect tem vitrine dedicada em NY (`showcase.available(..., min_items=5).available = True`). |
| **Fallback** | O trade só tem vitrine city-wide/genérica. Em NY, só `general_contractor` cai aqui. |
| **Exclusivo** | Cada empresa conta **uma vez**. Ordem de alocação: confiança DESC → `is_primary` DESC → ordem do nicho. 245 empresas multi-trade foram alocadas ao seu sinal mais forte. |

### Mapeamento dos 16 nichos

| # | Nicho oficial | Categoria canónica | Trade(s) de voz |
|---:|---|---|---|
| 1 | Roofing & Structure | `Roof` | `roofing` |
| 2 | Structure | `Structure` | `remodeling`, `general_contractor` |
| 3 | Plumbing | `Plumbing` | `plumbing` |
| 4 | Grass & Debris | `Grass` | `landscaping` |
| 5 | Painting | `Paint` | `painting` |
| 6 | Construction & Permits | `Permit_Rejected` | — (sem trade) |
| 7 | Heating & Hot Water | `Heating` | `hvac` |
| 8 | Electrical | `Electrical` | `electrical` |
| 9 | Elevators | `Elevator` | `elevator` |
| 10 | Gas & Leaks | `Gas` | `hvac` (partilhado) |
| 11 | Rodents & Pests | `Rodent` | `pest_control` |
| 12 | Mold & Moisture | `Mold` | `remediation` |
| 13 | Lead & Paint | `Lead` | `painting` (partilhado) |
| 14 | Unsanitary & Sewage | `Unsanitary` | `cleaning` |
| 15 | Doors & Windows | `Door_Window` | `windows` |
| 16 | Debris & Trash | `Debris` | `debris_removal` |

**Regra de exclusividade para pools partilhados:** `hvac` é atribuído a **Heating & Hot Water**; `painting` é atribuído a **Painting**. `Gas & Leaks` e `Lead & Paint` ficam com 0 exclusivo. Reutilizar o pool partilhado duplicaria contactos.

---

## 2. Tabela principal — ready vs verified vs exato/fallback

| # | Nicho oficial | Ready | Verified | Exato | Fallback |
|---:|---|---:|---:|---:|---:|
| 1 | Roofing & Structure | 116 | 114 | 114 | 0 |
| 2 | Structure | 9.818 | 5.515 | 5.438 | 77 |
| 3 | Plumbing | 980 | 975 | 975 | 0 |
| 4 | Grass & Debris | 187 | 187 | 187 | 0 |
| 5 | Painting | 228 | 229 | 229 | 0 |
| 6 | Construction & Permits | 0 | 0 | 0 | 0 |
| 7 | Heating & Hot Water | 283 | 274 | 274 | 0 |
| 8 | Electrical | 952 | 938 | 938 | 0 |
| 9 | Elevators | 5 | 8 | 8 | 0 |
| 10 | Gas & Leaks | 0 | 0 | 0 | 0 |
| 11 | Rodents & Pests | 3 | 3 | 3 | 0 |
| 12 | Mold & Moisture | 271 | 270 | 270 | 0 |
| 13 | Lead & Paint | 0 | 0 | 0 | 0 |
| 14 | Unsanitary & Sewage | 43 | 43 | 43 | 0 |
| 15 | Doors & Windows | 182 | 173 | 173 | 0 |
| 16 | Debris & Trash | 19 | 19 | 19 | 0 |
| | **Total dos 16** | **13.087** | **8.748** | **8.671** | **77** |

Fora dos 16: **signage** tem 192 ready e 194 verified; não entra na soma acima.

### Notas da tabela

- **Structure** é o único nicho com fallback: 5.438 remodeling com vitrine dedicada + 77 GC sem vitrine dedicada. Os outros 4.301 GC ready não passam no gate estrito (`primary_unconfirmed` a 0.40).
- **Verified > Ready** em Painting e Elevators porque uma empresa com trade primário noutro nicho pode ser alocada ao nicho onde tem o sinal verificado mais forte. **Verified < Ready** em Structure, Plumbing, Electrical, Heating, Mold, Windows e Roofing porque o gate estrito elimina sinais fracos e porque empresas multi-trade contam uma só vez.
- **Gas & Leaks** e **Lead & Paint** não têm trade próprio. O pool `hvac` (274 verified) pertence a Heating; o pool `painting` (229 verified) pertence a Painting. Não somar.
- **Construction & Permits** é `Permit_Rejected`; não existe trade de voz nem vitrine. Os 760 leads de permit do produto não têm prospects mapeados.
- Os **661** prospects sem trade são nomes de pessoa e já estão `do_not_call`; não entram em nenhuma contagem.

---

## 3. Gate DNC — o número que muda o plano

O inventário acima é o teto. O gate seguinte é DNC/supressão.

| # | Nicho | Verified | DNC staging | Sem check | DNC oficial |
|---:|---|---:|---:|---:|---:|
| 1 | Roofing & Structure | 114 | 75 | 39 | 0 |
| 2 | Structure | 5.515 | 2.996 | 2.519 | 0 |
| 3 | Plumbing | 975 | 15 | 960 | 0 |
| 4 | Grass & Debris | 187 | 91 | 96 | 0 |
| 5 | Painting | 229 | 175 | 54 | 0 |
| 6 | Construction & Permits | 0 | 0 | 0 | 0 |
| 7 | Heating & Hot Water | 274 | 156 | 118 | 0 |
| 8 | Electrical | 938 | 23 | 915 | 0 |
| 9 | Elevators | 8 | 0 | 8 | 0 |
| 10 | Gas & Leaks | 0 | 0 | 0 | 0 |
| 11 | Rodents & Pests | 3 | 2 | 1 | 0 |
| 12 | Mold & Moisture | 270 | 203 | 67 | 0 |
| 13 | Lead & Paint | 0 | 0 | 0 | 0 |
| 14 | Unsanitary & Sewage | 43 | 31 | 12 | 0 |
| 15 | Doors & Windows | 173 | 108 | 65 | 0 |
| 16 | Debris & Trash | 19 | 2 | 17 | 0 |
| | **Total** | **8.748** | **3.877** | **4.871** | **0** |

**Achado crítico:** os 3.877 que passam `_eligibility()` fazem-no por linhas `dnc_checks.source='staging'`, criadas em 2026-11-03 por `staging_clear_dnc()`. Não são um scrub DNC oficial. O `staging_mode` está `False`, mas as linhas continuam frescas (31 dias) e `listed=0`, por isso o código as aceita.

Consequência: **nenhum dos 8.748 verified tem scrub DNC oficial registado**. Antes de discar NY, é obrigatório correr o scrub oficial e reavaliar. As linhas staging expiram por volta de 2026-12-04; até lá, o código continuaria a deixar passar 3.877 contactos sem verificação real.

### Risco transversal — Dallas #12

O mesmo padrão existe no pool de Dallas: dos 324 candidatos do plano da campanha #12, **319 têm apenas staging** e **5 não têm check**. O lote de 43 de hoje sai desse pool. Nada foi alterado; o alerta fica registado para decisão antes das 10:00 ET.

---

## 4. Implicação para DIDs e rampa

### DIDs

`VOICE_DID_DAILY_CAP = 50` (config). Fórmula operacional:

```
DIDs = ceil(chamadas_pico_dia / 50) + 1 (rotação/reserva)
```

| Cenário | Chamadas/dia | DIDs mínimos | DIDs recomendados |
|---|---:|---:|---:|
| Arranque / warm-up | 25 | 2 | 2 |
| Semana 2 | 50 | 2 | 2–3 |
| Semana 3 | 75 | 3 | 3 |
| Semana 4 | 100 | 3 | 3 |

**Compra inicial recomendada:** 2 DIDs locais NYC (1 primário + 1 rotação). Comprar o 3.º ao passar 50/dia. Não é necessário um DID por nicho; a atribuição faz-se por `trade_code` na campanha.

**Configuração obrigatória:** `VOICE_DID_BY_CITY` hoje só tem Dallas. Adicionar `new york=+1...`; sem isso, `_did_for_city('New York')` devolve vazio e a campanha NY não arranca.

### Rampa

O orçamento de reserva é `$0.25/chamada` (`VOICE_ESTIMATED_CALL_COST_CENTS=25`). O custo Telnyx real é `$0.02/min`, mas a reserva interna usa $0.25.

| Semana | Chamadas/dia | Reserva $0.25/chamada | Nota |
|---|---:|---:|---|
| 1 | 25 | $6,25/dia | warm-up |
| 2 | 50 | $12,50/dia | 1 DID chega ao cap |
| 3 | 75 | $18,75/dia | 2 DIDs |
| 4 | 100 | $25,00/dia | 3 DIDs |

Se o orçamento ficar nos **$5/dia** atuais, o teto é **20 chamadas/dia** e 1–2 DIDs bastam. Para a rampa 25→100/dia, é preciso subir o budget diário e o total (1.750 chamadas × $0.25 = $437,50 de reserva; o custo real Telnyx é muito inferior).

### Prioridade de arranque

1. **Structure / remodeling** — 5.438 exact verified; 2.942 com staging.
2. **Plumbing** — 975 exact; **960 sem check** → scrub primeiro.
3. **Electrical** — 938 exact; **915 sem check** → scrub primeiro.
4. **Heating & Hot Water** — 274 exact; 118 sem check.
5. **Mold & Moisture** — 270 exact; 67 sem check.
6. **Painting** — 229 exact; 54 sem check.
7. **Grass & Debris** — 187 exact; 96 sem check.
8. **Doors & Windows** — 173 exact; 65 sem check.
9. **Roofing & Structure** — 114 exact; 39 sem check.
10. **Unsanitary & Sewage** — 43 exact; 12 sem check.
11. **Debris & Trash** — 19 exact; 17 sem check.
12. **Elevators** — 8 exact; 8 sem check.
13. **Rodents & Pests** — 3 exact; 1 sem check.

**Sem Structure, os outros 12 nichos somam 3.233 exact verified.** Plumbing + Electrical somam 1.913 exact, mas 1.875 não têm qualquer check DNC. O gargalo de NY não é inventário; é scrub DNC e orçamento.

---

## 5. Campanha #12

```
status = paused
next_batch_at = 2026-11-07T15:00:00Z
quota = 43
batch_plan = [15, 15, 13]
plan_index = 0
audit = 43/43 · GC 0 · all_green=true
calls = 0
```

A auditoria foi read-only. Nenhum dado de Dallas ou NY foi alterado.
