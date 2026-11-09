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

`NEXT_PUBLIC_LP_WIDGET=false` é o estado de produção. A prévia funciona apenas
com `LP_WIDGET_PREVIEW=true` (ou com a flag pública ligada num build de staging).

## O que existe nesta fase

### Frontend

- `components/landing/LpWidget/LpWidgetLauncher.tsx` — launcher flutuante,
  claro e de baixa intrusão. É o canal principal.
- `components/landing/LpWidget/LpWidgetPanel.tsx` — painel de conversa,
  branco, com chips, composer, fluxo adaptativo (2 passos; 3 para cidade+ofício)
  e entrega simulada/real.
- `components/landing/LpWidget/LpWidgetInline.tsx` — faixa inline opcional,
  leve (não é um segundo widget embutido).
- `components/landing/LpWidget/LpLanguagePicker.tsx` + `LpFlag.tsx` — seletor
  EN/PT/ES com bandeiras, busca rápida e EN por omissão.
- `components/landing/LpWidget/LpWidgetInboxPreview.tsx` — lado interno PT-BR
  usado **apenas** na pré-visualização.
- `lib/lp-widget.ts` — flag, tipos, cliente HTTP e eventos.
- `app/[locale]/widget-preview/page.tsx` — rota isolada, `noindex`, gated por
  `LP_WIDGET_PREVIEW`.

### Backend

- `services/lp_widget.py` — tabelas `lp_threads`, `lp_messages`, `lp_events`;
  criação de fio, follow-up do lead, lista/detalhe admin, resposta da equipa e
  envio via Resend.
- Endpoints públicos:
  - `POST /api/public/lp/threads` (6/hora, honeypot, consentimento)
  - `GET /api/public/lp/threads/{token}` (120/min)
  - `POST /api/public/lp/threads/{token}/messages` (20/hora)
- Endpoints admin (sessão real + `users.is_admin`):
  - `GET /api/admin/lp/threads`
  - `GET /api/admin/lp/threads/{id}`
  - `POST /api/admin/lp/threads/{id}/reply` — recebe `body_pt` (interno) e
    `body_en` (enviado), grava ambos e envia o EN por Resend.

### Fora do âmbito desta fase

- Tradução automática EN ↔ PT-BR por LLM (Fase 2). Na Fase 1 a equipa revê e
  escreve as duas versões manualmente; a inbox já está preparada para o campo
  PT-BR e para o envio final em inglês.
- Parsing de respostas de e-mail (Fase 2). O e-mail é entrega; a conversa
  instantânea é o widget.
- SMS/WhatsApp.
- Atendimento telefónico e agendamento de chamadas. A captação é 100% por
  mensagem/e-mail.
- UI visual da inbox admin (Fase 1b). Os endpoints admin já existem; a página
  com polling de 5 s é o próximo passo.
- Montagem do widget na LP oficial. Só depois de aprovação explícita.

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
vercel deploy --cwd frontend \
  -b NEXT_PUBLIC_LP_WIDGET=true \
  -b LP_WIDGET_PREVIEW=true \
  -e LP_WIDGET_PREVIEW=true
```

O deploy é um **preview**, não produção. A rota é `noindex` e não está ligada a
partir da LP.

## Testes

```bash
.venv/Scripts/python.exe -m pytest tests/test_lp_widget.py -v
cd frontend && npx tsc --noEmit && npm run build
```

## Isolamento

- Nenhuma alteração a `app/[locale]/(marketing)/page.tsx`, `LandingShell.tsx`,
  `AuthForm.tsx`, checkout Stripe, preços ou `voice_*`.
- Nenhuma tabela existente é alterada. As tabelas `lp_*` são novas.
- `LP_WIDGET_ENABLED=false` e `NEXT_PUBLIC_LP_WIDGET=false` por omissão.
