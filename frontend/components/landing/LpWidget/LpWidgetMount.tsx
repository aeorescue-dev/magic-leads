"use client";

import dynamic from "next/dynamic";
import { useState } from "react";

import { LP_WIDGET_ENABLED } from "@/lib/lp-widget";

/**
 * Ponto de montagem do widget na LP oficial.
 *
 * Enquanto `NEXT_PUBLIC_LP_WIDGET=false` o componente devolve `null` e o
 * launcher/panel nem chega a ser descarregado (chunk separado com `ssr:false`).
 * Ativar a flag é a única mudança necessária no dia da Fase 2.
 */
const LpWidgetLauncher = dynamic(() => import("./LpWidgetLauncher"), {
  ssr: false,
});

export default function LpWidgetMount() {
  const [open, setOpen] = useState(false);

  if (!LP_WIDGET_ENABLED) return null;

  return (
    <LpWidgetLauncher mode="live" open={open} onOpenChange={setOpen} />
  );
}
