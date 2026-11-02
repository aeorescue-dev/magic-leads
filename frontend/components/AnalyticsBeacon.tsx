"use client";

import { useEffect } from "react";

import { startAnalytics } from "@/lib/analytics";

/**
 * Monta o beacon first-party apenas nas páginas de marketing.
 * Não renderiza nada e não corre antes da hidratação.
 */
export default function AnalyticsBeacon() {
  useEffect(() => startAnalytics(), []);
  return null;
}
