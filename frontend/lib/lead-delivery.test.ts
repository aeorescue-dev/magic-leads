import { describe, expect, it } from "vitest";

import {
  isBlockedByQuota,
  isFreeLead,
  isIncompleteLead,
  isUnresolvableLead,
  shouldShowIncompleteBadge,
  shouldShowAddressWarning,
  countLeadsWithoutContact,
  type LeadDeliveryFlags,
} from "./lead-delivery";

/**
 * Estes testes cobrem a decisao que o utilizador VE: se o botao esta activo,
 * quanto custa, e se aparece o aviso. Era esta camada -- e nao o backend -- que
 * mantinha leads gratuitos bloqueados quando a cota estava esgotada, e nao tinha
 * um unico teste.
 */

/** Payload tal como o backend o envia (backend/services/lead_rules.py). */
const PAYLOADS = {
  completo: {
    charged: true,
    complete_delivery: true,
    incomplete_delivery: false,
    corporate: false,
    unresolvable: false,
  },
  corporativo: {
    charged: false,
    complete_delivery: false,
    incomplete_delivery: false,
    corporate: true,
    unresolvable: false,
  },
  incompleto: {
    charged: false,
    complete_delivery: false,
    incomplete_delivery: true,
    corporate: false,
    unresolvable: false,
  },
  becoSemSaida: {
    charged: false,
    complete_delivery: false,
    incomplete_delivery: true,
    corporate: false,
    unresolvable: true,
  },
} satisfies Record<string, LeadDeliveryFlags>;

describe("isFreeLead", () => {
  it("trata corporate como de graca", () => {
    expect(isFreeLead(PAYLOADS.corporativo)).toBe(true);
  });

  it("trata incompleto como de graca -- NAO como pago", () => {
    // A regressao central: um lead incompleto nao e `corporate`, por isso
    // inferir o preco de `corporate` dava "pago" e bloqueava a reserva.
    // Ambos os perfis sem telefone sao de graca, e nao apenas o corporativo.
    expect(isFreeLead(PAYLOADS.incompleto)).toBe(true);
    expect(isFreeLead(PAYLOADS.incompleto)).toBe(isFreeLead(PAYLOADS.corporativo));
    // ...e o que distingue "de graca" de "pago" e `charged`, nao `corporate`.
    expect(isFreeLead(PAYLOADS.incompleto)).not.toBe(isFreeLead(PAYLOADS.completo));
  });

  it("trata beco sem saida como de graca", () => {
    expect(isFreeLead(PAYLOADS.becoSemSaida)).toBe(true);
  });

  it("cobra so em sucesso total", () => {
    expect(isFreeLead(PAYLOADS.completo)).toBe(false);
  });

  it("usa `charged` como autoridade mesmo quando corporate vem discordante", () => {
    // Payload inconsistente: o backend diz charged=false. O preco e free.
    expect(isFreeLead({ charged: false, corporate: true })).toBe(true);
    expect(isFreeLead({ charged: true, corporate: true })).toBe(false);
  });

  it("cai para `corporate` so em payloads antigos sem `charged`", () => {
    expect(isFreeLead({ corporate: true })).toBe(true);
    expect(isFreeLead({ corporate: false })).toBe(false);
  });

  it("nao rebenta com null/undefined", () => {
    expect(isFreeLead(null)).toBe(false);
    expect(isFreeLead(undefined)).toBe(false);
  });
});

describe("isIncompleteLead", () => {
  it("marca incompleto e beco sem saida", () => {
    expect(isIncompleteLead(PAYLOADS.incompleto)).toBe(true);
    expect(isIncompleteLead(PAYLOADS.becoSemSaida)).toBe(true);
  });

  it("nao marca completo nem corporativo", () => {
    expect(isIncompleteLead(PAYLOADS.completo)).toBe(false);
    expect(isIncompleteLead(PAYLOADS.corporativo)).toBe(false);
  });
});

describe("isUnresolvableLead", () => {
  it("so marca o beco sem saida", () => {
    expect(isUnresolvableLead(PAYLOADS.becoSemSaida)).toBe(true);
    expect(isUnresolvableLead(PAYLOADS.incompleto)).toBe(false);
    expect(isUnresolvableLead(PAYLOADS.completo)).toBe(false);
    expect(isUnresolvableLead(PAYLOADS.corporativo)).toBe(false);
  });
});

