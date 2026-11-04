# Web Analytics first-party (Fase 29)

Rota: **`/admin/analytics`**. API: **`GET /api/admin/analytics?range=24h|7d|30d`**
ou **`?start=YYYY-MM-DD&end=YYYY-MM-DD`** (inclusive, UTC; máx. 366 dias).
Sessão + `is_admin`. Ingest: **`POST /api/analytics/ingest`** (chave
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
4. Links de voz (`/r/<token>`): o redirect adiciona
   `utm_source=voice&utm_medium=call&utm_campaign=voice_campaign_<id>&utm_content=showcase`
   quando o link tem `voice_call_id`/`campaign_id`; o token `vt` mantém-se. Isto
   isola o tráfego das campanhas #3/#4 do tráfego direto e do e-mail frio.
5. O CTA de checkout da vitrine (`ShowcaseCta`) envia `cta_click` com label
   `showcase_checkout`; os restantes CTAs têm labels próprios (`hero_cta`,
   `calc_cta`, `faq_cta`, `language_pt`, ...). Para conversão real, contar
   `showcase_checkout`/checkout, não qualquer CTA.

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

- **Saúde do tráfego**: score 0–100 = **40% volume + 30% engagement + 30% conversão**.
  - `volume = clamp(50 + 50*(visits-prev_visits)/prev_visits, 0, 100)`; sem
    período anterior (`prev=0`) devolve 100. É relativo, não volume absoluto.
  - `engagement = clamp((min(avg_engagement_s,60)/60)*60 + (avg_scroll_pct/100)*40, 0, 100)`.
  - `conversion = clamp((min(cta_rate,5%)/5%)*60 + (min(form_rate,2%)/2%)*40, 0, 100)`.
  - `bounce = 1 - engaged/visits`, com `engaged = scroll>=50% OR cta_click OR
    form_submit`. **Não é o bounce clássico de analytics** (sessão de uma página):
    é a fração de sessões sem scroll a 50% nem clique/submissão. Bounce não entra
    diretamente na fórmula; é um sintoma do engagement.
  - Amostra pequena (<100 visitas) torna o score ruidoso; 1 CTA em 19 visitas
    satura o teto de 5% e 1 form em 19 satura o teto de 2%.
- Cards: visitas, únicos, pageviews, cliques CTA, formulários, tempo médio,
  bounce — com sparkline e delta.
- Gráficos: tráfego (hora/dia), origens + **campanhas/UTM (campaign/content)**,
  funil, **e-mail → lead** (forms por campanha/step/cidade), geografia com
  **CTA e forms por cidade**, dispositivo/idioma, ações recentes **com a
  origem (email/UTM/direct)**. Filtros 24h/7d/30d **ou período De/Até**
  (inclusive, UTC, máx. 366 dias); SWR 30 s; API cache 60 s.
- **Exportar CSV** (long format: `section,metric,label,value`) com o período
  filtrado, séries, origens, campanhas, geo, funil, atribuição e eventos.
- `email_attribution` isola as sessões `source='email'` e cruza-as com
  `form_submit`; `campaigns` agrupa por `source/medium/campaign/content`.
  O tráfego de voz **não** entra em `email_attribution`: aparece em `sources` e
  `campaigns` como `voice/call` + `voice_campaign_<id>`.

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
