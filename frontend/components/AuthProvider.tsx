"use client";

import { AuthContext, useAuthState } from "@/lib/auth";

/**
 * Provider global de autenticação.
 *
 * Fica em `app/[locale]/layout.tsx`, que persiste entre navegações: `/me` e
 * `/subscription-status` deixam de ser repetidos a cada troca de página.
 */
export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const value = useAuthState();
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
