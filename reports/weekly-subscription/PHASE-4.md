# Fase 4 — UI do dashboard (staging)

**Branch:** `feat/weekly-subscription-quotas`  
**Commits:** `34393d0`, `e52dde6`, `da5f18a`  
**Âmbito:** frontend de staging + endpoints mock de staging.  
**Produção:** intocada; sem merge.

## Staging

- Backend: `https://magic-leads-staging-staging.up.railway.app` (health `healthy`).
- Frontend: `https://magic-leads-staging-fabio-dev2.vercel.app` (alias do preview `hn7tqph28`).
- Flags: `BILLING_MOCK=1`, `ADDONS_MOCK=1`, `SEARCHBUG_MOCK=1`, `BILLING_MODEL=weekly_quota`, `BILLING_TIMEZONE=America/New_York`, `DAILY_LETTER_LIMIT=10`.

## O que mudou

### Dashboard

- `SubscriptionFeed` substitui o painel de créditos e o feed legacy:
  - cartões com morada mascarada, dono mascarado e estado do telefone;
  - botão **Address / Letter** (10/dia, independente do telefone);
  - botão **Reveal Phone** com contador base e add-on separado;
  - modal de morada/proprietário e modal de telefone revelado;
  - “load more” preservado.
- Header: chip `Plano · usados/limite [+add-on]`.
- Sidebar: cartão de plano com telefones e cartas/visitas do dia; botão **Gerir/Assinar**.
- Removidos: `CreditsPanel`, `CreditWalletModal`, carteira em cêntimos, botões de $1,50/$3,00, pacotes de crédito e o lock screen legacy.
- `PlanModal`: 7 planos, preço semanal, telefones/dia, total semanal, letras/dia, plano atual destacado, portal Stripe quando aplicável.
- `AddonModal`: pacotes de 24h (+2 a +20), estado base/add-on e validade.
- Deep links: `?plans=1` e `?addon=success`; `/credits` redireciona para `?plans=1`.

### Landing e copy

- `PricingSection` e a secção de preço da landing mostram os 7 planos:
  - Starter $25.90/2, Essential $50.20/4, Growth $74.34/6, Pro $100.90/8,
    Business $126/10, Scale $178.50/15, Agency $231/20.
- Todos os planos: 10 cartas/visitas por dia.
- Add-ons: +2 $2.50, +4 $4.80, +6 $7.20, +8 $9.60, +10 $12, +15 $18, +20 $24.
- Removidas as referências a `$120` na landing, metadata, widget, termos e i18n.
- `HowItWorks` passa a usar o Starter como âncora de custo.

### Backend de staging

- `GET /api/billing/plans` passa a devolver `addons`.
- `POST /api/billing/mock-checkout` (apenas `BILLING_MOCK=1`) ativa plano para QA.
- `POST /api/billing/addons/mock-pay` (apenas `ADDONS_MOCK=1`) injeta add-on 24h.
- `/api/billing/mock-activate` continua **410 Gone**.

## QA de staging

- Utilizador: `qa-buyer+staging@magicleads.app`.
- Plano ativado via mock-checkout: **Pro (`weekly_8`)**, 8 telefones/dia, 10 cartas/dia.
- Add-on injetado: **+4** (24h).
- Uso observado: `1/8` telefones, `0/10` cartas, `4` add-on.
- Reset diário: `2026-11-18T05:00:00+00:00` (meia-noite de Nova Iorque).

## Verificação

- Backend: `1727 passed, 1 skipped` (`pytest tests/ -q`).
- Ruff: `ruff check backend tests --select=E,F,W,I --ignore=E501` limpo.
- Frontend: `npx tsc --noEmit` limpo; `vitest` 111 passed.
- Build: `npm run build` verde (Next.js 16.4.3).
- ESLint: 0 erros (121 avisos pré-existentes de `react-hooks`).

## Limitações conhecidas

