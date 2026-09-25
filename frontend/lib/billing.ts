import { useI18n } from "@/lib/i18n";
import { activateWeekMock, createCheckoutSession } from "@/lib/api-client";

export const SUBSCRIPTION_PLAN = {
  name: "Pro",
  interval: "weekly",
  amount: 79,
  amountCents: 7900,
  annual: 4108,
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

export async function confirmMockWeek() {
  return activateWeekMock();
}