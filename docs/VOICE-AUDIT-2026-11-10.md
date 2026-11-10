# Auditoria de voz B2B — 2026-11-10

Janela da auditoria: **08:07–08:15 ET** (13:07–13:15 UTC). Ações **read-only** em produção.
Nenhuma campanha, chamada ou configuração foi alterada durante a auditoria.

## 1. Agendamento, workers e timezone

- Não existe Celery/Bull/Redis para voz. O gatilho é um loop assíncrono interno:
  `_voice_campaign_resume_loop` (main.py), intervalo **300 s**.
- Processo de produção online; loop iniciado às **12:52:42 UTC / 07:52:42 ET**.
- Consequência dos ticks de 5 min: a campanha de hoje (due `14:00:00 UTC` =
  **09:00 ET**) será detetada no tick de **14:02:42 UTC / 09:02:42 ET**.
  - Início automático esperado: **~09:02:42 ET** (2m42s após 09:00).
  - Campanha de Dallas (due `15:00:00 UTC` = 10:00 ET) → **~10:02:42 ET**.
- Timezone está correta: `VOICE_CALL_START_HOUR=9`, `VOICE_CALL_END_HOUR=20`,
  `start_hour_et` das campanhas, timestamps `next_batch_at` em UTC e conversão
  EST/EDT correta. Hoje é EST (UTC-5).
- Serviço Railway: **Online**, uma instância. O controlo de tasks
  (`_voice_campaign_tasks`) é em memória, por processo; não há lock distribuído.
- **Risco de recuperação:** `mark_interrupted_campaigns` marca campanhas
  `running` como `status='error'` no arranque. O resume loop só retoma
  `status='paused'`; portanto um deploy/restart a meio de um lote **não
  retoma a campanha automaticamente**. Hoje não há campanha `running`, mas é
  um risco para o resto da semana.

## 2. Providers e conectividade

- Telnyx API: `phone_numbers` 200, `connection` 200, `assistant` 200.
- Connection `Magic Leads Voice` (`3084801788029699518`) ativa.
- Webhook configurado:
  `https://magic-leads-production.up.railway.app/api/voice/telnyx/webhook`.
  - Endpoint existe e devolve **403** sem assinatura (fail-closed).
  - Fallback MP3: `GET /api/voice/fallback.mp3` → **200**, `audio/mpeg`,
    253,056 bytes.
  - `webhook_event_failover_url` está **vazio** (sem failover de webhook).
- Credenciais presentes: `TELNYX_API_KEY`, `TELNYX_PUBLIC_KEY`,
  `TELNYX_WEBHOOK_SECRET`, `TELNYX_CONNECTION_ID`, DIDs.
- DIDs ativos e atribuídos à connection:
  - NY pool: `+19292562550`, `+19294480511`, `+19293571376`,
    `+19293571378`, `+19295567262`, `+19296280134`.
  - Dallas: `+14699607326`.
- Scripts: **15/15 aprovados**, todos com `assistant_id` Telnyx.
  `VOICE_SCRIPT_MODE=static`.
- AMD: `TELNYX_AMD_MODE=standard`.
- Telefonia hoje: 0 chamadas, 0 custo, 250 chamadas restantes no cap global.
- **Saldo Telnyx: $18.51 disponíveis.**
  - Média histórica: 328 chamadas / 594 cents ≈ **1,81¢/chamada**
    (máx. referência 2,2¢).
  - Quotas planeadas D2–D12: **1.940 chamadas** → ~**$35–$43**.
  - O saldo cobre ~1.022 chamadas a 1,81¢ ou ~841 a 2,2¢; deve esgotar-se
    entre **16 e 17 de novembro** se não houver recarga/auto-recharge.
  - **Ação crítica: recarregar Telnyx (sugestão: ≥ $50) antes da próxima
    semana.**

## 3. Cobertura, DIDs e agendas

### Hoje

- **Campanha 14 — NY 2W D2 130**:
  - status `paused`, due `2026-11-10T14:00:00+00:00` (09:00 ET);
  - 0/130 chamadas, `batch_size=130`, `include_fallback=0`,
    `call_interval_seconds=75`, orçamento $32.50/dia;
  - trade plan: remodeling 82, plumbing 15, electrical 14, hvac 4,
    remediation 4, painting 3, landscaping 3, windows 3, roofing 2.
