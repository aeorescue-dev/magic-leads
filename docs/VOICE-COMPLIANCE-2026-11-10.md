# Compliance de script de voz — TCPA/FCC + Telnyx AUP

Data: 2026-11-10. Análise técnica baseada nas regras citadas. **Não é
parecer jurídico.** Antes de alterar o script em produção, obter revisão de
advogado licenciado nos EUA.

## Veredito rápido

| Item | Situação |
|---|---|
| Script atual (v4) | **Não conforme** em 3 pontos federais + risco de consentimento |
| Script proposto (15–20 s) | **Não conforme**; pior que o atual em divulgação |
| Nomes de concorrentes | Não proibidos em si; risco de publicidade falsa/denúncia |
| STIR/SHAKEN | Sem impacto direto pelo conteúdo; risco indireto por reputação |
| Bloqueador principal | **Telnyx AUP proíbe voz pré-gravada/IA em chamadas não solicitadas** |

## 1. Identificação e divulgação — regra exata

### 47 CFR § 64.1200(b)

Toda mensagem de voz artificial ou pré-gravada deve:

1. **(b)(1) No início da mensagem**, declarar claramente a identidade da
   empresa/entidade responsável pela chamada. Se for uma empresa, usar o nome
   **registado na State Corporation Commission** (ou autoridade equivalente).
2. **(b)(2) Durante ou após a mensagem**, declarar claramente um **telefone de
   contacto** da empresa — diferente do número do discador — que permita pedir
   DNC em horário comercial.
3. **(b)(3)** Se for telemarketing (ou isenção residencial), oferecer um
   mecanismo **automático e interativo** de opt-out (voz e/ou tecla), com
   instruções breves, **nos 2 segundos seguintes à identificação do (b)(1)**.
   O opt-out deve registar o número na lista DNC e **terminar a chamada
   imediatamente**.
4. **(b)(4)** Em telemarketing, informar o nome do chamador individual, o nome
   da entidade em cujo nome a chamada é feita e um telefone/endereço.

### A frase exata "This is an automated message..." é obrigatória?

**Não existe uma frase literal exigida pelo TCPA.** O que a lei exige é a
**identidade no início**. Mas:

- A **Telnyx AUP** exige que a pessoa seja "clearly informed" de que interage
  com um sistema de IA **"no later than the start of the interaction"**, quando
  exigido por lei ou quando não for óbvio. O mesmo está no **AI Services
  Addendum**.
- Nova Iorque exige divulgações **no início da chamada** (até 30 s): nome do
  telemarketer/vendedor, opção de DNC, finalidade, bens/serviços e se a chamada
  está a ser gravada (GBL § 399-z(2); § 399-pp(6)(b)(1)).
- Alguns estados (ex.: Califórnia, AB 2905) exigem a palavra "prerecorded" no
  início. Não é o caso de NY/TX hoje, mas limita a portabilidade do script.

**Conclusão:** a identificação da empresa e a natureza automatizada devem estar
**no início**, não no fecho. Mover para o fim é risco alto de violação da AUP e
de leis estaduais.

### A abertura alternativa proposta cumpre?

> "Hi {{company}}, Magic Leads here with {{count}} new exclusive projects in
> {{city}}…"

**Não.** Falhas:
- Não divulga que é mensagem automatizada/IA no início (AUP Telnyx).
- "Magic Leads here" pode não ser o nome legal registado (b)(1).
- Não tem telefone de contacto (b(2)).
- Não tem opt-out nos 2 s seguintes à identificação (b(3)).
- "exclusive" é uma alegação que exige substanciação.

## 2. Nomes de concorrentes (Angi, HomeAdvisor, Thumbtack…)

### Telnyx AUP

Não há proibição específica de comparação com marcas. Mas a AUP proíbe:

- violação de leis de **trademark, copyright ou propriedade intelectual**;
- comportamento **"deceptive or fraudulent"**, **"defamatory"**, **"libelous"**
  ou **"harassing"**;
- chamadas não solicitadas que **"could reasonably be expected to or do in fact
  provoke complaints"**.

Portanto: citar uma marca em comparação **verdadeira** não é proibido pela AUP;
citar com afirmações falsas, difamatórias ou não substanciadas é.

### Lei de marcas / publicidade

- **Nominative fair use**: usar a marca do concorrente para o identificar é
  geralmente lícito se for verdadeiro, necessário, não sugerir patrocínio e não
  denegrir.
