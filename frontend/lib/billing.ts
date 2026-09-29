import { useI18n } from "@/lib/i18n";
import { createCheckoutSession } from "@/lib/api-client";

export const SUBSCRIPTION_PLAN = {
  name: "Pro",
  interval: "weekly",
  amount: 120,
  amountCents: 12000,
  annual: 6240,
} as const;

export interface CheckoutResult {
  mock: boolean;
  checkout_url: string | null;
}

export function useStartCheckout() {
  const { lang } = useI18n();
  return async (): Promise<CheckoutResult> => {
    const res = await createCheckoutSession(lang);
    return { mock: res.mock, checkout_url: res.checkout_url };
  };
}

// NOTA: confirmMockWeek / activateWeekMock foram removidos.
// Chamavam /api/billing/mock-activate, que concedia plano Pro sem verificar
// pagamento no Stripe. A unica via de ativacao e o webhook Stripe.