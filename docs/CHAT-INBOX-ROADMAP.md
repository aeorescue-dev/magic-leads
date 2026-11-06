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
- **Idioma de fábrica: EN (EUA)**. A landing page e toda a UI nativa do chat nascem em inglês; o seletor é apenas uma opção do visitante.
- Abre com:
  - saudação em inglês;
  - seletor de idioma no topo;
  - campo de telefone;
  - caixa de texto;
  - botão de áudio.
- Só o telefone é obrigatório. Sem nome, e-mail ou empresa.
- Microcopy de consentimento numa linha, em inglês:
  > “By submitting your phone number, you agree to receive calls/messages regarding our services.”
- Guardar `consent_text` + timestamp + IP hash.

### Out-of-hours
- O chat **nunca** mostra “fechado” antes do envio. O visitante pode escrever, gravar áudio e deixar o telefone a qualquer hora.
- Fora do horário, o sistema responde automaticamente no idioma selecionado:
  - confirma a receção;
  - informa que a resposta chega no próximo dia útil;
  - mantém a conversa aberta para o operador.
- A mensagem automática é editável no Admin.
- Configuração no `/admin/inbox`:
  - timezone;
  - horário de abertura/fecho por dia da semana;
  - mensagem personalizada de fora de horário (com tradução automática para o idioma do cliente).

### Seletor de idioma
- Default de fábrica: **EN**.
- Lista inicial: **top 20 idiomas mais falados nos EUA** — EN, ES, ZH, VI, FR, AR, KO, RU, HT, TL, PT, HI, BN, UR, PL, IT, DE, HE, JA, TR — com busca rápida.
- Fallback via LLM para qualquer outro idioma suportado pelo modelo.
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

### Qualificação do visitante
- Antes de migrar a lead para a base de voz, o chat pergunta o perfil:
  - **Contractor**
  - **Homeowner**
  - **Other**
- A resposta é guardada em `landing_contacts.profile_type` e `qualification_json`.
- Só `Contractor` (ou qualificação manual equivalente) pode ser promovido a `prospect_companies`/campanha de voz.
- Homeowner/Other ficam no CRM de landing, sem chamadas de voz automáticas.

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
- **Notificação visual + alerta sonoro** quando entra nova mensagem (som só com o painel aberto e aba visível; sem autoplay bloqueado).
- Configuração de horário: timezone, abertura/fecho por dia, mensagem fora de horário.
- **Broadcast Push Notifications**: compositor manual, segmentação por cidade/nicho/idioma/perfil, preview e disparo.

### Push Web (opt-in do visitante)
- Após a captura do telefone, o widget pede permissão:
  > “Stay updated on new project opportunities in your area.”
- O pedido é feito **num gesto do utilizador**; nunca no carregamento da página.
- Guardar em `landing_push_subscriptions`:
  - `landing_contact_id`, `endpoint`, `p256dh`, `auth`;
  - `locale`, `user_agent`, `consent_at`, `ip_hash`;
  - `disabled_at` para opt-out.
- O visitante pode desativar no widget ou no rodapé da notificação; a subscrição é desativada imediatamente.
- iOS: push só em PWA instalada (iOS 16.4+); o widget explica isso sem bloquear o chat.

### iOS / PWA — requisitos obrigatórios

- **PWA-Ready Landing Page:**
  - `manifest.json` completo: `name`, `short_name`, `start_url`, `scope`, `display: standalone`, `background_color`, `theme_color`.
  - Ícones 192, 512 e maskable; `apple-touch-icon`.
  - Meta tags: `apple-mobile-web-app-capable=yes`, `apple-mobile-web-app-status-bar-style`, `apple-mobile-web-app-title`.
  - Service Worker registado; HTTPS; VAPID.
- **Smart Prompt iOS:**
  - Detetar iPhone/iPad + Safari + `display-mode` não-standalone.
  - Depois do telefone e do opt-in, mostrar um guia visual curto:
    1. Share;
    2. Add to Home Screen;
    3. abrir pela Home Screen;
    4. Allow Notifications.
  - **Não é possível instalar a PWA com um único clique programático no iOS** — o Safari não expõe `beforeinstallprompt`. O “1 clique” é um CTA que abre o guia certo; a instalação continua a ser Share → Add to Home Screen.
  - Depois de aberta em standalone, pedir a permissão de notificações num gesto do utilizador.
