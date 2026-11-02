# Vitrine pública por cidade/nicho — Fase 2A

Rota pública: **`/{locale}/{city}/{trade}`** (EN default, ex.: `/en/boston/landscaping`).
Fonte de inventário: **`leads.db`** (oportunidades abertas dos últimos 30 dias).
Estado da vitrine: **`showcase.db`** (`SHOWCASE_DB_PATH`, default `/data/showcase.db`).

## Regra de publicação

- Mínimo **3 oportunidades** por cidade × trade nos últimos **30 dias**.
- Abaixo disso, não publica a página exata; aplica fallback:
  1. **Cidade**: mostra todos os trades com inventário suficiente naquela cidade.
  2. **Trade**: mostra o mesmo trade noutra cidade com inventário.
  3. Sem inventário: 404 (o guião de voz não deve prometer vitrine).
- Só entram `signal_status='open'` e `signal_type` em
  `SHOWCASE_SIGNAL_TYPES` (default `open_request,authorized_work`) e
  `is_junk=0`.

## Mascaramento

A página pública **nunca** mostra:
- `owner_name`, `owner_phone`, `owner_email`
- morada exata
- `external_id`/ID da fonte
- link direto para o registo original

Mostra apenas:
- bairro (`neighborhood`) ou `ZIP xxx`
- categoria/trade
- data de observação
- faixa de valor (quando existir; o schema atual não tem valor de obra, por
  isso aparece “Value on request”)
- rótulo neutro **property opportunity**; só usa “approved work” se houver
  `signal_type='authorized_work'`.

> Nota de produto: a base atual é maioritariamente 311/open requests. Não
> chamar “obras aprovadas” sem sinal `authorized_work`. O guião de voz deve
> consultar `showcase.available()` antes de prometer uma vitrine.

## Schema (`showcase.db`)

| Tabela | Função |
|---|---|
| `market_inventory` | agregado por cidade × trade (contagem, última observação) |
| `showcase_pages` | página publicada, título, contagem, estado |
| `showcase_items` | amostras mascaradas (até 12 por página) |
| `showcase_links` | token HMAC/hash por chamada/empresa, expira em 30 dias |
| `showcase_visits` | cliques/visitas (IP e UA em hash) |
| `showcase_checkouts` | Stripe session, user, valor, estado |

## Atribuição

```text
Chamada Telnyx
  → webhook DTMF 1
  → showcase_link (token opaco)
  → email Resend com /r/<token>
  → /r/<token> regista visita e 302 para /en/<city>/<trade>?vt=<token>
  → CTA → POST /api/showcase/checkout
  → Stripe Checkout com metadata:
       source=voice_showcase
       voice_call_id, showcase_link_id, company_id
       user_id, city, trade_code, new_user
  → Stripe webhook checkout.session.completed
  → extend_access 7 dias + showcase_checkouts.completed
  → se new_user: email com link para definir password
```

O link de email passa pelo backend (`/r/<token>`), não diretamente pela
página, para capturar o clique antes de qualquer JS.

## Endpoints

| Método | Rota | Função |
|---|---|---|
| GET | `/api/showcase/{city}/{trade}` | página pública + amostras mascaradas |
| GET | `/r/{token}` | regista clique e redireciona para a vitrine |
| POST | `/api/showcase/checkout` | cria Stripe Checkout com atribuição |
| POST | `/api/voice/telnyx/webhook` | eventos Telnyx; DTMF 1 envia vitrine |
| POST | `/api/admin/showcase/build` | recalcula inventário/páginas |
| GET | `/api/admin/showcase/stats` | páginas, links, visitas, checkouts, receita |
| POST | `/api/admin/voice/contacts/{id}/showcase` | gera link + email manual |
| POST | `/api/admin/voice/contacts/{id}/dial` | chamada Telnyx (dry-run sem chaves) |

## Configuração

```env
SHOWCASE_BASE_URL=            # default PUBLIC_API_URL
SHOWCASE_MIN_ITEMS=3
SHOWCASE_WINDOW_DAYS=30
SHOWCASE_SIGNAL_TYPES=open_request,authorized_work
PUBLIC_API_URL=https://magic-leads-production.up.railway.app
TELNYX_API_KEY=
TELNYX_CONNECTION_ID=
TELNYX_FROM_NUMBER=
TELNYX_WEBHOOK_SECRET=
TELNYX_WEBHOOK_URL=           # default PUBLIC_API_URL/api/voice/telnyx/webhook
```

Sem chaves Telnyx, `/dial` e o webhook funcionam em **dry-run** e registam
`voice_calls` sem gastar dinheiro.

## Build

- Manual: botão **Rebuild pages** em `/admin/voice` ou
  `POST /api/admin/showcase/build`.
- Recomendado: correr após cada ingestão ou 1×/dia na Control Tower.
- `build_pages()` marca todas as páginas como `draft`, republica as que
  cumprem o limiar e apaga itens das restantes.

## Limitações conhecidas

- Sem valor de obra no schema atual: `value_band=null` → “Value on request”.
- `authorized_work` pode estar vazio; a UI usa “property opportunity”.
- Sem geração automática de guião por trade ainda (Fase 2B).
- Telnyx: verificação por segredo partilhado; produção deve usar também
  Ed25519.
- Stripe: se `STRIPE_API_KEY`/`STRIPE_PRICE_ID_PRO` não estiverem
  configurados, o checkout devolve 503 e a página mostra fallback.

## Testes

- `tests/test_showcase.py`: limiar, fallback, mascaramento, tokens, visitas,
  email dry-run e atribuição.
- `tests/test_telnyx_voice.py`: dry-run, webhook DTMF 1, segredo fail-closed.
- `tests/test_admin_panel.py`: build, página pública, link `/r/<token>` e
  checkout com token inválido.
