/**
 * AgregaÃ§Ã£o por BAIRRO (nÃ£o por ZIP).
 *
 * O `opportunity_workflow` sÃ³ tem ZIP. Para o contractor nÃ£o faz sentido ver
 * "Dorchester" trÃªs vezes (02122/02124/02125): agrupamos os ZIPs no bairro.
 *
 * - Boston: mapa ZIP -> bairro oficial (nomes conhecidos).
 * - Dallas: setores/Ã¡reas reconhecÃ­veis; os ZIPs da amostra que pertencem a
 *   subÃºrbios vizinhos ficam com o nome do subÃºrbio (nÃ£o inventamos bairro).
 * - NYC: borough derivado do prefixo do ZIP (100/101/102 Manhattan, 112 Brooklyn,
 *   104 Bronx, 103 Staten Island, 110/111/113/114/116 Queens).
 */

export interface Zone {
  zip: string;
  label: string | null;
  total: number;
  niches: Array<{ key: string; n: number }>;
  lat: number;
  lng: number;
  geo_source: string;
}

export interface Snapshot {
  generated_at: string;
  window_days: number;
  cities: Record<
    string,
    {
      total: number;
      available: number;
      critical: number;
      zones: Zone[];
      niches: Array<{ key: string; n: number }>;
    }
  >;
}

export interface Neighborhood {
  name: string;
  zips: string[];
  /** Oportunidades no nicho ativo (ou todas, se `niche === "all"`). */
  count: number;
  /** Total no bairro, independentemente do nicho. */
  total: number;
  lat: number;
  lng: number;
}

export const CITY_META: Record<
  string,
  { label: string; center: [number, number]; zoom: number }
> = {
  Boston: { label: "Boston", center: [42.3601, -71.0589], zoom: 12 },
  Dallas: { label: "Dallas", center: [32.7767, -96.797], zoom: 11 },
  NYC: { label: "New York", center: [40.7128, -74.006], zoom: 11 },
};

export const CITY_ORDER = ["Boston", "Dallas", "NYC"] as const;

/**
 * Fora do perÃ­metro ou ZIP sem bairro reconhecido: agrupados em "Other areas"
 * para nÃ£o esconder leads nem inventar nomes.
 */
export const OTHER_AREAS = "Other areas";

export const BOSTON_ZIP_LABELS: Record<string, string> = {
  "02105": "Other areas",
  "02108": "Beacon Hill",
  "02109": "Downtown & Waterfront",
  "02110": "Downtown & Waterfront",
  "02111": "Downtown & Waterfront",
  "02113": "Downtown & Waterfront",
  "02114": "West End",
  "02115": "Fenway",
  "02116": "Back Bay",
  "02118": "South End",
  "02119": "Roxbury",
  "02120": "Mission Hill",
  "02121": "Roxbury",
  "02122": "Dorchester",
  "02124": "Dorchester",
  "02125": "Dorchester",
  "02126": "Mattapan",
  "02127": "South Boston",
  "02128": "East Boston",
  "02129": "Charlestown",
  "02130": "Jamaica Plain",
  "02131": "Roslindale",
  "02132": "West Roxbury",
  "02134": "Allston",
  "02135": "Brighton",
  "02136": "Hyde Park",
  "02163": "Allston",
  "02199": "Back Bay",
  "02210": "Seaport",
  "02215": "Fenway",
  "02467": "Chestnut Hill",
};

