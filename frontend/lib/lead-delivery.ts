/**
 * Veredito de entrega de um lead — fonte unica para o frontend.
 *
 * Estes predicados JA eram calculados no backend (`backend/services/lead_rules.py`)
 * e chegam no payload como flags. Aqui nao se reimplementa a regra: so se leem
 * as flags e se decide o que o utilizador ve.
 *
 * O predicado que decide o PRECO e `isFreeLead`, e nao `!corporate`. Um lead
 * incompleto (nome sem telefone e sem morada) nao e corporativo e mesmo assim
 * e entregue de graca. Inferir o preco a partir de `corporate` foi exatamente o
 * bug que mantinha leads gratuitos bloqueados quando a cota diaria estava
 * esgotada.
 *
 * Isolados num modulo proprio porque sao a decisao que faz o botao ficar
 * activo ou desactivado e o aviso aparecer ou nao -- e essa decisao precisa de
 * testes unitarios sem ter de montar o componente inteiro.
 */

/** Campos de custo/entrega que o backend pode enviar num lead. */
export interface LeadDeliveryFlags {
  /** true = o utilizador paga (credito + cota). Regra A: so com nome E telefone. */
  charged?: boolean;
  /** true = sucesso total de dados (owner_name + owner_phone). */
  complete_delivery?: boolean;
  /** true = entregue sem sucesso total: sem debito e sem consumir cota. */
  incomplete_delivery?: boolean;
  /** true = tem nome + morada, sem telefone. */
  corporate?: boolean;
  /** true = sem contacto E endereco que nunca resolve. */
  unresolvable?: boolean;
}

/**
 * O lead e entregue sem custo?
 *
 * `charged` e a autoridade. O fallback para `corporate` existe so para
 * payloads antigos (cache do service worker, sessoes em curso) e nao deve ser o
 * caminho normal: se `charged` faltar num payload novo, isso e um bug do
 * backend e vale a pena nao assumir silenciosamente "pago".
 */
export function isFreeLead(lead?: LeadDeliveryFlags | null): boolean {
  if (typeof lead?.charged === "boolean") return !lead.charged;
  return !!lead?.corporate;
}

/** O lead foi entregue sem sucesso total de dados? Nao bloqueia nada. */
export function isIncompleteLead(lead?: LeadDeliveryFlags | null): boolean {
  return !!lead?.incomplete_delivery;
}

/** Sem qualquer contacto E com um endereco que nunca vai resolver. */
export function isUnresolvableLead(lead?: LeadDeliveryFlags | null): boolean {
  return !!lead?.unresolvable;
}

/**
 * Deve aparecer o aviso discreto de "dados insuficientes"?
 *
 * Cobre os dois casos que o cliente tem de ser avisado: lead incompleto (falta
 * telefone) e beco sem saida (sem contacto e endereco irresolvivel). O aviso
 * e informativo -- NUNCA condiciona a acao: o lead e entregue na mesma.
 *
 * NOTA: isto ja nao e usado para pintar o cartao. Em producao 100% dos leads
 * caem em `incomplete_delivery` (so 1 dos 18.281 locais tem telefone), e um
 * aviso em todos os cartoes nao informa nada -- le-se como avaria. O cartao
 *_show_incomplete_badge_ mantem-se apenas para o caso raro e accionavel
 * (endereco que nunca resolve). O resto passou a um resumo agregado por lista.
 */
export function shouldShowIncompleteBadge(lead?: LeadDeliveryFlags | null): boolean {
  return isIncompleteLead(lead) || isUnresolvableLead(lead);
}

/**
 * Aviso por cartao: so o beco sem saida (endereco que nunca resolve).
 *
 * Raro (6,6% dos leads) e accionavel, portanto continua a merecer um aviso
 * no proprio cartao. O resto e agregado pela lista.
 */
export function shouldShowAddressWarning(lead?: LeadDeliveryFlags | null): boolean {
  return isUnresolvableLead(lead);
}

/**
 * Quantos leads da lista ficaram sem telefone, para o resumo agregado.
 *
 * O payload so expoe flags, nao `owner_phone`, por isso o unico sinal fiavel
 * de "tem telefone" e `complete_delivery` (que o backend define como nome +
 * telefone). Contar `incomplete_delivery` em vez disso dava um numero
 * diferente do que o texto promete: um lead corporativo tem nome mas nao tem
 * telefone e nao e `incomplete_delivery`, logo ficava de fora.
 */
export function countLeadsWithoutContact(leads?: LeadDeliveryFlags[] | null): number {
  if (!leads || leads.length === 0) return 0;
  return leads.reduce((acc, lead) => (lead && !lead.complete_delivery ? acc + 1 : acc), 0);
}

/**
 * O botao de reservar deve estar desactivado por falta de cota?
 *
 * So faz sentido para leads pagos. Um lead entregue de graca nunca e
 * bloqueado por a cota estar esgotada.
 */
export function isBlockedByQuota(
  lead: LeadDeliveryFlags | null | undefined,
  remaining: number | null | undefined
): boolean {
  if (remaining !== 0) return false;
  return !isFreeLead(lead);
}