# Fase 3 — Quotas diárias, carta e telefone on-demand (backend)

**Branch:** `feat/weekly-subscription-quotas`  
**Âmbito:** backend apenas; **sem alterações visuais**.  
**Staging:** `magic-leads-staging` (`SEARCHBUG_MOCK=1`, `BILLING_MOCK=1`, `ADDONS_MOCK=1`).  
**Produção:** intocada; sem merge.

## Quotas

`user_daily_usage` (data local `America/New_York`, reset DST-safe):

- `phone_used` / `phone_limit` (limite do plano);
- `letter_used` / `letter_limit` (10 em todos os planos);
- `reset_at` em UTC.

Add-ons vivem em `phone_addons` com validade de **24h corridas**.

## Regras implementadas

### Carta/Visita
- `POST /api/subscription/leads/{id}/reveal-letter`
- Exige assinatura ativa (`_require_active_access`).
- Limite **10/dia**, independente do telefone.
- Devolve `owner_name`, `address`, `city`, `state`, `zip_code`, `mailing_address` (quando existe).
- Idempotente por utilizador/lead: repetir não consome quota.
- Registo em `lead_reveals` (`reveal_type='letter'`, `credits_cents=0`).

### Telefone on-demand
- `POST /api/subscription/leads/{id}/reveal-phone`
- Ordem de consumo: **base diária → add-on ativo mais antigo**.
- `SEARCHBUG_MOCK=1` devolve telefone sintético para QA sem custo.
- Sem telefone/erro: **devolve a unidade ao bucket de origem**, com mensagem “cota preservada”.
- Idempotente por utilizador/lead; repetir não consome quota.
- Registo em `lead_reveals` (`reveal_type='phone'`, `credits_cents=0`).

### Add-ons 24h
- `POST /api/billing/addons/checkout` (`pack_code`):
  - Stripe `mode=payment` com `price_data` inline;
  - metadata `kind=phone_addon`, `user_id`, `pack_code`, `phone_count`.
- Webhook `checkout.session.completed` cria `phone_addons` (idempotente por `stripe_session_id`).
- `ADDONS_MOCK=1`/sem chave: `mock=true`, `checkout_url=null`; QA usa script interno.
- Pacotes: +2/$2.50, +4/$4.80, +6/$7.20, +8/$9.60, +10/$12, +15/$18, +20/$24.

### Estado/consumo
- `GET /api/subscription/usage` devolve:
  - plano, `phone_limit/used/remaining`, `letter_limit/used/remaining`,
  - `addon_remaining`, `addon_expires_at`, `reset_at`, `can_access`.

## Segurança

- Sem endpoint público de ativação/mock de plano (410 mantido).
- QA de plano/add-on é feita por scripts internos:
  - `backend/scripts/activate_staging_subscription.py`
  - `backend/scripts/add_staging_phone_addon.py`
- Ambos recusam correr fora de staging (ou `ALLOW_*_SEED=1`).

## Testes

- **1725 passed, 1 skipped**.
- Cobrem:
  - carta 10/dia + idempotência;
  - telefone base → add-on;
  - falha Searchbug preserva quota;
  - add-on 24h idempotente e expiração;
  - endpoints `/api/subscription/usage`, `/reveal-letter`, `/reveal-phone`;
  - regressões de billing security (`mock-activate` 410, checkout fail-closed).

## Limitações

- **Sem UI nesta fase**; o frontend de staging mantém a UI anterior até à Fase 4.
- Sem Price IDs reais enquanto não houver `sk_test_`; Stripe em mock.
- `Searchbug` em mock no staging; produção exige chave real.

**Gatekeeper:** não avançar para a Fase 4 (UI) sem autorização escrita do Fábio.
