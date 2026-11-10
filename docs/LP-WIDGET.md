# LP Widget — Fase 0/1

Widget de captação conversacional da landing page, implementado **fora** da LP
oficial. O objetivo desta fase é validar UI e fluxo em staging, sem publicar
nada na página de produção, sem tocar no `AuthForm`, no checkout Stripe, nos
preços ou no motor de voz.

## Feature flags

| Variável | Onde | Default | Efeito |
|---|---|---:|---|
| `NEXT_PUBLIC_LP_WIDGET` | frontend (build) | `false` | Liga o widget na LP. Nesta fase **não** está montado na LP oficial. |
| `LP_WIDGET_PREVIEW` | frontend (server) | `false` | Habilita `/{locale}/widget-preview` (noindex). |
| `LP_WIDGET_ENABLED` | backend | `false` | Habilita as rotas `/api/public/lp/*` e `/api/admin/lp/*`. Sem ela, tudo devolve 404. |
| `LP_WIDGET_SLA_HOURS` | backend | `4` | Prazo mostrado ao lead e gravado no fio. |
| `LP_WIDGET_REPLY_TO` | backend | `contato@magicleads.app` | `reply_to` dos e-mails transacionais. |
| `LP_WIDGET_PUBLIC_URL` | backend | vazio | Link opcional no e-mail de acknowledgment. |
| `LP_WIDGET_TZ` | backend | `America/New_York` | Fuso do horário de atendimento. |
| `LP_WIDGET_BUSINESS_START` | backend | `8` | Hora de abertura (0–23) no fuso acima. |
| `LP_WIDGET_BUSINESS_END` | backend | `18` | Hora de fecho (1–24) no fuso acima. |
| `LP_WIDGET_BUSINESS_DAYS` | backend | `0,1,2,3,4` | Dias úteis (0=segunda … 6=domingo). |

`NEXT_PUBLIC_LP_WIDGET=false` é o estado de produção. A prévia funciona apenas
com `LP_WIDGET_PREVIEW=true` (ou com a flag pública ligada num build de staging).

## O que existe nesta fase

### Frontend

- `components/landing/LpWidget/LpWidgetLauncher.tsx` — launcher flutuante,
  claro e de baixa intrusão. É o canal principal.
- `components/landing/LpWidget/LpWidgetPanel.tsx` — painel de conversa,
  branco, com chips, composer e entrega simulada/real. Fluxo de captação em
  **4 passos**: intenção → ofício + cidade → origem do lead → mensagem/contacto;
  depois abre a conversa (passo 5) com polling de 5 s, anexos e caixa de
  follow-up contínua (o lead responde na mesma thread sem reiniciar).
- `components/landing/LpWidget/i18n.ts` — copy EN/PT/ES, as 16 categorias
  canónicas (`TRADE_OPTIONS`) e as 4 origens (`WIDGET_SOURCES`), sempre
  traduzidas pelo idioma ativo.
- `components/landing/LpWidget/LpWidgetInline.tsx` — faixa inline opcional,
  leve (não é um segundo widget embutido).
- `components/landing/LpWidget/LpLanguagePicker.tsx` + `LpFlag.tsx` — seletor
  EN/PT/ES com bandeiras, busca rápida e EN por omissão.
- `components/landing/LpWidget/LpWidgetInboxPreview.tsx` — lado interno PT-BR
  usado **apenas** na pré-visualização.
- `lib/lp-widget.ts` — flag, tipos, cliente HTTP e eventos.
- `app/[locale]/widget-preview/page.tsx` — rota isolada, `noindex`, gated por
  `LP_WIDGET_PREVIEW`.
- `app/admin/lp-inbox/page.tsx` + `LpInboxClient.tsx` — inbox admin real,
  polling de 5 s, original + tradução PT-BR editável, rascunho PT/EN e envio.
  Inclui filtros por período (Hoje/Semana/Mês) e estado (Novo/Respondido/
  Arquivado), indicador de cobertura (cidade), origem do lead, histórico por
  e-mail, anexos e arquivar/reabrir. Tem um modo de demonstração local quando a
  API está desligada.