- **Lanham Act § 43(a)** (false advertising): afirmações como "they sell the same
  contact to five contractors" têm de ser **verdadeiras e substanciadas**.
  Caso contrário, exposição a ação do concorrente.
- **State UDAP / unfair competition**: mesmo risco ao nível estadual.
- **Dilution/tarnishment**: risco se o tom for depreciativo.

### STIR/SHAKEN

**Não há relação direta.** A atestação (A/B/C) refere-se ao direito do
originador de usar o número (relação com o cliente e o DID), não ao conteúdo da
mensagem. Citar "Angi" não muda a atestação.

O risco é **indireto**:
- analítica das operadoras (47 CFR 64.1200(k)(3)) e labeling "Spam Likely"
  olham para volume, padrão, taxa de complaints e reputação do número;
- taxas de complaint altas → enforcement da Telnyx (AUP) e degradação de
  entrega.

**Recomendação:** manter "shared lead apps" genérico. Se quiserem nomear
marcas, só com revisão jurídica e um dossier de substanciação de cada
afirmação.

## 3. Script proposto — viabilidade técnica e compliance

> "Hi {{company}}, Magic Leads here. We just unlocked {{count}} new direct
> homeowner projects in {{city}} before they hit shared lead platforms. No
> shared contacts, no bidding wars. Check the active details right now at
> magicleads.app, or press 2 to unsubscribe."

- **Duração:** ~48 palavras → **15–19 s** a 150–165 wpm. Tecnicamente viável.
- **Compliance:** falha em (b)(1) nome registado, (b)(2) telefone, (b)(3)
  opt-out nos 2 s, e na divulgação de automação no início.
- **Alegações:** "direct homeowner projects", "before they hit shared lead
  platforms" e "no shared contacts" exigem substanciação. Se os dados vierem de
  permits/public records e não de contacto direto do homeowner, "direct" pode
  ser enganoso.

### Versão conforme (curta, ~18–22 s)

> Hi {{company}}, this is an automated message from **Magic Leads LLC**. Press
> 2 at any time to stop. We've listed {{count}} active {{trade}} projects in
> {{city}} on magicleads.app — direct owner details, no shared contacts. Visit
> magicleads.app or call {{callback}}.

- Identidade + automação no início.
- Opt-out imediatamente após a identificação (≤2 s).
- Telefone de contacto no fim.
- ~45 palavras → ~17–20 s.
- Substituir "Magic Leads LLC" pelo nome legal registado e `{{callback}}` por
  um número que atenda pedidos de DNC em horário comercial.

### Versão conforme (25–28 s, com finalidade explícita)

> Hi {{company}}, this is an automated message from Magic Leads LLC about a
> paid lead service. Press 2 now or anytime to stop. We've listed {{count}}
> active {{trade}} projects in {{city}} at magicleads.app — direct owner
> details, no shared leads. Details at magicleads.app, or call {{callback}}.
> Again, press 2 to opt out.

## 4. Bloqueadores que nenhum script resolve

### 4.1 Consentimento (TCPA)

- Telemarketing com voz artificial/pré-gravada para **telemóvel** exige
  **prior express written consent** (47 CFR 64.1200(a)(2)); para **linha
  residencial**, idem (a)(3).
- **Não existe isenção B2B** para o §227(b)(1)(A)(iii). Um telemóvel de um
  empreiteiro é um número sem fio abrangido. A isenção B2B existe para DNC, não
  para voz artificial.
- Listas compradas/compiladas de licenças públicas **não** são consentimento.
- **5.º Circuito:** `Bradford v. Sovereign Pest Control` (fev/2026) decidiu que
  o TCPA exige apenas *prior express consent* (oral ou escrito), não escrito.
  Isso não legaliza chamadas frias — continua a exigir consentimento prévio. E
  não se aplica a NY (2.º Circuito), onde a regra da FCC (PEWC) prevalece.
- **Nova Iorque:** GBL § 399-z(6) exige **acordo escrito assinado** para
  mensagens pré-gravadas, com o número e assinatura do cliente. § 399-pp exige
  registo de telemarketer.
- **Texas:** Capítulos 301–305; § 305.001 proíbe chamadas de venda para
  telemóvel sem consentimento; SB 140 eleva penalidades (até $5.000/violação);
  registo e bond exigidos.