- Sem `sk_test_`: Stripe continua em mock e os 7 `stripe_price_id` estão vazios.
- O add-on modal foi aberto por deep link para auditoria; em uso normal abre quando a cota base chega a zero.
- O `investor-room` admin ainda usa `$120` como input do modelo interno; não é UI de cliente.
- Next.js 16.4.3 tem aviso de segurança; o worktree `garimpador-leads-security-next` já tem 16.4.6, mas não foi integrado nesta branch.

## Paragem obrigatória

**Fase 5:** auditoria visual do Fábio no alias de staging.  
**Não há merge para produção, nem deploy de produção, sem aprovação escrita.**

## Fase 4.1 — Face-lift e fluxo de conversão

**Commits:** `2888642`, `ab7db49`

- Header redesenhado numa única linha: logo, navegação central, seletor de idioma,
  link **Entrar** separado e CTA de conversão.
- CTA do header passou a fazer scroll suave até `#preco`; já não abre login.
- Os 7 cartões de plano são botões interativos, com hover/glow e seleção
  destacada a verde. Pro marcado como “Mais popular”.
- O plano escolhido é fixo no topo da modal de cadastro
  (`Plano selecionado · nome · preço · telefones/dia`).
- Registo e login com plano escolhido enviam `plan_code` para
  `/api/billing/checkout`. Em staging com `BILLING_MOCK=1`, o plano é ativado
  e o utilizador segue para `/dashboard?billing=success`.
- Copy nova:
  - header PT/EN/ES: `Começar por $25.90` / `Start for $25.90` / `Empezar por $25.90`;
  - CTA de planos: `DESBLOQUEAR TELEFONES E FALAR COM O DONO` /
    `UNLOCK PHONE NUMBERS & CALL HOMEOWNERS NOW` /
    `DESBLOQUEAR TELÉFONOS Y LLAMAR AL DUEÑO`.
- Corrigidos os textos com `?` em PT (`Come?ar agora`).
- Verificado em staging: seleção do plano Growth, login, ativação mock e
  redirecionamento para o dashboard com `Growth · 1/6 +4`.

## Fase 4.2 — Ajustes de lançamento

**Commits:** `c3a5b77`, `54e9092`

- Header: ações com gap real (`gap-2 sm:gap-3`), divisor entre **Entrar** e CTA,
  bandeiras compactas e navegação completa só em `2xl` — sem sobreposição em
  larguras intermédias.
- Título de preços: **“Sete Planos, Destrave, ligue e fature!”**.
- CTA principal: **“Desbloquear e falar com o contratante agora”**.
- Modal: removida a frase “O checkout abre logo a seguir”.
- Cartões: mais padding (`p-6`), `gap-4`, sombras subtis e seleção com glow
  verde mais contido; conteúdo alinhado ao fundo do cartão.
- Verificado no staging em PT/EN/ES: título, CTA, seleção de plano, modal com
  plano fixo e ausência da frase de checkout.

### Troca de idioma na landing

- As bandeiras PT/EN/ES trocam o dicionário **em memória**, sem `router.push`.
  O URL mantém-se e o utilizador não passa pelo gate/SSO do staging nem pelo
  login.
- Verificado no staging: `/en` → PT → ES sem mudar de página e sem pedir login;
  título e CTA atualizam imediatamente.

## Fase 4.3 — Polish e refinamento SaaS

**Commits:** `77a3817`, `2cf889b`

- Header reduzido a **4 links** (Trades, Como funciona, Preço, FAQ), com
  `h-[72px]`, `gap-6/xl:gap-10`, navegação sem “pílula” e sublinhado animado.
- Ações com `gap` maior e divider entre **Entrar** e o CTA; bandeiras compactas.
- Título EN exato: **“Seven Plans, Unlock, Call and Close!”**.
- Cartões reconstruídos com **borda em gradiente** (verde → violeta), fundo
  radial iluminado, `p-7`, `gap-5`, hover com elevação e check verde imediato.
- Pro: selo **Most Popular** abaixo do nome, sem corte; gradiente médio mesmo
  quando não selecionado e gradiente brilhante quando selecionado.
- Selo e check medidos no staging: sem sobreposição e totalmente dentro do cartão.
- Modal mantém o plano escolhido no topo e já não tem a frase de checkout.