- **Fallback cross-channel:**
  - Se não instalar, não autorizar ou o browser não suportar push, `landing_contacts.push_eligible=false`.
  - Guardar `push_platform='ios'`, `push_state` (`unsupported`, `not_installed`, `denied`, `subscribed`) e `fallback_channel` (`sms`/`voice`).
  - Contactos `push_eligible=false` entram no segmento Admin **“non-push iOS”** para broadcast via SMS ou voz.
  - O envio SMS/voz usa a Telnyx existente, com consentimento e orçamento; **não é $0 por mensagem**. A elegibilidade é registada a custo zero; o disparo real tem custo Telnyx.
  - Sem consentimento para SMS/voz, o contacto fica apenas no CRM e no chat, sem broadcast ativo.

### Broadcast no Admin
- Secção “Broadcast Push” no `/admin/inbox`.
- Operador escreve título/corpo em PT-BR (ou EN), escolhe segmento:
  - cidade;
  - nicho/trade;
  - idioma;
  - perfil Contractor/Homeowner/Other;
  - apenas opt-in ativo;
  - **non-push iOS** (`push_eligible=false`), com fallback SMS/voz.
- Preview da contagem antes do envio; teste para o próprio admin.
- Mostrar separadamente: subscrições push ativas, iOS sem PWA, iOS sem permissão e contactos sem push.
- Tradução automática para o `locale` de cada subscrição antes do envio.
- Envio por Web Push API nativa (VAPID + Service Worker), sem OneSignal/SaaS.
- Guardar `landing_push_campaigns` + `landing_push_deliveries` (status, HTTP, erro, clique).
- Payload sem PII: título, corpo traduzido, URL e `tag`; o telefone nunca vai no payload.
- Cap de tradução dentro dos $5/dia; se falhar, o envio desse idioma é bloqueado e registado — nunca sai texto no idioma errado.

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
  profile_type, qualification_json, consent_text, consent_at, ip_hash,
  push_eligible, push_platform, push_state, fallback_channel,
  fallback_consent, created_at, last_seen_at
)

chat_settings (
  id, timezone, hours_json, out_of_hours_message, auto_reply_enabled,
  updated_by, updated_at
)

landing_push_subscriptions (
  id, landing_contact_id, endpoint UNIQUE, p256dh, auth, locale,
  user_agent, consent_at, ip_hash, disabled_at, last_success_at, created_at
)

landing_push_campaigns (
  id, title_source, body_source, source_lang, segment_json, status,
  created_by, created_at, sent_at, sent_count, failed_count
)

