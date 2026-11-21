# Free account — bónus de boas-vindas 2+3 (2026-11-21)

**Estado:** implementado atras de `FREE_UNLOCKS_ENABLED=0` (default). Nada
concedido nem consumido em producao. `VOICE_FREEZE=1` intocado; sem voz/SMS.

---

## 1. Pacote

| Tipo | Total vitalicio | Comportamento |
|---|---:|---|
| Telefone | **2** | cache-first; consome 1 por reveal; refund em falha |
| Carta/visita | **3** | consome 1 por reveal; refund em falha |

- Contador **nao renova**; ao esgotar, os contactos voltam a mascarar e o
  clique abre o checkout (402 `subscription_required`/`free_unlocks_exhausted`).
- A mascara continua server-side (`_revealed`); o bonus grava em
  `subscription_reveals` e usa o mesmo `_mark_revealed`.
- Telefones frios passam pelo job assincrono existente; cada unlock gratuito
  regista **$0,20** de custo Searchbug.

## 2. Antiabuso

- **Email canonical**: lowercase, remove `+tag`; em Gmail/Googlemail remove
  tambem os pontos. Bloqueia aliases do mesmo email.
- **Disposable domains**: lista propria (mailinator, yopmail, 10minutemail,
  guerrillamail, etc., incluindo subdominios).
- **Verificacao de email**: conta criada sem bonus; link assinado (HMAC,
  24 h) → `/api/auth/verify-email` concede o pacote. Reenvio:
  `/api/auth/resend-verification` (3/h).
- **Dispositivo**: `device_id` (localStorage) + UA + IP → hash; 1 grant por
  dispositivo e por email.
- **Turnstile**: verificacao server-side quando `TURNSTILE_SECRET_KEY` existe;
  sem token → falha. (Widget no form a ligar quando a site key for criada.)
- **Circuit breaker**: 25 grants/dia e $75/mes de Searchbug; ao atingir, o
  circuito fecha e **bloqueia apenas novas concessoes** (os bonus ja
  atribuidos continuam validos) + alerta `FREE_UNLOCKS_PAUSED`. O tecto diario
  expira no dia seguinte; o mensal no mes seguinte. Admin:
  `GET /api/admin/free-unlocks`, `POST /pause`, `POST /resume`.
- **Rate limits** existentes no registo (3/min) e nos reveals (20/min)
  mantem-se; o registo devolve 409 `email_exists` + `next=login`.

## 3. Checkout e conta existente

- O bloqueio de email/dispositivo aplica-se **so a criacao de novas contas**.
- Email ja existente → **409** `{code:"email_exists", next:"login"}`; o form
  mostra a mensagem e passa para **Login**. Nunca bloqueia a compra: o upgrade
  faz-se na mesma conta/email via checkout.
- Com a flag ligada no frontend (`NEXT_PUBLIC_FREE_UNLOCKS=1`), o registo
  **nao** forca Stripe Checkout: entra na dashboard e usa o bonus.

## 4. Codigo

**Backend**
- `backend/services/free_unlocks.py` (novo): grants, keys, eventos, daily,
  pending, canonical/disposable, device key, Turnstile, tokens HMAC, email
  Resend, circuit breaker, consume/refund atomicos.
- `backend/main.py`: registo (checks + pending + email), verify/resend,
  `/api/subscription/usage.free_unlocks`, reveals com `free_bonus`, admin.
- `backend/services/subscription_reveals.py`: consume/refund bonus vs quota;
  refund no job.
- `backend/services/phone_jobs.py`: refund de `free_bonus`.
- `backend/config.py`: flag, totais, cap diario, orcamento, custo, Turnstile,
  segredo de verificacao.

**Frontend**
- `lib/api-client.ts`: `getDeviceId()`, `device_id` no registo, erro
  estruturado (`detail`) preservado.
- `AuthForm.tsx`: email existente → login; flag → dashboard sem checkout.
- Dashboard: `free_unlocks` no usage; banner e chip da sidebar com
  `X/2 phones · Y/3 letters`; gates de reveal aceitam bonus ate esgotar.
- `subscription-api.ts`: tipo `free_unlocks`.

## 5. Testes

- `tests/test_free_unlocks.py` (10): canonical, disposable, grant, device/email
  unico, consumo/esgotamento, refund, cap diario, orcamento, token, flag off.
- Suite completa: `reports/pytest-free-unlocks-2026-11-21.log`.
- Frontend: `tsc` limpo, ESLint 0 erros, Vitest 111.

## 6. Ativacao (quando aprovado)

1. Configurar `EMAIL_API_KEY`/`EMAIL_FROM` e `TURNSTILE_SECRET_KEY` no Railway;
   `NEXT_PUBLIC_TURNSTILE_SITE_KEY` + `NEXT_PUBLIC_FREE_UNLOCKS=1` na Vercel.
2. Ligar `FREE_UNLOCKS_ENABLED=1`; opcional ajustar totais/caps.
3. Adicionar o widget Turnstile ao form (site key) antes de abrir ao publico.
4. Testar com uma conta nova: verificar email → 2/2 + 3/3 → esgotar → checkout.
5. Rollback: `FREE_UNLOCKS_ENABLED=0` (grants existentes ficam congelados).