### 4.2 Telnyx AUP — o bloqueador mais directo

A AUP proíbe explicitamente:

> "use of call Services to deliver prerecorded, artificial or AI-generated
> voice **(i) in unsolicited calls**, (ii) in violation of any Laws, or (iii)
> in a manner that misleads any party to the call into believing they are
> speaking with a live human"

Chamadas frias para uma lista compilada são **não solicitadas**. Ainda que o
script fique perfeito, a operação continua exposta a suspensão pela Telnyx. A
AUP também diz que a Telnyx **não pré-aprova** casos de uso e que o cliente é
o único responsável.

### 4.3 Revogação por qualquer meio

47 CFR 64.1200(a)(10): o consumidor pode revogar por **qualquer meio
razoável** (incluindo verbal). O modo `static` só reconhece **DTMF 2**; não há
ASR. Um "stop" verbal não é capturado. É preciso ASR, transferência para humano
ou voicemail com triagem.

### 4.4 Início da mensagem em ≤2 s (abandoned call)

47 CFR 64.1200(a)(7)(ii): a mensagem pré-gravada deve começar **nos 2 segundos**
após a saudação. Nos dados de 09/11, o TTS foi criado **1,3–6,2 s** após
`answered_at` — antes de sintetizar e tocar. Há risco real de dead air >2 s.
Solução técnica: pré-sintetizar o áudio antes da chamada ser atendida.

### 4.5 DNC

O gate `can_call` exige check DNC fresco (31 dias, fail-closed), mas os dados
são **importados manualmente** (`import_dnc_csv` / `check_dnc`), não consultados
em tempo real. Confirmar que a fonte é o registo nacional oficial e que cobre
números sem fio.

### 4.6 Voicemail

Hoje o AMD deteta máquina e desliga — não deixa mensagem. Se um dia deixarem
mensagem em voicemail, é obrigatório um **número toll-free** que ligue ao
mecanismo de opt-out (64.1200(b)(3)).

## 5. Scorecard

| Elemento | v4 atual | Proposto | Versão conforme |
|---|---|---|---|
| Identidade no início | ✓ "Magic Leads" | ✓ "Magic Leads here" | ✓ nome legal |
| Nome legal registado | ? | ? | ✓ |
| Divulgação de automação no início | ✓ "automated message" | ✗ | ✓ |
| Telefone de contacto | ✗ | ✗ | ✓ |
| Opt-out ≤2 s após ID | ✗ (só no fim) | ✗ (só no fim) | ✓ |
| Opt-out DTMF funciona durante a mensagem | ✓ | ✓ | ✓ |
| Opt-out verbal | ✗ | ✗ | requer ASR |
| Finalidade explícita | parcial | parcial | ✓ |
| Alegações substanciadas | ? | ? (pior) | a validar |
| Base de consentimento | ✗ | ✗ | a resolver |

## 6. Recomendação

1. **Não deployar** o script proposto.
2. Resolver primeiro o modelo de consentimento: PEWC para telemóvel/residencial
   ou mudar para um modelo com agente humano ao vivo (o risco de voz
   pré-gravada desaparece; DNC/estado mantêm-se).
3. Se mantiver voz pré-gravada: usar a versão conforme, com nome legal,
   telefone e opt-out nos 2 s.
4. Pré-sintetizar o áudio antes do atendimento para cumprir os 2 s.
5. Adicionar captura de opt-out verbal (ASR) ou número humano.
6. Rever registo NY/TX, DNC oficial e substanciação das alegações.
7. Manter nomes de concorrentes fora do áudio até validação jurídica.

## Fontes

- 47 CFR § 64.1200(b), (a)(2), (a)(3), (a)(7), (a)(10) — eCFR/LII.
- FCC 24-84 (NPRM sobre IA, 2024) — sem regra final de divulgação de IA
  conhecida até out/2026; as regras de voz artificial já se aplicam.
- Telnyx Acceptable Use Policy v2.0 (cláusulas de voz pré-gravada/IA,
  chamadas não solicitadas e IP).
- Telnyx AI-Enabled Services Addendum (divulgação no início da interação).
- NY GBL § 399-z, § 399-pp.
- TX Bus. & Com. Code Cap. 301–305; SB 140.
- `Bradford v. Sovereign Pest Control of TX` (5.º Cir., 25/02/2026).
