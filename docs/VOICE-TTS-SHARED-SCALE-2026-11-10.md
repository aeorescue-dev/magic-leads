# Modo shared + escala de volume — projeção

Data: 2026-11-10. Base: campanha 14 fechada (125 chamadas). Branch
`feat/voice-tts-cache`. **Sem deploy.**

## 1. Alteração de texto

Apenas a primeira frase muda:

- Antes: `Hi {company}. This is an automated message from Magic Leads in New York...`
- Depois: `Hi there. This is an automated message from Magic Leads in New York...`

O resto do corpo (contagem, proposta, website, opt-out) fica **100% igual**.
A alteração é feita em runtime pelo modo `shared` (`VOICE_TTS_SHARED_NAME=there`),
sem editar o template na base de dados. O fallback também usa `there`.

## 2. Custo real da campanha 14 (125 chamadas)

| Componente | Valor |
|---|---:|
| Call-control (100 conectadas × $0.002) | $0.20000 |
| TTS (53 registos, 26.919 caracteres) | $0.86029 |
| **Total** | **$1.06029** |
| Por chamada discada | $0.00848 |

## 3. Custo no modo shared

- TTS: um áudio por **trade + cidade + contagem**. Na campanha 14 foram 7
  trades → ~$0.115/dia. Com margem para regeneração, **~$0.15/dia**.
- Call-control: **$0.0016 por chamada discada** (80% de atendimento, chamadas
  <60 s).

`custo(N) = 0.0016 × N + 0.15`

| Volume/dia | Call-control | TTS | Total | vs. $1.060 | Volume vs. 125 |
|---:|---:|---:|---:|---:|---:|
| 125 | $0.200 | $0.150 | **$0.350** | −67% | — |
| 250 | $0.400 | $0.150 | **$0.550** | −48% | +100% |
| **300** | **$0.480** | **$0.150** | **$0.630** | **−41%** | **+140%** |
| 400 | $0.640 | $0.150 | **$0.790** | −25% | +220% |
| 500 | $0.800 | $0.150 | **$0.950** | −10% | +300% |
| 569 | $0.910 | $0.150 | **$1.060** | 0% (break-even) | +355% |

O break-even teórico é ~569 chamadas/dia. Mas há limites operacionais.

## 4. Limites reais

### 4.1 Cap diário

- Produção: `VOICE_MAX_CALLS_PER_DAY=250`.
- Para 300: subir para **300**.
- Para 400: subir para **400**.

### 4.2 DIDs (capacidade)

- Pool de NY: **6 números**; `VOICE_DID_DAILY_CAP=50` → **300/dia**.
- 300/dia **não exige novos números**.
- 400/dia exige **+2 DIDs** (8 × 50).
- DIDs novos têm warm-up 20/25/30 nos primeiros dias.

### 4.3 Janela e pacing

O intervalo é 75 s + jitter, com pausa de 10 min a cada 25 chamadas.
Ritmo efetivo observado: **~95 s/chamada**.

| Volume | Tempo estimado | Cabe em 09:00–20:00? |
|---:|---:|---|
| 125 | 3h18 | sim |
| 250 | 6h36 | sim |
| **300** | **7h55** | **sim** |
| 400 | 10h33 | no limite |
| 500 | 13h12 | **não** |

### 4.4 Inventário elegível

Candidatos elegíveis na campanha 14 (10:56 ET, após DNC/cooldown):

| Trade | Elegíveis |
|---|---:|
| remodeling | 1.000 (limite de consulta) |
| plumbing | 965 |
| electrical | 930 |
| hvac | 407 |
| remediation | 282 |
| painting | 199 |
| windows | 168 |

- A 300/dia, o pool cobre ~13 dias; a 400/dia, ~10 dias.
- O plano atual é **63% remodeling**. A 300/dia, remodeling sozinho seria
  ~189/dia e esgotaria os 1.000 elegíveis em ~5 dias.
- Para escalar com segurança: rebalancear o mix e garantir reposição diária
  dos scrapers.

## 5. Recomendação

**Fase 1: 300/dia.**

- 2,4× o volume atual (125 → 300).
- Custo ~**$0.63/dia** (−41% vs. $1.06).
- Não exige DIDs novos.
- Cabe na janela (7h55).
- Requer subir `VOICE_MAX_CALLS_PER_DAY` de 250 para 300.
- Rebalancear o `trade_plan` das campanhas 15–24 para não concentrar em
  remodeling.

**Fase 2: 400/dia** (opcional, após 1–2 semanas).

- Comprar +2 DIDs e subir o cap para 400.
- Custo ~$0.79/dia (−25%).
- Pacing no limite (10h33); qualquer atraso passa das 20:00.

**500+/dia:** inviável com o pacing atual. Exigiria 10 DIDs e/ou reduzir a
pausa de 10 min, o que aumenta risco de complaints.

## 6. Ativação

1. Deploy da branch fora da janela 09:00–20:00 (hoje após 20:00 ET ou antes
   das 09:00 de amanhã).
2. Definir:
   - `VOICE_TTS_CACHE_ENABLED=1`
   - `VOICE_TTS_CACHE_MODE=shared`
   - `VOICE_TTS_SHARED_NAME=there`
   - `VOICE_MAX_CALLS_PER_DAY=300`
3. Testar com `test_call` e uma campanha pequena.
4. Monitorizar:
   - logs `[TTS-CACHE] synth/hit`;
   - `GET /api/voice/tts/{hash}.mp3` → 200;
   - TTS no CDR (~$0.15/dia);
   - `answered_at` → `call.playback.started`;
   - complaints/labeling das operadoras.
5. Rollback: `VOICE_TTS_CACHE_ENABLED=0` + restart.

## 7. Nota de compliance

O aumento de volume amplia a exposição já documentada (TCPA/consentimento e
AUP da Telnyx sobre chamadas não solicitadas). O modo shared reduz custo e
dead air, mas não resolve esse bloqueador.
