# Auditoria real da Campanha #5 — 50 chamadas NYC

**Data da auditoria:** 2026-11-05  
**Fonte:** `/data/voice.db` em produção, leitura direta (sem interface).  
**Campanha:** `id=5`, `Piloto V3 50 NY Multi 2026-11-05`, `completed`.

---

## 1. Resumo executivo

| Métrica | Valor |
|---|---:|
| Chamadas criadas | 50 |
| Estados finais | 50 `ended` |
| Atendidas pelo carrier (`answered_at`) | 42 (84%) |
| **Humanos reais** (AMD `human`) | **17** (34%) |
| AMD `not_sure` | 3 (6%) |
| **Voicemail** (AMD `machine`) | **22** (44%) |
| Sem resposta | 8 (16%) — 7 `timeout` + 1 `user_busy` |
| **Opt-outs reais (tecla 2)** | **0** |
| DTMF 1/2 registados | 0 |
| Vitrines enviadas | 0 |
| Falhas TTS registadas | 0 |
| Custo no DB (`cost_cents`) | 84¢ |
| Custo real CDR Telnyx | $0,7375 |

**Divisão por nicho:** 25 HVAC + 25 Remodeling. O bug do auto-dialer está confirmado: o `trade_plan` previa 10 trades, mas o lote foi consumido pelos dois primeiros.

---

## 2. Performance real das 50 chamadas

### 2.1 Funil bruto

| Bucket | Chamadas | % das 50 |
|---|---:|---:|
| Fluxo de áudio provavelmente completo (≥45 s) | **6** | 12% |
| Humano desligou a meio (7–24 s) | **14** | 28% |
| Voicemail detetado e desligado (2–5 s) | **22** | 44% |
| Sem resposta (0 s) | **8** | 16% |

> **Limitação importante:** não existe um evento `audio_completed` na BD. O `gather.ended` apenas desliga a chamada; `status` fica sempre `ended`. A classificação acima é inferida pela duração e pelo AMD. O template antigo tem ~45 s; chamadas ≥45 s são “provavelmente completas”.

### 2.2 Os 6 casos prováveis de áudio completo

| ID | Nicho | AMD | Duração | Hangup |
|---:|---|---|---:|---|
| 67 | HVAC | `not_sure` | 51 s | `normal_clearing` |
| 68 | HVAC | `human` | 47 s | `normal_clearing` |
| 88 | HVAC | `not_sure` | 52 s | `normal_clearing` |
| 91 | Remodeling | `not_sure` | 50 s | `normal_clearing` |
| 92 | Remodeling | `human` | 48 s | `normal_clearing` |
| 95 | Remodeling | `human` | 49 s | `normal_clearing` |

**Padrão:** não há chamadas entre 25 s e 46 s. Ou o humano desliga nos primeiros 24 s, ou fica até ao fim (47–52 s). Dos 20 humanos/`not_sure`, **6 completaram (30%)** e **14 desligaram antes de 25 s (70%)**.

### 2.3 Os 14 humanos que desligaram a meio

IDs: `69, 70, 71, 76, 78, 79, 86, 90, 93, 101, 104, 106, 107, 112`  
Durações: 7, 9, 9, 10, 10, 11, 13, 13, 14, 15, 20, 22, 23, 24 s.  
Todos com `amd_result='human'` e `hangup_cause='normal_clearing'`.

### 2.4 Voicemail

22 chamadas com `amd_result='machine'`, `intent='voicemail'`, duração 2–5 s.  
**Nenhuma mensagem foi deixada:** o handler de AMD desliga imediatamente ao detetar máquina. “Voicemail” no painel significa “detetado e desligado”, não “mensagem entregue”.

### 2.5 Sem resposta

| ID | Causa |
|---:|---|
| 66, 83, 84, 89, 97, 102, 114 | `timeout` |
| 98 | `user_busy` |

### 2.6 Opt-outs e DTMF

