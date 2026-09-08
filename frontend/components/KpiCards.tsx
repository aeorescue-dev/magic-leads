import { Users, CalendarClock, PhoneCall, Star, type LucideIcon } from "lucide-react";
import { LeadStats } from "@/lib/api-client";
import { useI18n } from "@/lib/i18n";
import { Skeleton } from "./ui/Skeleton";

interface KpiConfig {
  label: string;
  value: number | string | undefined;
  icon: LucideIcon;
  tint: string;
  bar: string;
}

function KpiCard({ config }: { config: KpiConfig }) {
  const Icon = config.icon;
  return (
    <div className="card card-hover p-5 group relative overflow-hidden">
      <div className={`absolute inset-x-0 top-0 h-1 ${config.bar}`} />
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{config.label}</p>
          <p className="text-3xl font-extrabold text-foreground mt-1.5">
            {config.value ?? <Skeleton className="h-8 w-12" />}
          </p>
        </div>
        <div className={`h-11 w-11 rounded-xl flex items-center justify-center ${config.tint}`}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  );
}

export function KpiCards({ stats }: { stats: LeadStats | null }) {
  const { t } = useI18n();
  const configs: KpiConfig[] = [
    {
      label: t("db.kpi.total"),
      value: stats?.total,
      icon: Users,
      tint: "bg-indigo-100 text-indigo-600",
      bar: "bg-gradient-to-r from-indigo-500 to-violet-500",
    },
    {
      label: t("db.kpi.today"),
      value: stats?.reported_today,
      icon: CalendarClock,
      tint: "bg-amber-100 text-amber-600",
      bar: "bg-gradient-to-r from-amber-400 to-orange-500",
    },
    {
      label: t("db.kpi.contacted"),
      value: stats?.contacted,
      icon: PhoneCall,
      tint: "bg-emerald-100 text-emerald-600",
      bar: "bg-gradient-to-r from-emerald-500 to-teal-500",
    },
    {
      label: t("db.kpi.fav"),
      value: stats?.favorited,
      icon: Star,
      tint: "bg-violet-100 text-violet-600",
      bar: "bg-gradient-to-r from-violet-500 to-fuchsia-500",
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {configs.map((c) => (
        <KpiCard key={c.label} config={c} />
      ))}
    </div>
  );
}
