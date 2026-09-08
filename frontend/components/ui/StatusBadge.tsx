import { useI18n } from "@/lib/i18n";
import { Badge } from "./Badge";

const statusTone: Record<string, "neutral" | "success" | "primary" | "danger" | "warning" | "info"> = {
  new: "primary",
  contacted: "success",
  won: "success",
  lost: "danger",
  no_interest: "neutral",
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const key = status === "no_interest" ? "db.status.no_interest" : `db.status.${status}`;
  return (
    <Badge tone={statusTone[status] || "neutral"} dot>
      {t(key)}
    </Badge>
  );
}
