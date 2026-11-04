# Web Push — regras de conteúdo por plataforma

Fonte: `backend/services/alert_planner.py`, `backend/services/push_service.py`,
`backend/services/lifecycle_push.py`, `frontend/public/sw.js` e
`frontend/public/manifest.json`.

## Distância

| Base do utilizador | Texto (PT) | Texto (EN) |
|---|---|---|
| GPS ou manual | `a 2,3 mi de si` | `2.3 mi away` |
| Cidade (centroide) | `~11,0 mi do centro de Chicago` | `about 11.0 mi from downtown Chicago` |
| Sem base | omite o segmento | omits the segment |

`source='city'` passou a mostrar distância **aproximada** (prefixo `~` e
“centro de …”); nunca é apresentada como GPS. Leads com coordenadas são a
maioria (114/114 alertas recentes tinham `lat/lng`).

## Payload

Campos comuns: `title`, `body`, `icon`, `badge`, `tag`, `renotify`, `silent`,
`leadId`, `occurrence`, `signalType`, `category`, `url`, `vibrate`,
`requireInteraction`, `timestamp`, e `nid`/`sig` quando `PUSH_CLICK_SECRET`
está definido.

- **Android/desktop:** payload completo, com `actions` (Ver lead / Dispensar).
  Os botões são mostrados pelo sistema (normalmente ao expandir/hover).
- **iOS (PWA):** variante sem `actions`/`requireInteraction`/`vibrate` e com
  CTA no corpo (`Toque para abrir o lead.` / `Tap to open the lead.`). O iOS
  ignora botões nativos.

A escolha é feita por `user_agent` guardado em `push_subscriptions`; o mesmo
utilizador pode ter Android e iOS e receber payloads diferentes.

## Ícones

- `icon`: `https://www.magicleads.app/icons/push-icon-192.png` (marca real)
- `badge`: `https://www.magicleads.app/icons/push-badge-72.png` (72×72,
  silhueta branca para o ícone pequeno do Android)
- `manifest.json` usa os mesmos PNGs (192 e 512); `apple-touch-icon` usa
  `/icons/magicleads-icon-192.png`.

## Cliques

`PUSH_CLICK_SECRET` configurado em produção → `nid`/`sig` assinados no payload;
o SW chama `/api/push/click` e o backend regista `push_deliveries.clicked_at`.
Sem segredo, o clique continua a abrir o lead mas não é medido (fail-closed).

## Idioma (i18n estrita — Fase 25)

- `push_subscriptions.locale` guarda o idioma do destinatário. É preenchido no
  registo (com fallback SQL para `users.locale`) e **atualizado** sempre que o
  utilizador muda o idioma (`update_user_locale` → todas as subscriptions).
- O envio resolve o locale **por dispositivo**: `subscription.locale` →
  `users.locale` → `en` (nunca PT por omissão). O mesmo utilizador com um
  Android em EN e um iPhone em ES recebe textos diferentes.
- Todos os textos do alerta são gerados nesse locale: título (sinal + ofício),
  morada, distância exata/aproximada, contexto, confiança do telefone, ações e
  CTA iOS, digest, onboarding e avisos de ciclo de vida.
- Avisos de ciclo de vida passaram a gravar `msg_key` + `msg_params` (antes
  eram strings PT hardcoded) e são renderizados nos 3 idiomas. Linhas antigas
  sem `msg_key` usam um fallback genérico localizado — nunca o texto PT gravado.
- Testes `tests/test_push_i18n.py`: payloads EN/ES sem vocabulário PT, distância
  nos 3 idiomas, CTA iOS, propagação do locale na BD e escolha por subscription.

## Matriz de validação em dispositivo

| Cenário | Esperado |
|---|---|
| Android Chrome (PWA instalada) | ícone pequeno branco (badge), título/corpo, botões ao expandir, vibração. |
| Android Chrome (aba normal) | notificação do sistema; ações conforme o SO. |
| iPhone (PWA no ecrã inicial, iOS 16.4+) | sem botões; corpo termina com “Toque para abrir o lead.”; CTA abre o dashboard no lead. |
| iPhone Safari (aba normal) | push indisponível até instalar como PWA. |
| Desktop Chrome/Edge | ícone PNG, ações visíveis no cartão de notificação. |

## Saúde e cobertura (2026-11-04)

- `push_health` conta apenas subscrições ativas (`disabled_at IS NULL`) e só
  alerta zero entregas quando existem notificações elegíveis nas 24h.
- Categorias são normalizadas para as 16 canónicas antes do Alert Planner;
  aliases como `Roofing`/`Roof`, `Heating & HVAC`/`Heating` e
  `General Contractors`/`Structure` não ficam silenciosos.
- Subs stale/demo são desativadas; as linhas ficam para auditoria.
