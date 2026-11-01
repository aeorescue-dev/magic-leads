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

**Não há variantes de copy implementadas.** O sistema tem um template por
nicho (passo 1) e um template de oferta (passo 2). O teste 1:1 em curso é de
**origem do e-mail**, não de texto.

Variantes propostas para aprovação (a implementar com rotação 50/50 e
atribuição no lote):

| Braço | Assunto | CTA | Hipótese |
|---|---|---|---|
| A (controlo) | `50 GC projects open in NYC` | `Reply with "send"` | número + verbo direto |
| B | `50 GC projects open in NYC this week` | `Reply "send"` | urgência explícita, CTA mais curta |
| C | `50 GC projects open in NYC - one per contractor` | `Reply with "send"` | escassez no assunto |

Só se declara vencedor com ≥300 envios por braço; com 4–6/dia isso são meses,
por isso a decisão é entre (a) esperar, ou (b) subir a rampa/volume primeiro.

## 7. Conformidade (verificada)

| Regra | Estado |
|---|---|
| Inglês US, ASCII | ✅ |
| Sem morada do lead / 311 / violation / report / case | ✅ |
| Sem termos de fonte/arquitetura | ✅ |
| Um URL, sem tracking | ✅ |
| Assunto ≤38 (passo 1), ≤52 (passo 2) | ✅ |
| Morada postal + opt-out assinado + List-Unsubscribe | ✅ |
| Alegações verificáveis (contagem, exclusividade) | ✅ |
