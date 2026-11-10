# LP Widget — auditoria de estabilidade (Fase 2)

Data: 2026-11-09/10 · Âmbito: widget público, inbox admin, endpoints `/api/*/lp/*`,
SQLite `lp_*`, tradução/IA, anexos, Resend e montagem invisível na LP.

## Correções aplicadas

1. **E-mail humanizado**
   - Removido `#LP-<id>` e qualquer texto de “referência/protocolo” do
     acknowledgment (EN/PT/ES).
   - Teste `test_acknowledgment_uses_lead_language` garante ausência de `#LP`.

2. **Controlo de horário permanente**
   - Cabeçalho da inbox + barra `Automático / Online / Fora de horário` passaram
     a um bloco `sticky` abaixo do `AdminNav` (altura medida por
     `ResizeObserver`, CSS `--admin-nav-height`).
   - Validado no browser: mantém-se visível após scroll; nav móvel de 120 px
     resulta em `top: 121 px`.

3. **“Atualizar” fiável**
   - O re-fetch passou a forçar as quatro fontes SWR: lista de threads,
     detalhe, feed de novos leads e disponibilidade.
   - Spinner + `aria-busy` confirmados; pedidos observados:
     `threads`, `threads/{id}`, `threads?status=new`, `availability`.

4. **Campainha de alertas**
   - Visível no cabeçalho, com estado ligado/desligado persistido em
     `localStorage`; toca dois tons via Web Audio após o primeiro gesto.

5. **Draft da inbox por thread**
   - `ReplyComposer` passou a ter `key={thread.id}`; trocar de thread já não
     reaproveita texto/estado da thread anterior.
   - Estado derivado (`ptEdit ?? initialPt`) permite que o rascunho da IA
     apareça depois do mount sem apagar edições humanas.

6. **Idioma do lead estável**
   - Um follow-up curto (“ok”) já não muda `lead_lang` de PT para EN.
   - `add_lead_message` mantém o idioma da thread; `enrich_thread` usa
     `detected` para traduzir a mensagem e `reply_lang` para o rascunho/envio.
   - Teste `test_follow_up_does_not_flip_lead_language`.

7. **Anexos**
   - SVG e tipos desconhecidos passam a ser rejeitados (evita SVG com script
     servido same-origin).
   - Imagens permitidas: PNG, JPEG, GIF, WebP, BMP. Documentos: PDF, Word,
     Excel, TXT, CSV. Limite 10 MB por ficheiro.
   - O anexo do lead fica associado à bolha da mensagem (`message_id`) e é
     renderizado inline no widget e na inbox.
   - O compositor de resposta da inbox tem botão **Anexar**; os ficheiros vão
     no e-mail Resend (limite 20 MB) e ficam inline na bolha de saída.
   - Se o lead anexa depois de uma resposta da equipa, é criada uma mensagem
     inbound própria (`📎 ficheiro`) para o ficheiro aparecer no fim da conversa.
   - `accept` do widget e da inbox alinhado com o backend.

8. **Latência do acknowledgment**
   - O envio Resend deixou de bloquear a resposta ao lead; passou para
     `BackgroundTasks` (`send_acknowledgment`).
   - `ack_sent` deixa de ser devolvido pela API pública.

9. **Retoma de conversa no widget**
   - O token guardado em `sessionStorage` é agora usado para retomar a conversa
     após reload; token inválido é limpo.
   - “Começar de novo” remove o token.
   - Disponibilidade do widget revalidada a cada 60 s.

10. **Filtros da inbox**
    - Mudar período/estado limpa a seleção, evitando detalhe de uma thread que
      já não pertence à lista.
    - Label dos dias úteis vem de `business_days` (não hardcoded).

11. **Conversa contínua no widget**
    - Após a resposta da equipa, o passo 5 mantém uma caixa de mensagem ativa
      (não força “Começar de novo”).
    - O follow-up usa `POST /api/public/lp/threads/{token}/messages`, cai na
      mesma thread, reabre o estado `new` e aparece na inbox por polling.
    - Validado E2E: thread #17, resposta da equipa, follow-up do lead e inbox
      com a mensagem e estado `NOVO`.

## Validações

- `pytest tests/test_lp_widget.py tests/test_lp_ai.py`: **28 passed**.
- `ruff check backend tests --select=E,F,W,I --ignore=E501`: limpo.
- `tsc --noEmit`: limpo.
- `eslint` nos ficheiros LP/admin: limpo.
- `npm run build` com `NEXT_PUBLIC_LP_WIDGET=false`: OK.
- Browser: sem launcher na LP, sem pedidos `/api/public/lp/*`, chunk do widget
  não descarregado; inbox funcional, sticky, refresh e campainha OK.
- Browser: troca de threads mostra rascunhos distintos e correctos.
- Backend deployado: acknowledgment sem `#LP`, com frase offline localizada.

## Falhas externas observadas (fora do widget)

A suite completa (`pytest tests/`) termina com duas falhas em módulos não
relacionados, já existentes no repositório:

- `tests/test_voice_live.py::test_voice_liquidity_separa_exact_e_desconta_7d`
- `tests/test_analytics.py::test_custom_range_e_inclusivo_e_filtra_dias`

Nenhuma toca em `lp_*`, no widget, na inbox, na IA de tradução, nos anexos ou no
Resend. O motor de voz e o analytics permanecem intocados.

## Limitações conhecidas

- Anexos de resposta seguem no e-mail via Resend; o acknowledgment inicial não
  leva anexos.
- Sem chave LLM no staging, a tradução usa MyMemory; produção deve usar
  Gemini/OpenAI.
- O alerta sonoro exige interação prévia com a página (política de autoplay dos
  browsers).