- **Campanha 12 — Dallas Pilot**:
  - status `paused`, due `2026-11-10 15:00:00` (10:00 ET);
  - 41/43 chamadas; restam 2 (remodeling); orçamento $5/dia;
  - `include_fallback=1`, `call_interval_seconds=75`.

Simulação read-only às **09:05 ET**:
- `paused_campaigns_due` devolveu `[14]`; budget 14 `ok=True`;
- inventário callable por trade > 0 (remodeling 5.440, plumbing 978,
  electrical 952, hvac 281, remediation 271, painting 228, landscaping 187,
  windows 182, roofing 116);
- `campaign_candidates` + `can_call` devolveram `allowed=True` em todos os
  trades do plano.
- `voice_segments` mostra `callable=0` agora porque está fora da janela; o
  `ensure_segments_fresh` reconstrói às 09:00 (trigger `inside_window` +
  inventário existente). O dialer não depende de `callable` para escolher
  candidatos; o gate é avaliado por chamada.

Simulação às 10:05 ET:
- `paused_campaigns_due` devolveu `[14, 12]`;
- campanha 12 `ok=True`; restam 2 remodelings, com candidatos e gate
  `allowed=True`.

### Próximos dias

- Campanhas 15–24: pausadas, `next_batch_at` diário às **14:00 UTC = 09:00 ET**,
  quotas 150–240, orçamento $32.50–$60/dia, intervalo 75 s.
- Capacidade NY por DID:
  - hoje: 6 × 25 = **150** (campanha 130);
  - amanhã: 6 × 30 = **180** (campanha 150);
  - a partir de 12/11: 6 × 50 = **300** (máx. campanha 240).
  - **DIDs suficientes** para o plano.
- Dallas: 1 DID, cap 20 hoje; campanha 12 só 2 chamadas.
- **Campanha 18 (D6, 14/11) é sábado.** O código só valida hora, não dia da
  semana. Confirmar se chamadas de sábado são autorizadas; caso contrário,
  pausar/remover D6.
- Campanhas 3 e 4 estão `paused` com `next_batch_at=NULL` — dormentes para
  sempre. Não bloqueiam nada, mas devem ser fechadas/arquivadas para higiene.
- Não há campanhas `running` nem chamadas presas (`queued/dialing/in_call`).
  `voice_calls`: 325 `ended`, 3 `failed` (apenas `test_call` antigos).
- Duplicados de produção nos últimos 7 dias: **0**; os únicos duplicados são
  chamadas `test_call`.

## 4. Fallback e re-enfileiramento

- O webhook Telnyx trata AMD `machine`/`fax_detected`/`greeting.ended`:
  atualiza `intent='voicemail'`, `hangup_cause='voicemail_detected'` e desliga.
  Timeout/no-answer/busy são registados e a chamada termina.
- Áudio de fallback responde 200; o fluxo `stop assistant → playback MP3`
  existe e é idempotente (`claim_fallback_playback`).
- **Não existe retry/re-enfileiramento curto para voicemail, no-answer ou busy.**
  `campaign_candidates` exclui qualquer empresa com chamada Telnyx nos últimos
  7 dias e `skip_campaign_company` remove bloqueios da campanha. O comportamento
  atual é “cooldown de 7 dias”, não re-tentativa. Se o requisito é re-enfileirar,
  isso **não está implementado** e precisa de decisão de produto.

## 5. Veredito

- **Provider, credenciais, scripts, DIDs, webhook, fallback MP3 e inventário: OK.**
- **Hoje às 09:00: pronto para chamar**, mas o gatilho automático deve começar
  em **~09:02:42 ET**. Para pontualidade exata, usar **Resume** da campanha 14
  às 09:00 (a campanha 12 fica para as 10:00).
- **Bloqueios/riscos para a próxima semana:**
  1. Saldo Telnyx $18.51 insuficiente para as 1.940 chamadas planeadas
     (~$35–$43) — recarregar antes de 16/11.
  2. Nenhum retry para voicemail/no-answer/busy (cooldown de 7 dias).
  3. Reinício/deploy durante campanha running marca-a `error` e não retoma.
  4. Loop de retoma de 300 s introduz até ~5 min de atraso (hoje ~2m42s).
  5. Campanha de sábado (14/11) a confirmar.
- **CI:** `e1b5ed3` com `Import & Syntax Check` e `Frontend Type Check`
  verdes; suite backend local **1626 passed, 1 skipped**.