## Fase 4.4 — Pricing minimalista (sem gradiente)

**Commit:** `c904e3c`, `340a6d6`

- Removido o preenchimento/borda em gradiente e qualquer efeito “neon”.
- Nova hierarquia: **cartão Pro em destaque** + **seis cartões compactos**
  (grelha 3×2) em vez de sete blocos iguais.
- Superfícies profundas: `#0a0f16` / `#080d14`; bordas finas `slate-800`.
- Seleção discreta: borda `emerald-400/40-45`, fundo levemente esverdeado
  (`#0b1210`) e check em `emerald-400/10` — sem manchas de cor.
- Tipografia mais leve: preços em `font-semibold`, labels em `slate-500`.
- Hover com elevação/realce de borda apenas nos cartões compactos.
- Transição limitada a `transform/box-shadow`; o estado de seleção é imediato.
- Verificado no staging: Pro selecionado por defeito; Growth selecionável;
  nenhum gradiente nos cartões.

## Fase 5 — Restauração do fluxo original de oportunidades

**Commits:** `0aa5194`, `5b38255`

Sem alterar a mecânica do produto, a dashboard voltou a usar o fluxo original:

- `OpportunityCard` e o feed de produção restaurados (reserva 1h, consentimento,
  enriquecimento completo, histórico, telefone e guia de ciclo de vida).
- Login com plano ativo entra direto em `/dashboard`; a modal de planos deixou
  de abrir no regresso do Stripe ou depois do login.
- Apenas o consumo mudou para as novas cotas:
  - **10 cartas/visitas/dia** via `user_daily_usage`;
  - **telefone do plano** (base → add-on 24h) via `subscription_reveals`;
  - telefone em cache também consome quota;
  - telefone não autorizado pela quota é mascarado na resposta;
  - falha/no resultado devolve a unidade ao bucket de origem.
- Add-ons 24h só aparecem quando a cota de telefones chega a zero; sem plano
  ativo, abre a seleção de planos.
- O componente `SubscriptionFeed` foi removido.

**Verificado no staging:** login sem modal; feed original com “Reserve 1 Hour”;
consentimento; reserva de 1h ativa; modal completo com proprietário, telefone,
morada de correspondência, histórico e fases.

### Correções da revisão visual

- Modais de detalhe, consentimento e guia passaram para `z-[900/1000]`; o mapa
  Leaflet ficou num stacking context `relative z-0`. O mapa deixa de cobrir as
  janelas.
- O texto do consentimento passou a usar a cota nova (`letter_used/letter_limit`)
  em vez do contador legacy — já não mostra `0/10` quando a sidebar mostra `1/10`.
- O botão de reserva deixou de depender do objeto `subscription` em cache;
  só exige consentimento, ausência de operação em curso e cota de cartas.
- Chicago foi adicionado ao `CITY_META`, eliminando o estado
  “Map unavailable for this city” na pré-inspeção.
- Confirmado que o login de uma conta com plano ativo entra em `/dashboard`
  sem modal de planos (`billing=success` não abre a modal).

### Auditoria prática (Playwright, staging)

- Login com Pro: `/en/dashboard`, **sem modal de planos e sem welcome popup**.
- Sidebar/header: `Pro · 3/8 +4`, `1/10 cartas/visitas`.
- Reserva: 50 botões disponíveis; botão bloqueado apenas antes do checkbox
  (comportamento original), **habilitado depois do consentimento**.
- Consentimento: `I agree to verify this lead's data (1/10 today).`
- Modal: `z-index: 1000`, acima do Leaflet.
- Reserva confirmada: guia de 1 hora abre com o pipeline completo.
- Pré-inspeção: mapa renderiza (`.opp-map` presente), sem
  “Map unavailable”; Nova Iorque usa o snapshot real quando o feed preventivo
  está vazio. Chicago mostra o mapa base, mas o staging não tem linhas
  preventivas de Chicago (0 KPIs), pelo que não há pins nem dados a somar.






