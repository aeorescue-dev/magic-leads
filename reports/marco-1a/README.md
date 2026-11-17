# Marco 1A — Carteira de créditos + reveal de sinal ($1,50)

**Branch:** `feat/credits-pay-as-you-go`  
**Data:** 2026-11-16  
**Estado:** implementado e validado em staging, **integrado no dashboard oficial** (sidebar/header existentes).  
**Regra:** produção intocada; fila de voz pausada; Searchbug/Telnyx desligados na 1A.

## O que foi entregue

- Conta grátis (registo/login sem checkout obrigatório) entra diretamente no **dashboard oficial**.
- Sidebar com “Visão Geral / Oportunidades / Mapa / …” e novo item **Créditos / Planos** com saldo.
- Carteira no **header** (chip `$0.00`) atualizada logo após pagamento/reveal.
- Carteira de créditos em **cents** ($1 = 100 créditos; $1,50 = 150; $3 = 300).
- Pacotes $6/$9/$15/$45/$90/$180 com bónus (700/1.100/1.900/6.000/12.500/26.000 créditos).
- Ledger `credit_ledger` como fonte de verdade; `credit_wallets` como cache.
- Compras one-time Stripe (Checkout `mode=payment`, `price_data` inline) + webhook idempotente; modo **mock** em staging enquanto a chave `sk_test_` não está configurada.
- Reveal de sinal **$1,50** com endereço exato, owner oficial e `mailing_address`; **sem Searchbug**.
- Exclusividade **7 dias por ofício**; o mesmo endereço pode ser vendido a outros ofícios.
- Paywall: “Revelar” com saldo insuficiente (402) abre uma **modal elegante sobre o dashboard** (pack $6–$180, carteira atual e valor necessário). A compra dentro da modal credita a carteira e **desbloqueia o lead automaticamente**, sem sair do painel.
- Telefone **$3** bloqueado na 1A (Marco 1B).
- `/pt/credits` deixou de ser página autónoma: redireciona para `/{locale}/dashboard?tab=credits`.
- Gate por token/password no staging (`STAGING_GATE=1` + `STAGING_ACCESS_TOKEN`), cookie httpOnly.
- Seed sintético: **50 leads** nas 4 praças + contas `qa-buyer+staging@magicleads.app` / `qa-free+staging@magicleads.app` (password `dev-demo-only`).
- Nenhum dado de produção usado no seed; nenhuma chamada Searchbug/Telnyx.

## Fluxo validado (dashboard)

1. Login gratuito → `/pt/dashboard` com o layout oficial e sidebar completo.
2. Aba **Oportunidades** → mapa + sinais mascarados (`*** Seed Street`, owner mascarado).
3. Sidebar **Créditos / Planos** → carteira + 6 pacotes + sinais no dashboard.
4. Pack Starter $6 → Checkout mock → webhook duplicado (idempotente) → **$7.00** no header.
5. **Revelar sinal — $1,50** → modal com endereço/owner/mailing → header passa a **$5.50**.
6. Conta sem saldo → “Revelar” abre a **modal de créditos** sobre o dashboard; a compra dentro da modal (mock) credita a carteira e desbloqueia o lead no mesmo fluxo.
7. `/pt/credits` redireciona para `/pt/dashboard?tab=credits` (sidebar e carteira visíveis).

## Provas visuais (staging)

Capturas em `reports/marco-1a/staging/`:

| Ficheiro | Conteúdo |
|---|---|
| `01-gate.png` | Staging protegido: redirect para token |
| `02-dashboard-freemium.png` | Login gratuito dentro do dashboard oficial |
| `03-map-masked-signals.png` | Aba Oportunidades: mapa + sinais mascarados |
| `04-credits-packs.png` | “Créditos / Planos” aberto no dashboard, pacotes $6–$180 |
| `05-webhook-idempotent.png` | Webhook 1 aplicado + Webhook 2 duplicado |
| `06-wallet-700-dashboard.png` | Carteira do header a $7.00 após pagamento |
| `07-reveal-dashboard.png` | Reveal $1,50: endereço + owner + mailing + exclusividade |
| `08-wallet-after-reveal.png` | Carteira do header a $5.50 após reveal |
| `09-insufficient-paywall.png` | Conta sem créditos: modal de pacotes sobre o dashboard |
| `10-paywall-purchase-unlock.png` | Compra na modal → créditos + lead desbloqueado sem sair do dashboard |
| `11-credits-redirect.png` | `/pt/credits` → `/pt/dashboard?tab=credits` |

