# Rampa de escala 11/11–21/11 — análise técnica

Data: 2026-11-10. Dados de produção (read-only). Base: campanha 14 fechada
(125 chamadas, $1.06029). Branch do cache: `feat/voice-tts-cache`.

## 1. Resumo

- **300/dia é viável** com o inventário atual e com o modo `shared`.
- O limite de 11/11 é o **warm-up dos DIDs**: 6 × 30 = **180**.
- A partir de 12/11, 6 × 50 = **300**. Para 300/dia com margem, comprar
  **+2 DIDs** (8 × 37,5).
- Inventário dedicado: **8.401** empresas em NY. A rampa até 21/11 usa
  **2.620** chamadas (31%), com margem de **3,2×**.
- Banco: 13,45 MB, 0,3 GB livres. O cache `shared` usa ~1,4–2 MB/dia;
  TTL de 14 dias ≈ 20–28 MB. **Não usar `dial`** (encheria o volume).

## 2. Rampa diária

| Data | Campanha | Chamadas | Cap DID (6) | Cap DID (8) | Tempo ~95 s/call |
|---|---|---:|---:|---:|---:|
| 11/11 | 15 (D3) | **165** | 180 | 220 | 4h21 |
| 12/11 | 16 (D4) | **200** | 300 | 350 | 5h17 |
| 13/11 | 17 (D5) | **230** | 300 | 360 | 6h04 |
| 14/11 | 18 (D6) | **250** | 300 | 400 | 6h36 |
| 15/11 | — | **0** | — | — | domingo |
| 16/11 | 19 (D7) | **275** | 300 | 400 | 7h15 |
| 17/11 | 20 (D8) | **300** | 300 (100%) | 400 (75%) | 7h55 |
| 18/11 | 21 (D9) | **300** | 300 | 400 | 7h55 |
| 19/11 | 22 (D10) | **300** | 300 | 400 | 7h55 |
| 20/11 | 23 (D11) | **300** | 300 | 400 | 7h55 |
| 21/11 | 24 (D12) | **300** | 300 | 400 | 7h55 |

Total: **2.620** chamadas. Sem os 2 DIDs novos, 300/dia usa 100% do cap
autoimposto de 50/DID — sem margem para falhas/retries. Com 8 DIDs, usa 75%.

## 3. Divisão por nicho

Mistura padrão de 300/dia (capacidade sustentável entre parênteses):

| Trade | 300/dia | % | Sustentável/dia (inv./7) | Utilização |
|---|---:|---:|---:|---:|
| remodeling | 150 | 50,0% | 777 | 19% |
| plumbing | 50 | 16,7% | 140 | 36% |
| electrical | 50 | 16,7% | 136 | 37% |
| hvac | 20 | 6,7% | 40 | 50% |
| remediation | 12 | 4,0% | 39 | 31% |
| painting | 8 | 2,7% | 33 | 24% |
| windows | 6 | 2,0% | 26 | 23% |
| cleaning | 2 | 0,7% | 6 | 33% |
| debris_removal | 1 | 0,3% | 3 | 33% |
| elevator/pest (rotativo) | 1 | 0,3% | ~1,1 | ~90% |

> `landscaping`, `roofing`, `signage` e `general_contractor` estão em
> `city_fallback` e **não são chamáveis** com `include_fallback=0`. Não
> alocar quota para eles.

### Tabela diária exata

| Data | Vol. | Remod. | Plumb. | Electr. | HVAC | Remed. | Paint. | Windows | Clean. | Debris | Elev./pest |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 11/11 | 165 | 82 | 28 | 28 | 11 | 7 | 4 | 3 | 1 | 1 | 0 |
| 12/11 | 200 | 101 | 33 | 33 | 13 | 8 | 5 | 4 | 1 | 1 | 1 |
| 13/11 | 230 | 115 | 38 | 38 | 15 | 9 | 6 | 5 | 2 | 1 | 1 |
| 14/11 | 250 | 123 | 42 | 42 | 17 | 10 | 7 | 5 | 2 | 1 | 1 |
| 16/11 | 275 | 137 | 46 | 46 | 18 | 11 | 7 | 6 | 2 | 1 | 1 |
| 17/11 | 300 | 150 | 50 | 50 | 20 | 12 | 8 | 6 | 2 | 1 | 1 |
| 18/11 | 300 | 151 | 50 | 50 | 20 | 12 | 8 | 6 | 2 | 1 | 0 |
| 19/11 | 300 | 150 | 50 | 50 | 20 | 12 | 8 | 6 | 2 | 1 | 1 |
| 20/11 | 300 | 151 | 50 | 50 | 20 | 12 | 8 | 6 | 2 | 1 | 0 |
| 21/11 | 300 | 150 | 50 | 50 | 20 | 12 | 8 | 6 | 2 | 1 | 1 |

