# System Health — painel operacional (Fase 27)

Rota: **`/admin/system-health`** (só leitura).
API: **`GET /api/admin/system-health?window=24`** (sessão + `users.is_admin`).

O painel responde a uma pergunta por camada: *“isto ainda está a produzir valor
ou está parado/degradado sem ninguém notar?”* Todos os números vêm de tabelas
persistidas, nunca de contadores em memória (que reiniciam no deploy).

## 1. Camadas, pesos e score

| Camada | Peso | O que mede |
|---|---:|---|
| Ingestão | 20 | Frescura por cidade (`MAX(date_reported)`), runs, `inserted`, streak de 0 |
| Enriquecimento | 15 | Prontos vs backlog, quota de domínio/Brave, fila de e-mail, owner backfill |
| Outreach | 20 | Fila + blocker, cap/caixa, warm-up, bounce/complaint, pausas |
| Web Push | 10 | Entregas 24h, subscrições mortas, dispositivos ativos, cliques |
| Cotas & Custos | 10 | Brave usado/limite/bloqueado, Searchbug $/24h + ghost % |
| Infra | 15 | Worker, backup, disco, tokens Gmail, VPS |
| Alertas | 10 | Abertos, críticos recentes, históricos (>7d), idade |

- Score de cada camada: **100 − penalizações** (0–100).
- Estado: `>=90 ok`, `>=60 warn`, `<60 fail`.
- Score global: média ponderada. **Estado global: o pior dos sete** (um
  problema não fica escondido por uma média alta).
- A UI mostra sempre o número + barra/anel + etiqueta textual (nunca só cor).

### Regras de penalização (resumo)

**Ingestão** — por cidade: 24–36h `-25`, >36h ou sem data `-50`; 2 runs
seguidos com `inserted=0` `-30`; sem runs `-50`; run vencido (`intervalo×1,75`)
`-30`; último run em erro `-20`.

**Enriquecimento** — Brave bloqueado `-25`; zero `ready` com backlog `-25`;
scheduler sem jobs depois das 10h NY `-15`; fila >24h `-15` / >72h `-30`;
owner backfill sem run em 6h `-10`.

**Outreach** — caixa pausada `-30` cada (cap 60); motor desligado com fila
`-30`; bounce >2% `-40` (>1% `-20`); complaint >0,1% `-50`; fila >3h com
blocker inesperado `-20`. `mailbox_cap` e `quiet_hours` são esperados: não
penalizam, mas o blocker fica visível.

**Push** — `not_configured` `-60`; zero entregas com subs ativas `-25`;
>20% mortas (≥10 entregas) `-30`; zero subs `-15`.

**Cotas** — Brave bloqueado `-40`, ≥90% `-20`; Searchbug >50% de
`transport_error` em 15 min `-40`; custo/hora 3× a média `-15`; >30% pagas
sem telefone `-15`.

**Infra** — BD `-50`; worker `-40`/`-10`; tokens Gmail `-40`; backup `-30`/`-15`;
VPS `-20`; disco >90% `-30`, >80% `-15`.

**Alertas** — crítico recente `-30`; crítico >7d `-5` (cap 20); warning `-2`;
alerta vivo >24h `-10`. Os históricos continuam no feed, mas não pintam o
painel inteiro de vermelho para sempre.

## 2. Snapshot e histórico

- A Control Tower grava **1 snapshot a cada 15 min** em
  `system_health_snapshots` (payload compacto: scores/status/headline por
  camada, ~750 bytes).
- **Retenção: 30 dias**; prune diário na própria captura.
- A API devolve `history` (até 24h) para o sparkline do score geral.
- Cache da API: **30 s** (refresh storms de vários admins não batem na BD).

## 3. Interface

`frontend/app/admin/system-health/page.tsx`:

1. **Score geral** (anel 0–100 + estado + motivos + sparkline 24h).
2. **7 cartões** com score, barra, headline e 3 métricas.
3. **Ingestão por cidade** + últimos runs (trigger, inseridos, brutos).
4. **Cotas** (barra Brave, Searchbug, backlog por cidade, owner backfill).
5. **Outreach** (blocker, caixas, enviados/cap, warm-up, 48h OK/falha).
6. **Push** (aceites/expiradas/mortas/sem VAPID, subs, cliques).
7. **Infra** (checks da Control Tower) e **alertas abertos**.
8. Link **System Health** no header do `/admin`.

SWR com refresh de 30 s, `keepPreviousData`; sem botões de escrita nesta fase.
Tipos/helpers puros em `frontend/lib/system-health.ts` (testados em vitest).

## 4. Baseline de produção (02/11/2026 00:09 UTC)

```
overall 97 warn  (4 críticos históricos + alerta vivo >24h)
ingest      100 4/4 cidades frescas · último run há 2,2h
enrichment  100 165 prontos · 24.433 por enriquecer · domínio 0/248
outreach    100 4/4 envios hoje · fila 1 (blocker mailbox_cap, esperado)
push        100 21 entregas 24h · 12 dispositivos ativos
quotas      100 Brave 16/250 · Searchbug $0,00/24h
infra       100 worker OK · backup 12h · disco 21%
alerts       66 6 abertos (4 históricos >7d)
```

## 5. Verificação

```bash
pytest tests/ -q                                  # 1204 + 1 skipped
cd backend && ruff check . --select=E,F,W,I --ignore=E501
cd frontend && npx tsc --noEmit && npm test && npm run lint
```

Testes dedicados: `tests/test_system_health.py` (scores, camadas, snapshots) e
`frontend/tests/unit/system-health.test.ts` (thresholds, formatação,
sparkline).

## 6. Fora de âmbito (fase seguinte)

- Drill-down por camada e export CSV.
- Tendências de 7 dias e “pior estado”.
- Prune de `health_checks` (cresce ~900 linhas/dia; hoje sem limite).
- Ações guardadas (correr scraper, retomar caixa) — só com confirmação e
  auditoria; a Fase 1 é estritamente read-only.
