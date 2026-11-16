# Marco 1A — Carteira de créditos + reveal de sinal ($1,50)

**Branch:** `feat/credits-pay-as-you-go`  
**Data:** 2026-11-16  
**Estado:** implementado e validado localmente; staging a ser publicado.  
**Regra:** produção intocada; fila de voz pausada; Searchbug/Telnyx desligados na 1A.

## O que foi entregue

- Conta grátis (registo/login sem checkout obrigatório).
- Carteira de créditos em **cents** ($1 = 100 créditos; $1,50 = 150; $3 = 300).
- Pacotes $6/$9/$15/$45/$90/$180 com bónus (700/1.100/1.900/6.000/12.500/26.000 créditos).
- Ledger `credit_ledger` como fonte de verdade; `credit_wallets` como cache.
- Compras one-time Stripe (Checkout `mode=payment`, `price_data` inline) + webhook idempotente; modo **mock** em staging enquanto a chave `sk_test_` não está configurada.
- Reveal de sinal **$1,50** com endereço exato, owner oficial e `mailing_address`; **sem Searchbug**.
- Exclusividade **7 dias por ofício**; o mesmo endereço pode ser vendido a outros ofícios.
- Telefone **$3** bloqueado na 1A (Marco 1B).
- Gate por token/password no staging (`STAGING_GATE=1` + `STAGING_ACCESS_TOKEN`), cookie httpOnly.
- Seed sintético: **50 leads** nas 4 praças + contas `qa-buyer+staging@magicleads.app` / `qa-free+staging@magicleads.app` (password `dev-demo-only`).
- Nenhum dado de produção usado no seed; nenhuma chamada Searchbug/Telnyx.

## Provas visuais (local)

| Ficheiro | Conteúdo |
|---|---|
| `01-login.png` | Conta grátis / login |
| `02-wallet-leads.png` | Carteira a $0 + 50 sinais mascarados |
| `03-mock-checkout.png` | Pack Starter $6 em modo mock |
| `04-webhook-idempotent.png` | Webhook 1 aplicado + Webhook 2 duplicado |
| `05-wallet-700.png` | Carteira creditada com 700 créditos |
| `06-signal-reveal.png` | Reveal $1,50: endereço + owner + mailing + exclusividade |
| `07-cross-trade.png` | Mesmo lead revelado noutro ofício |
| `08-duplicate.png` | Mesmo ofício/utilizador: duplicado, sem cobrança |
| `09-insufficient.png` | Conta sem créditos: 402 e pedido de pacote |
| `10-gate-login.png` | Staging protegido: redirect para token |
| `11-gate-entered.png` | Token correto: entrada no staging |

## Resultado do audit local

```
RESULT ALL PASS (9/9)
```

- Staging page loads
- Free account login
- Mock checkout created
- Webhook idempotency visible
- Wallet credited 700
- Signal reveal returns full owner/mailing
- Same lead can be revealed by another trade
- Same user/trade duplicate does not charge
- Insufficient credits blocked

## Resultado do audit de staging

```
RESULT ALL PASS (6/6)
```

- Staging gate redirects
- Staging token accepted
- Free account login in staging
- Staging webhook idempotency
- Staging wallet +700
- Staging signal reveal

Capturas em `reports/marco-1a/staging/` (`01-gate.png` … `05-reveal.png`).

## Ledger observado

| Evento | Créditos | Saldo |
|---|---:|---:|
| `pack_purchase` (Starter $6) | +700 | 700 |
| `reveal_signal` (Plumbing) | -150 | 550 |
| `reveal_signal` (Electrical, mesmo lead) | -150 | 400 |
| duplicado (mesmo ofício) | 0 | 400 |

O webhook duplicado não altera o saldo: `stripe_events` único + `credit_purchases` pago uma vez + `credit_ledger` com uma linha.

## Gate de staging

- Sem cookie: `/pt/credits` → **307** para `/pt/staging-login?next=%2Fpt%2Fcredits`.
- Token correto: `/pt/staging-login` → `/pt/credits`.
- Token errado: **401** “Token inválido.”.
- Cookie `staging_gate` httpOnly, 7 dias, `secure` apenas em HTTPS.
- `STAGING_GATE` não definido em produção → gate inativo.

## Testes e qualidade

- Backend: **1708 passed, 1 skipped** (4 novos testes em `tests/test_credits.py`).
- Ruff: **All checks passed**.
- Frontend: `tsc --noEmit` limpo; **111 testes / 14 ficheiros**; ESLint **0 erros** (112 warnings).
- `next build`: concluído com sucesso, incluindo `/[locale]/credits`, `/[locale]/staging-login` e `/api/staging-login`.

## Stripe

- O código suporta **Checkout real em test mode** com `price_data` inline; não exige price IDs pré-criados no dashboard.
- Para ativar: definir `STRIPE_API_KEY=sk_test_...` e `STRIPE_WEBHOOK_SECRET` no Railway staging; `CREDITS_MOCK=0`.
- Enquanto a chave não estiver configurada, o staging usa **mock** e o botão “Simular pagamento”; nenhum pagamento real.
- Webhook real: `POST /api/credits/stripe/webhook` (assinatura Stripe; idempotente).

## Staging

- Backend Railway: `magic-leads-staging` (`https://magic-leads-staging-staging.up.railway.app`), ambiente `staging`, volume próprio; health `healthy`.
- Frontend: preview Vercel `https://magic-leads-frontend-final-gv537n0ha-fabio-dev2.vercel.app` da branch.
- Seed: `backend/scripts/seed_staging_credits.py` executado no staging; **50 leads sintéticos** e contas de teste.
- Proteção: **Vercel Deployment Protection** + **token gate** da app (`STAGING_GATE=1`); credenciais partilhadas fora de banda.
- **Audit de staging: ALL PASS (6/6)** — gate, token, conta grátis, webhook idempotente, carteira +700 e reveal de sinal.
- `CREDITS_MOCK=1` enquanto a chave `sk_test_` não está configurada; o caminho Stripe real está implementado e pronto a ativar.
- O link e os tokens não ficam no repositório; são partilhados no canal seguro.

## Limitações da 1A

- Sem Searchbug; o telefone $3 está desativado.
- Sem Property Masters; os leads da 1A são sintéticos com `signal_ready=1`.
- Sem dados de produção; sem PII real.
- O seed e o modo mock são explicitamente de staging; produção continua com a assinatura legacy e a fila de voz pausada.
