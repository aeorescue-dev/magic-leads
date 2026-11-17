import { redirect } from "next/navigation";

/**
 * A página de créditos deixou de existir no modelo de assinatura semanal.
 * Esta rota mantém-se apenas como redirect para não quebrar links antigos,
 * emails ou retornos de Checkout/Portal.
 */
export default async function CreditsRedirect({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { locale } = await params;
  const sp = await searchParams;

  const query = new URLSearchParams({ plans: "1" });
  const billing = sp.billing ?? sp.checkout;
  if (typeof billing === "string" && billing) query.set("billing", billing);
  for (const key of ["session_id", "addon"]) {
    const value = sp[key];
    if (typeof value === "string" && value) query.set(key, value);
  }

  redirect(`/${locale}/dashboard?${query.toString()}`);
}