export const DALLAS_ZIP_LABELS: Record<string, string> = {
  // Centro
  "75201": "Downtown & Uptown",
  "75202": "Downtown & Uptown",
  "75204": "Downtown & Uptown",
  "75207": "Downtown & Uptown",
  "75226": "Downtown & Uptown",
  // Oak Cliff / oeste
  "75203": "Oak Cliff",
  "75208": "Oak Cliff",
  "75211": "Oak Cliff",
  "75224": "Oak Cliff",
  "75233": "Oak Cliff",
  "75236": "Oak Cliff",
  "75237": "Oak Cliff",
  "75212": "West Dallas",
  // Este
  "75206": "East Dallas",
  "75214": "East Dallas",
  "75218": "East Dallas",
  "75223": "East Dallas",
  "75228": "East Dallas",
  "75246": "East Dallas",
  // Lake Highlands / norte
  "75238": "Lake Highlands",
  "75243": "Lake Highlands",
  "75229": "North Dallas",
  "75230": "North Dallas",
  "75231": "North Dallas",
  "75240": "North Dallas",
  "75244": "North Dallas",
  "75248": "Far North Dallas",
  "75252": "Far North Dallas",
  "75254": "Far North Dallas",
  "75287": "Far North Dallas",
  // Oak Lawn / Park Cities
  "75205": "Oak Lawn & Park Cities",
  "75209": "Oak Lawn & Park Cities",
  "75219": "Oak Lawn & Park Cities",
  "75225": "Oak Lawn & Park Cities",
  // Sul
  "75210": "South Dallas",
  "75215": "South Dallas",
  "75216": "South Dallas",
  "75232": "South Dallas",
  "75241": "South Dallas",
  "75249": "South Dallas",
  "75253": "South Dallas",
  "75217": "Pleasant Grove",
  "75227": "Pleasant Grove",
  // Aeroporto
  "75235": "Love Field",
  "75247": "Love Field",
};

export function nycBorough(zip: string): string {
  const prefix = zip.slice(0, 3);
  if (["100", "101", "102"].includes(prefix)) return "Manhattan";
  if (prefix === "103") return "Staten Island";
  if (prefix === "104") return "Bronx";
  if (prefix === "112") return "Brooklyn";
  if (["110", "111", "113", "114", "116"].includes(prefix)) return "Queens";
  return OTHER_AREAS;
}

function zoneName(city: string, zone: Zone): string {
  if (city === "NYC") return nycBorough(zone.zip);
  if (city === "Boston") return BOSTON_ZIP_LABELS[zone.zip] ?? zone.label ?? OTHER_AREAS;
  if (city === "Dallas") return DALLAS_ZIP_LABELS[zone.zip] ?? OTHER_AREAS;
  return zone.label ?? OTHER_AREAS;
}

export function buildNeighborhoods(
  city: string,
  zones: Zone[],
  niche: string
): Neighborhood[] {
  const groups = new Map<
    string,
    {
      name: string;
      zips: string[];
      count: number;
      total: number;
      latWeighted: number;
      lngWeighted: number;
      weight: number;
    }
  >();

  for (const zone of zones) {
    const name = zoneName(city, zone);
    const nicheCount =
      niche === "all"
        ? zone.total
        : zone.niches.find((item) => item.key === niche)?.n ?? 0;
    if (niche !== "all" && nicheCount === 0) continue;

    const group = groups.get(name) ?? {
      name,
      zips: [],
      count: 0,
      total: 0,
      latWeighted: 0,
      lngWeighted: 0,
      weight: 0,
    };
    group.zips.push(zone.zip);
    group.count += nicheCount;
    group.total += zone.total;
    // Centroide ponderado pelo volume de cada ZIP.
    const weight = Math.max(zone.total, 1);
    group.latWeighted += zone.lat * weight;
    group.lngWeighted += zone.lng * weight;
    group.weight += weight;
    groups.set(name, group);
  }

  return Array.from(groups.values())
    .filter((group) => group.count > 0)
    .map((group) => ({
      name: group.name,
      zips: group.zips.sort(),
      count: group.count,
      total: group.total,
      lat: group.latWeighted / group.weight,
      lng: group.lngWeighted / group.weight,
    }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

const EARTH_RADIUS_MI = 3958.8;

export function distanceMiles(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number
): number {
  const toRad = (value: number) => (value * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_MI * Math.asin(Math.sqrt(a));
}

export function formatDistance(miles: number): string {
  if (miles < 0.1) return "<0.1 mi";
  if (miles < 10) return `${miles.toFixed(1)} mi`;
  return `${Math.round(miles)} mi`;
}
