import { LayoutGrid, Rows } from "lucide-react";

export type ViewMode = "table" | "cards";

export function ViewToggle({
  value,
  onChange,
}: {
  value: ViewMode;
  onChange: (v: ViewMode) => void;
}) {
  return (
    <div className="inline-flex items-center rounded-lg border bg-secondary p-0.5">
      <button
        onClick={() => onChange("table")}
        className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
          value === "table" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
        }`}
      >
        <Rows className="h-4 w-4" />
        Tabela
      </button>
      <button
        onClick={() => onChange("cards")}
        className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
          value === "cards" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
        }`}
      >
        <LayoutGrid className="h-4 w-4" />
        Cards
      </button>
    </div>
  );
}