### Backend

- `services/lp_widget.py` — tabelas `lp_threads`, `lp_messages`, `lp_events`,
  `lp_attachments`; criação de fio, follow-up do lead, lista/detalhe admin,
  resposta da equipa e envio via Resend.
- Endpoints públicos:
  - `POST /api/public/lp/threads` (6/hora, honeypot, consentimento)
  - `GET /api/public/lp/threads/{token}` (120/min)
  - `POST /api/public/lp/threads/{token}/messages` (20/hora)
  - `POST /api/public/lp/threads/{token}/attachments` (30/hora, máx. 10 MB)
  - `GET /api/public/lp/threads/{token}/attachments/{id}`
- Endpoints admin (sessão real + `users.is_admin`):
  - `GET /api/admin/lp/threads?status=&period=&limit=`
  - `GET /api/admin/lp/threads/{id}` — inclui `history` (mesmo e-mail) e
    `attachments`.
  - `POST /api/admin/lp/threads/{id}/reply` — recebe `body_pt` (interno) e
    `body_en` (texto final no idioma do lead), grava ambos e envia por Resend.
  - `PATCH /api/admin/lp/threads/{id}/status` — `new` / `replied` /
    `archived` (arquivar/reabrir).
  - `POST /api/admin/lp/threads/{id}/attachments` (60/hora) e
    `GET /api/admin/lp/threads/{id}/attachments/{id}`.
  - `PATCH /api/admin/lp/threads/{id}/messages/{message_id}` — guarda a
    revisão humana da tradução PT-BR de uma mensagem inbound.

### Fora do âmbito desta fase

- Parsing de respostas de e-mail (Fase 2). O e-mail é entrega; a conversa
  instantânea é o widget.
- Anexos no e-mail inicial de acknowledgment (o acknowledgment é só texto). Os
  anexos enviados com uma resposta da equipa seguem no e-mail Resend e ficam
  inline na conversa.
- SMS/WhatsApp.
- Atendimento telefónico e agendamento de chamadas. A captação é 100% por
  mensagem/e-mail.
- SSE na inbox/widget. A entrega usa polling de 5 s; SSE fica como evolução.
- Montagem do widget na LP oficial. Só depois de aprovação explícita.

## Fluxo de captação (widget)

Antes do campo de mensagem livre, o lead qualifica-se em dois passos de zero
fricção:

1. **Ofício + cidade** — 16 categorias canónicas da plataforma
   (`Roof`, `Structure`, `Plumbing`, … em `lib/categories.ts`), apresentadas com
   o nome traduzido no idioma ativo (EN/PT/ES), mais a cidade.
2. **Origem do lead** — `Google / Search`, `Social Media`,
   `Referral / Word of Mouth`, `Automated Phone Call / Direct Outreach`.

O backend guarda `trade`, `trade_code`, `city` e `lead_source` na thread. A
origem aparece na inbox como selo `Origem: …`; o ofício e a cidade aparecem no
cartão e no detalhe.

## Inbox admin

- **Contraste**: os campos `RASCUNHO PT-BR` e `VERSÃO <idioma>` usam fundo
  branco (`#FFFFFF`), texto `#0F172A`, `color-scheme: light` — legíveis tanto no
  tema claro como no escuro do sistema.
- **Cobertura**: 🟢 ponto verde = cidade atendida (New York, Boston, Dallas,
  Chicago); 🔴 ponto vermelho = fora da cobertura ou sem cidade. O detalhe mostra
  `Coberto` / `Fora da cobertura`.
- **Histórico por e-mail**: threads anteriores do mesmo e-mail aparecem em
  `Histórico deste e-mail` (até 10) e o selo `Cliente recorrente`; clicar abre a
  thread antiga.
