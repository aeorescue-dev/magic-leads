# Variações de script — avaliação e versões conformes

Data: 2026-11-10. **Não é parecer jurídico.** As versões abaixo corrigem os
requisitos de identificação/opt-out do TCPA e da Telnyx AUP, mas **não**
resolvem o bloqueador de consentimento/AUP descrito no fim.

## 0. Alerta crítico: idioma

As quatro opções estão em **português**. A campanha 14 é em **Nova York**,
com áudio `en-US` e leads americanos (empresas como "SIRIN PAINTING AND
RENOVATIONS CORP"). Correr estes textos como estão produz:

- áudio em português para quem fala inglês; ou
- pronúncia inglesa de palavras portuguesas, se forçado em `en-US`.

**As versões de produção têm de ser em inglês.** Abaixo seguem as versões EN
finais + a tradução PT apenas para aprovação comercial.

## 1. Diagnóstico por opção

| Opção | Essência comercial | Problemas legais/claims |
|---|---|---|
| 01 | "Empresas como a sua faturam o ano inteiro; temos {{count}}; pare de competir com 5–8 concorrentes" | Garantia de faturação; "5 a 8 concorrentes" sem substanciação; opt-out só no fim; sem identificação legal; sem telefone |
| 02 | "{{count}} oportunidades para faturar hoje; contacto + endereço + descrição; fale com quem assina o cheque e faz Zelle" | "Faturar ainda hoje" é garantia; "quem está precisando" implica procura ativa; "Zelle" é confuso e irrelevante; sem opt-out; sem identificação |
| 03 | "{{count}} oportunidades agora; pare de gastar em ferramentas caras que não funcionam" | Difamação genérica de concorrentes; sem opt-out; sem identificação; sem telefone |
| 04 | "Quer vender de verdade? Temos {{count}}; contacto + endereço + descrição; fale com quem assina o cheque" | "Vender de verdade" implica que os outros são falsos; sem opt-out; sem identificação |

## 2. Prefixo obrigatório (todas as opções)

```
Hi {{company}}, this is an automated message from Magic Leads LLC.
Press 2 at any time to stop.
```

- Identidade legal + natureza automatizada no início.
- Opt-out imediatamente após a identificação (≤2 s).
- `Magic Leads LLC` deve ser substituído pelo **nome legal registado**.
- `{{callback}}` deve ser um número que atenda pedidos de DNC em horário
  comercial (não o DID do discador).

## 3. Versões finais em inglês (produção)

### Opção 01 — "pare de pagar plataformas compartilhadas"

```
Hi {{company}}, this is an automated message from Magic Leads LLC. Press 2 at any time to stop. We list {{count}} active projects for contractors in your trade in New York — property address and job details. Visit magicleads.app, or call {{callback}}. Stop paying shared platforms that resell the same contact. Again, press 2 to opt out.
```

- ~55 palavras → **~20 s**.
- Removido: garantia de faturação, "5 a 8 concorrentes".
- Mantido: dor de concorrência em plataformas compartilhadas.

### Opção 02 — "contacto + endereço + descrição"

```
Hi {{company}}, this is an automated message from Magic Leads LLC. Press 2 at any time to stop. We have {{count}} active projects in New York for your trade — the property address, the job description, and the owner's name in one place. Visit magicleads.app, or call {{callback}}. Again, press 2 to opt out.
```

- ~52 palavras → **~19 s**.
- Removido: "faturar ainda hoje", "Zelle", "quem está precisando".
- Mantido: entrega de contacto/endereço/descrição num só lugar.

### Opção 03 — "não dependa de ferramentas caras"

```
Hi {{company}}, this is an automated message from Magic Leads LLC. Press 2 at any time to stop. We have {{count}} active projects in your trade in New York right now. Visit magicleads.app for the address and job details, or call {{callback}}. See the projects before you pay for another lead. Again, press 2 to opt out.
```

- ~52 palavras → **~19 s**.
- Removido: "ferramentas caras que não funcionam" (difamação).
- Mantido: alternativa antes de pagar por outro lead.

### Opção 04 — "vender a sério"

```
Hi {{company}}, this is an automated message from Magic Leads LLC. Press 2 at any time to stop. We have {{count}} active projects in New York for your trade right now — owner name, address, and job description in one place. Visit magicleads.app, or call {{callback}}. Again, press 2 to opt out.
```

- ~48 palavras → **~18 s**.
- Removido: "vender de verdade" (implica que os outros são falsos).
- Mantido: foco em projetos ativos + dados completos.

## 4. Traduções PT para aprovação (não usar em produção)

**01:** "Olá {{empresa}}, esta é uma mensagem automatizada da Magic Leads LLC.
Pressione 2 a qualquer momento para parar. Temos {{count}} projetos ativos
para empreiteiros do seu nicho em Nova York — endereço do imóvel e detalhes do
serviço. Acesse magicleads.app ou ligue para {{callback}}. Pare de pagar
plataformas compartilhadas que revendem o mesmo contato. Novamente, pressione
2 para sair."

**02:** "Olá {{empresa}}, esta é uma mensagem automatizada da Magic Leads LLC.
Pressione 2 a qualquer momento para parar. Temos {{count}} projetos ativos em
Nova York para o seu nicho — o endereço do imóvel, a descrição do serviço e o
nome do proprietário num só lugar. Acesse magicleads.app ou ligue para
{{callback}}. Novamente, pressione 2 para sair."

**03:** "Olá {{empresa}}, esta é uma mensagem automatizada da Magic Leads LLC.
Pressione 2 a qualquer momento para parar. Temos {{count}} projetos ativos no
seu nicho em Nova York agora. Acesse magicleads.app para o endereço e detalhes
do serviço, ou ligue para {{callback}}. Veja os projetos antes de pagar por
outro lead. Novamente, pressione 2 para sair."

**04:** "Olá {{empresa}}, esta é uma mensagem automatizada da Magic Leads LLC.
Pressione 2 a qualquer momento para parar. Temos {{count}} projetos ativos em
Nova York para o seu nicho agora — nome do proprietário, endereço e descrição
do serviço num só lugar. Acesse magicleads.app ou ligue para {{callback}}.
Novamente, pressione 2 para sair."

## 5. Claims que continuam a exigir prova

- "active projects" / "oportunidades": confirmar que a contagem `{{count}}` é
  exata e atual.
- "owner name" / "nome do proprietário": confirmar que o dado existe e é
  verificável.
- "property address" / "endereço": confirmar que é o endereço do projeto.
- "Stop paying shared platforms that resell the same contact": afirmação
  comparativa genérica; ter evidência ou suavizar.
- "call {{callback}}": o número tem de atender e aceitar DNC.

## 6. O que ainda impede "100% conforme"

Estas versões cumprem a **forma do script** (identidade, automação, opt-out
≤2 s, telefone, finalidade). Não tornam a campanha 100% conforme porque:

1. **Consentimento TCPA:** voz artificial para telemóvel/residencial em
   telemarketing exige prior express written consent (64.1200(a)(2)/(a)(3)).
   Listas de licenças públicas não são consentimento.
2. **Telnyx AUP:** proíbe voz pré-gravada/IA em **chamadas não solicitadas**.
   Enquanto forem cold calls, o risco de suspensão permanece.
3. **Nova Iorque:** GBL § 399-z(6) exige acordo escrito assinado para
   pré-gravadas; § 399-pp exige registo de telemarketer.
4. **Opt-out verbal:** o modo `static` só reconhece DTMF 2; "stop" falado não
   é capturado (64.1200(a)(10)).
5. **Início em ≤2 s:** pré-sintetizar o áudio (plano em
   `docs/VOICE-TTS-CACHE-PLAN.md`).

**Recomendação:** escolher a opção comercial, validar as claims e só depois
avançar para revisão jurídica e alteração do template. Não deployar sem essa
validação.
