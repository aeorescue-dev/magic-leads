# Fase 2 — Assinatura semanal Stripe (backend)

**Branch:** `feat/weekly-subscription-quotas`  
**Âmbito:** backend/Stripe apenas; **sem alterações visuais**.  
**Staging:** `magic-leads-staging` com `BILLING_MOCK=1`, `ADDONS_MOCK=1`, `SEARCHBUG_MOCK=1`.  
**Produção:** intocada; sem merge.

## O que foi implementado

### Catálogo e mapeamento

- `subscription_plans` (Fase 1) é a fonte de verdade.
- `plan_for_price_id(price_id)` resolve:
  1. `subscription_plans.stripe_price_id` na BD;
  2. fallback `STRIPE_PRICE_WEEKLY_*` no ambiente.
- `activate_weekly_subscription(user_id, plan_code)` grava:
  - `users.plan` = código;
  - `users.daily_phone_limit`;
  - `users.daily_letter_limit` (10);
  - `users.plan_until` (UTC);
  - `users.stripe_subscription_id` / `stripe_customer_id`.

### Checkout

`POST /api/billing/checkout`

- Com `plan_code`: checkout de **subscrição semanal** (`mode=subscription`, Price recorrente semanal).
- Sem `plan_code`: mantém o caminho legacy fail-closed (sem Stripe → `mock=True`, `checkout_url=None`).
- Com `BILLING_MOCK=1` ou sem chave/Price ID: devolve `mock=True` e **não** ativa nada.
- `POST /api/billing/portal`: Stripe Customer Portal (upgrade/downgrade/cancelamento).

### Webhooks

`POST /api/billing/webhook` (Stripe-Signature obrigatória):

| Evento | Efeito |
|---|---|
| `checkout.session.completed` (`kind=weekly_subscription`) | Ativa plano, limites e `plan_until` |
| `customer.subscription.created/updated` | Re-mapeia Price → plano; atualiza limites/estado |
| `invoice.paid` | Estende `plan_until` e mantém `active` |
| `invoice.payment_failed` | `past_due` (sem estender `plan_until`) |
| `customer.subscription.deleted` | `expired` |

Idempotência: `stripe_events` com `granted=0` até o efeito ser aplicado; retries do Stripe reprocessam eventos incompletos.

### Segurança

- `/api/billing/mock-activate` continua **410 Gone**: nenhum utilizador se auto-ativa.
- `test_billing_security.py` passa:
  - mock-activate não altera plano/acesso;
  - checkout sem Stripe é fail-closed (`mock=True`, `checkout_url=None`).
- Ativação de QA no staging é feita por script interno, não por endpoint:
  `backend/scripts/activate_staging_subscription.py`.

### Provisionamento Stripe

`backend/scripts/setup_stripe_weekly_plans.py`:

- Cria/reutiliza 1 Product + 1 Price semanal por plano.
- Idempotente por metadata `plan_code` e por `unit_amount`/`interval=week`.
- Dry-run por defeito; `--apply` grava `stripe_price_id`/`stripe_product_id` na BD.
- Recusa `sk_live_` sem `--allow-live`.

**Estado atual:** staging não tem `sk_test_`; os 7 Price IDs ainda estão vazios e o checkout usa `BILLING_MOCK=1`. Assim que a chave for fornecida:

```bash
STRIPE_API_KEY=sk_test_... python backend/scripts/setup_stripe_weekly_plans.py --apply
```

## Evidência no staging

- `GET /api/billing/plans` → 7 planos, `billing_model=weekly_quota`, `billing_mock=true`.
- `POST /api/billing/checkout` com `plan_code=weekly_6` → `mock=true`, `checkout_url=null`.
- `GET /api/billing/subscription` → plano/limites/estado do utilizador.
- `legacy_pro` continua ausente (`0`).

## Testes

- **1719 passed, 1 skipped**.
- Novos testes Fase 2:
  - ativação mapeia `daily_phone_limit`/`daily_letter_limit`;
  - `price_id → plano`;
  - checkout mock sem chave;
  - ciclo `subscription.created → payment_failed → deleted`;
  - idempotência do webhook;
  - `checkout.session.completed` ativa plano;
  - endpoint público `/api/billing/plans`.

## Limitações / próximos passos

- **Sem UI nesta fase**: o frontend de staging continua com a UI anterior até à Fase 4.
- **Sem Price IDs reais** enquanto não houver `sk_test_`; `BILLING_MOCK=1`.
- A Fase 3 implementa quotas diárias, carta livre (10/dia), telefone on-demand, add-ons 24h e UI de consumo.
- Paragem obrigatória: **não avançar para a Fase 3 sem autorização escrita do Fábio**.
