# Opportunities — mapa + bairros dentro do dashboard real

**Branch:** `feat/territory-view-preview` (não pushed, produção intocada)
**Onde vive:** tela **Opportunities / Pre-inspection** do dashboard autenticado
**Capturas:** `reports/dashboard-map-preview/`

---

## 1. O que mudou face à v2

A v2 era uma rota isolada (`/opportunities-preview`). A v3 **não tem página
separada**: é um painel dentro da tela real, com o mesmo sidebar, topbar, tabs,
filtros e os cartões de leads logo abaixo.

```
[ sidebar real ] [ topbar: cidade + busca ]
                  [ KPIs reais ]
                  [ tabs: All | Reactive | Preventive | Works ]
                  [ filtros reais: cidade, ofício, severidade… ]
                  ┌ Where the work is ──────────── [Hide map] ┐
                  │ cidade · ofício · chips                    │
                  │ [ mapa de pins ]   [ lista de bairros ]    │
                  └────────────────────────────────────────────┘
                  [ Neighborhood: Dorchester × ]   ← filtro ativo
                  [ cartões de leads filtrados               ]
```

- O painel é **expansível** (`Hide map` / `Show map`), aberto por defeito.
- Cidade e ofício do painel são **os mesmos filtros** da dashboard: escolher no
  painel atualiza a topbar e o feed; escolher na topbar atualiza o painel.
- Clicar num bairro (pin ou linha) **não navega**: aplica o filtro de ZIPs ao
  feed, mostra o chip do bairro e faz scroll suave até aos cartões.
- O filtro limpa-se com o `×` do chip ou ao mudar de cidade/ofício.

## 2. Todas as cidades ativas

O painel usa a lista real de cidades da dashboard (`cityOptions`), não uma lista
fixa: **New York, Chicago, Dallas, Boston** (e “All” na topbar).

| Cidade | Comportamento |
|---|---|
| **Boston** | Mapa com 22 bairros (ZIPs agregados: Dorchester = 02122/02124/02125) |
| **Dallas** | 11 setores + **Other areas**; mapa só com os setores (o catch-all estica o enquadramento) |
| **New York** | Boroughs por prefixo de ZIP + Other areas |
| **Chicago** | Seletor funciona; o mapa mostra **“Map unavailable for this city”** e os leads de Chicago aparecem normalmente abaixo |
| **All cities** | Painel pede para escolher uma cidade; feed global continua como hoje |

“Other areas” mantém **todos** os leads no agregado (não escondemos registos),
mas não entra no mapa para não abrir o zoom até aos subúrbios.

## 3. Filtro por bairro no feed

- `GET /api/opportunities` ganhou `zips=02122,02124,02125` (lista de ZIPs do
  bairro, máx. 200).
- `opportunity_workflow.list(zips=[...])` adiciona
  `SUBSTR(TRIM(zip_code),1,5) IN (...)` à query já existente.
- `PreventiveFeed` passa `filters.zips`; o chip de bairro limpa o filtro.
- O filtro é aplicado no servidor: os cartões abaixo são exatamente os leads
  daquele bairro (sem carregar tudo e filtrar no cliente).

## 4. Decisões aprovadas

1. **Dallas:** mantidos os 11 setores; restantes em “Other areas”.
2. **View leads / clique no bairro:** filtra o feed na mesma tela + scroll suave;
   não abre página nem drawer.
3. **Tiles:** Esri World Dark Gray + labels (sem chave, com atribuição).
4. **Chicago:** presente no seletor; mapa substituído por aviso discreto; leads
   normais abaixo.

## 5. Dados e honestidade

| Campo | `opportunity_workflow` |
|---|---|
| `zip_code` | 100% Boston/Dallas |
| `category` | 100% |
| `neighborhood`, `lat/lng` | **não existem** (ficam em `leads`) |

- Agrupamento por ZIP → bairro no cliente (`neighborhoods.ts`), num único
  ficheiro de mapeamento para revisão.
- Boston: bairros oficiais. Dallas: setores amplos (Downtown & Uptown, Oak Cliff,
  East Dallas…). NYC: boroughs. Nada inventado; sem ZIP reconhecido → Other areas.
- Mapa: centroide do bairro, não morada. Clusters somam oportunidades dos
  bairros próximos. “Near me” usa geolocalização do browser, só a pedido, e a
  posição não sai do dispositivo.

## 6. Performance

- Agregação territorial (SQL `GROUP BY`): **5,7 ms** Boston (1.027 linhas → 154
  grupos) e **6,7 ms** Dallas (7.264 → 219), medidos em produção.
- O painel usa hoje o snapshot real exportado (read-only) para os pins; em P1
  passa a chamar `GET /api/opportunities/territories`.
- Filtro de bairro no feed: predicado adicional sobre o subconjunto da cidade
  (≤ ~7 mil linhas no período), sem impacto percetível; índice composto
  (`source_kind, city, zip_code, category`) se o p95 subir.
- Tiles são cacheados pelo browser; pins são DOM simples.

## 7. Validação local (dev)

As capturas foram feitas na dashboard real, com backend local
(`127.0.0.1:8011`), proxy same-origin do Next (`NEXT_PUBLIC_API_PROXY=true`) e
uma amostra read-only de 100 oportunidades preventivas reais semeada no
`data/leads.db` de desenvolvimento. Nenhuma escrita em produção.