landing_push_deliveries (
  id, campaign_id, subscription_id, status, http_status, error,
  clicked_at, created_at
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
POST /api/chat/push/subscribe   # opt-in, subscription nativa
POST /api/chat/push/unsubscribe # opt-out imediato
POST /api/admin/inbox/push/broadcast
GET  /api/admin/inbox/push/segments
GET  /api/admin/inbox/push/deliveries
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
| Web Push VAPID/Service Worker | $0 |
| Fallback SMS/voz (non-push iOS) | custo Telnyx por envio |
| SaaS novo | $0 |

O maior custo é o LLM; usar cache, limites e modelo barato. Sem Google Places/Searchbug/novo SaaS.

**Cap inicial aprovado:** **$5/dia** para tradução + rascunhos. O sistema deve:
- bloquear novas chamadas ao LLM quando o cap diário for atingido;
- mostrar aviso no Admin;
- usar cache e fallback sem tradução quando possível.

**Retenção de áudio:** **30 dias no VPS** durante o piloto; S3/R2 fica para avaliação futura.

---

## 6. Roadmap da semana

| Dia | Entrega |
|---|---|
| **Seg** | Spec freeze, wireframes, schema, consentimento, lista de idiomas |
| **Ter** | `landing_contacts`, `chat_*`, `chat_settings`, APIs de sessão/mensagem, validação de telefone, rate limit |
| **Qua** | Widget público (texto + áudio), EN default, seletor top 20, qualificação, SSE/polling, transcrição local, opt-in push pós-telefone, deteção iOS/PWA e guia Add to Home Screen |
| **Qui** | Inbox Admin, tradução PT-BR, rascunho IA, envio traduzido, horário/out-of-hours, notificação visual + som, Broadcast Push + segmentos, `push_eligible`/fallback |
| **Sex** | Segurança, testes de carga, retenção 30 d, cap $5/dia, VAPID/service worker, opt-out push, fallback SMS/voz, piloto admin-only; deploy após 20:00 |

**Gate:** `CHAT_INBOX_ENABLED=0` por defeito; ativar primeiro para admin; público só depois de 48 h de piloto limpo.

---

## 7. Critérios de aceitação

- UI inicial em **EN**; seletor muda o idioma apenas por ação do visitante.
- Telefone inválido não cria conversa.
- Telefone válido cria `landing_contacts` e conversa com o microcopy de consentimento exato.
- Mensagem de texto e áudio aparecem no Admin em PT-BR.
- Rascunho PT-BR é editável e enviado no idioma do cliente.
- Áudio ≤60 s é transcrito e traduzido; retenção 30 dias.
- Fora de horário: mensagem é aceite, auto-resposta no idioma do cliente, conversa aberta.
- Admin configura timezone, horários por dia e mensagem out-of-hours.
- Nova mensagem gera badge + som no Admin (com aba visível).
- Push opt-in só depois do telefone e num gesto do utilizador; `consent_at`/`ip_hash` guardados.
- Opt-out push desativa imediatamente a subscrição.
- iOS: landing PWA-ready; manifest/meta/ícones/service worker válidos.
- iOS Safari não-standalone vê o guia Share → Add to Home Screen; não há promessa de instalação programática.
- iOS sem PWA/permissão fica `push_eligible=false` e `fallback_channel` preenchido.
- Segmento “non-push iOS” visível no Broadcast; SMS/voz respeita consentimento e orçamento.
- Broadcast segmentado por cidade/nicho/idioma/perfil; preview e contagem corretos.
- Push traduzido para o locale de cada subscrição; falha bloqueia aquele envio.
- Nenhum telefone/PII no payload push.
- Qualificação Contractor/Homeowner/Other; só Contractor pode ir para voz.
- Nenhuma mensagem é enviada sem tradução confirmada ou fallback explícito.
- SSE entrega em <2 s; polling fallback.
- Rate limit e consentimento registados.
- Admin-only; público bloqueado por flag.
- Cap IA $5/dia com bloqueio e aviso.
- Testes de XSS, upload inválido, número inválido, tradução falhada, conversa fechada, out-of-hours, qualificação.

---

## 8. Decisões fechadas

1. **Consentimento:** “By submitting your phone number, you agree to receive calls/messages regarding our services.”
2. **Idioma:** EN de fábrica; seletor com top 20 idiomas dos EUA + busca; fallback LLM para outros.
3. **Orçamento IA:** cap **$5/dia** para tradução + rascunhos, com bloqueio e aviso.
4. **Áudio:** retenção **30 dias no VPS**; S3/R2 apenas no futuro.
5. **Notificação:** badge visual + alerta sonoro no `/admin/inbox` quando entra mensagem.
6. **Qualificação:** Contractor / Homeowner / Other antes de migrar para a base de voz; só Contractor entra em campanhas de voz.
7. **Push Web:** opt-in após o telefone, VAPID + Service Worker, custo $0; opt-out imediato; Broadcast segmentado no Admin.
8. **iOS:** PWA-ready, Smart Prompt para Add to Home Screen, `push_eligible` e fallback SMS/voz para non-push iOS.
9. **Notificação de nova mensagem:** badge visual + som no `/admin/inbox`.

### Ainda por decidir na implementação
- Modelo LLM exato (DeepSeek/GLM) e fallback.
- Quem recebe/atribui conversas e se há notificação por email.
- Limite de conversas por telefone/IP por dia.
- Política de apagação de PII a pedido.
