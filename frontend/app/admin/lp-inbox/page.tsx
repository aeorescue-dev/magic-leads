import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { isLpWidgetPreviewEnabled } from "@/lib/lp-widget";
import LpInboxClient from "./LpInboxClient";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "LP Inbox · Admin",
  description: "Inbox interna do widget de captação. Uso interno.",
  robots: { index: false, follow: false },
};

/**
 * Fase 1b — inbox admin do LP widget.
 * Só existe quando a prévia/staging está ligada; em produção a flag fica
 * desligada e a rota devolve 404. O backend valida a sessão + is_admin.
 */
export default function LpInboxPage() {
  if (!isLpWidgetPreviewEnabled()) {
    notFound();
  }
  return <LpInboxClient />;
}