## Resultado do audit de staging

```
RESULT ALL PASS (17/17)
```

- Staging gate redirects
- Staging token accepted
- Free login lands in official dashboard
- Official sidebar keeps Opportunities
- Freemium keeps dashboard + masked signals
- Sidebar opens credit packs in dashboard
- Header wallet visible
- Mock checkout created
- Webhook idempotency
- Credits appear in header wallet ($7.00)
- Signal unlocks full address + owner + mailing
- Wallet debited $1.50 after reveal ($5.50)
- Insufficient balance opens elegant paywall modal
- Paywall shows $6–$180 packs over the dashboard
- Zero-balance wallet unchanged
- Payment in paywall unlocks lead without leaving dashboard
- Header wallet after paywall purchase + reveal ($5.50)

## Ledger observado

| Evento | Créditos | Saldo |
|---|---:|---:|
| `pack_purchase` (Starter $6) | +700 | 700 |
| `reveal_signal` (Plumbing) | -150 | 550 |

O webhook duplicado não altera o saldo: `stripe_events` único + `credit_purchases` pago uma vez + `credit_ledger` com uma linha.

## Gate de staging

- Sem cookie: `/pt/dashboard` → **307** para `/pt/staging-login?next=%2Fpt%2Fdashboard`.
- Token correto → `/pt/dashboard` (ou `/pt/auth` se ainda não houver sessão).
- Cookie `staging_gate` httpOnly, 7 dias, `secure` apenas em HTTPS.
- `STAGING_GATE` não definido em produção → gate inativo.

## Testes e qualidade

- Backend: **1708 passed, 1 skipped** (4 novos testes em `tests/test_credits.py`).
- Ruff: **All checks passed**.
- Frontend: `tsc --noEmit` limpo; **111 testes / 14 ficheiros**; ESLint **0 erros**.
- `next build`: concluído com sucesso, incluindo `/[locale]/dashboard`, `/[locale]/credits` (redirect), `/[locale]/staging-login` e `/api/staging-login`.

## Stripe

- O código suporta **Checkout real em test mode** com `price_data` inline; não exige price IDs pré-criados no dashboard.
- Para ativar: definir `STRIPE_API_KEY=sk_test_...` e `STRIPE_WEBHOOK_SECRET` no Railway staging; `CREDITS_MOCK=0`.
- Enquanto a chave não estiver configurada, o staging usa **mock** e o botão “Simular pagamento”; nenhum pagamento real.
- Webhook real: `POST /api/credits/stripe/webhook` (assinatura Stripe; idempotente).
- `success_url`/`cancel_url` apontam para `/{locale}/dashboard?tab=credits&checkout=success|cancel`.

## Staging

- Backend Railway: `magic-leads-staging` (`https://magic-leads-staging-staging.up.railway.app`), ambiente `staging`, volume próprio; health `healthy`.
- Frontend: **`https://magic-leads-staging-fabio-dev2.vercel.app`** (alias estável do preview aprovado). O preview antigo `magic-leads-frontend-final-gv537n0ha-fabio-dev2.vercel.app` está **obsoleto** e já não deve ser usado.
- Seed: `backend/scripts/seed_staging_credits.py` executado no staging; **50 leads sintéticos** e contas de teste.
- Proteção: **Vercel Deployment Protection** + **token gate** da app (`STAGING_GATE=1`); credenciais partilhadas fora de banda.
- **Audit de staging: ALL PASS (17/17)** — dashboard oficial, mapa/sinais mascarados, pacotes, webhook idempotente, carteira $7.00, reveal $1,50, saldo $5.50, modal de paywall e desbloqueio automático após compra na modal.
- `CREDITS_MOCK=1` enquanto a chave `sk_test_` não está configurada; o caminho Stripe real está implementado e pronto a ativar.
- O link e os tokens não ficam no repositório; são partilhados no canal seguro.

## Limitações da 1A

- Sem Searchbug; o telefone $3 está desativado.
- Sem Property Masters; os leads da 1A são sintéticos com `signal_ready=1`.
- Sem dados de produção; sem PII real.
- O seed e o modo mock são explicitamente de staging; produção continua com a assinatura legacy e a fila de voz pausada.
- A landing page continua a vender o passe de $120/semana; a migração da copy pública para créditos não faz parte da 1A.