`elevator/pest` aparece com quota 1 nos dias indicados e 0 nos restantes. A
soma de cada linha bate com o volume.

Rotação exata do slot `elevator/pest`: **12/11 elevator, 13/11 pest, 14/11
elevator, 16/11 elevator, 17/11 pest, 19/11 elevator, 21/11 pest.** Assim,
elevator usa 4 dos 5 disponíveis e pest usa os 3, sem bater no cooldown de
7 dias.

## 4. Inventário — a correção dos 3.951

O número 3.951 era a soma de `campaign_candidates` com limite de 1.000 por
trade; **remodeling estava truncado em 1.000**. O inventário real:

| Métrica | Valor |
|---|---:|
| Prospects em NY | 14.101 |
| Status `ready` | 13.272 |
| `do_not_call` | 829 |
| Telefone válido | 14.101 (100%) |
| DNC fresco e limpo | 13.272 (100% dos ready) |
| Dedicados chamáveis (`voice_segments`) | **8.401** |
| Elegíveis hoje (após cooldown 7d) | ~8.000 |

### Capacidade por trade (inventário dedicado)

| Trade | Inventário | Sustentável/dia |
|---|---:|---:|
| remodeling | 5.439 | 777 |
| plumbing | 978 | 140 |
| electrical | 952 | 136 |
| hvac | 281 | 40 |
| remediation | 271 | 39 |
| painting | 228 | 33 |
| windows | 182 | 26 |
| cleaning | 43 | 6 |
| debris_removal | 19 | 3 |
| elevator | 5 | 0,7 |
| pest_control | 3 | 0,4 |
| **Total** | **8.401** | **1.200** |

A 300/dia, a utilização é **25%** da capacidade sustentável. Até 21/11 são
2.620 chamadas = **31% do inventário**. Não há risco de esgotar nenhum nicho
com a tabela acima.

### Semanas seguintes

- A 300/dia, o ciclo completo dos 8.401 leva ~28 dias (8.401/300).
- O cooldown de 7 dias deixa sempre ~6.301 elegíveis (21× o volume diário).
- Para evitar reciclar os mesmos contactos a cada 28 dias, repor
  **≥2.100 empresas novas/semana**. Os lotes recentes foram 8.534 (02/11) e
  5.567 (07/11); se a cadência semanal continuar, há folga.
- **DNC:** os 13.272 ready têm DNC fresco. Novos lotes precisam de
  `import_dnc_csv`/`scrub_prospects_with_dnc_text`; sem isso ficam bloqueados
  por `dnc_not_checked`.

## 5. Banco e armazenamento

| Item | Valor |
|---|---:|
| `voice.db` | 13,45 MB |
| `/data` total | 0,9 GB |
| `/data` livre | **0,3 GB** |
| Chamadas totais | 453 |
| Chamadas 7d | 434 |
| Prospects totais | 15.507 |

- A 300/dia: ~2.100 chamadas/semana, ~2 MB/semana de DB. SQLite aguenta.
- Cache `shared`: 7–10 MP3/dia × ~200 KB = 1,4–2 MB/dia.
  Com TTL **14 dias** ≈ 20–28 MB. Cabe nos 0,3 GB.
- **Não ativar `dial`**: 300 MP3/dia encheria o volume em ~3 dias.
- O `cleanup()` do cache foi ligado ao arranque da campanha.

## 6. Alterações necessárias antes de 11/11

1. **2 DIDs novos** em NY, adicionados a `VOICE_DID_POOL_BY_CITY`, com warm-up
   20/25/30. Sem eles, 300/dia fica no limite exato de 6 × 50.
2. `VOICE_MAX_CALLS_PER_DAY=300`.
3. `VOICE_TTS_CACHE_ENABLED=1`, `VOICE_TTS_CACHE_MODE=shared`,
   `VOICE_TTS_SHARED_NAME=there`, `VOICE_TTS_CACHE_TTL_DAYS=14`.
4. Atualizar as campanhas 15–24:
   - `quota_total` e `max_calls` para o volume do dia;
   - `trade_plan` da tabela da secção 3 (zerar landscaping/roofing);
   - `budget_total_usd` e `budget_daily_usd` = volume × $0,25.
5. Confirmar a cadência do scraper semanal e o DNC dos novos lotes.

## 7. Riscos

- **DIDs:** 300/dia em 6 DIDs = 50/DID, sem margem. 8 DIDs = 37,5/DID.
- **Pacing:** 300/dia cabe (7h55); 400/dia fica no limite (10h33).
- **Inventário:** 21/11 está coberto; semanas seguintes dependem de reposição.
- **Compliance:** o aumento de volume amplia a exposição TCPA/AUP já
  documentada; o cache não resolve esse bloqueador.