- **Filtros**: período `Hoje` / `Semana` (7 d) / `Mês` (30 d) e estado
  `Novo` / `Respondido` / `Arquivado`; o polling mantém os filtros ativos.
- **Arquivar/reabrir**: `PATCH .../status`, sem apagar histórico.
- **Anexos**: upload/download nos dois sentidos (lead e equipa), com o ficheiro
  inline na bolha da mensagem. Imagens abrem em lightbox; o download é explícito.
  O compositor aceita `Ctrl+V` de prints. PDF, Word, Excel, TXT, CSV e imagens
  até 10 MB; os anexos da resposta seguem no e-mail Resend (máx. 20 MB). Ficam
  em `LP_UPLOAD_DIR` (default `$DATA_DIR/lp_uploads`), um diretório por thread.

### Alertas de novos leads

- A inbox mantém uma consulta própria de threads `status=new` (polling de 5 s),
  independente dos filtros ativos.
- Quando surge um ID novo, o operador recebe:
  - **som** de dois tons via Web Audio (respeita o bloqueio de autoplay; o
    contexto é desbloqueado no primeiro clique/tecla);
  - **pulso visual** no cartão (ponto âmbar animado + fundo âmbar);
  - **título da aba** `(N) Novo Lead - LP Inbox`.
- Abrir o cartão limpa o alerta daquele lead; responder/arquivar também o
  remove no ciclo seguinte.
- O botão de campainha no cabeçalho liga/desliga o som e guarda a preferência
  em `localStorage`.

### Acesso no Control Tower

O menu superior do admin (`components/admin/AdminNav.tsx`) inclui
**LP Inbox** entre `Overview` e `Data Plane`, com o ícone de inbox. A rota
continua protegida por sessão real + `users.is_admin`.

## Horário de atendimento (online / fora de horário)

- **Modo automático** (default): segunda a sexta, 08:00–18:00 em
  `America/New_York` (`LP_WIDGET_TZ`/`LP_WIDGET_BUSINESS_*`). Fora dessa janela
  o estado efetivo é `offline`.
- **Override manual** na inbox (`GET/PUT /api/admin/lp/availability`):
  `auto`, `online` ou `offline`. O override é persistido em `lp_settings`
  (`availability_mode`) e não altera o cálculo automático.
- **Widget**: nunca bloqueia a mensagem. O lead vê o estado no topo; ao enviar
  fora de horário, aparece um aviso no idioma dele a dizer que a equipa recebeu
  a mensagem e responde nas primeiras horas do próximo dia útil.
- **E-mail**: o acknowledgment inclui a mesma frase no idioma do lead, com o
  próximo dia/hora úteis calculados. O assunto e o corpo continuam localizados.
- **API pública**: `GET /api/public/lp/availability` devolve apenas estado e
  próximo horário útil (o modo manual e o autor ficam internos).



- O acknowledgment inicial e o assunto são gerados no idioma detetado do lead
  (`lead_lang`: EN/PT/ES), não no locale do browser.
- Ao aprovar a resposta, `POST .../reply` grava o texto final no idioma do lead
  e envia-o **nesse exato instante** por Resend, com assunto localizado. O
  `body_pt` fica apenas como nota interna.
- O widget mostra a resposta no idioma do lead no polling seguinte (≤5 s).

## Pré-visualizar localmente

```bash
cd frontend
LP_WIDGET_PREVIEW=true NEXT_PUBLIC_LP_WIDGET=true npm run dev
# http://localhost:3000/en/widget-preview
```

Sem backend, a prévia usa o modo `demo` (determinístico). Para testar o modo
`live`, suba o backend com `LP_WIDGET_ENABLED=true` e aponte
`NEXT_PUBLIC_API_URL` para ele.

## Staging (Vercel preview)

```bash
vercel deploy --yes --project frontend \
  -b NEXT_PUBLIC_LP_WIDGET=true \
  -b LP_WIDGET_PREVIEW=true \
  -b API_PROXY_TARGET=https://<staging-backend> \
  -e LP_WIDGET_PREVIEW=true
```

