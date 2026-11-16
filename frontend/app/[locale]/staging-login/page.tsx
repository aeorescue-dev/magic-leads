"use client";

import { useEffect, useState } from "react";

export default function StagingLoginPage() {
  const [token, setToken] = useState("");
  const [next, setNext] = useState("/en/credits");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const value = new URLSearchParams(window.location.search).get("next") || "";
    if (value.startsWith("/") && !value.startsWith("//")) setNext(value);
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const res = await fetch("/api/staging-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token.trim() }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(body?.error === "invalid_token" ? "Token inválido." : "Acesso negado.");
        return;
      }
      window.location.href = next;
    } catch {
      setError("Falha de rede.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#0b1220] p-4 text-white">
      <div className="w-full max-w-md rounded-3xl border border-white/10 bg-[#101826] p-6 shadow-2xl sm:p-8">
        <div className="text-[10px] font-black uppercase tracking-[0.2em] text-[#34e0a1]">Staging Magic Leads</div>
        <h1 className="mt-2 text-2xl font-black">Acesso protegido</h1>
        <p className="mt-1 text-sm text-slate-400">
          Introduz o token de staging para abrir o ambiente de testes. Não é a password de produção.
        </p>
        <form onSubmit={submit} className="mt-5 space-y-3">
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="STAGING_ACCESS_TOKEN"
            className="w-full rounded-xl border border-white/10 bg-[#0b1220] px-4 py-3 text-sm text-white outline-none focus:border-[#34e0a1]"
            autoFocus
          />
          {error && <p className="text-xs font-semibold text-rose-400">{error}</p>}
          <button
            disabled={busy || !token.trim()}
            className="w-full rounded-xl bg-[#34e0a1] px-4 py-3 text-sm font-black text-[#06251c] disabled:opacity-50"
          >
            {busy ? "A validar…" : "Entrar no staging"}
          </button>
        </form>
        <p className="mt-4 text-[11px] text-slate-500">
          O cookie expira em 7 dias. Nenhum dado de produção é alterado.
        </p>
      </div>
    </main>
  );
}
