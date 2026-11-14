/**
 * Mapeamento único de códigos de erro da API para chaves i18n.
 *
 * O backend devolve códigos estáveis (ex.: PROPERTY_LOCKED), nunca frases
 * visíveis. A UI traduz aqui, no idioma ativo, sem texto hardcoded.
 */
const API_ERROR_KEYS: Record<string, string> = {
  CONSENT_REQUIRED: "dashboard.opportunity.consent_required",
  NOT_FOUND: "dashboard.opportunity.not_found",
  PROPERTY_LOCKED: "dashboard.opportunity.property_locked",
  ALREADY_RESERVED: "dashboard.opportunity.property_locked",
  ALREADY_CONVERTED: "dashboard.opportunity.already_converted",
  NOT_OWNER: "dashboard.opportunity.not_owner",
  DAILY_LIMIT_REACHED: "dashboard.opportunity.daily_limit",
  NOT_RESERVED: "dashboard.opportunity.not_reserved",
  OPPORTUNITY_ERROR: "dashboard.opportunity.not_found",
};

export function apiErrorKey(value?: string | null): string | null {
  const code = String(value || "").trim().toUpperCase();
  if (!code) return null;
  return API_ERROR_KEYS[code] || null;
}
