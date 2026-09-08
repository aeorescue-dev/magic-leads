import { Badge } from "./Badge";

const categoryTone: Record<string, "amber" | "info" | "violet" | "danger" | "success" | "neutral"> = {
  Grass: "success",
  Plumbing: "info",
  Paint: "violet",
  Roof: "amber",
  Structure: "danger",
  Permit_Rejected: "neutral",
};

export function CategoryBadge({ category }: { category: string }) {
  return <Badge tone={categoryTone[category] || "neutral"}>{category}</Badge>;
}
