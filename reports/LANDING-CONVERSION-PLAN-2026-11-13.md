# Landing page — plano de conversão para empreiteiros de alto padrão

Data: 2026-11-13
Estado: proposta estratégica (sem alterações de código nesta fase)
Público: empreiteiros licenciados nos EUA (NYC, Chicago, Boston, Dallas)

## Regra de ouro de copy

Nenhum termo de fonte/arquitetura pode aparecer na landing (311, HPD, DOB, Socrata,
dataset, BBL/BIN, scraper, API). O valor comunica-se por **resultado**, não por fonte:

- “chamados municipais abertos”, “avisos de conservação”, “risco de multa”;
- “contacto do proprietário”, “revelações diárias” (nunca “créditos”);
- “passe semanal de $120” (nunca “saldo” ou “pacote de créditos”).

## 1. Proposta de valor central (hero)

**Promessa:** “Veja a obra antes da multa — e fale com o dono antes de qualquer
concorrente.”

Variações para teste A/B:

| PT | EN | ES |
|---|---|---|
| A obra antes da multa. | The job before the fine. | El trabajo antes de la multa. |
| 1 obra, 1 empreiteiro, 1 hora. | One job. One contractor. One hour. | Una obra. Un contratista. Una hora. |
| O chamado chega antes do concorrente. | The request reaches you first. | La solicitud te llega primero. |

**CTA primário:** “Ver obras na minha cidade” (abre o seletor de cidade/ZIP).
**CTA secundário:** “Ver uma oportunidade real” (sample card animado).

## 2. Blocos que faltam na landing (por prioridade)

### P0 — Exclusividade de 1 hora
- Bloco visual com relógio/contador: “Quando reserva, o endereço fica só seu por 1 hora.
  Sem leilão. Sem 5 orçamentos. Sem disputa de preço.”
- Prova: “1 obra = 1 empreiteiro” + mini-timeline `Reservar → Contactar → Negociar`.
- Microcopy de risco: “Se não agir em 1 hora, a obra volta ao pool.”
- CTA: “Quero exclusividade”.

### P0 — Prevenção proativa (antes da multa)
- Título: “A multa não é surpresa. O aviso também não devia ser.”
- Explicar em 3 passos: sinal aberto → janela de vistoria → risco de multa.
- Cartão de exemplo com severidade, prazo e “Ainda sem multa”.
- **Não nomear agências**; usar “chamados municipais” / “avisos de conservação”.
- CTA: “Ver preventivos na minha cidade”.

### P0 — Revelações diárias (modelo de passe)
- “10 contactos de proprietário por dia. $120 por semana. Sem comissão.”
- Mostrar `usadas / limite` de forma simples (“0/10 hoje”).
- Reforçar: “Obras sem telefone entram como bónus e não gastam revelações.”
- CTA: “Começar esta semana”.

### P1 — Prova social e casos reais
- 3 cartões “antes → depois”: oportunidade reservada, contacto feito, obra fechada.
- Números honestos por cidade (obras ativas, donos identificados, ZIPs cobertos).
- Depoimentos curtos com ofício + cidade (sem promessas de rendimento).
- Selo “dados verificados” com a taxa real de telefone (80–85%, já usada no produto).

### P1 — Calculadora de custo de oportunidade
- “Quantas obras precisa fechar por mês?” → mostra quantas reservas/semana cobrem o passe.
- Inputs: ticket médio, taxa de fecho. Output: “o passe paga-se com X obra(s)”.
- Já existe base (`landing.calc*`); transformar num bloco com CTA.

### P1 — Objeções
- “E se não houver telefone?” → morada completa + proprietário + carta/visita.
- “É lead compartilhado?” → não; reserva exclusiva.
- “Preciso de marketing?” → não; mensagem pronta para WhatsApp/SMS/email.
- “Posso cancelar?” → passe semanal, sem fidelidade.

### P2 — Confiança e conformidade
- Privacidade/termos em destaque, Stripe, headers de segurança.
- Explicar consentimento na revelação (“autoriza verificar os dados do lead”).
- Nota de transparência: “não vendemos créditos; vendemos acesso semanal”.

## 3. Estrutura recomendada da página

1. Hero com promessa + CTA + sample card (com dono mascarado).
2. Barra de confiança (cidades/BACEN? não — “4 cidades”, “X obras ativas”, “dono identificado”).
3. **Exclusividade 1h** (novo).
4. **Prevenção antes da multa** (novo).
5. Como funciona em 3 passos.
6. **Revelações diárias / passe** (novo, substitui qualquer menção a créditos).
7. Casos/prova social.
8. Calculadora de ROI.
9. Objeções/FAQ.
10. CTA final com seletor de cidade + garantia de cancelamento.

## 4. Experiências de conversão

- **Seletor cidade/ZIP no hero** (não só no CTA final): reduz atrito e qualifica.
- **Sample card interativo**: mostra severidade, prazo e “dono protegido”; clique abre
  modal de consentimento em modo demo.
- **Sticky CTA** no mobile após 40% de scroll.
- **Contador de escassez honesto**: “X preventivos com prazo ≤ 7 dias nesta cidade”
  (dados reais; nunca inventar).
- **Exit intent** apenas desktop, com oferta de amostra (não pop-up agressivo).
- **Prova de velocidade**: “pedido → reserva em menos de 60 segundos”.

## 5. SEO e aquisição

- Páginas locais: `/{locale}/obras/{city}` e `/{locale}/preventivos/{city}` com H1 próprio.
- Páginas por ofício: `/{locale}/obras/{city}/{trade}` (16 ofícios).
- Schema.org `Service` + `FAQPage`; meta titles com “obras exclusivas em {city}”.
- Conteúdo: “como evitar multa de conservação” (sem citar agência), “quanto custa um
  contacto de proprietário”, “o que fazer quando o chamado não tem telefone”.
- Performance: manter LCP < 2,5 s (a landing atual já é estática; vigiar imagens do hero).

## 6. Testes A/B sugeridos (30 dias)

| Teste | Variante A | Variante B | Métrica |
|---|---|---|---|
| Headline | “A obra antes da multa” | “1 obra, 1 empreiteiro, 1 hora” | signup rate |
| CTA | “Ver obras na minha cidade” | “Reservar minha primeira obra” | clique → signup |
| Sample card | estático | interativo (modal demo) | tempo na página / signup |
| Preço | “$120/semana” | “$17/dia” | checkout iniciado |
| Prova | números de cidade | depoimentos | conversão final |

## 7. O que NÃO fazer

- Não usar “HPD/DOB/311” nem nomes de datasets na copy.
- Não prometer “leads ilimitados” (o limite diário é parte do valor).
- Não vender “créditos” nem “saldo”.
- Não usar escassez falsa; os números devem vir da base real.
- Não esconder a taxa de assertividade do telefone (80–85%); transparência vende.

## 8. Impacto esperado

Com exclusividade + prevenção + passe semanal no topo, a landing passa a responder às
três perguntas do empreiteiro de alto padrão: **“a obra é minha?”**, **“chego antes da
multa?”** e **“quanto custa por semana?”**. São exatamente os diferenciais que o produto
já entrega no staging.