- `intent='opt_out'`: **0**.
- `status='opt_out'`: **0**.
- `voice_suppressions` com `caller_opt_out`: **1 em todo o sistema**, mas pertence à **Campanha #4**, chamada 53 (Radant Plumbing & Heating, 285 s). Não é da #5.
- Nenhum `website_reminder` (tecla 1).
- Conclusão: **ninguém pressionou 2 na #5**. Também não há registo de ninguém a pressionar 1.

---

## 3. Divisão por nicho

| Nicho | Chamadas | Atendidas | Voicemail | Humano | `not_sure` | Sem resposta | ≥45 s | <45 s | Opt-outs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HVAC | 25 | 21 | 11 | 8 | 2 | 4 | 3 | 7 | 0 |
| Remodeling | 25 | 21 | 11 | 9 | 1 | 4 | 3 | 7 | 0 |
| **Total** | **50** | **42** | **22** | **17** | **3** | **8** | **6** | **14** | **0** |

Distribuição dos `hangup_cause`:

| Causa | HVAC | Remodeling | Total |
|---|---:|---:|---:|
| `normal_clearing` | 21 | 21 | 42 |
| `timeout` | 4 | 3 | 7 |
| `user_busy` | 0 | 1 | 1 |

Não há `static_tts_failed`, `render_failed`, `missing_assistant` nem `assistant_start_failed`.

---

## 4. O que o painel admin está a mostrar mal

### 4.1 O KPI principal é global de 30 dias, não da #5

O `/admin/voice` arranca com `metricsDays=30`. O endpoint `/api/admin/voice/metrics` não aceita `campaign_id`. Resultado:

| KPI | Painel 30 d | #5 real |
|---|---:|---:|
| Discadas | **83** (campanhas 3+4+5) | **50** |
| Atendidas | **69** | **42** |
| Engajadas (≥30 s) | **12** | **6** |
| Aceites | **1** | **0** |
| Cliques | **1** | **0** |
| Custo | **$1,72** | **$0,84 DB / $0,7375 CDR** |

O único “aceite” e o único “clique” vêm da **Campanha #4, chamada 57**, não da #5. Sem filtrar “1 dia”, o painel mistura V2/V3 e três campanhas.

### 4.2 “Atendidas” inclui voicemail

`answered_at` é gravado no evento `call.answered`, **antes** do AMD. As 22 máquinas contam como “atendidas”. O painel diz **42/50 = 84%**; o humano real é **17/50 = 34%** (ou 20/50 = 40% incluindo `not_sure`). A taxa de resposta está inflacionada em ~44–50 p.p.

### 4.3 “Drop / Voicemail” é só “sem resposta”

O valor mostrado é `drop_rate = (discadas − atendidas) / discadas` = **16% (8 chamadas)**. As 22 voicemails estão dentro das “atendidas” e não aparecem. O label sugere voicemail, mas o número só conta timeouts/busy.

### 4.4 “Voice Accept” é 0 por desenho

A V3 estática só tem **tecla 2** (opt-out). Não há tecla 1 nem `intent='showcase'` no fluxo estático. O cartão mostra “Aceite (1/Yes)” e 0 — não é falha de conversão, é uma métrica que não se aplica à V3.

### 4.5 “Showcase CTR” é 0 por desenho

A V3 não cria link por chamada nem grava `showcase_clicked_at`. O 0 não significa “ninguém clicou”; significa “não há mecanismo de clique”. O clique de 30 d é da campanha #4.

### 4.6 “Listen médio” é duração da chamada, não áudio ouvido

`listen_seconds = duration_seconds` para atendidas. As 22 voicemails de 2–5 s entram na média. A #5 mostra **13,4 s**, mas:
- 6/42 ≥45 s;
- 11/42 ≥15 s;
- 6/42 ≥30 s;
- 0/42 ≥60 s.

Se o denominador fosse só humanos/`not_sure` (20):
- 11/20 = **55%** ouviram ≥15 s;
- 6/20 = **30%** ouviram ≥30 s;
- 6/20 = **30%** chegaram ao fim.

O painel dilui a retenção com 22 voicemails.

### 4.7 Não há estado de “áudio completo”

