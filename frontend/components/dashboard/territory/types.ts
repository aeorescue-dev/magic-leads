/** Tipos da vista territorial (agregação ZIP × nicho). */

export interface NicheCount {
  key: string;
  n: number;
}

export type GeoSource = "leads" | "address_join" | "city_center";

export interface Zone {
  zip: string;
  /** Nome local do bairro quando existe (Boston). Nunca inventado noutras cidades. */
  label: string | null;
  total: number;
  available: number;
  critical: number;
  next_deadline: string | null;
  niches: NicheCount[];
  lat: number;
  lng: number;
  geo_source: GeoSource;
}

export interface CityTerritory {
  total: number;
  available: number;
  critical: number;
  with_deadline: number;
  zones: Zone[];
  niches: NicheCount[];
  coverage: {
    zones: number;
    zones_with_local_geo: number;
    exact_geo: number;
  };
}

export interface TerritorySnapshot {
  generated_at: string;
  window_days: number;
  source: string;
  cities: Record<string, CityTerritory>;
}

export type TerritoryView = "zones" | "map" | "matrix";
