"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Bell, Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { fetchUserNotifications, markAllUserNotificationsRead, markUserNotificationRead } from "@/lib/api-client";

export default function DashboardNotificationsPage() {
  const { user, loading } = useAuth();
  const { t } = useI18n();
  const [items, setItems] = useState<any[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);

  const userId = user?.id;

  const load = async () => {
    if (!userId) return;
    setLoadingItems(true);
    try {
      setItems(await fetchUserNotifications(userId));
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingItems(false);
    }
  };

  useEffect(() => {
    if (userId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const markRead = async (id: number) => {
    if (!userId) return;
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: 1 } : n)));
    await markUserNotificationRead(userId, id).catch(() => {});
  };

  const markAll = async () => {
    if (!userId) return;
    setItems((prev) => prev.map((n) => ({ ...n, read: 1 })));
    await markAllUserNotificationsRead(userId).catch(() => {});
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="max-w-2xl mx-auto px-4 py-8 space-y-5">
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex-1">
            <h1 className="text-xl font-semibold">{t("dashboard.notifications.title")}</h1>
            <p className="text-sm text-slate-400">{t("dashboard.notifications.sub")}</p>
          </div>
          {items.some((n) => !n.read) && (
            <button onClick={markAll} className="text-xs text-indigo-400 hover:underline">
              {t("dashboard.notifications.mark_all")}
            </button>
          )}
        </div>

        {loading || loadingItems ? (
          <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-emerald-500" /></div>
        ) : items.length === 0 ? (
          <div className="rounded-2xl border border-white/10 bg-[#14161d] p-12 text-center">
            <Bell className="w-8 h-8 text-slate-500 mx-auto mb-2" />
            <p className="text-sm text-slate-400">{t("dashboard.notifications.empty")}</p>
          </div>
        ) : (
          <ul className="space-y-2">
            {items.map((n) => (
              <li
                key={n.id}
                onClick={() => markRead(n.id)}
                className={`rounded-2xl border p-4 cursor-pointer transition ${!n.read ? "border-indigo-500/40 bg-indigo-500/10" : "border-white/10 bg-[#14161d]"}`}
              >
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-semibold uppercase ${!n.read ? "text-indigo-400" : "text-slate-400"}`}>{n.type}</span>
                  <span className="ml-auto text-[11px] text-slate-500">{n.created_at}</span>
                </div>
                <p className="text-sm mt-1">{n.title}</p>
                {n.message && <p className="text-xs text-slate-400 mt-0.5">{n.message}</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}