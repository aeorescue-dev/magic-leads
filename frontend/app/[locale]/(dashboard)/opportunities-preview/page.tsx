import { OpportunitiesMap } from "@/components/dashboard/opportunities-map/OpportunitiesMap";

/**
 * Preview da vista "Opportunities" com mapa + bairros.
 *
 * Rota isolada de validação: sem link na navegação, sem escrita e sem chamadas
 * de produção. Em produção é a própria tela de Opportunities, com os filtros
 * de cidade e ofício já existentes.
 */
export default function OpportunitiesPreviewPage() {
  return (
    <div data-theme="dark">
      <OpportunitiesMap />
    </div>
  );
}
