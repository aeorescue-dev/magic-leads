# Mapa Vivo de Amostra na Landing — plano e implementação (preview)

**Estado:** implementado na branch `feat/landing-live-map-preview`. **Sem push e
sem deploy.** Validado localmente com `audit-landing-map.mjs` (ALL PASS).

## 1. Decisões aprovadas

1. Herói com abas `[ Map | By trade ]`, mapa por defeito.
2. Contagens exatas a partir de **5** oportunidades; abaixo disso entra em
   `other`.
3. Teto de **60 zonas por cidade**.
4. Basemap **Esri Light Gray** (mesmo domínio já permitido no CSP).
5. Rollout com A/B de 2 semanas e kill switch `PUBLIC_LIVE_MAP_ENABLED`.

## 2. Endpoint público

`GET /api/public/live-map` — sem sessão, 60/min/IP.

```json
{
  "generated_at": "2026-11-15T21:30:00Z",
  "window_days": 7,
  "cities": [
    {
      "key": "boston",
      "label": "Boston",
      "totals": { "count": 384, "fresh": 41, "zones": 18, "other": 6 },
      "zones": [
        { "slug": "dorchester", "label": "Dorchester", "count": 58,
          "fresh": 7, "lat": 42.301, "lng": -71.061 }
      ]
    }
  ]
}
```

- Cabeçalhos: `Server-Timing: db;dur=…`, `Cache-Control: public, max-age=30,
  s-maxage=60, stale-while-revalidate=300`, `ETag` com **304**.
- Kill switch: `PUBLIC_LIVE_MAP_ENABLED=0` devolve **503
  `live_map_disabled`**; o frontend esconde a aba Map e cai em “By trade”.

## 3. Privacidade

| Regra | Implementação |
|---|---|
| Sem dados de lead | Só `slug/label/count/fresh/lat/lng`; nunca id, morada, owner, telefone, descrição |
| k-anonimato | Zonas com `<5` não aparecem; contam em `other` |
| Frescos | `fresh` só é exposto quando `>=3` |
| Geo | Centroide da zona arredondado a **3 casas** (~110 m) |
| ZIP | Resolvido no servidor; NYC usa borough, Boston bairro, Dallas setor, Chicago área/ZIP (o ZIP já é público na pesquisa) |
| Fontes | Zero termos de fonte/arquitetura no payload ou UI |

**População = trade grid** (`is_qualified=1`, `is_junk=0`, 7 dias, 16 ofícios):
o total do mapa, do herói e dos cartões nunca diverge. O `audit` compara os dois
(Boston 176 = 176).

## 4. Índice e performance

```sql
CREATE INDEX IF NOT EXISTS idx_leads_public_geo
ON leads (city COLLATE NOCASE, date_reported, created_at, issue_category,
          case_status, neighborhood, zip_code, lat, lng)
WHERE is_qualified = 1 AND COALESCE(is_junk, 0) = 0;
```

Medido numa cópia com as **135.951** linhas de produção:

| Métrica | Valor |
|---|---|
| Criação do índice | **102,4 ms** |
| Tamanho | **6,5 MB** |
| 4 cidades numa query | **16,1 ms** (15,0–16,9 ms em 8 execuções) |
| Plano | `SEARCH l USING INDEX idx_leads_public_geo (city=? AND date_reported>?)` |
| `quick_check` | `ok` |

Cache em 3 camadas: in-process 60 s com *stale-while-revalidate* (lock
não-bloqueante), HTTP/CDN e warm-up no arranque (medido **50 ms** local). O
cálculo corre no máximo **1×/min**, independentemente do tráfego.

## 5. UX

- O painel direito do herói ganhou as abas **Map** (defeito) e **By trade**
  (a grelha existente, sem regressões).
- Mapa com bolhas de contagem, halo âmbar nos frescos, overlay
  `N opportunities` + `N new in 24h`, e as 3 zonas mais quentes em chips.
- Cidade partilhada com os chips do herói; ZIP muda automaticamente para
  “By trade”.
- Clique numa zona abre o **teaser** no modal: `LIVE AREA · <cidade>`,
  `<zona>`, contagem + frescos, 3 benefícios e `AuthForm` já em modo
  **Create account** (com empresa).
- Mobile: cartão abaixo do ZIP, 300 px, `scrollWheelZoom` desligado, chips
  acessíveis por teclado.
- `prefers-reduced-motion` desliga a pulsação.

## 6. Ficheiros

- `backend/services/public_map.py` (novo), `backend/main.py` (endpoint +
  warm-up + kill switch), `backend/services/db.py` (índice + retry de init).
- `backend/data/zip_centroids.json` (centroides de Dallas/Boston/NYC).
- `frontend/components/landing/PublicLiveMap.tsx` (novo),
  `LandingShell.tsx` (contexto do modal), `AuthForm.tsx` (`initialRegister`),
  `(marketing)/page.tsx` (abas), `lib/api-client.ts`, i18n EN/PT/ES,
  `app/globals.css`.
- `frontend/scripts/audit-landing-map.mjs` (novo).
- `tests/test_public_map.py`, `tests/test_public_map_api.py`.

## 7. Validação local

```bash
cd frontend
node scripts/audit-landing-map.mjs
```

Cobre: latência <50 ms, 4 cidades, igualdade com o trade grid, ausência de
campos privados, piso de 5, frescos ≥3, coordenadas a 3 casas, ETag/304, mapa
por defeito, bolhas + chips, troca de cidade, aba By trade, teaser e modo de
registo. **ALL PASS** (endpoint 0,5–1,8 ms).

Capturas: `reports/landing-live-map-preview/01-hero-map.png`,
`02-hero-trades.png`, `03-teaser-modal.png`.

## 8. Antes de produção

1. `PUBLIC_LIVE_MAP_ENABLED=0` no Railway antes do deploy; ligar no canary.
2. Confirmar no arranque `[DB] idx_leads_public_geo criado …` e
   `[PUBLIC-MAP] warmup …`.
3. `audit-landing-map.mjs` contra produção (sem token) com o gate de 50 ms.
4. A/B 50/50 durante 2 semanas (CTR do teaser, início de registo, LCP).
5. Só então tornar o mapa o default permanente.
