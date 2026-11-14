export const OPPORTUNITIES_REFRESH_EVENT = "magic:opportunities-refresh";

/** Pede ao feed preventivo que volte a carregar os dados (após reservar/avançar). */
export function requestOpportunitiesRefresh(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(OPPORTUNITIES_REFRESH_EVENT));
}
