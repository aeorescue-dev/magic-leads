# Auditoria preventiva — cruzeiro autónomo (2026-11-01)

Bateria pedida antes do "ok" final: simulação do salto de rampa, disjuntor,
integridade dos links e varredura de erros/recursos. Método: leitura do código,
simulações puras com os valores reais de produção, testes automatizados novos e
verificação read-only na base e nos logs de produção.

## 1. Simulação do salto de patamar (03/11 e 05/11)

**Encontrado:** o intervalo era comparado ao segundo, mas o Auto-Ramp só é
avaliado **uma vez por dia**, no primeiro tick depois da meia-noite de NY. O
tick tem jitter de até 60 s: um passo gravado às `05:00:30` e avaliado dois
dias depois às `05:00:10` ficava 20 s "cedo", devolvia `hold: interval` e — como
a marca diária já tinha sido escrita — **o degrau escorregava um dia inteiro**.

**Correção:** `INTERVAL_TOLERANCE = 1 hora`. A decisão continua a ser tomada
uma vez por dia, mas absorve o jitter do tick sem antecipar o degrau.

Simulação com os valores de produção (`cap=2`, último passo `2026-11-01
00:43:47 UTC`, saúde limpa):

| Data avaliada (00:00 ET) | Decisão |
|---|---|
| 02/11 | `hold: interval` (só 1 d 4 h desde o passo) |
| 03/11 | `step 2 → 3` ✅ |
| 04/11 | `hold: interval` (nunca sobe dois dias seguidos) |
| 05/11 | `step 3 → 5` ✅ (mesmo com 20 s de jitter) |

Fuso: o dia operacional atravessa a mudança de hora. `day_start_utc("2026-11-01")
= 04:00 UTC` (EDT) e `("2026-11-02") = 05:00 UTC` (EST); `day_key` só vira
depois das 05:00 UTC. Teste novo fixa isto.

Custo/limites: um envio de cada vez por tick (sem rajada), Gmail API por caixa,
`mix_cache`/snapshot por cidade são dicionários por tick (sem crescimento
ilimitado). Não há cache global a estourar.

## 2. Disjuntor

| Gatilho | Regra | Teste |
|---|---|---|
| Bounce | `>2%` com `>=20` envios | sim |
| Bounces consecutivos | 2 seguidos, **sem mínimo de amostra** | sim |
| Complaint | `>0,1%` | sim |
| Auth | qualquer `401/403/invalid_grant/insufficient` | sim, na falha de envio e na exceção |

- Limites exatos **não** pausam (`2,0%` e `0,1%` ficam dentro da regra `>`);
  teste novo cobre os dois.
- A pausa é imediata (`enabled=0`, `paused_at`, alerta `MAILBOX_PAUSED`) e
  **nada a retoma automaticamente**: o Auto-Ramp devolve `hold: paused` mesmo
  com métricas perfeitas (teste novo).
- O disjuntor é avaliado antes de cada tick de envio. Durante quiet hours ou
  com o motor desligado não é avaliado — mas também não há envios, pelo que
  não existe janela de risco (é avaliado de novo no primeiro tick ativo).

## 3. Links e parâmetros

**Encontrado:** `sequence_url` concatenava `city`/`niche` crus. Os tokens
atuais são seguros, mas um valor com `&` ou espaço partiria o redirecionamento.

**Correção:** `urlencode`. Para os tokens reais o URL é idêntico ao anterior.

Verificações:
- `4 cidades × 8 nichos × 2 passos = 64` URLs: `parse_qs` devolve exatamente
  `city`, `niche` e `step` esperados.
- Token "sujo" (`"new york city"`, `"roofing & siding"`) é codificado e
  reconvertido corretamente.
- Cada variante de campanha tem **um único** link `?city=&niche=&step=`.
- Mensagem em fila em produção (id 22, `control`): CTA `reply "send"` presente
  e nenhum link de campanha — comportamento correto do braço de controlo.
- 8 URLs reais (4 cidades × passo 1/2) devolvem **200** e preservam os
  parâmetros.

## 4. Base, fila e recursos (produção, read-only)

| Verificação | Resultado |
|---|---|
| `PRAGMA integrity_check` / `quick_check` | `ok` / `ok` |
| WAL / SHM | 0,1 MB / 0,0 MB |
| Base | 169,2 MB · 693 MB livres em `/data` |
| Mensagens presas em `sending` >15 min | 0 |
| Mensagens ativas duplicadas (e-mail+passo) | 0 |
| Falhas nos últimos 7 dias | 0 |
| Alertas críticos 7 dias | 0 (só 1 `warn` de acesso admin) |
| Logs (451 linhas) | 0 `ERROR`, 0 `Traceback`, 0 `MAILBOX_PAUSED` |
| Avisos | 84 × orçamento Brave (esperado), 1 × queue_age por cap (esperado), 1 × Overpass |
| Processo | RSS 53 MB · threads 2 |

**Achado (dívida, sem impacto no envio):** `PRAGMA foreign_keys = 0` (default do
SQLite), pelo que existem **1.058 linhas órfãs** em tabelas de dashboard:
`lead_case_history` 912, `credit_ledger` 52, `lead_events` 38, `notifications`
24, `user_interests` 6, `user_daily_stats` 5. No domínio de envio: **0** órfãos
(`outbound_messages` → contactos/lotes limpos). Não se ativa FK enforcement em
cruzeiro (poderia rejeitar inserções antigas e disparar cascatas); a limpeza
fica como tarefa separada, sem tocar em `credit_ledger`.

## 5. Concorrência

- Um único processo uvicorn (`--workers` não usado) → um worker loop.
- `claim` atómico `queued → sending` impede reenvio com ticks sobrepostos.
- Auto-Ramp é sequencial no loop e idempotente por dia (`system_kv`).
- `_pick_mailbox` devolve referência ao snapshot e consome folga no mesmo tick
  (regressão 995007d coberta).
- Reaper de `sending` corre mesmo com envio desligado.

## 6. Consistência de nicho (Fase 21)

O enfileiramento já escrevia a copy e a URL com o **nicho do destinatário**
(`contact.niche_key` confirmado). O re-render de envio usava o nicho do lote —
num lead de categoria partilhada (ex.: `Roof` em `general_contractors` e em
`roofing`) o texto podia sair de um nicho e o link de outro.

Correção: `_recipient_niche(contact, batch_niche)` devolve o nicho do contacto
quando `niche_status == "confirmed"` e só cai para o do lote quando não há
confirmação. Aplicado em `_render_message` (passos 1 e 2) e em
`schedule_next_steps`. Teste novo captura a URL no enfileiramento, re-renderiza
como o envio e exige igualdade exata.

O `body_hash` continua a ser auditoria histórica (não é comparado no envio);
com a fonte de nicho unificada, as duas renderizações convergem.

## Veredicto

Fluxo de cruzeiro aprovado: **rampa, disjuntor, links e base de envio passaram**
nos testes preditivos. Correções feitas antes do "ok": jitter do intervalo,
encoding do URL e consistência de nicho entre fila e envio — todas cobertas por
testes. O único achado aberto é a higiene de órfãos no dashboard, fora do
caminho de envio.
