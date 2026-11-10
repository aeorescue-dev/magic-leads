# LP Widget — auditoria de idioma e E2E multilíngue

Data: 2026-11-10 · Ambiente: **staging apenas** · Build: `NEXT_PUBLIC_LP_WIDGET=false`

## Diagnóstico (causa raiz)

1. **O widget não enviava o idioma escolhido.**
   - O picker PT/EN/ES alterava a UI, mas o `createLpThread` enviava
     `locale: document.documentElement.lang` (idioma da LP), não o `lang`
     selecionado no widget.
   - Um lead que escolhia PT numa LP EN enviava `locale=en`.

2. **O backend ignorava o `locale` na criação.**
   - `create_thread` calculava `lead_lang = detect_language(message)`.
   - Uma pergunta PT como “O que recebo exatamente por $120 por semana?”
     era classificada como ES por causa da palavra partilhada “semana”.
   - A partir daí, o acknowledgment, o assunto da resposta, o alvo da
     tradução e o rascunho da IA seguiam o idioma errado.

3. **O idioma do lead podia oscilar.**
   - `enrich_thread` usava a deteção da última mensagem para reescrever
     `lead_lang`; um follow-up ambíguo podia trocar PT → ES/EN.

## Correção aplicada

- **Frontend**
  - `createLpThread` envia `locale: lang` (idioma selecionado no widget).
  - O widget inicializa o idioma a partir do `document.documentElement.lang`
    (PT/EN/ES) quando disponível.
  - Ao retomar uma conversa (`sessionStorage`), o idioma do thread é aplicado
    à UI (`lead_lang` na resposta pública).

- **Backend**
  - `create_thread` passou a tratar o locale selecionado como autoridade:
    - `pt`, `es`, `fr`, `de`, `it` → `lead_lang` = locale;
    - `en` (default) → só é substituído se a mensagem for claramente PT/ES/etc.;
    - sem locale → deteção.
  - A mensagem guarda `lang = detected_lang` (idioma real do texto), separado
    de `lead_lang` (idioma estável da conversa).
  - `enrich_thread` mantém `reply_lang` estável; traduz a mensagem com
    `detected` e o rascunho final para `reply_lang`.
  - Deteção corrigida: removida a palavra partilhada `semana` dos marcadores
    ES e adicionados marcadores PT (`recebo`, `exatamente`, `morada`,
    `equipa`).
  - Logs novos: `thread #N ... lead_lang=... (selected=... detected=...)`,
    `resposta ... lang=... subject=...`, e ID Resend no envio.

## Matriz E2E (widget real → inbox → resposta aprovada)

| Idioma | Thread | `lead_lang` | `locale` | `messages[0].lang` | `draft_out_lang` | Acknowledgment | Assunto da resposta |
|---|---:|---|---|---|---|---|---|
| PT-BR | 24 | `pt` | `pt` | `pt` | `pt` | Recebemos a sua mensagem | Re: a sua pergunta sobre a Magic Leads |
| EN | 25 | `en` | `en` | `en` | `en` | We received your message | Re: your question about Magic Leads |
| ES | 26 | `es` | `es` | `es` | `es` | Hemos recibido tu mensaje | Re: tu pregunta sobre Magic Leads |

As três respostas foram enviadas com `email_sent=true`.

### IDs Resend (staging)

| Idioma | Acknowledgment | Resposta |
|---|---|---|
| PT | `01a1c36a-4931-779f-9164-7c692df132cd` | `01a1c378-0bf9-76d5-a17d-f9f1c9169659` |
| EN | `01a1c36a-8b07-74f3-916f-56a9bf224e4a` | `01a1c36c-7c4b-7cec-9bc9-bf335ac1ef37` |
| ES | `01a1c36a-d977-75fc-ba07-d79cbeff07ca` | `01a1c378-3c46-7ab3-b749-696169670200` |

## Caixas de entrada de teste

Foram usadas caixas reais temporárias (mail.tm) para receber os e-mails via
Resend:

- PT: `lp-pt-220403@fldubai.com`
- EN: `lp-en-220403@fldubai.com`
- ES: `lp-es-220510@fldubai.com`

Conteúdo confirmado:

- PT — “Olá Teste PT … Obrigado por contactar a Magic Leads …” / resposta
  “Por $120 por semana tem acesso ao painel … ofício … proprietário … é …”.
- EN — “Hi Test EN … Thanks for reaching out …” / resposta
  “For $120 per week you have access …”.
- ES — “Hola Teste ES … Gracias por contactar Magic Leads …” / resposta
  “Por 120 $ a la semana tienes acceso … dirección y teléfono …”.

Foi feita verificação de code points para excluir duplo encoding:

- PT `ofício`: `111,102,237,99,105,111` (í = 237)
- ES `dirección`: inclui `243` (ó); `teléfono`: inclui `233` (é)
- Nenhum corpo contém `Ã` ou `&Atilde;`.

O relatório visual com as caixas está em
[`docs/lp-language-e2e-inboxes.html`](lp-language-e2e-inboxes.html).

## Qualidade

- `pytest tests/test_lp_widget.py tests/test_lp_ai.py`: **35 passed**
- `ruff check backend tests --select=E,F,W,I --ignore=E501`: limpo
- `tsc --noEmit`: limpo
- `eslint` widget/admin: limpo
- `npm run build` com `NEXT_PUBLIC_LP_WIDGET=false`: OK
- Staging preview: `https://frontend-m2acf2d9j-fabio-dev2.vercel.app`
  - `/en/widget-preview` (teste isolado; LP oficial escondida pelo flag)

## Estado final de produção

- Correção desenvolvida em `fix/lp-language-persistence`
  (`4b26d63`, `860a69a`, `d1f3a86`).
- Kill-switch aplicado em produção antes da aprovação final:
  `NEXT_PUBLIC_LP_WIDGET=false`, com redeploy de `master` (`586195e`) e
  `/admin/lp-inbox` a 404.
- Após a validação final, a branch foi merged em `master` (`d1f3a86`) e o
  backend/frontend de produção foram deployados com
  `NEXT_PUBLIC_LP_WIDGET=true` e `LP_WIDGET_ENABLED=true`.
- Verificação pós-deploy em `https://www.magicleads.app`:
  - `/en`, `/pt`, `/es` → 200;
  - launcher presente e painel abre no idioma da LP (EN/PT/ES);
  - `/api/public/lp/availability` → 200;
  - `/admin/lp-inbox` → 200 (protegido por sessão admin);
  - base de produção limpa: 0 threads e 0 anexos;
  - `/health` do backend → 200.
- Produção usa MyMemory enquanto não existir uma chave Gemini/OpenAI dedicada;
  recomenda-se configurar a chave para qualidade e privacidade de nível
  enterprise.
