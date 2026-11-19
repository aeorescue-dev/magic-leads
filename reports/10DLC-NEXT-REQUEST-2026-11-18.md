# 10DLC — pedido objetivo à Telnyx e preparação SOLE_PROPRIETOR

**Data:** 2026-11-18 · **Brand:** `4b2001a1-d187-485a-2062-cb5501a9fe37` · **TCR:** `BCW3GRB`
**Estado:** recurso **negado** pelo TCR; Telnyx a pedir o motivo. Produção intocada.

---

## 1. Estado verificado na API (read-only, 2026-11-18)

| Item | Valor |
|---|---|
| Brand `status` | `OK` |
| `identityStatus` | **`UNVERIFIED`** |
| `entityType` | **`PRIVATE_PROFIT`** |
| `companyName` | FABIO HENRIQUE SOARES DE OLIVEIRA |
| `displayName` | MAGIC LEADS TECHNOLOGIES |
| `ein` | 432940311 |
| `mobilePhone` | **vazio** (bloqueia OTP SP) |
| `businessContactEmailVerifiedDate` | **vazio** |
| `failureReasons` | vazio |
| Número `+19739137808` | `active`, associado ao profile |
| Messaging profile `4001a1d1-…` | `enabled=true`, destinos `US` |

Nenhuma campanha foi criada e nenhum número foi atribuído a campanha.

---

## 2. Cronologia

| Data | Evento |
|---|---|
| 2026-11-12 20:52 | Brand criado na Telnyx (`PRIVATE_PROFIT`, EIN). |
| 2026-11-12 21:44 | Pedido de verificação manual enviado (CP575G anexado). |
| 2026-11-13 02:40 | Telnyx: recurso submetido ao TCR. |
| 2026-11-18 11:08 | Follow-up entregue (ticket, estado, `entityType`, e-mail). |
| 2026-11-18 13:22 | Telnyx: **recurso negado**; a pedir o motivo ao TCR. |

---

## 3. Gate operacional

- **Não enviar** o pedido objetivo antes de **2026-11-20 18:00 ET** (2 dias úteis após o follow-up).
- **Não criar** brand, campanha ou associação de número antes da resposta da Telnyx e da validação do owner.
- Se não houver resposta até 2026-11-20, enviar o pedido objetivo em **2026-11-23**.
- Qualquer resposta da Telnyx chega a `aeorescue@gmail.com`; o owner encaminha.

---

## 4. Pedido objetivo (pronto a enviar)

O texto está em `scripts/send_10dlc_email.py`. Pergunta, em três pontos:

1. O brand atual pode ser corrigido **no lugar** para `entityType=SOLE_PROPRIETOR` com os dados do CP575G?
2. Se não, podemos apagar/substituir **sem pagar duas vezes** brand/vetting e **sem conflito no TCR**?
3. Se for preciso um brand SP novo com OTP, o número `+19739137808` e o profile `4001a1d1-…` são **reaproveitáveis**?

**Destinatário:** `10dlcquestions@telnyx.com`
**Reply-To / Cc:** `aeorescue@gmail.com`
**Assunto:** `Re: Manual brand verification request - Brand ID 4b2001a1-d187-485a-2062-cb5501a9fe37 / TCR BCW3GRB`
**Anexo:** `CP575G.pdf`

### Comando (depois do gate)

```powershell
cd garimpador-leads-br
railway run --service magic-leads --environment production -- `
  python scripts/send_10dlc_email.py --send --attachment C:\caminho\CP575G.pdf
```

Sem `--send` o script apenas imprime o payload (dry-run). As chaves vêm de
`RESEND_API_KEY`/`EMAIL_API_KEY` e `EMAIL_FROM`; nunca são escritas no repo.

---

## 5. Preparação SOLE_PROPRIETOR + OTP (não executar)

### Pré-requisitos

| Requisito | Estado |
|---|---|
| Nome legal | FABIO HENRIQUE SOARES DE OLIVEIRA (CP575G) |
| Trade name | MAGIC LEADS TECHNOLOGIES |
| EIN / Name Control | 43-2940311 / SOAR |
| Morada US | 418 7th St Apt B, Harrison, NJ 07029 |
| Data de nascimento do titular | **a confirmar com o owner** |
| E-mail de contacto | `fabio@magicleads.app` (verificar) |
| **Mobile US/CA para OTP** | **em falta** — `mobilePhone` vazio |
| CP575G.pdf | **não está no workspace**; obter com o owner |

### Sequência (planeada)

1. `POST /v2/10dlc/brand` com `entityType=SOLE_PROPRIETOR`, nome legal, morada, DOB, e-mail, telefone e mobile US/CA.
2. `POST /v2/10dlc/brand/{id}/smsOtp` → PIN por SMS (janela de 24 h).
3. `PUT /v2/10dlc/brand/{id}/smsOtp` com o PIN → brand `VERIFIED`.
4. `POST /v2/10dlc/campaignBuilder` (`usecase=SOLE_PROPRIETOR`, descrição, message flow, HELP/STOP, 2 amostras).
5. `POST /v2/10dlc/phone_number_campaigns` para o número.

### Custos e limites

- Brand **$4,50** + vetting **$15** + **$2/mês**; SMS ~$0,004/parte + carrier fee.
- **1 campanha por brand**, **1 número por campanha**, throughput baixo — serve para fallback transacional, não para broadcast.

### Bloqueio principal

O OTP exige um **mobile US/CA** que receba SMS. O número A2P `+19739137808` é de envio; não assumir que serve para OTP. O owner tem de indicar um mobile válido (ou confirmar que `+19292562550` é móvel).

---

## 6. Árvore de decisão

| Resposta da Telnyx | Ação |
|---|---|
| Brand corrigível no lugar | Corrigir `entityType`, verificar e-mail, reenviar ao TCR. |
| Não corrigível, taxas reaproveitáveis | Criar brand SP com OTP; reutilizar número/profile. |
| Não corrigível e taxas novas | Avaliar Toll-Free Verification (1–2 semanas, SSN) antes de pagar de novo. |
| TCR mantém recusa sem motivo claro | Escalar por escrito; não insistir com os mesmos dados. |

---

## 7. O que falta do owner

1. `CP575G.pdf` para anexar.
2. Data de nascimento do titular (SP).
3. Mobile US/CA para OTP (ou confirmação de que o número indicado é móvel).
4. Validação para executar o caminho SP depois da resposta da Telnyx.
