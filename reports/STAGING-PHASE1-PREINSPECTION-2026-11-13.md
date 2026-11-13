# Fase 1 — Pré-inspeção fiel ao protótipo (staging)

Data: 2026-11-13
Branch: `staging/opportunity-foundation`
Commits: `fe6b5dd` (base) · `dac1a08` (relatório) · `0221535` (KPI + painel lateral)
Produção (`master` em `3b53962`): intocada.

## O que foi entregue

### Feed e detalhe
- **Grid de 2 colunas** em `PreventiveFeed` (1 coluna abaixo de `md`, com filtros empilhados).
- **`PreventiveCard`** com:
  - badge `Pré-inspeção` + severidade com cor;
  - categoria localizada, morada, cidade e ZIP;
  - descrição curta do sinal (2 linhas);
  - mini-timeline `Chamado aberto → Vistoria → Multa emitida`;
  - rodapé com prazo, proprietário e `Ver detalhes`.
- **`OpportunityDrawer`** lateral (tecla `Esc` fecha) com:
  - cabeçalho e severidade;
  - aviso `Ainda sem multa` + explicação de risco;
  - timeline vertical com estados done/current/future;
  - grelha de factos: imóvel, proprietário, vistoria, origem, recebido, estado;
  - descrição do sinal + tags;
  - cartão do proprietário com telefone mascarado e CTA `Revelar dados do proprietário`.

### Paridade visual (2.ª iteração)
- **Painel lateral direito** (`FeedRail`) com os três blocos do protótipo:
  - `Prazos críticos` — lista dos 5 prazos mais próximos, com dias em falta (vermelho ≤ 2,
    âmbar ≤ 7), morada, cidade e atalho para o detalhe;
  - `Gravidade da amostra` — barra empilhada + legenda Crítica/Alta/Média/Rotina;
  - `ZIPs mais quentes` — top 5 ZIPs com barra proporcional e contagem.
- Rail aplicado **nos dois separadores**: pré-inspeção (dados de
  `opportunity_workflow.insights`) e oportunidades (derivado do feed reativo carregado).
- **KPI do topo** (`KpiPulse`) reformulado:
  - sparkline de 10 dias em cada cartão (série real de `daily_series` / `insights`);
  - métrica secundária detalhada;
  - 4.º cartão escuro para “Multas em risco” (valor em `$k`);
  - no separador de pré-inspeção os cartões passam a ser os do protótipo:
    `Oportunidades ativas`, `Preventivos`, `Prazos ≤ 7 dias`, `Multas em risco`.

### Dados e API
- **Modelo aditivo** em `opportunity_workflow`:
  - `description`, `owner_name`, `owner_type`, `inspection_status`, `received_at`,
    `tags_json`, `timeline_json`, `source_payload`;
  - migração idempotente em `_migrate_schema` (não toca em `leads`).
- **`GET /api/opportunities/insights?kind=preventive`** devolve:
  - `totals` (count, aguardando vistoria, prazos ≤ 7d/≤ 3d, valor em risco);
  - `by_severity`, `by_zip`, `deadlines`, `series` (10 dias) e `deadline_series`.
- `GET /api/leads/dashboard-summary` passa a expor `daily_series` (10 dias) para o sparkline.
- `GET /api/opportunities` inclui `insights` na resposta (o feed não faz pedido extra).
- **i18n**: 1.346 chaves em EN/PT/ES, paridade garantida pelo teste.
  - 20 chaves novas do painel lateral e dos KPI.
  - Corrigidos 31 valores com acentos corrompidos (`?` no lugar de `ã/é/ç/…`) em PT/ES.
- **Seed**: 12 preventivos ricos (severidade e ZIPs variados, prazos e valores) + 4 leads
  reativos (`hpd_violation`, `dob_violation`, `311`, `permit`).

## Validação

- Fluxo real: card → drawer → modal de consentimento → checkbox → reserva `59:58` →
  guia 1h/48h/48h. Confirmado em PT.
- PT/EN/ES: KPI, filtros, severidades, timeline, drawer e painel lateral localizados.
- Sem erros de consola no browser; `insights` pedido uma vez por carregamento (~80 ms).
- `npx tsc --noEmit`: limpo.
- `npx eslint . --quiet`: limpo.
- `npm test`: 117 pass (inclui paridade i18n).
- `pytest tests/ -q`: 1676 pass, 1 skip.
- Capturas: `C:\Users\Fabio\AppData\Local\Temp\opencode\staging-opportunity\shots\`
  - `pt-prevention-desktop.png`, `pt-prevention-drawer.png`, `pt-prevention-bottom.png`
  - `rail-zoom.png`, `pt-opportunities-rail.png`
  - `en-prevention-desktop.png`, `es-prevention-desktop.png`
  - `pt-prevention-mobile.png`, `pt-prevention-drawer-mobile.png`

## Como validar

- Frontend: `http://localhost:3000/pt/dashboard` (também `/en` e `/es`).
- Login: `staging@magicleads.app` / `Staging123!`.
- Separador `Pré-inspeção` na barra lateral.
- Base de staging: `C:\Users\Fabio\AppData\Local\Temp\opencode\staging-opportunity\leads.db`.
- Backend: `http://127.0.0.1:8010` com schedulers desligados.

## Notas

- As descrições dos sinais estão em PT porque o protótipo aprovado é PT-BR e os dados são
  conteúdo, não copy de UI. Toda a chrome (labels, botões, estados) está localizada.
- O cartão do feed `Oportunidades` mantém o visual atual; só o rail e os KPI já seguem o
  protótipo. O cartão novo entra na Fase 2.
- `counts.reactive` em `/api/opportunities` continua 0: os leads reativos vivem em `leads`,
  não em `opportunity_workflow`. A Fase 2 decide se unifica a leitura.
- Tailwind 3 não aplica modificadores de opacidade a cores `var(--sd-*)`; nos componentes
  novos usa-se cor sólida ou `color-mix` inline.

## Próximo passo

Fase 2: aplicar o padrão visual (card rico, drawer, timeline) ao feed `Oportunidades`,
reutilizando `PreventiveCard`/`OpportunityDrawer` como base e mantendo o ciclo de
reserva/reveal existente.
