import { TerritoryBoard } from "@/components/dashboard/territory/TerritoryBoard";

/**
 * Preview isolado da vista territorial (ZIP × nicho).
 *
 * Rota de validação em branch, sem link na navegação e sem chamadas de escrita.
 * Em produção será uma aba do dashboard alimentada por
 * `GET /api/opportunities/territories`.
 */
export default function TerritoryPreviewPage() {
  return (
    <div data-theme="dark">
      <TerritoryBoard />
    </div>
  );
}
