# Web Analytics first-party (Fase 29)

Rota: **`/admin/analytics`**. API: **`GET /api/admin/analytics?range=24h|7d|30d`**
(sessão + `is_admin`). Ingest: **`POST /api/analytics/ingest`** (chave
servidor-a-servidor).

## Princípios

- **Cookieless**: sessão em `sessionStorage` (morre com o separador); sem
  identificador persistente entre sites.
- **Sem IP em repouso**: visitante único diário = HMAC-SHA256(salt do dia,
  IP + User-Agent), truncado. O salt roda por dia UTC e os anteriores são
  apagados.
- **Sem PII**: nunca envia e-mail, nome, conteúdo de formulário ou query
  string; só path, label e valor.
- **Zero impacto no LCP**: o beacon só arranca depois da hidratação e envia em
  lote (`sendBeacon`) após `requestIdleCallback`/`pagehide`. Nenhum script de
  terceiros.

## Fluxo

```
Landing → POST /api/track (Vercel, same-origin)
        → lê x-vercel-ip-country/region/city + UA + IP do cliente
        → POST Railway /api/analytics/ingest (X-Analytics-Key)
        → analytics.db (sessions, events)
Admin  → GET /api/admin/analytics (cache 60 s)
```

O `analytics.db` é separado do `leads.db` para não competir com a ingestão.

## Eventos

`pageview`, `cta_click`, `form_start`, `form_submit`, `scroll` (25/50/75/100%),
`outbound_click`, `language_switch`, `pricing_view`.

Sessão: `started_at`, `last_seen_at` (timeout 30 min), UTM first-touch,
referrer, locale, device/browser/OS, pageviews, engagement_ms, scroll_pct.

## Origem

1. UTM (`utm_source/media/campaign/content/term`).
2. Referrer: google/bing → organic; linkedin/facebook/x → social;
   mail/outlook → email; outros → referral; sem referrer → direct.
3. Links do outreach: `sequence_url()` adiciona
   `utm_source=magicleads&utm_medium=outreach&utm_campaign=<cidade>_<nicho>&utm_content=stepN`.
   Sem UTM, o Gmail remove o Referer e o e-mail apareceria como “direct”.

## Tabelas e retenção

- `sessions` (uma linha por sessão; hash do visitante, geo cidade, UTM,
  device, engagement).
- `events` (`event_uid` único para idempotência; path/label/value/props).
- `meta` (salt diário, último purge).
- **Retenção**: eventos 90 dias, sessões 180 dias, salts só o dia atual.
  Purge diário na Control Tower (`analytics.maintenance_if_due`).
- Índices por `started_at`, visitante, origem e geo; eventos por `ts`,
  `(name, ts)` e `(session_id)`.

## Admin

- **Saúde do tráfego**: score 0–100 = 40% volume (vs período anterior), 30%
  engagement (tempo + scroll), 30% conversão (CTA + formulário).
- Cards: visitas, únicos, pageviews, cliques CTA, formulários, tempo médio,
  bounce — com sparkline e delta.
- Gráficos: tráfego (hora/dia), origens, funil, geografia, dispositivo/idioma,
  ações recentes. Filtros 24h/7d/30d; SWR 30 s; API cache 60 s.

## Operação

Variáveis:
```
ANALYTICS_ENABLED=1
ANALYTICS_INGEST_KEY=<mesmo valor na Vercel e no Railway>
ANALYTICS_DB_PATH=/data/analytics.db   # opcional
```

- Sem `ANALYTICS_INGEST_KEY`, o ingest responde **503** (fail-closed) e o
  proxy descarta o lote em silêncio; a landing nunca quebra.
- O proxy na Vercel tem o mesmo `ANALYTICS_INGEST_KEY` e injeta geo/UA/IP
  (projeto de produção **`magic-leads-frontend-final`**).
- Bot filter no servidor (UA): Googlebot, headless, preview, curl, etc.
- Rate limit: 120 lotes/min por IP.
- Limites: 20 eventos/lote, 24 KB no proxy, 32 KB no backend.

## Verificação

```bash
pytest tests/test_analytics.py -q
cd backend && ruff check . --select=E,F,W,I --ignore=E501
cd frontend && npx tsc --noEmit && npm test -- --run
```

Testes: classificação UTM/referrer/bot/UA, idempotência de `event_uid`,
ausência de IP, resumo/funil, rate limit, retenção e endpoint com chave.
