import { createContext, useCallback, useContext, useEffect, useState } from "react";
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

export interface SubscriptionStatus {
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

export interface AuthContextValue {
  user: AuthUser | null;
  subscription: SubscriptionStatus | null;
  loading: boolean;
  signIn: (
    email: string,
    password: string,
    companyName?: string,
    locale?: string,
  ) => Promise<AuthUser>;
  signOut: () => Promise<void>;
  updateUser: (user: AuthUser) => void;
  refreshSubscription: () => Promise<void>;
}

/**
 * Contexto global de autenticação.
 *
 * Antes, `useAuth()` era um hook que chamava `/me` e `/subscription-status`
 * em CADA componente/página montada. Trocar de rota repetia as duas chamadas.
 * O provider vive no layout do locale (persistente entre navegações), pelo que
 * a validação acontece uma vez por sessão de app.
 */
export const AuthContext = createContext<AuthContextValue | null>(null);

/** Estado de autenticação — usar apenas dentro de <AuthProvider>. */
export function useAuthState(): AuthContextValue {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const attempt = async () => {
      // Se já existe token, valida com /me
      if (getToken()) {
        try {
          const u = await fetchMe();
          if (!active) return;
          storeUser(u);
          setUser(u);

          // Busca status da subscription
          if (u?.id) {
            try {
              const sub = await fetchUserSubscriptionStatus(u.id);
              if (active) setSubscription(sub);
            } catch (e) {
              console.error("Erro ao buscar subscription:", e);
            }
          }
        } catch {
          if (!active) return;
          setToken(null);
          storeUser(null);
          setUser(null);
        }
      } else {
        // Fallback para sessão local legada (demo)
        const legacy = readStoredUser();
        if (active && legacy) setUser(legacy);
      }
      if (active) setLoading(false);
    };
    attempt();
    return () => {
      active = false;
    };
  }, []);

  // Refetch do status da subscription a cada 10min para bloquear/avisar na hora
  useEffect(() => {
    const id = setInterval(() => {
      refreshUserSubscription(user, setSubscription);
    }, SUBSCRIPTION_REFRESH_MS);
    return () => clearInterval(id);
  }, [user]);

  const signIn = useCallback(
    async (
      email: string,
      password: string,
      companyName?: string,
      locale?: string,
    ) => {
      const withSubscription = async (u: AuthUser) => {
        setUser(u);
        storeUser(u);
        await refreshUserSubscription(u, setSubscription);
        return u;
      };
      if (companyName) {
        const out = await registerUser({
          email,
          password,
          company_name: companyName,
          ...(locale ? { locale } : {}),
        });
        return withSubscription(out.user);
      }
      const out = await loginUser({ email, password });
      return withSubscription(out.user);
    },
    [],
  );

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

  const refreshSubscription = useCallback(async () => {
    if (user?.id) {
      await refreshUserSubscription(user, setSubscription);
    }
  }, [user]);

  return { user, subscription, loading, signIn, signOut, updateUser, refreshSubscription };
}

/** Consumidor do contexto global (falha alto se faltar o provider). */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth tem de ser usado dentro de <AuthProvider>");
  }
  return ctx;
}

export default useAuth;
