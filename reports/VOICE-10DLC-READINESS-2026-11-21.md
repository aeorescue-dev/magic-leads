# Voz + 10DLC (SMS) — auditoria read-only (2026-11-21)

**Modo:** apenas leitura (GET). Nenhuma chamada, SMS, campanha ou variável foi
alterada. `VOICE_FREEZE=1` mantido. Backend `271eb41`, frontend `53bf2f2`.

---

## 1. Telnyx — estado real hoje

| Item | Estado |
|---|---|
| Brand 10DLC | `4b2001a1-...-a9fe37` · TCR `BCW3GRB` · `status=OK` · **`identityStatus=VERIFIED`** |
| Campanhas 10DLC | **0** (`assignedCampaignsCount=0`) |
| Número SMS `+1***7808` | ativo, local, **no** Messaging Profile, **sem campanha** |
| Número configurado `TELNYX_FROM_NUMBER` `+1***2550` | ativo, **voz** (Call Control), **sem Messaging Profile** |
| Atribuições número↔campanha | **0** |
| Messaging Profile `4001a1d1-...` | `enabled=true`, `webhook_url=null` |
| Call Control App `Magic Leads Voice` | ativo, webhook `https://magic-leads-production.up.railway.app/api/voice/telnyx/webhook` |
| Saldo | **$0,99** (`available_credit`) |

**Mudança face a 18/11:** a identidade do brand passou de `UNVERIFIED` para
**`VERIFIED`**. O brand está pronto para criar campanha; a campanha e a
atribuição do número continuam a faltar.

**Ponto importante:** o número configurado como remetente no backend
(`+1***2550`) é o número de **voz** e **não** está no Messaging Profile. O número
com perfil de SMS é outro (`+1***7808`). Enviar SMS a partir do número de voz
seria rejeitado/bloqueado.

---

## 2. Webhooks e chaves (backend)

| Item | Estado |
|---|---|
| Endpoint de voz | `POST /api/voice/telnyx/webhook` (existe) |
| Assinatura | **Ed25519** (`TELNYX_PUBLIC_KEY`, 44 chars) + segredo partilhado (64 chars) |
| URL no Call Control | `https://magic-leads-production.up.railway.app/...` (correta) |
| `TELNYX_API_KEY` / `TELNYX_CONNECTION_ID` | presentes e válidos |
| `TELNYX_MESSAGING_PROFILE_ID` | **ausente** (o backend não conhece o perfil) |
| Endpoint de SMS recebido (STOP/HELP) | **não existe** |
| `VOICE_FREEZE` | `1` |

---

## 3. Fluxo DTMF no código

- `VOICE_SCRIPT_MODE=static` → `gather_using_speak`/`gather_using_audio` com
  `maximum_digits=1` e **`valid_digits="2"`**.
- **Tecla 2** → opt-out: suppression + DNC + “You've been removed…”. Testado.
- **Tecla 1** → **não é capturada** neste modo (`valid_digits` só aceita 2).
  Existe um ramo no handler que, se receber `1`, apenas fala “Visit MagicLeads
  dot app…”; **não envia SMS**.
- O guião aprovado diz explicitamente “To opt out, press 2.” e
  “Do not promise email or SMS delivery”.
- **Não existe código de envio de SMS** em lado nenhum do backend
  (sem `POST /v2/messages`, sem opt-out STOP/HELP, sem webhook de SMS).

**Conclusão:** o fluxo “digitar 1 → SMS” **não está implementado**; hoje só
existe opt-out por voz na tecla 2.

---

## 4. Voz — evidência operacional

- Últimas chamadas: **2026-11-16** (campanha 19), depois pausadas.
- Campanhas 19–24 `paused`; 17 `stopped`; 18 `completed`.
- Últimos resultados: `voicemail/machine` e 2 `timeout`; sem erros de API.
- 2 supressões `caller_opt_out` registadas.
- Sem chamadas desde o freeze; logs recentes sem erros `TELNYX`.

---

## 5. Checklist para o teste pago

### Pronto
- [x] Brand 10DLC **VERIFIED** (TCR `BCW3GRB`)
- [x] Call Control App ativo e webhook de voz correto
- [x] Ed25519 + segredo no webhook
- [x] Opt-out de voz (tecla 2) e supressões
- [x] Chaves/IDs de voz presentes; `VOICE_FREEZE=1`

### Falta antes de SMS / teste
- [ ] **Saldo**: $0,99 — insuficiente para o teste de $16
- [ ] **Campanha 10DLC**: criar e aguardar aprovação (é a etapa paga)
- [ ] **Atribuir `+1***7808`** à campanha aprovada
- [ ] **Messaging Profile**: definir `webhook_url` para o backend (inbound)
- [ ] **Código SMS**: enviar, STOP/HELP, inbound, texto com opt-out
- [ ] **DTMF 1**: decidir e implementar (hoje só fala website)
- [ ] Usar o número SMS (`+1***7808`), nunca o de voz (`+1***2550`)

### Recomendação
Manter `VOICE_FREEZE=1`. O brand já está verificado, mas o teste de $16 sem
saldo, sem campanha e sem número atribuído falharia. Ordem segura:
**carregar saldo → criar campanha → atribuir número → implementar SMS/opt-out →
teste único para `VOICE_TEST_NUMBERS`**.
