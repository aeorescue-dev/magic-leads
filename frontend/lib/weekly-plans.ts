export interface WeeklyPlan {
  /** Código do plano no backend (`subscription_plans.code`). */
  code: string;
  name: string;
  /** Preço formatado para apresentação. */
  price: string;
  /** Telefones por dia. */
  phones: number;
  /** Plano em destaque comercial. */
  popular?: boolean;
}

/**
 * Catálogo público dos 7 planos semanais.
 * A fonte de verdade continua a ser `subscription_plans` no backend; este
 * array serve apenas para a landing e para o resumo do plano na modal.
 */
export const WEEKLY_PLANS: WeeklyPlan[] = [
  { code: "weekly_2", name: "Starter", price: "$25.90", phones: 2 },
  { code: "weekly_4", name: "Essential", price: "$50.20", phones: 4 },
  { code: "weekly_6", name: "Growth", price: "$74.34", phones: 6 },
  { code: "weekly_8", name: "Pro", price: "$100.90", phones: 8, popular: true },
  { code: "weekly_10", name: "Business", price: "$126", phones: 10 },
  { code: "weekly_15", name: "Scale", price: "$178.50", phones: 15 },
  { code: "weekly_20", name: "Agency", price: "$231", phones: 20 },
];

export function weeklyPlanByCode(code?: string | null): WeeklyPlan | undefined {
  if (!code) return undefined;
  return WEEKLY_PLANS.find((plan) => plan.code === code);
}
