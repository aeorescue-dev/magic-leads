/**
 * Categorias (ofícios) partilhadas pelo Onboarding Wizard.
 *
 * A fonte de verdade do vocabulário é o backend (`user_interests.category`).
 * Aqui só guardamos a chave estável + a chave de tradução, para o wizard não
 * duplicar 16 strings em três idiomas.
 */

export interface TradeCategory {
  key: string;
  labelKey: string;
}

export const TRADE_CATEGORIES: readonly TradeCategory[] = [
  { key: "Roof", labelKey: "dashboard.cat.telhado" },
  { key: "Structure", labelKey: "dashboard.cat.estrutura" },
  { key: "Plumbing", labelKey: "dashboard.cat.encanamento" },
  { key: "Grass", labelKey: "dashboard.cat.mato" },
  { key: "Paint", labelKey: "dashboard.cat.pintura" },
  { key: "Permit_Rejected", labelKey: "dashboard.cat.obras" },
  { key: "Heating", labelKey: "dashboard.cat.heating" },
  { key: "Electrical", labelKey: "dashboard.cat.electrical" },
  { key: "Elevator", labelKey: "dashboard.cat.elevator" },
  { key: "Gas", labelKey: "dashboard.cat.gas" },
  { key: "Rodent", labelKey: "dashboard.cat.rodent" },
  { key: "Mold", labelKey: "dashboard.cat.mold" },
  { key: "Lead", labelKey: "dashboard.cat.lead" },
  { key: "Unsanitary", labelKey: "dashboard.cat.unsanitary" },
  { key: "Door_Window", labelKey: "dashboard.cat.door_window" },
  { key: "Debris", labelKey: "dashboard.cat.debris" },
] as const;

export const TRADE_CATEGORY_KEYS: readonly string[] = TRADE_CATEGORIES.map((c) => c.key);

/**
 * O onboarding é obrigatório quando o utilizador ainda não escolheu nenhum
 * ofício. "Sem categorias" no backend significa "todas" (fallback), por isso
 * um conjunto vazio nunca é uma escolha válida — é um utilizador por configurar.
 */
export function needsOnboarding(categories: string[] | null | undefined): boolean {
  return !Array.isArray(categories) || categories.length === 0;
}
