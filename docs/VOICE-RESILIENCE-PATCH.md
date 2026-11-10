# Patch de resiliência de voz — isolado (sem deploy)

Data: 2026-11-10 · Base: `master` (`e1b5ed3`) · Destino: branch de revisão.

## 1. Retoma de campanhas interrompidas por restart

- `b2b_voice.mark_interrupted_campaigns` deixou de marcar campanhas `running`
  como `status='error'` definitivo.
- Agora marca `status='paused'`, `error='campanha interrompida...'`,
  `next_batch_at = agora + VOICE_INTERRUPTED_RESUME_DELAY_SECONDS` e mantém
  `calls_started`/quotas intactos.
- O resume loop retoma a campanha no próximo tick, continuando o lote no ponto
  em que ficou (o contador de chamadas já feitas é preservado).
- Novo env: `VOICE_INTERRUPTED_RESUME_DELAY_SECONDS` (default **120**).
- Teste: `test_campanha_interrompida_e_reagendada_no_arranque`.

## 2. Intervalo de retoma 30 s

- `VOICE_CAMPAIGN_RESUME_INTERVAL_SECONDS` default passou de **300** para
  **30**.
- O loop lê o valor no arranque; para aplicar em produção é necessário
  redeploy/restart (não feito).
- Efeito esperado: o atraso máximo entre o `next_batch_at` e o arranque passa
  de ~5 min para ≤30 s.

## 3. Política de retry (default OFF)

- Novo bloco em `b2b_voice._retry_candidates`, integrado em
  `campaign_candidates`.
- Default: `VOICE_RETRY_ENABLED=false` — comportamento atual mantido
  (cooldown global de 7 dias para qualquer chamada Telnyx).
- Quando ligado:
  - só retoma contactos **do mesmo lote**;
  - apenas desfechos transitórios: `amd_result` machine/not_sure,
    `hangup_cause` timeout/user_busy/no_answer ou `intent=voicemail`;
  - exige que a última chamada seja mais antiga que
    `VOICE_RETRY_DELAY_HOURS` (default **48**);
  - máximo de `VOICE_RETRY_MAX_ATTEMPTS` chamadas por contacto no lote
    (default **2**, ou seja, uma repetição);
  - nunca retoma contacto com human/meeting/callback/opt-out/not_interested/
    wrong_number, nem contacto chamado por outra campanha nos últimos 7 dias;
  - respeita `voice_campaign_skips` e o gate `can_call` (DNC, horário, etc.);
  - retries só preenchem capacidade quando não há candidatos novos suficientes.
- Teste: `test_retry_policy_is_off_by_default_and_adds_transient_candidates`.

## Ativação (depois de aprovação)

1. Revisão de código + CI verde na branch.
2. Testes em staging, com `VOICE_FREEZE=1`, simulando restart e retry.
3. Deploy fora da janela 09:00–20:00 (idealmente antes das 09:00 ou após as
   20:00).
4. Configurar em produção apenas se desejado:
   - `VOICE_INTERRUPTED_RESUME_DELAY_SECONDS=120`
   - `VOICE_CAMPAIGN_RESUME_INTERVAL_SECONDS=30`
   - `VOICE_RETRY_ENABLED=false` (manter off até decisão de produto)
5. Rollback: manter `VOICE_RETRY_ENABLED=false` e, se necessário, voltar a
   `VOICE_CAMPAIGN_RESUME_INTERVAL_SECONDS=300`; nenhum schema é alterado.

## Testes executados no patch

- Testes focados:
  - retry default off + retry ativo com contacto transitório;
  - campanha interrompida → paused e due no resume.
- Suite de voz (`auto_dialer`, `b2b_voice`, `voice_live`, `telnyx_voice`,
  `voice_scripts`, `voice_freeze`): **120 passed** numa execução limpa.
- `ruff` nos ficheiros alterados: limpo.
