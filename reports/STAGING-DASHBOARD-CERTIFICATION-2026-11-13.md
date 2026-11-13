# Certificação do staging — Dashboard (landing congelada)

Data: 2026-11-13
Branch: `staging/opportunity-foundation`
Produção: `master` em `3b53962` — intocada, sem deploy ou migração.

## 1. Landing page — congelada e revertida

- **Nenhuma alteração pendente**: `git status` limpo e `git diff` vazio no repositório
  de staging.
- Todos os ajustes rejeitados foram revertidos com `git restore`:
  `frontend/app/[locale]/(marketing)/page.tsx` e os três dicionários (`en.ts`, `pt.ts`,
  `es.ts`).
- A landing está exatamente como em `HEAD`: hero original, inventário interativo intacto,
  sem secção `#prevencao`, sem item de menu, sem pill e sem alterações de copy.
- O único histórico recente relacionado é documental (remoção da maquete paralela e
  relatórios). **Não há código da landing modificado.**
- Diretriz registada: landing **congelada**; qualquer alteração futura exige autorização
  explícita e um novo ciclo de aprovação.

## 2. Dados de staging — restaurados ao estado certificado

Os 36 sinais de teste usados apenas para o inventário da landing foram removidos
(`external_id LIKE 'staging-inventory-%'`).

| Item | Estado |
|---|---|
| Leads reativos | 4 |
| Oportunidades preventivas | 14 |
| Reservadas | 0 |
| Property locks | 0 |
| Revelações hoje | 0 / 10 |
| New York (inventário público) | 2 sinais ativos (estado original) |

Nenhum dado de produção foi tocado; tudo vive em
`C:\Users\Fabio\AppData\Local\Temp\opencode\staging-opportunity\leads.db`.

## 3. Dashboard — funcionalidades certificadas

- **Fluxo preventivo** 1h → 48h → 48h: reserva, contacto, negociação, conversão e outcomes.
- **Card rico + drawer lateral**: severidade, categoria, morada, descrição, timeline,
  proprietário, valor estimado, tipo de proprietário, tags e CTA de consentimento.
- **Filtros unificados**: abas Todos/Reativos/Preventivos/Obras, cidades, especialidade,
  gravidade, “somente com prazo” e busca — partilhados pelos dois feeds.
- **Painel lateral**: Prazos críticos, Gravidade da amostra e ZIPs mais quentes, calculados
  a partir das linhas filtradas.
- **KPI**: sparklines e métricas detalhadas; no separador preventivo usa os quatro
  indicadores do protótipo.
- **Dados**: `insights` na API, `daily_series`, tags/timeline, `source_payload` não exposto.
- **Enriquecimento**: Managing Agent do HPD persistido, limpo e exposto só após reveal.
- **Ingestão preventiva**: serviço + script de staging, deduplicação por morada/BBL.

## 4. Evidência técnica

| Verificação | Resultado |
|---|---|
| `pytest tests/ -q` | 1678 passed, 1 skipped |
| `npm test -- --run` | 123 passed |
| `npx tsc --noEmit` | limpo |
| `npx eslint . --quiet` | limpo |
| `ruff check backend tests` | limpo |
| API preventiva | 14 oportunidades, 9 com prazo ≤ 7 dias, valor em risco $106.500 |
| API leads | 4 reativos |
| Quota | 0 / 10 |
| `source_payload` na resposta | ausente |
| Landing `git diff` | vazio |
| Produção | `3b53962` |

Cenários de erro já simulados e certificados: `PROPERTY_LOCKED` (409 + toast PT),
`DAILY_LIMIT_REACHED` (429 + alerta PT/EN/ES), prazos imunes a fuso (UTC/Tóquio/LA/Honolulu)
e troca rápida de abas com somas do rail a fechar (4/3/12/1).

## 5. Foco e próximos passos

- **Escopo trancado**: apenas Dashboard. Nenhuma tarefa de landing será iniciada.
- Consolidação restante sugerida (sem alterar UI sem aprovação):
  1. Revisão final do seed de staging (14 preventivos + 4 reativos) para demonstração.
  2. Repetir a checklist visual do drawer/filtros em PT/EN/ES numa sessão limpa.
  3. Preparar o pacote de evidências (capturas e relatórios) para a decisão de merge.
- Produção continua em `master` `3b53962`, intocada e isolada.
