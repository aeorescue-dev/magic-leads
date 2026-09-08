"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, CreditCard, Loader2, LogOut } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import CheckoutModal from "@/components/CheckoutModal";

const PLAN_LABELS: Record<string, string> = {
  free: "Free",
  pro: "Pro",
  enterprise: "Enterprise",
};

export default function DashboardSettingsPage() {
  const { user, loading, signOut } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const [showCheckout, setShowCheckout] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  const handleLogout = async () => {
    setLoggingOut(true);
    await signOut();
    router.push("/");
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-xl font-semibold">{t("dashboard.nav.settings")}</h1>
            <p className="text-sm text-slate-400">{t("dashboard.settings.sub")}</p>
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-emerald-500" /></div>
        ) : !user ? (
          <p className="text-slate-400">{t("dashboard.settings.logged_out")}</p>
        ) : (
          <>
            <div className="rounded-2xl border border-white/10 bg-[#14161d] p-5 space-y-4">
              <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">{t("dashboard.settings.account")}</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.auth.company")}</p>
                  <p className="font-medium">{user.company_name || "—"}</p>
                </div>
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.field.email")}</p>
                  <p className="font-medium break-all">{user.email}</p>
                </div>
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.settings.plan")}</p>
                  <p className="font-medium capitalize">{PLAN_LABELS[user.plan || "free"] || user.plan}</p>
                </div>
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.settings.status")}</p>
                  <p className="font-medium capitalize">{user.subscription_status || user.plan}</p>
                </div>
              </div>
              <div className="rounded-xl bg-white/5 border border-white/10 p-3 text-sm">
                <p className="text-xs text-slate-400">{t("dashboard.settings.access_until")}</p>
                <p className="font-medium">
                  {user.plan_until ? new Date(user.plan_until.replace(" ", "T")).toLocaleDateString("pt-BR") : "—"}
                </p>
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-[#14161d] p-5 space-y-4">
              <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">{t("dashboard.settings.reputation")}</h2>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.kpi.score.delta")}</p>
                  <p className="font-medium text-fuchsia-300">{user.score || 100} pts</p>
                </div>
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.kpi.taken")}</p>
                  <p className="font-medium">{user.leads_taken || 0}</p>
                </div>
                <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                  <p className="text-xs text-slate-400">{t("dashboard.kpi.conversions")}</p>
                  <p className="font-medium">{user.conversions || 0}</p>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-[#14161d] p-5 flex flex-col sm:flex-row sm:items-center gap-4">
              <div className="flex-1">
                <h2 className="text-sm font-semibold text-slate-300">{t("dashboard.settings.subscription_title")}</h2>
                <p className="text-sm text-slate-400">
                  {t("dashboard.settings.subscription_body")}
                </p>
              </div>
              <button
                onClick={() => setShowCheckout(true)}
                className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-900 font-semibold text-sm"
              >
                <CreditCard className="w-4 h-4" /> {t("dashboard.settings.renew")}
              </button>
            </div>

            <button
              onClick={handleLogout}
              disabled={loggingOut}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 font-medium text-sm disabled:opacity-50"
            >
              {loggingOut ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogOut className="w-4 h-4" />} {t("dashboard.settings.logout")}
            </button>
          </>
        )}

        <CheckoutModal
          open={showCheckout}
          onClose={() => setShowCheckout(false)}
          onActivated={() => window.location.reload()}
          isDark
        />
      </div>
    </div>
  );
}