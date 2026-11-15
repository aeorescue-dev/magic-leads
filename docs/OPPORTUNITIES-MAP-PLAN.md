# Opportunities com mapa + bairros — proposta v2

**Branch:** `feat/territory-view-preview` (não pushed, produção intocada)
**Preview:** `/en/opportunities-preview`
**Dados:** snapshot real read-only de 2026-11-15 16:17 UTC

---

## 1. Princípio

O cliente é um **contractor**, não um analista. Ele escolhe a cidade e o ofício e
quer ver **onde estão os trabalhos** e **quantos** há em cada bairro, com um
caminho direto para os leads.

Por isso a v2 substitui os cartões por ZIP, a matriz e os KPIs por **dois
elementos**: um mapa da cidade e uma lista curta de bairros. Nada de “signals”,
“heatmap”, “matriz”, gráficos minúsculos ou o mesmo bairro repetido por ZIP.

## 2. Ecrã

```
Opportunities                          [Boston] [Dallas] [New York]
Roofing & Structure · Boston

[All trades] [Construction & Permits] [Structure] [Electrical] [Roofing] ...

┌──────────────────────── mapa ────────────────────────┐  ┌── bairros ───────────┐
│  (Near me)                                           │  │ 44 opportunities     │
│                                                      │  │ in 13 neighborhoods  │
│        (204)  (112)     (86)                         │  │                      │
│           (41)     (37)                              │  │ West Roxbury    15   │
│                                                      │  │ Dorchester       7   │
│                    (59)                              │  │ Roxbury          5   │
│  ┌ Dorchester · 204 opportunities ─── [View leads] ┐ │  │ ...                  │
└──────────────────────────────────────────────────────┘  └──────────────────────┘
```

- **Mapa** (esquerda): pins por bairro com o número de oportunidades; clusters
  quando os bairros estão próximos; posição estimada pelo centro do bairro.
- **Lista** (direita): nome do bairro, total no ofício escolhido e botão
  **View leads**. Sem barras, sem percentagens, sem métricas.
- **Near me**: botão explícito (não pede permissão ao abrir), mostra a posição
  do utilizador e ordena a lista por distância (“2.4 mi”).
- **Mobile**: alternador Mapa/Lista; a lista ocupa a largura toda.
- Sem aba nova: isto é a própria tela de **Opportunities**, com os filtros de
  cidade e ofício que já existem.

Fluxo de ação: cidade → ofício → bairro → **View leads** abre o feed com
`city` + `zip`/bairro + `category` (o feed já aceita esses filtros). Nenhuma
regra nova de cobrança.

Capturas: `reports/opportunities-map-preview/` (01 visão geral, 02 ofício,
03 Dallas, 04 perto de mim, 06 bairro selecionado, 07 view leads, 05/08 mobile).

## 3. Agrupamento por bairro (a correção principal)

O `opportunity_workflow` guarda **ZIP**, não bairro. A v1 mostrava um cartão por
ZIP e por isso “Dorchester” aparecia três vezes. A v2 agrupa os ZIPs:

| Cidade | Regra | Exemplo |
|---|---|---|
| **Boston** | ZIP → bairro oficial | 02122/02124/02125 → **Dorchester** (204) |
| **Dallas** | setores reconhecíveis | 75203/75208/75211/75224/75233/75236/75237 → **Oak Cliff** |
| **New York** | borough pelo prefixo do ZIP | 100/101/102 → **Manhattan**; 112 → **Brooklyn**; 104 → **Bronx** |
| Chicago | fora do mapa por agora: 50 registos sem ZIP | — |

Regras de higiene:

- **Nada inventado.** Em Dallas usamos setores amplos (Downtown & Uptown, Oak
  Cliff, East Dallas, South Dallas…). Nomes de bairro finos só entram quando
  houver fonte validada por ops.
- **Fora do perímetro**: ZIPs de subúrbios (Coppell, Garland, Grand Prairie,
  Lancaster, Duncanville, Mesquite) e registos sem ZIP reconhecido (“Other
  Boston/Dallas”) não entram no mapa nem na lista. **Continuam no feed.**
