# Orçamento e capacidade — rampa 8 DIDs + fase 500/dia

Data: 2026-11-10. Saldo Telnyx consultado: **$16.75**.
Conta: **8 números** (6 no pool NY + 1 secundário 518 + 1 Dallas).
Preços Telnyx confirmados na API: número 929 = **$1,00 upfront + $1,00/mês**.

## Revisão 10/11 14:00 ET — decisão: sem compra de DIDs

- O 518 entra no pool; o pool fica com **7 DIDs** e a conta continua com **8
  números** (não 9).
- **Rampa 11–21/11:** tráfego $5,69 + aluguel 8 × $1 = **$13,69**, sem upfront.
  O saldo atual de **$16,75 cobre** (sobram $3,06; margem de 22%).
- **300/dia com 7 DIDs:** 42,9 chamadas/DID = **86%** do cap de 50. É
  operacional, mas acima do alvo de 75–80%. Para ≤80%, o máximo é
  **280/dia**. Os dias de 300 só começam a 17/11; dá para decidir até lá.
- **Fase 500/dia:** 14 DIDs no pool → 7 novos (o 518 já conta). Conta total
  de 15 números: aluguel $15 + upfront $7 + tráfego $11,40 = **$33,40**.
- **Consolidado até 05/12:** tráfego $17,09 + aluguel $15 + upfront $7 =
  **$39,09**; com margem 50% = **$58,64**.
- **Enriquecimento:** o primeiro passe importou **+777** empresas (NY total
  14.878), mas **777 ficaram sem DNC** (`dnc_not_checked`) e **não são
  chamáveis**. O alvo de +5.000 não foi atingido com a fonte atual; é preciso
  uma extração direcionada + DNC oficial.

## 1. Rampa 11/11–21/11 (2.620 chamadas, 8 DIDs no pool)

### Premissas

- Call-control: **$0,0016 por chamada discada** (80% de atendimento × $0,002).
- TTS `shared`: **$0,15/dia** (7–10 áudios reutilizados).
- Aluguel: **$1,00/número/mês**; a conta passa a ter 10 números
  (6 pool + 2 novos + 518 + Dallas) = **$10/mês**.
- Upfront dos 2 novos: **$2**.

### Cálculo

| Item | Valor |
|---|---:|
| Call-control (2.620 × $0,0016) | $4,19 |
| TTS shared (10 dias × $0,15) | $1,50 |
| **Tráfego** | **$5,69** |
| Aluguel (10 números × $1) | $10,00 |
| Upfront (2 números × $1) | $2,00 |
| **Total exato do período** | **$17,69** |
| Com margem de 50% | **$26,54** |

**Saldo necessário:** ~**$26,54**.
**Saldo atual:** $16,75 → **recarga de ~$9,79 (arredondar $10)**.

## 2. Fase 500/dia — 23/11 a 05/12 (12 dias, 6.000 chamadas)

### DIDs necessários

| Utilização alvo | Cálculo | DIDs |
|---|---|---:|
| ≤80% | 500 / (50 × 0,80) = 12,5 → **13** | **13** (76,9%) |
| ≤75% | 500 / (50 × 0,75) = 13,3 → **14** | **14** (71,4%) |
| 12 DIDs | 500 / 600 = 83,3% | acima do alvo |

**Recomendação: 14 DIDs no pool NY** (6 atuais + 2 da rampa + 6 novos).
Conta total: 16 números (14 pool + 518 + Dallas).

### Cálculo

| Item | Valor |
|---|---:|
| Call-control (6.000 × $0,0016) | $9,60 |
| TTS shared (12 dias × $0,15) | $1,80 |
| **Tráfego** | **$11,40** |
| Aluguel (16 números × $1) | $16,00 |
| Upfront (6 novos × $1) | $6,00 |
| **Total exato da fase** | **$33,40** |
| Com margem de 50% | **$50,10** |

**Orçamento recomendado para a fase:** **$50,10**.

### Custo das linhas

- 8 números novos no total (2 rampa + 6 fase 2).
- **Upfront:** 8 × $1 = **$8**.
- **Aluguel incremental:** 8 × $1 = **$8/mês**.
- **Aluguel total da conta:** 16 × $1 = **$16/mês**.
- Sem taxa de plataforma; SMS/MMS não é necessário (+$0,10/mês se ativar).

