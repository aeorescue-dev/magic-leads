# Roadmap — Chat Multilíngue da Landing Page + Inbox Admin

**Estado:** especificação aprovada para desenvolvimento na semana seguinte.  
**Dependência:** infraestrutura de voz/P0/Phase 1 consolidada.  
**Princípio:** custo marginal próximo de zero; sem SaaS novo caro; admin-only no arranque.

---

## 1. Objetivo

Permitir que um visitante da landing page inicie uma conversa em qualquer idioma, por texto ou áudio, deixando apenas o telefone. O operador recebe tudo traduzido em PT-BR no Admin, com rascunho de resposta por IA; a resposta é entregue ao visitante no idioma dele.

---

## 2. UX do chat público

### Entrada
- Widget flutuante, lazy-loaded, sem bloquear o LCP.
- Abre com:
  - saudação em inglês (default);
  - seletor de idioma no topo;
  - campo de telefone;
  - caixa de texto;
  - botão de áudio.
- Só o telefone é obrigatório. Sem nome, e-mail ou empresa.
- Microcopy de consentimento numa linha: contacto futuro por telefone/WhatsApp; guardar `consent_text` + timestamp + IP hash.

### Seletor de idioma
- Lista priorizada: EN, PT-BR, ES, ZH, RU, HT, FR, AR, BN, UR, PL, IT, DE, KO, VI, TL, HE, HI, JA, TR.
- Busca por nome nativo; bandeiras não são obrigatórias (evitar poluição).
- `dir="auto"` para RTL.
- Guardar escolha em `localStorage` por conversa; default EN.

### Telefone
- Input único com seletor de país (default +1).
- Validação em tempo real no cliente com `libphonenumber-js`.
- Normalização E.164 no servidor com `phonenumbers`.
- Rejeitar números inválidos/curtos; rate limit por IP/telefone.
- Guardar em `landing_contacts` com `source='landing_chat'`, `consent_at`, `page_url`, UTM, idioma.
- Não inserir automaticamente em `prospect_companies`/campanhas de voz; qualificação posterior.

### Texto e áudio
- Texto com limite de 2.000 caracteres.
- Áudio via `MediaRecorder`, máximo 60 s e 5 MB.
- Formatos: webm/ogg; converter para wav no servidor.
- Player no chat; transcrição visível após processamento.
- Sem vídeo.

### Entrega
- Envio otimista com estado `sending/sent/failed`.
- Respostas em tempo real por SSE; fallback polling 5 s.
- Indicador de “a escrever” do operador.

---

## 3. Inbox Admin

Rota: `/admin/inbox` (alias `/admin/chat`).

### Lista
- Conversas por: não lidas, abertas, pendentes, fechadas.
- Filtros: idioma, cidade/UTM, telefone, operador, data.
- Badge de não lidas e idade da última mensagem.
- Auto-refresh 10 s + SSE.

### Thread
- Mensagens originais + tradução PT-BR lado a lado ou toggle.
- Áudio: player + transcrição + tradução.
- Contacto: telefone, idioma, página, UTM, consentimento, histórico.
- Estado: open / pending / closed; atribuição a operador.
- Notas internas (não enviadas ao cliente).

### IA copiloto
- Botão “Gerar rascunho” em PT-BR.
- Contexto: últimas 10 mensagens, idioma do cliente, intenção, produto.
- Operador edita e envia.
- Se o operador responder em PT-BR, o sistema traduz para o idioma do cliente antes de entregar.
- Guardar `draft_model`, tokens, custo e aceitação.

### Envio
- `POST /api/admin/inbox/{id}/reply` com texto PT-BR.
- Tradução para `conversation.source_lang`; gravar original e traduzido.
- Entregar no chat; marcar `delivered_at`.
- Falha de tradução: bloquear envio ou enviar original com aviso; nunca enviar texto errado em silêncio.

---

## 4. Arquitetura técnica

### Tabelas
```sql
landing_contacts (
  id, phone_e164 UNIQUE, language, source, page_url, utm_json,
  consent_text, consent_at, ip_hash, created_at, last_seen_at
)

chat_conversations (
  id, public_id UNIQUE, contact_id, source_lang, status,
  assigned_to, created_at, last_message_at, closed_at
)

chat_messages (
  id, conversation_id, direction, kind, original_text,
  original_lang, translated_text, translated_lang, transcript,
  audio_path, audio_seconds, translation_status, delivered_at,
  read_at, created_at
)

chat_ai_drafts (
  id, message_id, draft_text, model, prompt_tokens, completion_tokens,
  cost_usd, accepted, created_at
)

chat_events (
  id, conversation_id, actor, event, payload_json, created_at
)
```

