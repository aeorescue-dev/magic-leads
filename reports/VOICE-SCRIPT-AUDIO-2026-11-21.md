# Roteiro de voz e audio MP3 — estado atual e preparacao (2026-11-21)

**Modo:** leitura + preparacao de codigo. `VOICE_FREEZE=1` mantido; nenhuma
chamada nem SMS real. Backend em producao antes deste ajuste: `f6828da`.

---

## 1. Texto exato que esta no ar

Fonte: `voice.db` → `voice_scripts` (15 trades, **version 4**, `status=approved`,
`approved_at=2026-11-07T01:39:31Z`). `voice_meta.scripts_template_version =
2026-11-06.1` (V3). Os 15 trades partilham o mesmo corpo:

> Hi {{company | Contractor}}. This is an automated message from Magic Leads in
> New York. We just unlocked {{count}} active opportunities in your trade right
> now on magicleads.app. While shared lead apps sell the same contact to five
> local contractors and eat into your margins, we give you the owner's direct
> name, verified address, and job details 5 to 7 days before anyone else in your
> area. You just call, visit, or send a letter, and close the deal before your
> competitors do. Go to magicleads.app right now. **To opt out, press 2.**

Substituicoes em tempo de render:
- `{{company | Contractor}}` → **`there`** no modo `shared` (ou o nome da empresa
  no modo `dial`);
- `{{count}}` → contagem verificada do trade exato (o guard exige scope `trade`;
  sem inventario suficiente a chamada e bloqueada).

**Dallas** tem 15 overrides `status=approved` com precedencia sobre o global;
usam `{{showcase_line}}` ou `{{count}}` e terminam igualmente em
“To opt out, press 2.”.

> **Importante:** o texto com “press 1” **nao esta no ar**. O codigo chegou a
> ter essa frase na v5, mas o `voice_meta` continuava em `2026-11-06.1` e o
> `init()` nao correu. Reverti o template/instrucoes para o V3 aprovado para
> evitar que a primeira chamada aplicasse um guiao nao revisto.

### Teclas e confirmacoes de voz

| Evento | Texto falado |
|---|---|
| Tecla **1** (SMS) | sucesso: “We've texted the link to this number. Goodbye.” |
| Tecla **1** (bloqueado) | “We couldn't send the text right now. Visit MagicLeads dot app to see this week's active opportunities.” |
| Tecla **2** (opt-out) | “You've been removed from our list. Goodbye.” |
| Sem digitos / fim do gather | desliga (test call mantem a linha) |
| Fallback de audio | `backend/static/voice_fallback.mp3` (253.056 B), usado no modo assistant para website_redirect |

`gather` aceita **1 e 2** (`valid_digits="12"`), mas o guiao atual so anuncia a
tecla 2 — os callers nao sabem da tecla 1 ate o novo texto ser aprovado.

### SMS atual

> Magic Leads: here is the link you requested during your call:
> https://magicleads.app. Reply STOP to opt out, HELP for help. Msg&data rates
> may apply.

---

## 2. Como o audio e reproduzido hoje

`VOICE_SCRIPT_MODE=static` + cache TTS (`VOICE_TTS_CACHE_ENABLED=1`,
`VOICE_TTS_CACHE_MODE=shared`, voz `Telnyx.Ultra.00a77add-...`,
`VOICE_TTS_CACHE_TTL_DAYS=14`).

1. **No dial** (`create_call`): renderiza o greeting e chama
   `voice_audio_cache.get_or_create(texto)`.
2. **Cache hit**: usa o MP3 existente em `/data/voice_cache/<hash>.mp3`
   (`hash = sha256(voz + "\n" + texto)`), servido em
   `/api/voice/tts/<hash>.mp3`.
3. **Cache miss**: sintetiza **uma vez** via REST TTS da Telnyx
   (`POST /v2/text-to-speech/speech`), grava o MP3 e regista em
   `voice_tts_cache` (chars, bytes, hits).
4. **No atendimento**: se `tts_url`/`tts_hash` e o ficheiro existir →
   **`gather_using_audio`** (sem sintese por chamada); caso contrario →
   `gather_using_speak` (TTS in-call).

Amostra real do cache: `c57062ee...` — 507 chars, 548.736 B, **41 hits**,
ultimo uso 2026-11-16. Ha varios hashes (506–509 chars) porque o texto varia
com `{{count}}`/`{{showcase_line}}`.

**Custo:** a sintese paga-se uma vez por texto unico; por chamada so se paga o
audio ja servido (milésimos de centavo), como antes.

---

## 3. Preparacao para o novo texto + MP3 estatico

Implementado neste ciclo:

- `voice_tts_cache.pinned` (nova coluna, `ALTER` para bases antigas). O
  `cleanup` por TTL **ignora** os MP3 com `pinned=1`.
- `voice_audio_cache.get_or_create(text, pin=...)` e `pin(hash)`.
- O modo `shared` passa a **pin automaticamente** o MP3 do greeting no dial.
- Script operacional:
  `python -m backend.scripts.prerender_voice_script --trade plumbing --city Dallas`
  (ou `--text-file novo.txt` para um texto exato).
  Devolve `hash`, `url`, `chars`, `bytes`, `pinned`.

**Para um unico MP3 em todas as chamadas**, o novo texto nao deve conter
placeholders por chamada (`{{company}}`, `{{count}}`, `{{showcase_line}}`);
caso contrario cada variante gera um hash/MP3 diferente. Um texto fixo (com
tecla 1 e tecla 2) gera **um** MP3, pré-renderizado e pinned.

### Quando o novo texto chegar

1. Atualizar `voice_scripts` (template/override) e `TEMPLATE_VERSION`; aprovar.
2. Correr o `prerender_voice_script` em producao → MP3 `pinned=1`.
3. Confirmar `hash/url` e o `voice_tts_cache` (1 registo, `pinned=1`).
4. Manter `VOICE_FREEZE=1` ate autorizacao do teste unico.

---

## 4. Estado

- Script em producao: **V3 antigo** (so tecla 2) — inalterado.
- Tecla 1/SMS: implementada e bloqueada por `VOICE_FREEZE` e campanha
  `TCR_ACCEPTED` (ainda nao `ACTIVE`).
- Preparacao de MP3 estatico/pinned: implementada e testada (65 testes
  dirigidos verdes; suite completa em validacao).
