import { useCallback, useEffect, useState } from "react";
import {
  AuthUser, registerUser, loginUser, logoutUser, fetchMe, getToken, setToken,
  fetchUserSubscriptionStatus,
} from "@/lib/api-client";

const STORAGE_KEY = "garimpador.user";

export function readStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

function storeUser(user: AuthUser | null) {
  if (typeof window === "undefined") return;
  if (user) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
  else window.localStorage.removeItem(STORAGE_KEY);
}

interface SubscriptionStatus {
  status: string;
  is_active: boolean;
  can_access: boolean;
  message: string;
  days_remaining?: number;
  hours_remaining?: number;
  expires_at?: string;
  action?: string | null;
}

const SUBSCRIPTION_REFRESH_MS = 10 * 60 * 1000; // 10 minutos

async function refreshUserSubscription(
  user: AuthUser | null,
  setSubscription: (s: SubscriptionStatus | null) => void,
) {
  if (!user?.id || !getToken()) return;
  try {
    const sub = await fetchUserSubscriptionStatus(user.id);
    setSubscription(sub);
  } catch (e) {
    console.error("Erro ao atualizar subscription:", e);
  }
}

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const attempt = async () => {
      // Se já existe token, valida com /me
      if (getToken()) {
        try {
          const u = await fetchMe();
          storeUser(u);
          setUser(u);
          
          // Busca status da subscription
          if (u?.id) {
            try {
              const sub = await fetchUserSubscriptionStatus(u.id);
              setSubscription(sub);
            } catch (e) {
              console.error("Erro ao buscar subscription:", e);
            }
          }
        } catch {
          setToken(null);
          storeUser(null);
          setUser(null);
        }
      } else {
        // Fallback para sessão local legada (demo)
        const legacy = readStoredUser();
        if (legacy) setUser(legacy);
      }
      setLoading(false);
    };
    attempt();
  }, []);

  // Refetch do status da subscription a cada 10min para bloquear/avisar na hora
  useEffect(() => {
    const id = setInterval(() => {
      refreshUserSubscription(user, setSubscription);
    }, SUBSCRIPTION_REFRESH_MS);
    return () => clearInterval(id);
  }, [user]);

  const signIn = useCallback(async (email: string, password: string, companyName?: string, locale?: string) => {
    const withSubscription = async (u: AuthUser) => {
      setUser(u);
      storeUser(u);
      await refreshUserSubscription(u, setSubscription);
      return u;
    };
    if (companyName) {
      const out = await registerUser({ email, password, company_name: companyName, ...(locale ? { locale } : {}) });
      return withSubscription(out.user);
    }
    const out = await loginUser({ email, password });
    return withSubscription(out.user);
  }, []);

  const signOut = useCallback(async () => {
    await logoutUser();
    setToken(null);
    storeUser(null);
    setUser(null);
    setSubscription(null);
  }, []);

  const updateUser = useCallback((u: AuthUser) => {
    setUser(u);
    storeUser(u);
  }, []);

  return { user, subscription, loading, signIn, signOut, updateUser };
}

export default useAuth;
