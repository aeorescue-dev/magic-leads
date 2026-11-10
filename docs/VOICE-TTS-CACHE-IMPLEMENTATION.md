# Implementação — cache/pré-renderização de TTS

Data: 2026-11-10. Branch: **`feat/voice-tts-cache`** (base `master` `e1b5ed3`).
Estado: implementado e testado localmente. **Não deployado.**

## O que foi feito

| Ficheiro | Alteração |
|---|---|
| `backend/services/voice_audio_cache.py` | Novo módulo: síntese REST TTS, cache em disco, tabela `voice_tts_cache`, prewarm, stats, cleanup |
| `backend/services/telnyx_voice.py` | `create_call` pré-sintetiza e injeta `tts_url`/`tts_hash` no `client_state`; `_start_static_script_for_call` usa `gather_using_audio` com fallback para `gather_using_speak` |
| `backend/main.py` | `GET /api/voice/tts/{hash}.mp3` serve o MP3 com cache imutável |
| `backend/config.py` | Flags `VOICE_TTS_CACHE_*` (default OFF) |
| `backend/services/auto_dialer.py` | Prewarm dos áudios partilhados no arranque (modo `shared`) |
| `tests/test_voice_audio_cache.py` | Testes do cache, hit/miss, prewarm, stats, clear |
| `tests/test_telnyx_voice.py` | Testes de `gather_using_audio`, fallback e `tts_url` no `client_state` |

## Modos

| `VOICE_TTS_CACHE_MODE` | Texto | Dead air de síntese | Custo TTS |
|---|---|---|---|
| `dial` (default) | Atual, com nome da empresa | **eliminado** | **sobe** (~2,4×) |
| `shared` | "Hi there." (sem nome) | **eliminado** | **cai** (~80%) |

### Porquê o custo sobe no `dial`

O REST TTS custa o mesmo por caractere que o TTS in-call
(**$0.000032/caractere**, confirmado no CDR). No modo `dial` o texto inclui o
nome da empresa, logo é único por chamada; o cache não reutiliza nada e passa a
sintetizar **todas** as chamadas discadas, incluindo máquinas e não atendidas.

Com os dados de hoje (118 discadas, 49 sínteses, $0.809):

- `dial`: 118 × $0.0165 ≈ **$1.95/dia** (+$1.14)
- `shared`: ~9 variantes × ~530 caracteres ≈ **$0.15/dia** (−$0.66)

### Porquê o `shared` reduz

O texto deixa de ter o nome da empresa. O mesmo MP3 é reutilizado em todas as
chamadas do mesmo trade/cidade/contagem. O prewarm no arranque gera os ~9
áudios antes da primeira chamada.

## Flags

| Variável | Default | Nota |
|---|---|---|
| `VOICE_TTS_CACHE_ENABLED` | `false` | interruptor mestre |
| `VOICE_TTS_CACHE_MODE` | `dial` | `dial` ou `shared` |
| `VOICE_TTS_CACHE_DIR` | `/data/voice_cache` | volume persistente |
| `VOICE_TTS_CACHE_BASE_URL` | `PUBLIC_API_URL` | base do URL público |
| `VOICE_TTS_VOICE` | `TELNYX_ASSISTANT_VOICE` | mesma voz |
| `VOICE_TTS_CACHE_TTL_DAYS` | `30` | limpeza |
| `VOICE_TTS_TIMEOUT_SECONDS` | `20` | timeout da síntese |
| `VOICE_TTS_MAX_CHARS` | `3000` | limite por áudio |

## Ativação (fora do pico)

1. Revisão da branch + CI verde.
2. Deploy fora da janela 09:00–20:00, com `VOICE_FREEZE=1` durante o restart.
3. Definir:
   - `VOICE_TTS_CACHE_ENABLED=1`
   - `VOICE_TTS_CACHE_MODE=dial` (sem mudar texto) **ou** `shared` (muda o texto)
4. Testar com `test_call` e depois uma campanha pequena:
   - logs `[TTS-CACHE] synth/hit`;
   - `GET /api/voice/tts/{hash}.mp3` → 200;
   - `gather_using_audio` nos webhooks;
   - custo TTS no CDR;
   - tempo `answered_at` → `call.playback.started`.
5. Rollback: `VOICE_TTS_CACHE_ENABLED=0` + restart. O código volta a
   `gather_using_speak` sem perda de dados.

## Limitações importantes

1. **O AMD continua no caminho.** O pré-render elimina a síntese (1,3–6,2 s
   medidos), mas o AMD ainda introduz ~2–4 s antes do áudio. Para "instantâneo"
   absoluto seria preciso tocar no `call.answered` (fala para voicemail) ou
   desativar o AMD — decisão de produto/compliance, não feita.
2. **O modo `dial` aumenta o custo** com o texto atual. A redução de custo só
   existe no `shared` (sem nome da empresa) ou num híbrido futuro (áudio
   estático + nome concatenado).
3. **O modo `shared` altera a fala** de "Hi {company}" para "Hi there". Não
   ativar sem aprovação do texto.
4. O endpoint do MP3 tem de ser público e o volume `/data` tem de persistir.
5. A tabela `voice_tts_cache` é criada automaticamente no `voice.db`.

## Testes

- `tests/test_voice_audio_cache.py`: 7 testes.
- `tests/test_telnyx_voice.py`: `gather_using_audio`, fallback e `tts_url`.
- Suite completa: **1635 passed, 1 skipped**.
- `ruff`: limpo nos ficheiros alterados.

## Recomendação

- Para resolver o dead air **sem mexer no texto**: ativar `dial` fora do pico,
  aceitando +~$1.14/dia de TTS.
- Para **reduzir custo**: aprovar o modo `shared` ("Hi there") ou autorizar o
  híbrido (nome preservado + áudio estático concatenado) numa fase 2.
