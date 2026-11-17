import { redirect } from "next/navigation";

/**
 * A página de créditos passou a viver dentro do dashboard oficial.
 *
 * Marco 1A: o login gratuito entra no painel (sidebar/header oficiais) e os
 * pacotes abrem na aba "Créditos / Planos". Esta rota mantém-se apenas como
 * redirect para não quebrar links antigos, emails ou o retorno do Checkout.
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

  const query = new URLSearchParams({ tab: "credits" });
  for (const key of ["checkout", "session_id", "mock_purchase"]) {
    const value = sp[key];
    if (typeof value === "string" && value) query.set(key, value);
  }

  redirect(`/${locale}/dashboard?${query.toString()}`);
}
