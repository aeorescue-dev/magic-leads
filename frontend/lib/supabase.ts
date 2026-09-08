import { useEffect, useState } from "react";

/**
 * Auth local simples (MVP sem custo, sem serviço externo).
 * Armazena a sessão em localStorage. Quando o produto monetizar,
 * substituir por NextAuth/OAuth sem mudar a interface do hook.
 */

export interface AuthUser {
  id: string;
  email: string;
  company_name?: string;
}

const STORAGE_KEY = "garimpador.auth";
const COOKIE_KEY = "garimpador_auth";

function readStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

function setAuthCookie(value: string | null) {
  if (typeof document === "undefined") return;
  if (value) {
    document.cookie = `${COOKIE_KEY}=${encodeURIComponent(value)}; path=/; max-age=2592000; samesite=lax`;
  } else {
    document.cookie = `${COOKIE_KEY}=; path=/; max-age=0; samesite=lax`;
  }
}

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setUser(readStoredUser());
    setLoading(false);
  }, []);

  return {
    user,
    loading,
    signIn: (email: string, companyName?: string) => {
      const u: AuthUser = {
        id: `local-${Date.now()}`,
        email,
        company_name: companyName,
      };
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(u));
      setAuthCookie(JSON.stringify(u));
      setUser(u);
    },
    signOut: () => {
      window.localStorage.removeItem(STORAGE_KEY);
      setAuthCookie(null);
      setUser(null);
    },
  };
}

export default useAuth;