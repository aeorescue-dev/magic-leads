"use client";

import { Loader2, LockKeyhole } from "lucide-react";
import { useState } from "react";

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ||
  "https://magic-leads-production.up.railway.app"
).replace(/\/$/, "");

export function ShowcaseCta({
  token,
  city,
  trade,
  priceUsd,
}: {
  token: string;
  city: string;
  trade: string;
  priceUsd: number;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const start = async () => {
    if (!token) {
      window.location.href = "/en";
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/showcase/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, city, trade }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.checkout_url) {
        setError(
          data.detail === "stripe_not_configured"
            ? "Checkout is being configured. Reply to the email and we will send a payment link."
            : "Could not open checkout. Please try again."
        );
        setBusy(false);
        return;
      }
      window.location.href = data.checkout_url;
    } catch {
      setError("Network error. Please try again.");
      setBusy(false);
    }
  };

  return (
    <div>
      <button
        type="button"
        onClick={() => void start()}
        disabled={busy}
        data-track="showcase_checkout"
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 px-5 py-3 text-sm font-black text-[#052018] transition-colors hover:bg-emerald-400 disabled:opacity-60"
      >
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <LockKeyhole className="h-4 w-4" />
        )}
        {token
          ? `Unlock the full list — $${priceUsd}/week`
          : "Join Magic Leads"}
      </button>
      <p className="mt-2 text-center text-[10px] text-slate-500">
        Secure Stripe checkout · 7-day pass · cancel anytime
      </p>
      {error ? (
        <p className="mt-2 rounded-lg border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
          {error}
        </p>
      ) : null}
    </div>
  );
}
