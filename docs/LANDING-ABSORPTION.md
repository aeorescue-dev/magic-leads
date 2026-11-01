# Landing → Outbound: absorção da vitrine (2026-11-01)

Leitura completa de `frontend/app/[locale]/(marketing)/page.tsx`,
`frontend/lib/i18n.tsx` (EN/PT/ES) e da página em produção
`https://www.magicleads.app/en`.

## Proposta de valor (como a landing vende)

> "The owner just asked for the repair. **You are the only one with the phone.**"
> Sem leilão. Sem concorrente no mesmo endereço. $120/semana.

- **Mecânica da exclusividade:** reserva de **1 hora** por endereço; "no other
  pro on the same contact at the same time".
- **Promessa de contacto:** nome + endereço verificados; **telefone só quando
  encontrado**; "credit is only spent when there is a phone".
- **Risco reverso:** $120/semana, pausa no dia 8, sem fidelidade, sem multa,
  sem comissão; "the risk is $120, not $2,000 in ads".
- **Prova:** 106.782 leads, 80.142 com dono, 4 cidades; testemunhos com "2 jobs
  in week one", "full calendar", "no ad spend".
- **Comparativo:** $1,60 por lead exclusivo vs $15–60 por lead partilhado
  (3 a 8 empresas); "100% yours"; "guaranteed or free".
- **Escassez:** "limited spots per area so it does not saturate".

## Estrutura e fluxo de conversão

1. Hero (headline + preço + trust bar) → CTA "I want to enter the panel".
2. Cobertura (telefone verificado / institucional / crédito protegido).
3. Problema (ads, leads partilhados, referrals) → "see how".
4. 16 ofícios + 3 caminhos (multa, obra aprovada, pedido aberto).
5. Painel de amostra (reserva 1 h, endereço mascarado, telefone após reserva).
6. Comparativo de canais (Meta, LSA, HomeAdvisor, Magic Leads).
7. Como funciona (job filtrado → prioridade 1 h → mensagem pronta).
8. 48 mensagens prontas (16 trades × 3 canais).
9. Calculadora (1 job/mês paga o ano; ~$2,29 por contacto).
10. Testemunhos → preço → FAQ → CTA final → sticky mobile → modal.

Todos os CTAs apontam para **entrar no painel / começar por $120** — o site é o
canal de conversão, não a resposta ao e-mail.

## Divergências entre a landing e os e-mails atuais

| Landing | E-mail atual | Ação |
|---|---|---|
| CTA = entrar no painel e ligar ao dono | CTA = "reply send" | **Mudar o CTA para o link da landing** |
| Telefone "when found"; crédito protegido | "property details" genérico | Dizer "phone when we find it" |
| Exclusividade = 1 hora por endereço | "one contractor at a time" | Alinhado; manter |
| Nomeia Angi/HomeAdvisor | Não nomeia | Manter sem nomes no e-mail (entregabilidade) |
| "Guaranteed or free" / crédito protegido | ausente | Acrescentar a prova de risco |

## Problemas vistos na página em produção (corrigidos na Fase 17)

1. ~~**Painel de amostra em português na versão EN**~~ (“URGENTE”, “Telhado &
   Cobertura”, “Infiltração grave…”). Eram dados hardcoded em PT no
   `page.tsx`. Agora vêm de `landing.sampleLeads` + `landing.badge.*` em EN/PT/ES.
2. ~~**Hero mostra “0 jobs in the bank right now”**~~ no primeiro render (o
   componente arrancava com `EMPTY_PUBLIC_METRICS`). Agora o estado começa a
   `null`: “—” e `landing.heroLoading` até a API responder.
3. Respostas do FAQ só aparecem ao clicar (comportamento normal, mas o texto
   inicial fica vazio no HTML).

## Emails propostos (alinhados à landing)

Ver `docs/OUTBOUND-COPY.md` para o histórico; as três opções usam o vocabulário
da landing (owner just asked / only one with the phone / phone when found /
$120 a week / limited spots per area / pauses on day 8).
