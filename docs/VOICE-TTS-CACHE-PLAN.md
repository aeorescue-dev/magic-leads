# Plano — pré-renderização e cache de TTS

Data: 2026-11-10. Estado: **proposta**, sem alteração de produção.

## Problema atual

No modo `static`, cada chamada atendida por humano faz
`gather_using_speak` com `payload = greeting`. A Telnyx sintetiza o texto
**naquele momento**.

- Custo: **$0.52378** em 32 chamadas hoje (16.403 caracteres) = **$0.0164
  por chamada**; ~81% do custo total.
- Latência: TTS criado **1,3–6,2 s** após `answered_at` (dados de 09/11),
  antes de tocar. Risco de dead air >2 s (47 CFR 64.1200(a)(7)(ii)).

## Opções

### A. Pré-sintetizar por chamada (sem cache)

Gerar o áudio ao criar a chamada (antes de atender), guardar por `hash(texto)`
e usar `gather_using_audio`.

- Elimina o dead air.
- **Não** reduz o custo: o texto inclui o nome da empresa, logo é único por
  chamada.

### B. Cache por trade/cidade/contagem (recomendado)

Remover o nome da empresa do áudio (ou torná-lo opcional) e gerar **um áudio
por trade + cidade + contagem**. Reutilizar em todas as chamadas do lote.

- Custo: ~9 áudios/dia em vez de ~130 → **~93–97% menos TTS**.
- Exemplo: 9 trades × 500 caracteres = 4.500 caracteres = **$0.144/dia**,
  reutilizado por 130 chamadas → **$0.0011/chamada**.
- Perda: menos personalização ("Hi {company}").

### C. Híbrido

Áudio estático por trade/cidade + segmento curto com o nome da empresa
gerado por chamada. Reduz parcialmente o custo; complexidade maior.

### D. TTS local (Piper/Coqui)

Custo marginal zero, mas muda a voz/qualidade e exige hospedagem. Avaliar
separadamente.

## Recomendação

**B + A**: cache por trade/cidade/contagem, pré-aquecido no arranque da
campanha, com fallback para `gather_using_speak`.

- Manter o nome da empresa apenas se o teste A/B mostrar ganho de retenção
  que justifique o custo; caso contrário, remover.
- Feature flag `VOICE_TTS_CACHE_ENABLED=false` (default OFF).
- O áudio é servido por URL HTTPS pública (backend static ou S3/R2) e
  reproduzido com `gather_using_audio` (`valid_digits="2"`).

## Implementação proposta

1. Novo módulo `backend/services/voice_audio_cache.py`:
   - `cache_key(text) -> sha256`;
   - `get_or_create(text) -> {"url","path","chars","created_at","hit"}`;
   - síntese via API TTS da Telnyx (mesma voz `Telnyx.Ultra...`);
   - armazenamento em `backend/static/voice_cache/{sha}.mp3`;
   - tabela `voice_tts_cache` (hash, texto, chars, path, hits, created_at).
2. `telnyx_voice._start_static_script_for_call`:
   - se a flag estiver ligada e o áudio existir → `gather_using_audio`;
   - senão → `gather_using_speak` (comportamento atual).
3. Pré-aquecimento no arranque da campanha:
   - para cada trade do `trade_plan`, renderizar o texto com a contagem atual
     e gerar o áudio em falta;
   - mostrar no log `cache_hit` / `cache_miss`.
4. Métricas:
   - `tts_cache_hits`, `tts_cache_misses`, `tts_cost_cents`, `dead_air_ms`.
5. Limpeza: TTL de 30 dias; invalidar quando o texto/versão do script mudar.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| `gather_using_audio` com DTMF 2 | Testar em staging com `VOICE_FREEZE=1` |
| Voz diferente da atual | Usar a mesma `voice_id`/modelo Telnyx |
| URL/CDN lenta | Servir do backend com cache imutável; medir latência |
| Texto muda (script/contagem) | Chave = hash do texto; regenerar |
| Perda de personalização | Teste A/B com e sem nome da empresa |
| Compliance | O áudio continua a ser pré-gravado; mantém as regras do script |

## Rollout

1. Implementar na branch isolada `feat/voice-tts-cache` (sem deploy).
2. Testes unitários + staging com `VOICE_FREEZE=1`.
3. Deploy fora da janela 09:00–20:00, com a flag OFF.
4. Ativar primeiro numa campanha pequena; comparar custo, dead air e retenção.
5. Rollback: desligar a flag (volta a `gather_using_speak`).

## Impacto estimado

| Cenário | TTS/dia | Por chamada |
|---|---:|---:|
| Atual (por chamada) | ~$0.52 para 32 | $0.0164 |
| Cache por trade/cidade (9 áudios) | ~$0.14 | ~$0.0011 |
| Redução | **~73% no dia** / **~93% por chamada** | — |

O custo de call-control ($0.002/chamada conectada) não muda.
