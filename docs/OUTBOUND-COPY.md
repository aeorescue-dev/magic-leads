# Outbound — copy em produção (2026-11-01)

Documento de revisão do pitch. Renderizado a partir de
`backend/services/outbound_templates.py`. Nenhuma variante A/B de **copy**
está ativa hoje (ver secção 6); a alternância 1:1 atual é por **origem do
e-mail** (`owner_osint` vs `smtp_pattern`), não por texto.

## 1. Política de copy

- Inglês americano, ASCII, sem acentos nem travessões tipográficos.
- Nunca revela fonte/arquitetura (permit, 311, DOB, dataset, API, scraping).
- Nunca inclui morada do lead, número de porta, "complaint", "violation",
  "report" ou "case".
- Exclusividade honesta: "one contractor at a time - first come, first served".
- Rodapé obrigatório: assinatura da caixa, morada postal, link de opt-out
  assinado (HMAC) e instrução de resposta.
- Um único URL no corpo; sem preço no assunto; assunto do passo 1 ≤ 38
  caracteres.

## 2. Passo 1 — amostra

**Assunto:** `{count} {trade} projects open in {city_short}`
(fallback: `... projects in {city_short}`; último recurso sem ofício).

**Corpo:**

```
{greeting}

{count} active {hook_trade} projects are open in {city} this week{composition}.

Each project is offered to one contractor at a time - first come, first
served - with the property details and the exact service needed.

Reply with "send" and I will forward this week's verified list.

{signature}
Magic Leads
110-33 64th Rd, Forest Hills, NY 11375, USA

https://www.magicleads.app/

Unsubscribe: {unsubscribe_url}
To stop receiving these emails, reply "unsubscribe".
```

- `{composition}` = " - including X and Y." derivado do inventário real
  (só serviços do próprio nicho; exige ≥40% do total).
- `{greeting}` = `Hi {Company} team,` (empresa em Title Case) ou
  `Hi {Nome},` quando há contacto nominal; `Hi there,` como último recurso.

## 3. Passo 2 — oferta

**Assunto:** `{count} {trade} {noun} in {city_short} - one contractor per job`
(fallback `- one each` quando passa de 52 caracteres).

**Corpo:**

```
{greeting}

Following up on my last note with the commercial part.

Magic Leads gives you {count} verified {category} {noun} in {city} this week,
each offered to one contractor at a time, with the property details and the
exact service needed.

It is $120 for 7 days. No commitment, cancel anytime. One closed job covers
the entire week.

View this week's list here:
{url}

{signature}
Magic Leads
110-33 64th Rd, Forest Hills, NY 11375, USA

https://www.magicleads.app/

Unsubscribe: {unsubscribe_url}
To stop receiving these emails, reply "unsubscribe".
```

## 4. Variáveis por nicho

| Nicho | Assunto (trade) | Hook | Audiência | Serviços usados na composição |
|---|---|---|---|---|
| general_contractors | GC | construction | general contractors | structural repairs, roof replacements, interior painting, window and door replacements |
| roofing | roofing | roofing | roofing companies | structural repairs, roof replacements |
| remodeling | remodeling | remodeling | remodeling companies | interior painting, structural repairs, window and door replacements |
| plumbing | plumbing | plumbing | plumbing companies | burst pipes and sewer backups, lead abatement |
| electrical | electrical | electrical | electrical contractors | panel upgrades, elevator repairs, gas line work |
| hvac | HVAC | heating and HVAC | HVAC companies | no-heat emergencies, gas line work |
| restoration | restoration | restoration | restoration companies | mold remediation, unsanitary conditions, rodent cleanup, debris removal |
| landscaping | landscaping | groundskeeping | landscaping and groundskeeping companies | groundskeeping |

## 5. Exemplos reais renderizados

**NYC · General Contractors (18.013 oportunidades reais; 50 divulgadas)**

```
Subject: 50 GC projects open in NYC

Hi Kelso-Burnett Co. team,

50 active construction projects are open in New York City this week - including
structural repairs and window and door replacements.

Each project is offered to one contractor at a time - first come, first
served - with the property details and the exact service needed.

Reply with "send" and I will forward this week's verified list.
```

**Chicago · Plumbing (2.817 reais)**

```
Subject: 50 plumbing projects open in Chicago

Hi Hogan Plumbing, Inc. team,

50 active plumbing projects are open in Chicago this week - including burst
pipes and sewer backups.
```

**Dallas · Roofing (7.570 reais)**

```
Subject: 50 roofing projects open in Dallas

Hi 123 Remodeling and Roofing LLC team,

50 active roofing projects are open in Dallas this week - including structural
repairs.
```

**Boston · Restoration (1.203 reais)**