Todos os 50 registos estão `status='ended'`. O `gather.ended` handler não grava um estado de conclusão. `normal_clearing` cobre tanto quem ouviu tudo como quem desligou aos 7 s. Sem `audio_completed_at` ou um event log, a conclusão é inferida pela duração.

### 4.8 O custo do painel não é o CDR

`cost_cents = ceil(duration/60) * 2` (Call Control), não o custo real Telnyx. Para a #5:
- DB: **84¢**;
- CDR real: **$0,7375**;
- o painel sobrestima ~14%.

Além disso, chamadas sem resposta ficam com `cost_cents=0`, embora a Telnyx possa cobrar o attempt.

### 4.9 `call_attempts` está vazia

A tabela tem **0 linhas** após 83 chamadas. O auto-dialer nunca chama `log_attempt()`. Consequências:
- `attempts_today` no admin é sempre 0;
- o limite `MAX_ATTEMPTS_7D` nunca bloqueia por tentativas;
- o `call_attempts` não serve para auditoria.

A exclusão real de 7 dias é feita por `voice_calls`, não por `call_attempts`.

### 4.10 O cartão da campanha não mostra outcomes

O cartão da campanha mostra apenas `calls_started/quota`, `showcases_sent` e `skipped`. Não mostra:
- atendidas vs voicemail vs humano;
- opt-outs;
- custo real;
- duração;
- falhas.

Para ver algo da #5 é preciso ir aos KPIs globais e filtrar 1 dia — e mesmo assim os outcomes estão errados.

### 4.11 Analytics também está contaminado

Além da voz, o Web Analytics continua com:
- `form_submit` a contar login/auth;
- `cta_click` a incluir mudanças de idioma;
- `language_switch`/`pricing_view` nunca emitidos.

Isto não é da #5, mas é o mesmo padrão: o painel mostra números que não correspondem à realidade operacional.

---

## 5. O que está correto

- 50 chamadas, 25/25 HVAC/Remodeling: confirmado.
- 42 chamadas com `answered_at`: correto como “carrier atendeu”.
- 22 voicemails: corretos no AMD.
- 8 sem resposta: corretos.
- 0 opt-outs na #5: confirmado.
- 0 falhas TTS registadas: confirmado.
- 0 vitrines: correto para a V3 estática.
- `normal_clearing` em 42 chamadas: correto como “terminou normalmente”, mas não como “ouviu tudo”.

---

## 6. Recomendações de instrumentação

1. **Adicionar `outcome` explícito** em `voice_calls`: `human_full`, `human_partial`, `voicemail`, `no_answer`, `opt_out`, `failed`.
2. **Gravar `audio_completed_at`** no `gather.ended`/`speak.ended` e guardar `last_event`.
3. **Separar `answered` em `connected`, `human`, `voicemail`, `not_sure`** no `/admin/voice/metrics`.
4. **Adicionar `campaign_id` ao endpoint de métricas** e mostrar outcomes no cartão da campanha.
5. **Registar `call_attempts`** ou remover o KPI morto.
6. **Reconciliar custo com CDR** e rotular `cost_cents` como estimativa.
7. **Marcar `Voice Accept`/`Showcase CTR` como N/A na V3** em vez de 0.
8. **Guardar eventos Telnyx numa tabela append-only** para auditoria de DTMF, gather, playback e hangup.

---

## 7. Reprodução

```sql
SELECT id, trade_code, status, intent, amd_result, duration_seconds,
       listen_seconds, hangup_cause, answered_at, ended_at, cost_cents
FROM voice_calls
WHERE campaign_id='5'
ORDER BY id;
```

```sql
SELECT trade_code, amd_result, COUNT(*), MIN(duration_seconds),
       MAX(duration_seconds), SUM(duration_seconds>=45)
FROM voice_calls
WHERE campaign_id='5'
GROUP BY 1,2;
```

```sql
SELECT value, reason, created_at
FROM voice_suppressions
WHERE channel='phone' AND reason LIKE '%opt%';
```
