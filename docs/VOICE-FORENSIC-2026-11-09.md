# Caixa preta — campanha de voz de 2026-11-09

Fonte primária: SQLite de produção (`voice_calls`, `voice_campaigns`) + Telnyx
Detail Records (`call-control` + `tts`). Janela: **00:00–24:00 ET de 09/11/2026**
(05:00 UTC 09/11 → 05:00 UTC 10/11). Auditoria read-only.

## 1. Contagem bruta

| Métrica | DB (09/11) | Campanha 13 (NY) | Campanha 12 (Dallas) |
|---|---:|---:|---:|
| Dialed | **121** | 110 | 11 |
| Answered (`answered_at`) | **104** | 96 | 8 |
| Human | **39** | 39 | 0 |
| Machine/voicemail | **61** | 53 | 8 |
| `not_sure` | **4** | 4 | 0 |
| Sem AMD / não atendida | **17** | 14 | 3 |
| Timeout | 15 | 14 | 1 |
| Busy | 2 | 0 | 2 |
| Failed / network | **0** | 0 | 0 |
| Custo DB (`cost_cents`) | **208¢ = $2.08** | 192¢ = $1.92 | 16¢ = $0.16 |

- **AHT humano**: 39 chamadas humanas, média **20,67 s** (5–49 s; total 806 s).
- **AHT de todas as atendidas**: 104 chamadas, média **10,83 s** (total 1.126 s).
- **Listen médio das 43 atendidas não-machine**: 22,63 s (total 973 s).
- A campanha 13 foi 110 chamadas; a campanha 12 foi 11. Total 121.

## 2. Reconciliação Telnyx (CDR)

Consulta: `record_type=call-control` e `record_type=tts`, `date_range=yesterday`.

### Call-control

- **137 registos**: **132 outbound** + **5 inbound**.
- Sessões únicas (`telnyx_session_id`): **126** = **121 outbound** + 5 inbound.
- 11 sessões outbound têm **2 leg records** (um connected + um unconnected) — não são chamadas duplicadas; as sessões únicas outbound são **121**, exatamente o DB.
- Outbound: **104 connected** e **17 unconnected** — exatamente `answered` e `não atendidas` do DB.
- Inbound: 5 registos, 0 s, custo 0 (não entram no dialer).
- `call_sec` total: 1.182 s; `billed_sec`: 6.240 s (104 min); custo call-control: **$0.208** (104 × $0.002).

### TTS

- **43 registos**, 22.755 caracteres, custo **$0.72816** (média $0.016934/registo).
- Os 43 registos correspondem às 43 chamadas não-machine atendidas (human + not_sure).

### Custo real total

| Componente | Custo |
|---|---:|
| Call-control | $0.20800 |
| TTS | $0.72816 |
| **Total CDR 09/11** | **$0.93616** |

Exclui aluguer de números, subscrições, impostos e eventuais encargos fora dos
record types acima. Não foram encontrados registos `ai-voice-assistant`,
`inference`, `stt`, `media-streaming` ou `recording` para o dia.

## 3. Painel vs raw

| Métrica | Raw DB 09/11 | Painel `live_dashboard(13)` | Divergência |
|---|---:|---:|---|
| Dialed | 121 | 110 (campanha 13) | OK por campanha |
| Answered | 104 | 96 (campanha 13) | OK |
| Human | 39 | 39 | OK |
| Voicemail/machine | 61 | 53 (campanha 13) | OK |
| not_sure | 4 | 4 | OK |
| Disconnected | 17 | 67 (`110 - 43`) | Definição: inclui voicemail; OK |
| Custo | **$2.08** | **$1.92 (13) + $0.16 (12)** | **2,22× acima do CDR** |
| Avg listen | 11,53 s (todas as 96) | 11,53 s | OK |
| AHT humano | **20,67 s** | não é AHT; `avg_listen`=11,53 s | rótulo/definição |
| Thermometer | 43 não-machine: 19 red / 14 yellow / 10 green | 19/14/10 | OK |
| Retenção ≥15 s | 24 (campanha 13) | `metrics(1d)`=25 | +1 por janela móvel |
| Retenção ≥30 s | 12 | 12 | OK |
| ≥60 / ≥90 s | 0 / 0 | 0 / 0 | OK |
| Tecla 2 / cliques / checkouts / receita | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | OK |

- `metrics(days=1)` é **24 h móveis**, não o dia civil de ontem. Às 09:05 ET de
  hoje já incluía as primeiras chamadas da campanha 14 (`123` dialed vs `121`),
  o que explica +2 dialed / +2 answered / +2¢ no painel.
- O painel **não mostra AHT humano**: `avg_listen` é a média de `listen_seconds`
  de todas as atendidas (inclui machine). O AHT humano real é 20,67 s.

## 4. Custo: causa da divergência

O código grava `cost_cents` com:

```python
ceil(duration/60) * TELNYX_COST_PER_MINUTE_CENTS
```

`TELNYX_COST_PER_MINUTE_CENTS` não está definido em produção → default **2
cent/min**. O CDR Telnyx mostra:

- call-control: **$0.002/min = 0,2 cent/min**;
- TTS: **$0.000032/caractere**, 43 registos, $0.72816.

Para as 104 chamadas, call-control real = 104 × $0.002 = $0.208; TTS =
$0.72816; total **$0.93616**. O DB somou 208¢ ($2.08), cerca de **2,22×** o
custo real. A campanha 12 (só voicemail, sem TTS) ficou **10×** acima
($0.16 vs $0.016).

Isto é uma **estimativa interna**, não bilhetagem Telnyx. Se o painel apresenta
“custo” como real, está incorreto. Correção recomendada: ler custo do CDR
Telnyx (call-control + tts) ou trocar a unidade para USD/min fracionário
(0,002) e somar TTS; não usar 2¢/min fixo.

## 5. Funil / Tecla 2

- `intent`: campanha 13 → 53 `voicemail`, 57 vazio; campanha 12 → 8
  `voicemail`, 3 vazio. Não há `website_redirect`, `meeting_booked`,
  `callback`, `opt_out` ou `not_interested`.
- `showcase_clicked_at`, `checkout_session_id`, `revenue_cents`: **0**.
- Portanto **0 conversões/Tecla 2** registadas; o painel também mostra 0. Não
  há divergência de conversão — apenas ausência real de interação.
- Retenção (não-machine, 43): 19 <15 s, 14 entre 15–39 s, 10 ≥40 s;
  ≥15 s = 24; ≥30 s = 12; ≥60 s = 0. Bate com o thermometer do painel.

## 6. Conclusão forense

- **Contagem de chamadas: consistente.** 121 outbound únicos no Telnyx = 121 no
  DB; 104 connected = 104 answered; 17 unconnected = 17 não atendidas.
- **Custo: divergente.** Painel/DB $2.08 vs Telnyx CDR **$0.93616**
  (call-control + TTS). Causa: estimativa fixa de 2¢/min e TTS não contabilizado.
- **AHT: definição divergente.** Painel mostra `avg_listen` de todas as
  atendidas (11,53 s); AHT humano real é **20,67 s**.
- **Retenção/thermometer: consistente** para a campanha 13. `metrics(1d)` é
  janela móvel e inclui chamadas de hoje; não deve ser lida como “ontem”.
- **Tecla 2/conversões: 0 reais e 0 no painel.**
- **Sem chamadas failed/network no dia.**

Raw por chamada: `docs/voice-2026-11-09-calls.csv` (121 linhas, sem telefone
nem nome de empresa).
