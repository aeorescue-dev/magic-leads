# Free Account — bónus de 2 desbloqueios: impacto e plano (2026-11-21)

**Estado:** analise read-only. Nada foi alterado; `VOICE_FREEZE=1` intocado.
Este documento propoe o desenho e pede as decisoes antes da implementacao.

---

## 1. Como funciona hoje (confirmado em producao)

| Peca | Comportamento atual |
|---|---|
| Conta free | `users.plan='free'`, `subscription_status='expired'`, `plan_until=NULL` |
| Quotas | `_user_limits` devolve **0/0** telefones/cartas (plano `free` fora de `plans.py`) |
| Acesso | `_require_active_access` → **402** `subscription_required` + `REDIRECT_TO_CHECKOUT` |
| Dados do lead | `_revealed=false` → `owner_name/owner_phone/owner_email/mailing_address = null`; morada/cidade/zip continuam visiveis |
| Reveal | `/api/leads/{id}/reveal-phone` e `/api/subscription/leads/{id}/reveal-letter` exigem acesso ativo e consomem a cota diaria; o telefone frio passa por Searchbug (job assincrono, **$0,20/chamada**) |
| Frontend | handlers de reveal/reserva abrem o **PlanModal** quando `!hasAccess`; o 402 dispara `PAYMENT_REQUIRED_EVENT` |
| Antiabuso | email unico em `users`; **nao ha telefone no registo**, nao ha verificacao de email, e o registo nao guarda IP/device (a sessao de signup e criada com `ip=NULL`) |

Teste real com sessao free: `owner_name/owner_phone/owner_email = null`, morada
visivel — a mascara **ja e server-side**, o que e a base certa para o bonus.

---

## 2. Impacto tecnico por area

### Backend

1. **Contador vitalicio (nao renova):** nova tabela
   `free_unlock_grants(user_id PK, total=2, used, grant_key, created_at)` +
   `free_unlock_keys(key UNIQUE, user_id, created_at)` para o gate de
   unicidade (email/fingerprint/telefone quando existir).
2. **Consumo atomico:** `UPDATE ... SET used=used+1 WHERE user_id=? AND used<total`;
   `rowcount=0` → **402 `free_unlocks_exhausted`** (mesmo contrato de checkout).
   Refund se o reveal falhar (Searchbug/job). Idempotencia por `(user, lead)`.
3. **Reveal:** permitir o bypass de `_require_active_access` **apenas** quando
   `free_remaining>0` e a conta e `free`; gravar em `subscription_reveals`
   (`reveal_type='phone'|'letter'`) para que `_revealed` passe a verdadeiro.
4. **Usage:** `/api/subscription/usage` passa a devolver
   `free_unlocks_total/used/remaining`.
5. **Custo:** cada unlock com telefone frio custa **$0,20**. Duas por conta =
   **$0,40/conta**. Precisa de tecto global diario + alerta de orcamento, ou
   limitar o bonus a telefones ja em cache (`phone_ready`).
6. **Antiabuso:** email unico + fingerprint (hash UA+IP do registo) + limite de
   registos por IP. **Telefone unico so e possivel** quando o registo pedir e
   verificar um numero — hoje isso depende de SMS (10DLC `TCR_ACCEPTED`, ainda
   nao `ACTIVE`) ou de OTP por voz (bloqueado por `VOICE_FREEZE`). Ate la, o
   gate realista e **email verificado + device/IP**.

### Frontend

1. `isFreemium` continua `!hasAccess`, mas os handlers de reveal/reserva passam
   a usar `hasAccess || freeRemaining > 0`; so abrem o PlanModal quando ambos
   falham.
2. Sidebar/`plan-quota`: `2/2 free unlocks left` → `0/2` (PT/EN/ES).
3. Banner free: substituir o texto generico por bonus + CTA; apos `0/2`,
   CTA direto ao checkout.
4. Apos o 2.o unlock, o backend devolve 402 e o modal de planos abre como hoje.

### Dados / rollout

- `FREE_UNLOCKS_ENABLED=0` por defeito (flag), `FREE_UNLOCKS_TOTAL=2`,
  `FREE_UNLOCKS_DAILY_CAP` (ex.: 20 contas/dia) e `FREE_UNLOCK_BUDGET_USD_MES`.
- Aplicar **so a novos registos** (sem backfill retroativo).
- Testes: consumo atomico, refund, idempotencia, 402 esgotado, mascara antes/
  depois, unicidade por fingerprint, i18n e contadores.

---

## 3. Decisoes necessarias antes de implementar

1. **O unlock inclui pesquisa paga de telefone?**
   - (A) Sim, ate 2 por conta (custo maximo $0,40/conta) + tecto global.
   - (B) Primeiro so dados ja disponiveis/cache (`phone_ready`), sem Searchbug.
   Recomendo **A com tecto global e cache-first**: cumpre “telefone
   desmascarado” sem abrir um buraco de custo ilimitado.
2. **Gate antiabuso inicial:** email verificado (link) + fingerprint UA/IP, com
   telefone verificado apenas quando o SMS 10DLC estiver `ACTIVE`? (recomendado)
3. **Contas free existentes** recebem o bonus ou so novos registos? (recomendo
   so novos)
4. **Tectos:** `FREE_UNLOCKS_DAILY_CAP` e orcamento mensal.

---

## 4. Seguranca operacional

- Nada disto toca em voz/SMS: `VOICE_FREEZE=1` mantem-se e a campanha 10DLC
  continua em `TCR_ACCEPTED`.
- O bonus e concedido no registo e consumido no reveal; nao ha chamadas a
  Telnyx nem a Searchbug no pedido HTTP (o job assincrono existente continua a
  ser o unico caminho pago).
- A mascara atual (`_revealed`) e server-side, pelo que o bonus nao depende de
  esconder dados no cliente.
