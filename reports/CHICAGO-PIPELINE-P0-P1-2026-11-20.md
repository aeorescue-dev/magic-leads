# Chicago P0/P1 — implementação e validação (2026-11-20)

**Worktree:** `garimpador-pipeline-fix` · **Branch:** `fix/chicago-pipeline` · **Base:** `master` @ `0294448`
**Estado:** implementado e testado localmente. **Nada foi publicado em produção** (sem push, sem deploy, sem migration executada).

---

## 1. O que foi implementado

### P0 — ZIP e mapa

| Item | Implementação |
|---|---|
| Derivar ZIP por coordenadas | `backend/services/zip_lookup.py` + `backend/data/chicago_zip_centroids.json` (60 ZIPs de Chicago, centroides derivados dos leads). Distância máxima 8 km; devolve `zip_source=centroid`. |
| Fallback por endereço | Correspondência exata do endereço normalizado nos leads 311 de Chicago (`zip_source=address`). |
| Fallback de contacto | `contact_1_zipcode` de alvarás, validado contra a faixa 606xx/607xx/608xx (`zip_source=contact`). |
| Rastreio | Nova coluna `opportunity_workflow.zip_source` (CREATE + migração idempotente). |
| Violações de Chicago | `fetch_chicago_violations` passa a preencher `zip_code`/`zip_source`; mantém a chave de imóvel por endereço para não duplicar. |
| Backfill | `backend/scripts/backfill_chicago_zip.py` (dry-run por defeito, `--apply` para gravar). O próximo passe do coletor também atualiza as linhas antigas via `_enrichment_fields`. |
| `territories` | Deixa de descartar linhas sem ZIP: devolve `zones` (com ZIP), `unmapped` (sem ZIP) e `niches` de **todas** as linhas. |
| UI | Painel do mapa mostra o escopo “Oportunidades preventivas · 30 dias”, nichos ao vivo mesmo sem zonas e “X oportunidades sem localização (ZIP)”. |

### P1 — volume, permits e clareza

| Item | Implementação |
|---|---|
| Paginação + watermark | `fetch_chicago_violations` pagina por `coalesce(violation_last_modified_date, violation_date)` com watermark em `phase1_watermarks`; orçamento padrão `PHASE1_CHICAGO_VIOLATIONS=1000` (configurável). |
| Permits de Chicago | `fetch_chicago_permits` mapeia `ydr8-5enu` para oportunidades `authorized_work`, com endereço, ZIP (coordenadas/contacto), categoria, custo declarado e histórico. |
| Scheduler | Passa `chi_violations=1000` e `chi_permits=300` (configuráveis) em vez do limite operacional 100. |
| Contadores | Sidebar mudou de “Oportunidades” para **“Leads no feed”** (PT/EN/ES); mapa rotulado como oportunidades preventivas · 30 dias. |

---

## 2. Validação local

### Testes

| Verificação | Resultado |
|---|---|
| `pytest tests/test_chicago_pipeline.py tests/test_opportunity_territories.py -q` | **14 passed** |
| `pytest tests -q` (suite completa, execução isolada) | **1.735 passed, 1 skipped** (4m57s) |
| `ruff check` nos ficheiros alterados | **All checks passed** |
| `npx tsc --noEmit` | **sem erros** |
| `npm run lint` | **0 erros** (122 warnings pré-existentes) |
| `npm run build` | **OK** |

### Cobertura real do resolvedor (API pública, read-only)

Amostra de 100 violações abertas e 50 alvarás de Chicago, executada localmente:

```json
{
  "violations": { "total": 100, "resolved": 100, "by_source": { "centroid": 100 }, "max_centroid_km": 2.46 },
  "permits":    { "total": 50,  "resolved": 50,  "by_source": { "centroid": 50 } }
}
```

- 100% de cobertura na amostra, com erro máximo de 2,46 km.
- Na produção, o fallback por endereço entra primeiro quando o endereço existe nos leads 311; o centroid cobre o resto.

### Comportamento esperado em produção (sem executar)

| Cenário | Antes | Depois |
|---|---|---|
| Chicago com ZIP nas oportunidades | 0/166 | preenchido no próximo passe + backfill |
| Mapa Chicago | 0 zonas / 0 nichos | zonas reais + nichos; linhas sem ZIP aparecem como `unmapped` |
| Oportunidades preventivas Chicago | 166 (top-100 repetido) | backfill paginado + permits `authorized_work` |
| Contadores | “2.249” leads vs “0” mapa | “Leads no feed” e “Oportunidades preventivas” rotulados |

---

## 3. Ficheiros alterados

```text
backend/services/zip_lookup.py              (novo)
backend/data/chicago_zip_centroids.json     (novo)
backend/scripts/backfill_chicago_zip.py     (novo)
backend/services/db.py                      (zip_source + phase1_watermarks)
backend/services/opportunity_workflow.py    (zip_source, territories, centroides)
backend/services/phase1_enrichment.py       (ZIP, watermark, permits)
backend/services/phase1_scheduler.py        (limites Chicago)
frontend/components/dashboard/opportunities-map/NeighborhoodPanel.tsx
frontend/components/dashboard/opportunities-map/NeighborhoodList.tsx
frontend/lib/api-client.ts
frontend/lib/i18n/{pt,en,es}.ts
tests/test_chicago_pipeline.py              (novo)
tests/test_opportunity_territories.py
```

---

## 4. O que falta antes de publicar

1. ~~Fechar a suite completa sem execuções concorrentes~~ — feita: **1.735 passed, 1 skipped**. (A primeira tentativa teve 78 erros de `showcase_checkouts` porque dois `pytest` partilhavam o mesmo SQLite temporário; a execução isolada passou.)
2. Revisão do diff e aprovação do owner.
3. Deploy backend (Railway) + frontend (Vercel) a partir de `master` — **não executado**.
4. Depois do deploy: `python -m backend.scripts.backfill_chicago_zip --apply` e validar Chicago no mapa.
5. Confirmar que `VOICE_FREEZE=1` continua ativo; a frente BR permanece em `feat/br-environmental-mvp`.

---

## 5. Limitações conhecidas

- O centroid é uma aproximação; o fallback por endereço reduz o erro quando o endereço existe nos leads. Linhas sem ZIP continuam visíveis como `unmapped`, nunca desaparecem.
- Violações de Chicago não publicam prazo de cumprimento nem multa; esses KPIs continuam a 0 para Chicago (limitação da fonte, não do parser).
- O telefone continua desligado por decisão de custo (`ENRICH_MAX_CALLS_PER_DAY=0`).
- O backfill por endereço pode não resolver todos os 166; o próximo passe paginado do coletor reencontra os mesmos endereços e preenche via coordenadas.