## 3. Consolidado até 05/12

| Item | Valor |
|---|---:|
| Tráfego rampa + fase 2 | $17,09 |
| Aluguel (16 números, 1 mês) | $16,00 |
| Upfront (8 novos) | $8,00 |
| **Total exato** | **$41,09** |
| Com margem de 50% | **$61,64** |

**Recomendação de saldo:** **$60–65**.
**Saldo atual:** $16,75 → **recarga de ~$45** (arredondar $45–50).

## 4. Inventário: 8.401 vs 8.620 chamadas

| Métrica | Valor |
|---|---:|
| Inventário dedicado chamável | 8.401 |
| Rampa 11–21/11 | 2.620 (31%) |
| Fase 500/dia (12 dias) | 6.000 (71%) |
| **Total** | **8.620 (102,6%)** |

- O total planeado **excede o inventário em 219 chamadas (2,6%)**.
- O sistema **não trava**: o cooldown de 7 dias devolve ao pool as empresas
  chamadas na rampa, e elas voltam a ser elegíveis na fase 2.
- Mas o inventário único fica **saturado**; a operação passa a depender de
  reciclagem.
- Ciclo de reciclagem:
  - 8.401 / 500 = **16,8 dias**.
  - Com +5.000 novas = 13.401 / 500 = **26,8 dias**.
  - Com +5.600 novas = 14.001 / 500 = **28,0 dias**.

## 5. Recomendação de enriquecimento

**Sim, extrair já um novo lote de ≥5.000–6.000 empresas únicas em NY** antes
de 23/11.

- 5.000 novas → 13.401 no pool → ciclo de **26,8 dias**.
- 5.600 novas → 14.001 → ciclo de **28 dias**.
- O lote tem de passar por:
  1. classificação de trade (`sync_company_trades`);
  2. DNC (`import_dnc_csv` / `scrub_prospects_with_dnc_text`);
  3. rebuild de `voice_segments`;
  4. validação de telefone/estado.
- Sem DNC, os novos ficam bloqueados por `dnc_not_checked`.
- Os lotes recentes (8.534 em 02/11 e 5.567 em 07/11) mostram que a
  cadência semanal suporta esse volume.

## 6. Como o sistema recicla e evita SPAM

- `campaign_candidates` exclui **qualquer** empresa chamada por campanha
  Telnyx nos **últimos 7 dias** (cooldown fixo no código).
- Não há prioridade por desfecho: no-answer, máquina e hangup voltam ao pool
  geral após 7 dias, ordenados por `score DESC, permit_count DESC`.
- `MAX_ATTEMPTS_7D=3` limita tentativas, mas o cooldown de 7 dias já impede
  mais de 1 chamada de campanha por semana.
- Opt-out/DNC são **permanentes** (`voice_suppressions`,
  `status='do_not_call'`) e nunca reciclam.
- `VOICE_RETRY_ENABLED` está OFF; se ligado, aumenta a frequência de reciclagem.
- **Risco de SPAM:** com 500/dia e 8.401 de inventário, o mesmo número é
  chamado a cada ~17 dias. Com 13.401, a cada ~27 dias. Para 500/dia,
  recomendo:
  1. subir o cooldown para **14–21 dias** (hoje é fixo em 7; exige code
     change/config);
  2. manter 14 DIDs a 71% do cap;
  3. monitorizar complaints, opt-out e labeling “Spam Likely”;
  4. repor inventário semanalmente.

## 7. Resumo executivo

| Pergunta | Resposta |
|---|---|
| Custo exato da rampa 11–21/11 | **$17,69** (50% margem: $26,54) |
| Recarga para a rampa | **~$10** (saldo $26,75) |
| DIDs para 500/dia | **14** (13 a 80%; 12 = 83,3%) |
| Custo exato da fase 500/dia | **$33,40** (50% margem: $50,10) |
| Custo consolidado até 05/12 | **$41,09** (50% margem: $61,64) |
| Recarga consolidada | **~$45** (saldo ~$62) |
| Inventário atual cobre 8.620? | **Não** (8.401; 102,6%) |
| Enriquecimento imediato? | **Sim, ≥5.000–6.000 novas** |
| Cooldown para 500/dia | Subir de 7 para **14–21 dias** |
