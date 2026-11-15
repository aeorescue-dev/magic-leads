import rawSnapshot from "./opportunities-sample.json";

import type { Snapshot } from "./neighborhoods";

/** Snapshot real (read-only) usado no preview. Em produção vem da API. */
export const SNAPSHOT = rawSnapshot as unknown as Snapshot;

const NICHE_LABEL_KEYS: Record<string, string> = {
  Structure: "dashboard.cat.estrutura",
  Plumbing: "dashboard.cat.encanamento",
  Roof: "dashboard.cat.telhado",
  Electrical: "dashboard.cat.electrical",
  Permit_Rejected: "dashboard.cat.obras",
  Heating: "dashboard.cat.heating",
  Gas: "dashboard.cat.gas",
  Debris: "dashboard.cat.debris",
  Rodent: "dashboard.cat.rodent",
  Door_Window: "dashboard.cat.door_window",
  Unsanitary: "dashboard.cat.unsanitary",
  Mold: "dashboard.cat.mold",
  Elevator: "dashboard.cat.elevator",
  Paint: "dashboard.cat.pintura",
  Grass: "dashboard.cat.mato",
  Lead: "dashboard.cat.lead",
  Unclassified: "dashboard.cat.unclassified",
};

export function nicheLabel(key: string, t: (key: string) => string): string {
  const labelKey = NICHE_LABEL_KEYS[key];
  if (!labelKey) return key;
  const value = t(labelKey);
  return value === labelKey ? key : value;
}