- Os totais do cabeçalho refletem só o que está no mapa: Boston 1.026 de 1.027
  (1 sem ZIP), Dallas 7.094 de 7.264 (170 em subúrbios).

A tabela de mapeamento vive num único ficheiro
(`components/dashboard/opportunities-map/neighborhoods.ts`) para revisão e
substituição sem tocar no resto.

## 4. Geolocalização

- Só é pedida quando o utilizador carrega em **Near me** (nunca no carregamento).
- A posição fica **no browser**; não é enviada nem guardada no servidor.
- A distância é calculada no cliente (Haversine até ao centro do bairro) e
  arredondada (`2.4 mi`). Sem coordenadas exatas do imóvel na UI.
- Se a permissão for negada, o botão mostra “Location off” e uma explicação
  curta; a lista continua utilizável por volume.

## 5. Mapa

- **Preview:** Leaflet 1.9 + MarkerCluster via CDN (zero dependências no
  `package.json`), com tiles **Esri World Dark Gray + labels** (sem chave,
  com atribuição). Testado local e no browser.
- **Produção:** avaliar MapLibre/Leaflet com um fornecedor licenciado ou manter
  Esri de acordo com os termos; o componente isola o provedor num único URL.
- Pins mostram **contagem** (não preço), agrupam-se quando próximos e abrem o
  bairro na lista. A posição é o centroide do bairro, não uma morada.
- Atribuição visível; sem watermarks de “API key”.

## 6. Performance

- A agregação continua a ser a query SQL já implementada e medida:
  **5,7 ms** Boston (1.027 linhas → 154 grupos) e **6,7 ms** Dallas
  (7.264 → 219), sem carregar o inventário para Python.
- O agrupamento por bairro é feito no cliente sobre ~150–220 linhas: custo
  desprezável e nenhum pedido extra.
- Payload ~8–12 KB por cidade; `Cache-Control: private, max-age=60`.
- Tiles são cacheados pelo browser; os pins são DOM simples (sem biblioteca de
  gráficos).
- Sem polling: a vista atualiza com o SWR do feed (60 s) quando integrada.

## 7. O que foi removido (e porquê)

- Cartões por ZIP repetidos → substituídos por bairros agregados.
- Matriz ZIP × nicho, heatmap, KPIs e barras minúsculas → removidos.
- Jargão (“Zones with signals”, “Matrix”, “Heatmap”) → vocabulário do contractor:
  “opportunities”, “neighborhoods”, “View leads”.

## 8. Fases

| Fase | Entrega |
|---|---|
| **P0** | Preview v2 (este branch): mapa + lista + geolocalização + dados reais |
| **P1** | Integrar na tela Opportunities atrás de `OPPORTUNITIES_MAP_ENABLED=0`; reutilizar `CityPicker` e chips de ofício; evento de seleção preenche os filtros do feed |
| **P2** | Endpoint `GET /api/opportunities/neighborhoods` (agregação por bairro no servidor, mesma tabela) + cache; move o mapeamento para o backend quando os alertas precisarem dele |
| **P3** | Bairros finos de Dallas com fonte validada; geocodificação por imóvel se o produto exigir pins exatos |

### Decisões pendentes

1. **Dallas:** validar os 11 setores com ops (ou manter só ZIP até haver fonte).
2. **Fornecedor de tiles:** Esri (rápido) vs MapLibre + fornecedor licenciado.
3. **Chicago:** precisa de ZIP/geo na ingestão para entrar no mapa.
4. **“View leads”:** abrir o feed com filtro de bairro (ZIPs do bairro) ou abrir
   um painel lateral com os leads? A v2 assume o feed filtrado.

## 9. Validação

```bash
cd frontend
npm run dev            # /en/opportunities-preview
node scripts/opportunities-map-shots.mjs
npx tsc --noEmit
npx eslint components/dashboard/opportunities-map "app/[locale]/(dashboard)/opportunities-preview"
```

O endpoint existente `GET /api/opportunities/territories` continua testado em
`tests/test_opportunity_territories.py` (4 testes) e não foi alterado nesta v2.
