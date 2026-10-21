# Prioridade B — Infraestrutura `@magicleads.app` + 3-5 caixas em warm-up

> Documento operacional. **Nenhum comando aqui altera a base de dados ou envia
> e-mails.** Tudo o que é executado tem de ser explicitamente autorizado.

---

## 1. Porquê o domínio próprio é o bloqueio nº1 do canal de email

Hoje o outbound envia de `magicleadsus@gmail.com`, uma caixa de webmail público
sem SPF/DKIM próprios. Isso é aceito pelo Gmail, mas:

- **Sem SPF/DKIM/DMARC próprios**, a reputação é a da conta, não do domínio.
  Um gmail.com novo que começa a enviar frio é sinalizado mais depressa.
- **From ≠ link.** O e-mail diz "Magic Leads" com `from: magicleadsus@gmail.com`
  e assina `https://www.magicleads.app/`. O Gmail penaliza a divergência entre
  a identidade do remetente e o domínio do link.
- **Conta de e-mail `@magicleads.app`** resolve os dois pontos de uma vez:
  identidade, SPF/DKIM/DMARC e reputação por domínio.

O que já está pronto para receber isto: o motor, o warm-up, os tetos, as quiet
hours, o dedup e o claim atómico. Falta **só** a identidade de envio.

---

## 2. Fase 1 — Google Workspace (a tua contratação de fim de semana)

### 2.1 Registo do domínio