Sem `API_PROXY_TARGET`, o rewrite `/api` continua a apontar para produção. Para
testar a inbox admin com dados reais, o backend de staging tem de ter
`LP_WIDGET_ENABLED=true` e o preview tem de ser construído com o alvo correto.
Enquanto isso não existir, `/admin/lp-inbox` mostra `API OFF` e o modo de
demonstração local.

Para o E2E completo (lead → inbox → tradução → aprovação → Resend → widget),
construir o preview com `NEXT_PUBLIC_LP_WIDGET_LIVE=true` e
`NEXT_PUBLIC_API_PROXY=true`, além de `API_PROXY_TARGET`. O login e o widget
passam a usar `/api` relativo, sem CORS. O backend de staging deve ter
`VOICE_FREEZE=1`, `SCRAPER_SELF_SCHEDULED=false`,
`ENRICH_SCHEDULER_ENABLED=false` e `LP_WIDGET_ENABLED=true`.

O deploy é um **preview**, não produção. A rota é `noindex` e não está ligada a
partir da LP.

## Testes

```bash
.venv/Scripts/python.exe -m pytest tests/test_lp_widget.py tests/test_lp_ai.py -v
.venv/Scripts/python.exe -m ruff check backend tests --select=E,F,W,I --ignore=E501
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

## Pipeline de IA (Fase 2)

- Na criação da thread (e em cada follow-up), um background task chama
  `enrich_thread`: deteta o idioma pelo texto, traduz para PT-BR, guarda
  `body_pt`, escolhe uma sugestão da biblioteca aprovada e traduz esse rascunho
  para o idioma do lead (`draft_pt` / `draft_out` / `draft_out_lang`).
- A inbox admin pré-preenche a tradução e os dois campos. Ao editar o PT-BR, o
  botão **Traduzir PT →** (e o blur do campo) chama `POST .../translate-draft` e
  atualiza a versão final no idioma do lead (`draft_out`/`draft_out_lang`), que
  pode ser EN, PT, ES, FR, DE ou IT.
- Providers: `GEMINI_API_KEY` → Gemini; `OPENAI_API_KEY` → OpenAI;
  `LP_AI_PROVIDER=mymemory`/`LP_AI_FREE_FALLBACK=true` → MyMemory (sem chave,
  usado no staging). O staging atual usa MyMemory; produção deve usar uma chave
  LLM dedicada.
- PII (email/telefone) é redigida antes de sair para o provider e reinserida
  depois. O texto do lead é tratado como dado, nunca como instrução.
- Endpoints novos: `POST /api/admin/lp/threads/{id}/ai-enrich` e
  `POST /api/admin/lp/threads/{id}/translate-draft`.

## Staging E2E

Backend isolado: `https://magic-leads-staging-staging.up.railway.app`
(serviço `magic-leads-staging`, volume próprio, `VOICE_FREEZE=1`,
`SCRAPER_SELF_SCHEDULED=false`, `ENRICH_SCHEDULER_ENABLED=false`).

Verificado em 2026-11-09:

1. Lead submete no widget live (ofício + cidade + origem + mensagem) → thread
   criada em staging com `trade_code` e `lead_source`.
2. Inbox admin atualiza em ≤5 s; a IA pré-preenche tradução PT-BR e rascunhos;
   cobertura e origem aparecem no cartão.
3. A equipa revê/edita o PT-BR; a versão final é gerada no idioma do lead.
4. Equipa aprova → `POST .../reply` com `email_sent=true` e assunto no idioma
   do lead.
5. Widget live atualiza em ≤5 s com a resposta no idioma do lead e os selos
   Widget + Resend.
6. Anexos (lead → inbox e equipa → widget) aparecem nos dois lados; filtros de
   período/estado e arquivar/reabrir funcionam sem perder histórico.

