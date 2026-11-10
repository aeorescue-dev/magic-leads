# Projeção de custo Telnyx até 2026-11-21

Base: custo real medido no CDR de 09/11/2026 (não a estimativa do painel).
Snapshot: **10/11/2026 ~09:25 ET**. Consulta read-only.

## 1. Custo unitário real (CDR 09/11)

| Desfecho | Quantidade | Custo Telnyx | Unitário |
|---|---:|---:|---:|
| Discada, não atendida | 17 | $0.00000 | **$0.000000** |
| Atendida → máquina/voicemail | 61 | $0.12200 | **$0.002000** (call-control, mínimo 60 s) |
| Atendida → humano / `not_sure` | 43 | $0.81416 | **$0.018934** ($0.002 + TTS $0.016934) |
| **Total** | **121** | **$0.93616** | **$0.007737 por discada** |

- Call-control: $0.002/min, mínimo 60 s por chamada conectada.
- TTS: $0.000032/caractere; 22.755 caracteres / 43 chamadas = **529,19
  caracteres por chamada** (≈ $0.016934).
- Não houve cobrança para as 17 não atendidas nem para 5 inbound (0 s, $0.00).

Taxas de referência: **85,95%** atendidas; **35,54%** das discadas geram TTS
(humano + `not_sure`); **50,41%** caem em máquina; **14,05%** não atendem.

## 2. Volume planeado até 21/11

| Campanha | Data | Planeado | Já feito | Em falta |
|---|---:|---:|---:|---:|
| 12 — Dallas Pilot | 07/11 | 43 | 41 | **2** |
| 14 — NY 2W D2 | 10/11 | 130 | 39 | **91** |
| 15 — NY 2W D3 | 11/11 | 150 | 0 | **150** |
| 16 — NY 2W D4 | 12/11 | 170 | 0 | **170** |
| 17 — NY 2W D5 | 13/11 | 190 | 0 | **190** |
| 18 — NY 2W D6 | 14/11 | 140 | 0 | **140** |
| 19 — NY 2W D7 | 16/11 | 170 | 0 | **170** |
| 20 — NY 2W D8 | 17/11 | 190 | 0 | **190** |
| 21 — NY 2W D9 | 18/11 | 210 | 0 | **210** |
| 22 — NY 2W D10 | 19/11 | 220 | 0 | **220** |
| 23 — NY 2W D11 | 20/11 | 240 | 0 | **240** |
| 24 — NY 2W D12 | 21/11 | 130 | 0 | **130** |
| **Total** | | **1.983** | **80** | **1.903** |

- 15/11 (domingo) não tem campanha no plano de 2 semanas.
- Campanha 12 tem 2 chamadas pendentes e `next_batch_at` para 10/11 10:00 ET.
- Campanha 18 (sábado, 14/11) está agendada; se for cancelada por decisão de
  produto, subtrair **$1.08**.

## 3. Projeção base (mesma mistura de 09/11)

| Item | Cálculo | Valor |
|---|---|---:|
| Discadas em falta | — | 1.903 |
| Atendidas previstas | 1.903 × 85,95% | **1.636** |
| Com TTS (humano/not_sure) | 1.903 × 35,54% | **676** |
| Máquina/voicemail | 1.636 − 676 | **960** |
| Não atendidas | 1.903 − 1.636 | **267** |
| Call-control | 1.636 × $0.002 | **$3.27** |
| TTS | 676 × 529,19 car. × $0.000032 | **$11.45** |
| **Total base** | 1.903 × $0.007737 | **$14.72** |

Conferência: 1.903 × $0.0077369 = **$14,72**.

### Custo base por campanha

| Campanha | Em falta | Custo base |
|---|---:|---:|
| 12 | 2 | $0.02 |
| 14 | 91 | $0.70 |
| 15 | 150 | $1.16 |
| 16 | 170 | $1.32 |
| 17 | 190 | $1.47 |
| 18 | 140 | $1.08 |
| 19 | 170 | $1.32 |
| 20 | 190 | $1.47 |
| 21 | 210 | $1.62 |
| 22 | 220 | $1.70 |
| 23 | 240 | $1.86 |
| 24 | 130 | $1.01 |
| **Total** | **1.903** | **$14.72** |

## 4. Cenários de sensibilidade

| Cenário | Premissas | Total |
|---|---|---:|
| Base (medido) | 86% atendidas, 35,5% TTS, 529 car. | **$14.72** |
| Chamadas mais longas | 25% das atendidas passam de 60 s | $15.54 |
| TTS +25% | 661 caracteres por chamada | $17.58 |
| Stress | 50% das discadas geram TTS + 25% mais texto | $23.42 |
| Severo | 60% TTS, 700 car., call-control 1,5× | $30.49 |

O TTS é **78%** do custo. É a variável que mais afeta a projeção; a duração das
chamadas só pesa se passar de 60 s.

## 5. Saldo e recarga

Saldo Telnyx consultado em 10/11: **$18,01** (available_credit = balance,
frozen $0,00, pending $0,00).

| Referência | Custo | Saldo após | Situação |
|---|---:|---:|---|
| Base | $14.72 | $3.29 | cobre, margem de 22% |
| Stress | $23.42 | **−$5.41** | **não cobre** |
| Severo | $30.49 | **−$12.48** | **não cobre** |

### Recarga recomendada

- **Mínimo matemático:** $0 para o cenário base; **$12,48** para cobrir o
  cenário severo sem margem.
- **Recomendado: $25,00** → saldo **$43,01**
  - 2,9× o cenário base;
  - 1,8× o stress;
  - 1,4× o cenário severo.

## 6. Notas

- Exclui aluguer de DIDs (7 números ≈ $7/mês), subscrições, impostos e
  encargos fora de `call-control` + `tts`.
- Exclui retries: `VOICE_RETRY_ENABLED=false`; se for ligado, acrescentar
  volume.
- Os tetos internos (`budget_daily_usd` = quota × 25¢) não param as campanhas
  antes da quota: o custo gravado é ~2¢/chamada, muito abaixo do teto.
- `VOICE_MAX_CALLS_PER_DAY=250` e pool de 6 DIDs em NY (50/dia por DID após
  warm-up) comportam a maior campanha (240).
- Se uma campanha não arrancar na data (ex.: 15/11 ou decisão sobre sábado), o
  custo desloca-se no tempo, não desaparece — exceto se for cancelada.