```bash
cd frontend
npm run dev                    # com API_PROXY_TARGET no backend local
node scripts/dashboard-map-shots.mjs
```

## 10. Aba Opportunities (leads reativos) — integração final

O mesmo painel foi replicado na aba **Opportunities**, logo abaixo dos 4 cartões
(*In your interest / Urgent / With owner / New*) e da barra de filtros. Aí a
fonte é a tabela `leads` (13,6 mil ativos nos últimos 7 dias), não o preventivo.

- **Endpoint:** `GET /api/leads/neighborhoods?city=&type=&category=&urgency=&include_closed=&days=7`
  — um `GROUP BY` no SQLite com **o mesmo WHERE do feed** (`is_feed_ok`,
  `signal_type`, status, janela, gate de utilizador).
- **Filtro do feed:** `neighborhoods=` / `zips=` / `no_geo=true` no
  `/api/leads/today`; o clique no mapa/lista aplica o filtro no servidor,
  mostra o chip do bairro e faz scroll suave até aos cartões.
- **Semântica exata do bairro:** a linha entra na zona se `neighborhood` bate,
  **ou** se não tem bairro e o ZIP pertence à zona (`neighborhood='' AND zip IN
  (...)`). Sem esta regra, um ZIP partilhado por dois bairros inflacionava a
  contagem (ex.: NYC 10462: 200 em vez de 47).
- **Filtros do mapa iguais aos cartões:** deadline only, camada
  (reactive/permit), tipo de proprietário e busca passam também para
  `/api/leads/neighborhoods`; o mapa e o feed nunca divergem.
- **Agrupamento por cidade:**
  - Boston → bairro (`leads.neighborhood`, 95% na janela);
  - New York → borough (96%);
  - Dallas → ZIP → setor (11 setores + Other areas); ZIPs têm 85% de cobertura;
  - Chicago → community area oficial (1–77) + ZIP (bairro só em 10%).
- **Coordenadas:** quando o grupo não traz `lat/lng` (Dallas), usamos os
  centroides por ZIP já derivados no snapshot preventivo; “Other areas” fica na
  lista, sem pin, para não esticar o enquadramento.
- **Performance:** a agregação pura custava ~97 ms (lookup aleatório por linha).
  O índice covering `idx_leads_geo(is_feed_ok, city COLLATE NOCASE, date_reported,
  created_at, signal_type, lead_status, signal_status, reserved_by, neighborhood,
  zip_code, lat, lng)` baixou para **0,4–7,1 ms** no tamanho de produção (135k),
  já a contar os frescos. A criação é `CREATE INDEX IF NOT EXISTS` no arranque
  (**234,5 ms** numa base de 135k; segunda execução 0,57 ms). Um índice antigo
  sem `created_at` é recriado uma vez.
- **Ligação de leitura:** a agregação reutiliza uma ligação SQLite persistente
  (com lock); evita abrir/fechar uma ligação por pedido.

## 11. Oportunidades frescas (<24 h)

- **Definição:** `leads.created_at` nas últimas 24 h; no preventivo conta também
  prazo de inspeção ≤3 dias.
- **Backend:** `fresh` por grupo em `/api/leads/neighborhoods` e por zona/total
  em `/api/opportunities/territories`.
- **Mapa:** pin/cluster âmbar com halo pulsante e ponto no canto; animação
  desligada em `prefers-reduced-motion`.
- **Lista:** selo `NEW <n>`, chip `<n> NEW` no cabeçalho, toggle
  **New (<24h)** e ordenação fresh-first.
- **Pre-inspection:** passa a ler a API `territories` ao vivo (fallback ao
  snapshot). Os centroides dos ZIPs continuam a vir do snapshot.

Capturas: `reports/opportunities-tab-preview/` (Boston, filtro por Dorchester,
Near me, Dallas, Chicago, mobile, `fresh-*-boston.png`).

## 12. Pendências antes do deploy


- [ ] Feature flag `OPPORTUNITIES_MAP_ENABLED=0` e painel só com a flag ligada.
- [x] Substituir o snapshot pela API `territories` (P1) no painel preventivo.
- [ ] Validar com ops os 11 setores de Dallas.
- [ ] Traduzir “Other areas” (PT/ES) quando o mapeamento for para o backend.
- [ ] Chicago: precisa de ZIP/geo na ingestão para ter pins.
- [x] Medir p95 do feed com filtro de ZIPs e criar o índice covering.

## 13. Runbook pós-deploy (obrigatório)

1. Confirmar `railway deployment list` = SUCCESS no commit esperado e `/health`
   healthy. Procurar no log `[DB] idx_leads_geo ...` e `[GEO] warmup ...`.
2. Correr a verificação de latência:

```bash
cd frontend
AUDIT_API_URL=https://magic-leads-production.up.railway.app \
AUDIT_TOKEN=<sessão com acesso ativo> \
node scripts/audit-map-ui.mjs --latency-only
```

3. Critério **go/no-go**: `Server-Timing: db` < 50 ms nas 4 cidades (Boston,
   NYC, Dallas, Chicago), HTTP 200 e payload com `total`/`groups`. Qualquer
   falha bloqueia o deploy.
4. O modo completo (sem `--latency-only`) valida também lista = painel = feed,
   o clique no bairro, o destaque de frescos (selo + pin + toggle) e a
   agregação ao vivo do separador Pre-inspection.