Validado em 2026-11-09 com EN, PT e ES (incluindo edição PT → ES e envio),
8 threads em staging, incluindo uma fora da cobertura (Miami → 🔴).

## Fase 2 — plano de montagem na LP oficial

**Estado atual:** `LpWidgetMount` já está montado no `LandingShell`. A branch de
integração e o build de pré-produção usam obrigatoriamente
`NEXT_PUBLIC_LP_WIDGET=false`: o componente devolve `null`, o chunk do
launcher/panel não é descarregado e não há pedidos a `/api/public/lp/*`.
A ativação continua dependente de autorização explícita.

Objetivo: deixar o widget **montado mas invisível** na LP oficial com
`NEXT_PUBLIC_LP_WIDGET=false`, para que a ativação futura seja só uma mudança de
flag (com aprovação explícita), sem novo desenvolvimento.

### 2.1 Pré-condições

- Sign-off do staging atual (widget, inbox, horário, alertas, anexos, e-mail).
- Chave LLM de produção (`GEMINI_API_KEY` ou `OPENAI_API_KEY`) configurada.
- `LP_WIDGET_ENABLED=true` no serviço de produção **apenas** no dia da ativação.
- `ALLOWED_ORIGINS` com `https://magicleads.app` e o domínio base Vercel exato
  (sem wildcards `project-*`/`-git-*`).

### 2.2 Montagem com a flag desligada

1. Criar `components/landing/LpWidget/LpWidgetMount.tsx`:
   - lê `LP_WIDGET_ENABLED` (`NEXT_PUBLIC_LP_WIDGET`);
   - devolve `null` quando `false`;
   - só importa o launcher/panel quando ligado (evita custo no bundle).
2. Incluir `<LpWidgetMount />` no fim do `LandingShell` (ou da página de
   marketing), sem alterar `AuthForm`, checkout Stripe, preços ou `voice_*`.
3. Build de produção com `NEXT_PUBLIC_LP_WIDGET=false`.
4. Validar no artefacto de produção:
   - nenhum launcher visível;
   - nenhum pedido a `/api/public/lp/*`;
   - nenhuma alteração no HTML/SSR da LP;
   - Lighthouse/acessibilidade sem regressões.

### 2.3 Ativação controlada (depois da autorização)

1. Ativar primeiro num preview/canary com a flag `true` e o backend de
   produção com `LP_WIDGET_ENABLED=true`.
2. Smoke test: lead EN/PT/ES, inbox, tradução, aprovação, Resend, polling,
   anexos, horário online/offline e alertas.
3. Só então rebuild de produção com `NEXT_PUBLIC_LP_WIDGET=true`.
4. Monitorizar 24–48 h: erros 5xx, taxa de entrega Resend, SLA, volume de
   threads e custo do provider LLM.

### 2.4 Rollback

- Rebuild com `NEXT_PUBLIC_LP_WIDGET=false` remove o launcher.
- `LP_WIDGET_ENABLED=false` faz a API devolver 404, mantendo os dados `lp_*`
  intactos para reativação.
- Nenhuma migração destrutiva e nenhuma alteração a tabelas existentes.

### 2.5 Critérios de aceitação da Fase 2

- Widget visível apenas com a flag `true`.
- LP oficial, `AuthForm`, Stripe, preços e motor de voz sem alterações.
- Inbox acessível no menu do Control Tower.
- E-mail final no idioma do lead, com acknowledgment offline correto.
- Nenhum merge/deploy de produção antes de autorização explícita.

## Isolamento

- Nenhuma alteração a `app/[locale]/(marketing)/page.tsx`, `LandingShell.tsx`,
  `AuthForm.tsx`, checkout Stripe, preços ou `voice_*`.
- Nenhuma tabela existente é alterada. As tabelas `lp_*` são novas.
- `LP_WIDGET_ENABLED=false` e `NEXT_PUBLIC_LP_WIDGET=false` por omissão.