```
Subject: 50 restoration projects open in Boston

Hi Corona Craft Restoration team,

50 active restoration projects are open in Boston this week - including rodent
cleanup and unsanitary conditions.
```

**Passo 2 (NYC, exemplo)**

```
Subject: 50 GC projects in NYC - one contractor per job

Following up on my last note with the commercial part.

Magic Leads gives you 50 verified GC projects in New York City this week, each
offered to one contractor at a time, with the property details and the exact
service needed.

It is $120 for 7 days. No commitment, cancel anytime. One closed job covers
the entire week.
```

## 6. A/B de copy — estado

Existem **dois testes em paralelo**, em dimensões diferentes:

| Dimensão | Braços | Onde é atribuído | Estado |
|---|---|---|---|
| Origem do e-mail | `owner_osint` vs `smtp_pattern` | `outbound_contacts.email_source` | ativo desde a Fase 12 (1:1 na fila) |
| Texto do passo 1 | `control`, `five_crews`, `owner_asked`, `limited_spots` | `outbound_messages.copy_variant` | **implementado, com gate de volume** |

### Gate de volume

- Enquanto o dia de Nova Iorque tiver **menos de 20 envios**, todas as mensagens
  saem em `control` — não se gasta amostra pequena a dividir por quatro textos.
- A partir de 20 envios/dia, a rotação é **1:1:1:1** por lote: `control` →
  `five_crews` → `owner_asked` → `limited_spots`.
- O gate é configurável: `OUTBOUND_COPY_VARIANT_MIN_SENDS` (default 20) e
  `OUTBOUND_COPY_VARIANTS_ENABLED` (default `true`; `false` força `control`).
- A variante fica gravada no envio e aparece no cartão de métricas do Admin
  (`A/B de texto: ativo` ou `inativo · N/20 envios hoje`).

### Braço `control` (copy atual)

Assunto `50 GC projects open in NYC`; CTA `Reply with "send" and I will
forward this week's verified list.`

### Braço `five_crews` — concorrência e margem

Assunto: `The same job, five crews` (24 caracteres)

```
The same job is sold to three, five, even eight contractors, and the fastest
bid wins instead of the best builder.

We do the opposite: 50 construction projects in New York City this week, each
offered to one contractor only. No auction, no bidding war, no race to the
bottom. $120 a week, cancel anytime.

See this week's list:
https://www.magicleads.app/en?city=NYC&niche=general_contractors&step=1
```

### Braço `owner_asked` — velocidade e contacto direto

Assunto: `The owner just asked for the repair` (35 caracteres)

```
Every project arrives ready to work: the property address, the owner's name
and the phone number when we find it. No forms, no sales call, no middleman.

50 construction projects in New York City this week. Open the list, pick the
ones you want and call the owner today. $120 a week.

Open this week's list:
https://www.magicleads.app/en?city=NYC&niche=general_contractors&step=1
```

### Braço `limited_spots` — escassez por área

Assunto: `Limited spots in your area` (26 caracteres)

```
We keep the number of contractors per area limited on purpose, so projects do
not get saturated and each address belongs to one contractor at a time.

50 construction projects in New York City this week for $120. It unlocks 7
days and pauses on day 8 if you do not renew.

See if your area still has a spot:
https://www.magicleads.app/en?city=NYC&niche=general_contractors&step=1
```

Todas usam o mesmo rodapé do `control` (assinatura da caixa, morada postal,
`Unsubscribe:` assinado e `reply "unsubscribe"`).

### Duas frases que mudaram face à proposta inicial

1. `owner_asked` diz **“the phone number when we find it”** — a landing só
   promete telefone quando existe; prometer sempre seria falso no primeiro
   lead sem número.
2. `limited_spots` diz **“each address belongs to one contractor at a time”** —
   a exclusividade real é a reserva de 1 hora, não a venda única permanente.
   “Once taken, it is gone” só pode ir ao ar se aplicarmos a invariante de
   venda única.

### Amostra necessária

Só se declara vencedor com **≥300 envios por braço**. Com 4 braços e 20/dia
são ~60 dias; a 75/dia são ~16 dias. Até lá, o cartão mostra contagem e taxa,
nunca “vencedor”.

## 7. Conformidade (verificada)

| Regra | Estado |
|---|---|
| Inglês US, ASCII | OK |
| Sem morada do lead / 311 / violation / report / case | OK |
| Sem termos de fonte/arquitetura | OK |
| Um URL de marketing, sem tracking | OK |
| Assunto ≤38 (passo 1), ≤52 (passo 2) | OK |
| Morada postal + opt-out assinado + List-Unsubscribe | OK |
| Alegações verificáveis (contagem, exclusividade) | OK |
| Preço só no corpo (nunca no assunto) | OK |