1. [Google Workspace](https://workspace.google.com/business/) → "Start free trial".
2. Verificar a posse de `magicleads.app` (registar no DNS do domínio).
3. Escolher o plano (Business Starter chega; 1 utilizador + aliases).

### 2.2 Criar as caixas de envio

Depois de teres a Workspace activa, criar **uma caixa por "rota" de envio**:

| Caixa | Papel | Warm-up |
|---|---|---|
| `outbound1@magicleads.app` | Envio frio principal (roofs/general) | dia 0 → 25/dia |
| `outbound2@magicleads.app` | Envio frio (plumbing/electrical) | dia 0 → 25/dia |
| `outbound3@magicleads.app` | Envio frio (hvac/restoration) | dia 0 → 25/dia |
| `hello@magicleads.app` | Reply-to / contacto comercial (opcional) | — |
| `noreply@magicleads.app` | Transacional (Resend: recuperação de checkout) | — |

⚠️ **Cada caixa de envio é um "reputação" separado.** Começar com 1 e só
escalar quando a entrega estiver >90% e o spam report <0,1%.

### 2.3 Registos DNS (a parte que bloqueia tudo se falhar)

Aplicar em **todos os nameservers do domínio**:

**SPF** (num único registo TXT — nunca mais do que um, ou dá erro de DNS):

```
v=spf1 include:_spf.google.com ~all
```

> `~all` (soft fail) em vez de `-all` (hard fail): enquanto o envio frio está
> a aquecer, um hard fail quebras envios legítimos das outras ferramentas.

**DKIM** (Google Workspace gera o selector; o valor aparece em
Admin → Apps → Gmail → Autenticação):

```
Host: google._domainkey.magicleads.app
Type: TXT
Value: v=DKIM1; k=rsa; p=<valor do painel>
```

**DMARC** — começar em modo de observação (não rejeita nada, só reporta):

```
Host: _dmarc.magicleads.app
Type: TXT
Value: v=DMARC1; p=none; rua=mailto:dmarc@magicleads.app; fo=1; pct=100
```

DMARC exige SPF **e** DKIM alinhados com o domínio do From. Por isso o
`from_name`/`from` do Gmail tem de ser `@magicleads.app` (ver §4).

**Verificação do envio de alias (Google → Receiving/Route):** para que
`noreply@magicleads.app` possa ser o From, é preciso activar o "Enviar como"
alias na caixa base (ou criar `noreply@` como utilizador completo).

**Checklist de validação (fazer antes de ligar o motor):**

```bash
# SPF
dig +short TXT magicleads.app | grep spf

# DKIM
dig +short TXT google._domainkey.magicleads.app

# DMARC
dig +short TXT _dmarc.magicleads.app
```

E um envio de teste real para o Gmail — confirmar que **"Mostrar original"**
mostra `SPF: pass`, `DKIM: pass` e `DMARC: pass`.

### 2.4 Fazer o Resend usar o domínio próprio

O e-mail de recuperação de checkout (Prioridade A) sai pela Resend. Para usar
`noreply@magicleads.app`:

1. resend.com → Domains → Add Domain → `magicleads.app`.
2. Adicionar os registos DNS que a Resend indicar.
3. Definir `EMAIL_FROM="Magic Leads <noreply@magicleads.app>"` no Railway.

> ### ⚠️ ARMADILHA CRÍTICA: só pode existir **UM** registo SPF
>
> Se a Resend te pedir para criar um registo SPF **novo**, **NÃO o cries**.
> Dois registos SPF no mesmo nome = `permerror` = **todo o correio do domínio
> passa a ser rejeitado** (Google e Gmail inclusive). O SPF tem de ser **um
> único registo**, com a include da Resend **somada** à do Google:
>
> ```
> v=spf1 include:_spf.google.com include:<include-da-resend> ~all
> ```
>
> A Resend normalmente só exige **DKIM** (CNAME) quando o domínio já tem SPF —
> nesse caso basta acrescentar o CNAME de DKIM. Se ela insistir no SPF, usa a
> **opção mais segura: um subdomínio dedicado** (ex.: `send.magicleads.app`),
> que tem o seu próprio SPF e não colide com nada:
>
> ```
> # no subdomínio send.magicleads.app (isolado, sem conflito)
> send.   TXT   "v=spf1 include:<include-da-resend> ~all"
> ```
>
> E define `EMAIL_FROM="Magic Leads <noreply@send.magicleads.app>"`.
> **DKIM pode ter vários selectors** (Google + Resend em simultâneo) — só o
> SPF é exclusivo.


---

## 3. Fase 2 — Ligar as caixas ao motor

### 3.1 OAuth2 por caixa (o que já foi feito para `magicleadsus@gmail.com`)

Para **cada** caixa nova é preciso um par de credenciais Gmail:

1. Google Cloud Console → o mesmo projeto → **APIs & Services → Credentials**.
2. **Create Credentials → OAuth client ID → Web application**.
3. Authorize com a **nova** caixa (`outbound1@magicleads.app`).
4. Scopes mínimos: `https://www.googleapis.com/auth/gmail.send`
   (recomendado: `gmail.send` + `gmail.readonly` — ver §5).
5. Gerar refresh token → guardar em `client_id`, `client_secret`, `refresh_token`.

> **Nota de âmbito:** o scope actual é `gmail.send` (envio). Para ler respostas
> (necessário para a detecção automática de replies da sequência) é preciso
> `gmail.readonly` — ver §5.

### 3.2 Variáveis de ambiente (Railway)

Para cada caixa, 3 variáveis (ou um único `auth_ref` JSON, que o motor já
suporta — ver `backend/services/gmail.py:parse_auth_ref`):

```
GMAIL_CLIENT_ID_OUTBOUND1
GMAIL_CLIENT_SECRET_OUTBOUND1
GMAIL_REFRESH_TOKEN_OUTBOUND1
```

Alternativa (recomendada, porque o `sending_mailboxes.auth_ref` aceita JSON):
guardar as 3 credenciais no `auth_ref` da caixa, em Railway, como JSON — sem
expor nada em variáveis globais.

### 3.3 Registar a caixa na base

A tabela `sending_mailboxes` (schema em `backend/services/db.py:604-624`):

| Campo | Valor | Nota |
|---|---|---|
| `email` | `outbound1@magicleads.app` | |
| `provider` / `transport` | `gmail` / `gmail_api` | |
| `display_name` | `Magic Leads` | From visível |
| `city` | `''` (vazio) | = caixa global; se preenchido, só envia dessa cidade |
| `daily_cap` | `25` | teto por caixa; o rampa do warm-up aplica-se acima |
| `enabled` | `1` | |
| `warmup_state` | `cold` | o motor muda para `warming`/`warm` sozinho |
| `auth_ref` | JSON com as 3 credenciais | ver §3.2 |

**Registar pelo painel** (admin) é preferível a SQL directo, para o motor
aplicar as validações.

---

## 4. Fase 3 — Ligar o motor (aspetos técnicos)

### 4.1 `from` com o domínio próprio

O `gmail.py` monta o From a partir de `display_name` + `email` da caixa. Com
`email=outbound1@magicleads.app` o From sai correto — **não é preciso alterar
código**.

### 4.2 O `from` da caixa global actual

`magicleadsus@gmail.com` continua a funcionar. Para uma transição suave:
manter a caixa gmail.com ligada mas com `daily_cap` baixo, e ir transferring
o volume para as caixas `@magicleads.app` à medida que cada uma passa o warm-up.

### 4.3 Ordem recomendada de bring-up

1. Criar 1 caixa `@magicleads.app` + DNS + OAuth.
2. Registar a caixa com `daily_cap=1` (warm-up dia 0 = 1/dia).
3. Enviar 1-2 e-mails de teste reais e verificar SPF/DKIM/DMARC `pass`.
4. Verificar a entrega na caixa de destino (Spam?) e confirmar que o
   destinatário responde.
5. Só depois subir `daily_cap` e deixar o warm-up correr (14 dias até 25/dia).
6. Repetir para as caixas 2 e 3, em paralelo (cada uma tem o seu ramp).

---

## 5. Detecção automática de respostas (necessita de scope extra)

O passo 2 da sequência (`step2_offer`) **só deve ser enviado a quem não
respondeu**. Hoje isso é feito com o campo `outbound_contacts.replied_at`, que
é marcado **manualmente** (ou por um script).

Para automatizar: incluir `gmail.readonly` no scope e fazer polling de
`GET /gmail/v1/users/{email}/messages?q=from:{contact_email}` (ou
`threadId` por mensagem). Sem esse scope, **não** é possível ler respostas.

Trade-off: `gmail.readonly` é mais permissivo que `gmail.send` e pode
provocar recusas na revisão OAuth do Google (é um scope sensível). Alternativa
mais conservative: manter `gmail.send` e tratar a detecção de respostas como
manual, ou usar a caixa `hello@` como reply-to e acompanhar por lá.

---

## 6. Checklist de DNS (copiar/colar para o registo de domínio)

```
# 1. SPF (TXT, no apex)
v=spf1 include:_spf.google.com ~all

# 2. DKIM (TXT)
Host: google._domainkey.magicleads.app
Value: v=DKIM1; k=rsa; p=<valor do painel Workspace>

# 3. DMARC (TXT)
Host: _dmarc.magicleads.app
Value: v=DMARC1; p=none; rua=mailto:dmarc@magicleads.app; fo=1; pct=100

# 4. Resend (TXT) — a Resend dá o valor exacto no painel Domains
Host: resend._domainkey.magicleads.app
Value: p=<valor fornecido pela Resend>
```

> **SPF: UM registo só.** Se a Resend pedir um SPF novo, **NÃO o cries** —
> dois SPF no mesmo nome dão `permerror` e o correio do domínio inteiro
> (Google incluído) deixa de ser aceito. Ou se faz `include:` da Resend no
> SPF que já existe, ou se usa um subdomínio dedicado (`send.`) com SPF
> próprio. Ver §2.4.

### Registos MX

A activação do Google Workspace **normalmente exige** apontar os MX para o
Google (`smtp.google.com` / `aspmx.l.google.com`, etc.). Isso **é seguro**
para o outbound: o motor envia pela **Gmail API** (HTTPS), não por MX — o MX
só governa quem *recebe* correio no domínio.

> Antes de mudar os MX, confirma onde estão hoje. Se `magicleads.app` já tem
> MX de outro serviço (parcelling, forwarding, um mail provider antigo) e
> **recebes** correio importante lá, guarda os registos actuales antes de
> substituir.

