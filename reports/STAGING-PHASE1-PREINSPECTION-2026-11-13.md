# Fase 1 — Pré-inspeção fiel ao protótipo (staging)

Data: 2026-11-13
Branch: `staging/opportunity-foundation`
Commit: `fe6b5dd`
Produção (`master` em `3b53962`): intocada.

## O que foi entregue

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
- **Modelo de dados aditivo** em `opportunity_workflow`:
  - `description`, `owner_name`, `owner_type`, `inspection_status`, `received_at`,
    `tags_json`, `timeline_json`, `source_payload`.
  - Migração idempotente em `_migrate_schema` (não toca em `leads`).
- **i18n**: 1.326 chaves em EN/PT/ES, paridade garantida pelo teste.
  - 14 chaves novas do drawer/timeline.
  - Corrigidos 31 valores com acentos corrompidos (`?` no lugar de `ã/é/ç/…`) em PT/ES.
- **Seed**: 6 preventivos ricos + 4 leads reativos (`hpd_violation`, `dob_violation`,
  `311`, `permit`), todos com proprietário e descrição.

## Validação

- Fluxo real: card → drawer → modal de consentimento → checkbox → reserva `59:58` →
  guia 1h/48h/48h. Confirmado em PT.
- PT/EN/ES: navegação, filtros, severidades, timeline e drawer localizados.
- `npx tsc --noEmit`: limpo.
- `npx eslint . --quiet`: limpo.
- `npm test`: 117 pass (inclui paridade i18n).
- `pytest tests/ -q`: 1676 pass, 1 skip.
- Capturas: `C:\Users\Fabio\AppData\Local\Temp\opencode\staging-opportunity\shots\`
  - `pt-prevention-desktop.png`, `pt-prevention-drawer.png`
  - `en-prevention-desktop.png`, `es-prevention-desktop.png`
  - `pt-prevention-mobile.png`, `pt-prevention-drawer-mobile.png`
  - `pt-opportunities-baseline.png` (feed reativo antigo — base para a Fase 2)

## Como validar

- Frontend: `http://localhost:3000/pt/dashboard` (também `/en` e `/es`).
- Login: `staging@magicleads.app` / `Staging123!`.
- Separador `Pré-inspeção` na barra lateral.
- Base de staging: `C:\Users\Fabio\AppData\Local\Temp\opencode\staging-opportunity\leads.db`.
- Backend: `http://127.0.0.1:8010` com schedulers desligados.

## Notas

- As descrições dos sinais estão em PT porque o protótipo aprovado é PT-BR e os dados são
  conteúdo, não copy de UI. Toda a chrome (labels, botões, estados) está localizada.
- O separador `Oportunidades` mantém o feed reativo atual; é o alvo da Fase 2.
- `counts.reactive` em `/api/opportunities` continua 0: os leads reativos vivem em `leads`,
  não em `opportunity_workflow`. A Fase 2 decide se unifica a leitura.

## Próximo passo

Fase 2: aplicar o padrão visual (grid, card rico, drawer, timeline) ao feed
`Oportunidades`, reutilizando `PreventiveCard`/`OpportunityDrawer` como base e mantendo o
ciclo de reserva/reveal existente.
