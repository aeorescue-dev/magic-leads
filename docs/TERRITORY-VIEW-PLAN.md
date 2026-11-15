# Vista territorial (ZIP × nicho) — proposta e plano

**Branch:** `feat/territory-view-preview` (não deployada)
**Preview:** `/en/territory-preview` (rota isolada, sem link na navegação)
**Dados do preview:** snapshot real read-only de 2026-11-15 16:17 UTC

---

## 1. Resumo

O dashboard passa a ter uma terceira leitura do mesmo inventário: além da lista
cronológica de oportunidades, uma vista **territorial** que responde a “onde está
o trabalho?” e “qual nicho domina cada zona?”.

A unidade geográfica é o **ZIP** (zona). Entra em produção sem migração: o
`opportunity_workflow` tem ZIP e categoria em 100% das linhas de Boston/Dallas.
Nome de bairro e coordenadas por imóvel não existem nessa tabela — ficam para a
fase 2 (ver §3).

Três modos na mesma aba:

1. **Zonas** — cartões por ZIP com volume, mix de nichos, críticas e próximo prazo.
2. **Mapa** — bolhas por centroide de ZIP, tamanho = volume, cor = nicho dominante.
3. **Matriz** — ZIP × nicho, heatmap com contagens, para decidir oferta e equipas.

Um painel lateral mostra o detalhe da zona e o botão **“Apply to feed”**, que
prepara o feed existente com cidade + ZIP + nicho (deep link, sem nova query de
listagem).

## 2. O que o utilizador vê (preview validado)

| Ecrã | Ficheiro |
|---|---|
| Zonas (desktop) | `reports/territory-preview/01-zones-desktop.png` |
| Matriz | `reports/territory-preview/02-matrix-desktop.png` |
| Mapa (Dallas) | `reports/territory-preview/03-map-dallas.png` |
| Detalhe de zona | `reports/territory-preview/04-zone-detail.png` |
| Mobile 390 px | `reports/territory-preview/05-mobile-zones.png` |

Comportamento: filtro de nicho recalcula KPIs e cartões; selecionar zona abre o
detalhe; mapa e matriz partilham a mesma seleção; estados vazios tratados
(Chicago tem 50 registos históricos sem ZIP — aparece como “sem zonas”).

## 3. Realidade dos dados (medida em produção)

| Campo | `opportunity_workflow` | `leads` |
|---|---|---|
| `zip_code` | **100%** Boston (1.027) e Dallas (7.264) | Boston 99% · Dallas **6,7%** |
| `category` | **100%** | — |
| `neighborhood` | **não existe** | Boston 99% (15.876/16.033) · Dallas **0%** |
| `lat`/`lng` | **não existe** (0 linhas) | Boston 99% · Dallas 93% |

Consequências:

- A vista territorial **não pode depender de `neighborhood` nem de `lat/lng` do
  `opportunity_workflow`**: essas colunas não existem. O ZIP é a chave viável hoje.
- Para o mapa, os centroides vêm de duas fontes reais: `leads` quando tem ZIP
  (Boston/NYC, 100% exato) e junção por endereço quando não tem (Dallas, 47/55
  zonas; 8 zonas ficam fora do mapa e aparecem na lista).
- Nomes de bairro só são mostrados quando são oficiais/reconhecidos (Boston:
  Dorchester, East Boston, Hyde Park…). Em Dallas a zona aparece como
  **“ZIP 75214”** — não inventamos bairros. Um mapa ZIP→área de Dallas terá de ser
  validado por ops antes de entrar na UI.

## 4. Agregação no backend

### 4.1 Contrato

`GET /api/opportunities/territories?city=Boston&days=30&kind=preventive&category=Roof`

```json
{
  "city": "Boston",
  "kind": "preventive",
  "window_days": 30,
  "generated_at": "2026-11-15T16:17:53+00:00",
  "totals": { "count": 1027, "available": 1027, "critical": 53, "zones": 31 },
  "zones": [
    {
      "zip": "02124",
      "total": 101,
      "available": 101,
      "critical": 5,
      "next_deadline": "2026-11-14",
      "niches": [{ "key": "Permit_Rejected", "n": 53 }, { "key": "Structure", "n": 20 }]
    }
  ],
  "niches": [{ "key": "Permit_Rejected", "n": 487 }]
}
```

- Autenticação e gate de assinatura iguais ao feed (`_get_current_user` +
  `_require_active_access`).
- `Cache-Control: private, max-age=60`; o SWR do dashboard deduplica pedidos.
- Sem `source_payload` e sem termos de fonte no payload (invariante 27).

### 4.2 Implementação

Uma única query `GROUP BY zip, categoria`, já implementada em
`OpportunityWorkflowService.territories()`:

```sql
SELECT SUBSTR(TRIM(zip_code), 1, 5) AS zip,
       COALESCE(NULLIF(TRIM(category), ''), 'Unclassified') AS niche,
       COUNT(*) AS n,
       SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END) AS available,
       SUM(CASE WHEN <severidade crítica> THEN 1 ELSE 0 END) AS critical,
       MIN(compliance_deadline) AS next_deadline
FROM opportunity_workflow
WHERE source_kind = ? AND UPPER(TRIM(city)) = UPPER(?)
  AND LENGTH(TRIM(COALESCE(zip_code, ''))) >= 5
  AND date(COALESCE(received_at, created_at)) >= date('now', ?)
GROUP BY zip, niche
```

O Python só pivota ~200-400 linhas; **nunca carrega o inventário da cidade**.

### 4.3 Performance medida (produção, read-only)

| Cidade | Linhas no período | Linhas devolvidas | min / avg / max |
|---|---:|---:|---|
| Boston | 1.027 | 154 | 5,0 / **5,7** / 6,8 ms |
| Dallas | 7.264 | 219 | 6,3 / **6,7** / 7,2 ms |

Plano: `SEARCH opportunity_workflow USING INDEX sqlite_autoindex_... (source_kind=?)`
+ `TEMP B-TREE` para `GROUP BY`/`ORDER BY`. Não é preciso índice novo nesta escala.

Comparação com o caminho atual: `insights()` carrega todas as linhas do período
para Python e agrega em memória (≈12,5 ms para 1.329 linhas). É O(N): aos 100 mil
registos passa a ~1 s por pedido. **Recomendação:** migrar `insights()` para SQL
agregado no mesmo ciclo (fora do âmbito do preview) e manter a vista territorial
sempre em SQL.

Quando o volume justificar índice:

```sql
CREATE INDEX IF NOT EXISTS idx_wf_territory
  ON opportunity_workflow(source_kind, city, zip_code, category);
```

Só faz sentido depois de normalizar `city` na escrita (hoje há `Boston`/`BOSTON`
no `leads`), porque o `UPPER(TRIM(city))` impede o índice de cidade.

### 4.4 Payload no browser

Boston: 31 zonas × ~5 nichos ≈ 8 KB; Dallas: 55 zonas ≈ 12 KB. O preview usa o
mesmo formato (45 KB com as 4 cidades e metadados), sem chamadas em runtime.

## 5. Fluxo de distribuição para o utilizador

1. Utilizador escolhe cidade no topo (já existe `CityPicker`).
2. Vista **Zonas** ordena por volume; chips de nicho filtram tudo.
3. Clica numa zona → painel com mix completo, críticas e próximo prazo.
4. **Apply to feed** abre o feed com `city`, `zip` e `category` —
   reaproveita `GET /api/opportunities` (o `search` já aceita ZIP).
5. Mapa e Matriz são lentes da mesma seleção; não há estado paralelo.

Sem novos conceitos de cobrança, reservas ou revelações: é leitura do inventário
que o utilizador já pode comprar.

## 6. Fases

| Fase | Entrega | Estado |
|---|---|---|
| **P0** | Preview visual isolado + snapshot real | **feito neste branch** |
| **P1** | Endpoint + testes + feature flag (`TERRITORY_VIEW_ENABLED=0`) e aba no dashboard | a seguir à aprovação |
| **P2** | `neighborhood`/`lat`/`lng` no `opportunity_workflow` (nullable) + backfill por endereço (`geocode_jobs`); mapa por imóvel | precisa de migração |
| **P3** | Mapa com tiles (MapLibre) e agrupamento por bairro oficial; Dallas exige fonte/validação de áreas | opcional |

P2 é a única que toca em schema: `ALTER TABLE ... ADD COLUMN` é seguro em SQLite,
mas o backfill de coordenadas é batch e deve correr fora da janela de voz, como o
backfill preventivo.

## 7. Guardrails

- **Sem escrita**: a vista territorial só lê `opportunity_workflow`.
- **Sem termos de fonte**: rótulos vêm de `dashboard.cat.*`; nada de “311”,
  “violation”, “permit dataset”, “BBL”.
- **Bairros honestos**: nome só quando é conhecido; caso contrário ZIP.
- **Mapa honesto**: centroide de ZIP, nota explícita; zonas sem localização ficam
  na lista, não empilhadas no centro da cidade.
- **Sem dependências novas** no P0/P1 (o mapa é SVG; sem biblioteca de mapas).
- **Acessibilidade**: bolhas e linhas da matriz são focáveis por teclado; cores
  nunca são o único sinal (número sempre visível).

## 8. Como validar o preview

```bash
cd frontend
npm run dev
# abrir /en/territory-preview
node scripts/territory-preview-shots.mjs   # gera reports/territory-preview/*.png
```

## 9. Checklist antes de P1

- [ ] Aprovar copy (EN/PT/ES já adicionada em `lib/i18n/*`).
- [ ] Testar endpoint com `pytest tests/test_opportunity_territories.py`.
- [ ] Adicionar `fetchTerritories()` ao `lib/api-client.ts` e SWR key
      `["territories", city, days, niche]`.
- [ ] Feature flag desligada por defeito; aba só aparece com a flag.
- [ ] Medir p95 do endpoint em produção com 1 utilizador e com 20 concorrentes.
- [ ] Revisão de privacidade: o payload não expõe moradas nem IDs de registo.