- Áudio em `/data/chat_audio/<conversation>/<uuid>.wav`; retenção 30 dias no piloto; R2/S3 depois.
- `public_id` opaco para o cliente; nunca expor IDs sequenciais.
- `chat_events` append-only para auditoria.

### APIs públicas
```text
POST /api/chat/session          # telefone + idioma + consentimento + UTM
POST /api/chat/messages         # texto
POST /api/chat/audio            # multipart, ≤60 s
GET  /api/chat/messages         # token público, polling/SSE
```

### APIs admin
```text
GET  /api/admin/inbox
GET  /api/admin/inbox/{id}
POST /api/admin/inbox/{id}/reply
POST /api/admin/inbox/{id}/draft
POST /api/admin/inbox/{id}/status
GET  /api/admin/inbox/stream    # SSE
```

### Tradução
- **Texto:** LLM low-cost já usado no projeto (DeepSeek) com prompt de tradução + detecção de idioma (`langid`/`lingua`). Fallback: mostrar original + aviso.
- **Áudio:** `faster-whisper` local no VPS (modelo `small`, CPU) para transcrição multilíngue; sem custo por minuto. Se a fila crescer, fallback pago opcional.
- **Rascunho:** DeepSeek/GLM Flash; prompt com contexto e tom; custo por mensagem mínimo.
- **Limites:** 1 tradução + 1 rascunho por mensagem; orçamento diário; cache por hash de texto+idioma.

### Tempo real
- SSE no Admin; público com SSE + fallback polling.
- Sem Redis no piloto: fila em processo + DB; se necessário, worker separado.

### Segurança
- Admin-only no inbox; RBAC e audit log.
- Token público opaco, TTL 24 h, rate limit.
- Sanitização XSS; texto renderizado como texto.
- Áudio: MIME/tamanho/duração; nomes UUID; sem execução.
- Consentimento explícito para marketing; opt-out no chat e na voz.
- Retenção e apagação de PII; não enviar PII a LLM sem necessidade.

---

## 5. Custos

| Componente | Custo |
|---|---|
| Widget/UI | $0 |
| DB SQLite | $0 |
| Áudio local | $0 (disco; limitar 30–60 s) |
| Transcrição local Whisper | $0 (CPU VPS) |
| Tradução/rascunho LLM | ~$0,0002–$0,002 por mensagem |
| SSE/polling | $0 |
| SaaS novo | $0 |

O maior custo é o LLM; usar cache, limites e modelo barato. Sem Google Places/Searchbug/novo SaaS.

---

## 6. Roadmap da semana

| Dia | Entrega |
|---|---|
| **Seg** | Spec freeze, wireframes, schema, consentimento, lista de idiomas |
| **Ter** | `landing_contacts`, `chat_*`, APIs de sessão/mensagem, validação de telefone, rate limit |
| **Qua** | Widget público (texto + áudio), SSE/polling, transcrição local |
| **Qui** | Inbox Admin, tradução PT-BR, rascunho IA, envio traduzido |
| **Sex** | Segurança, testes de carga, retenção, monitorização, piloto admin-only; deploy após 20:00 |

**Gate:** `CHAT_INBOX_ENABLED=0` por defeito; ativar primeiro para admin; público só depois de 48 h de piloto limpo.

---

## 7. Critérios de aceitação

- Telefone inválido não cria conversa.
- Telefone válido cria `landing_contacts` e conversa.
- Mensagem de texto e áudio aparecem no Admin em PT-BR.
- Rascunho PT-BR é editável e enviado no idioma do cliente.
- Áudio ≤60 s é transcrito e traduzido.
- Nenhuma mensagem é enviada sem tradução confirmada ou fallback explícito.
- SSE entrega em <2 s; polling fallback.
- Rate limit e consentimento registados.
- Admin-only; público bloqueado por flag.
- Testes de XSS, upload inválido, número inválido, tradução falhada, conversa fechada.

---

## 8. Decisões em aberto

1. Consentimento: texto exato para contacto futuro (voz/WhatsApp) e base legal.
2. Lista inicial de idiomas (20 prioritários vs todos os ISO via LLM).
3. Modelo de tradução/rascunho e orçamento diário.
4. Retenção de áudio (30 dias?) e necessidade de R2/S3.
5. Quem recebe/atribui conversas e notificação (in-app/email).
6. Se o chat deve qualificar o visitante (contractor vs homeowner) antes de criar lead de voz.