describe("shouldShowIncompleteBadge (o aviso discreto)", () => {
  it("mostra para lead incompleto", () => {
    expect(shouldShowIncompleteBadge(PAYLOADS.incompleto)).toBe(true);
  });

  it("mostra para beco sem saida", () => {
    expect(shouldShowIncompleteBadge(PAYLOADS.becoSemSaida)).toBe(true);
  });

  it("NAO mostra para lead completo", () => {
    expect(shouldShowIncompleteBadge(PAYLOADS.completo)).toBe(false);
  });

  it("NAO mostra para corporativo (tem nome e morada, so falta telefone)", () => {
    expect(shouldShowIncompleteBadge(PAYLOADS.corporativo)).toBe(false);
  });
});

describe("shouldShowAddressWarning (badge por cartao)", () => {
  // O aviso por cartao e so para o endereco irresolvivel. Um aviso em 100% dos
  // cartoes (que era o que acontecia em producao) nao informa nada.
  it("mostra para beco sem saida", () => {
    expect(shouldShowAddressWarning(PAYLOADS.becoSemSaida)).toBe(true);
  });

  it("NAO mostra para lead so incompleto (falta telefone, nao o endereco)", () => {
    expect(shouldShowAddressWarning(PAYLOADS.incompleto)).toBe(false);
  });

  it("NAO mostra para corporativo nem completo", () => {
    expect(shouldShowAddressWarning(PAYLOADS.corporativo)).toBe(false);
    expect(shouldShowAddressWarning(PAYLOADS.completo)).toBe(false);
  });

  it("nao rebenta com null/undefined", () => {
    expect(shouldShowAddressWarning(null)).toBe(false);
    expect(shouldShowAddressWarning(undefined)).toBe(false);
  });
});

describe("countLeadsWithoutContact (resumo agregado)", () => {
  it("conta os leads sem contacto na lista", () => {
    expect(
      countLeadsWithoutContact([PAYLOADS.incompleto, PAYLOADS.becoSemSaida, PAYLOADS.completo]),
    ).toBe(2);
  });

  it("conta um payload corporativo como sem contacto (nao tem telefone)", () => {
    expect(countLeadsWithoutContact([PAYLOADS.corporativo])).toBe(1);
  });

  it("devolve 0 para lista vazia ou ausente (para nao mostrar o banner)", () => {
    expect(countLeadsWithoutContact([])).toBe(0);
    expect(countLeadsWithoutContact(null)).toBe(0);
    expect(countLeadsWithoutContact(undefined)).toBe(0);
  });

  it("devolve 0 quando todos tem contacto", () => {
    expect(countLeadsWithoutContact([PAYLOADS.completo])).toBe(0);
  });
});

describe("isBlockedByQuota", () => {
  it("NUNCA bloqueia um lead de graca, mesmo com a cota a 0", () => {
    // Este e o teste que trava o bug reportado pelo cliente: a cota esgotada
    // impedia a "reserva gratis" que a landing page promete.
    expect(isBlockedByQuota(PAYLOADS.incompleto, 0)).toBe(false);
    expect(isBlockedByQuota(PAYLOADS.corporativo, 0)).toBe(false);
    expect(isBlockedByQuota(PAYLOADS.becoSemSaida, 0)).toBe(false);
  });

  it("bloqueia um lead pago com a cota a 0", () => {
    expect(isBlockedByQuota(PAYLOADS.completo, 0)).toBe(true);
  });

  it("nao bloqueia com cota disponivel", () => {
    for (const remaining of [1, 3, 10]) {
      expect(isBlockedByQuota(PAYLOADS.completo, remaining)).toBe(false);
    }
  });

  it("nao bloqueia quando a cota e desconhecida (undefined/null)", () => {
    expect(isBlockedByQuota(PAYLOADS.completo, undefined)).toBe(false);
    expect(isBlockedByQuota(PAYLOADS.completo, null)).toBe(false);
  });

  it("trata um lead ausente como nao bloqueavel em vez de rebentar", () => {
    expect(isBlockedByQuota(null, 0)).toBe(true);
  });
});

describe("matriz completa: payload x cota", () => {
  const matrix = [
    ["completo", true],
    ["corporativo", false],
    ["incompleto", false],
    ["becoSemSaida", false],
  ] as const;

  it.each(matrix)("%s: bloqueado a cota 0 = %s", (nome, deveBloquear) => {
    expect(isBlockedByQuota(PAYLOADS[nome], 0)).toBe(deveBloquear);
  });
});