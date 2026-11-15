import type { LeadGeoGroup } from "@/lib/api-client";

import {
  BOSTON_ZIP_LABELS,
  DALLAS_ZIP_LABELS,
  OTHER_AREAS,
  nycBorough,
} from "./neighborhoods";
import { SNAPSHOT as PREVENTIVE_SNAPSHOT } from "./data";

/**
 * Zona da aba Opportunities (leads reativos).
 *
 * O SQL devolve grupos por `neighborhood` ou por ZIP. Aqui:
 * - Boston/NYC: o bairro/borough é a zona (ZIPs de apoio para o filtro).
 * - Dallas: ZIP -> setor reconhecível (o mesmo mapa do preventivo).
 * - Chicago: ZIP (a cobertura de bairro é baixa).
 * - Sem bairro nem ZIP: "Other areas" (lista, sem pin).
 */
export interface LeadZone {
  name: string;
  count: number;
  lat: number | null;
  lng: number | null;
  neighborhoods: string[];
  zips: string[];
  noGeo: boolean;
}

interface DraftZone extends LeadZone {
  weight: number;
  latSum: number;
  lngSum: number;
}

/** Community areas oficiais de Chicago (a fonte usa o número 1-77). */
const CHICAGO_COMMUNITY_AREAS: Record<string, string> = {
  "1": "Rogers Park", "2": "West Ridge", "3": "Uptown",
  "4": "Lincoln Square", "5": "North Center", "6": "Lake View",
  "7": "Lincoln Park", "8": "Near North Side", "9": "Edison Park",
  "10": "Norwood Park", "11": "Jefferson Park", "12": "Forest Glen",
  "13": "North Park", "14": "Albany Park", "15": "Portage Park",
  "16": "Irving Park", "17": "Dunning", "18": "Montclare",
  "19": "Belmont Cragin", "20": "Hermosa", "21": "Avondale",
  "22": "Logan Square", "23": "Humboldt Park", "24": "West Town",
  "25": "Austin", "26": "West Garfield Park", "27": "East Garfield Park",
  "28": "Near West Side", "29": "North Lawndale", "30": "South Lawndale",
  "31": "Lower West Side", "32": "Loop", "33": "Near South Side",
  "34": "Armour Square", "35": "Douglas", "36": "Oakland",
  "37": "Fuller Park", "38": "Grand Boulevard", "39": "Kenwood",
  "40": "Washington Park", "41": "Hyde Park", "42": "Woodlawn",
  "43": "South Shore", "44": "Chatham", "45": "Avalon Park",
  "46": "South Chicago", "47": "Burnside", "48": "Calumet Heights",
  "49": "Roseland", "50": "Pullman", "51": "South Deering",
  "52": "East Side", "53": "West Pullman", "54": "Riverdale",
  "55": "Hegewisch", "56": "Garfield Ridge", "57": "Archer Heights",
  "58": "Brighton Park", "59": "McKinley Park", "60": "Bridgeport",
  "61": "New City", "62": "West Elsdon", "63": "Gage Park",
  "64": "Clearing", "65": "West Lawn", "66": "Chicago Lawn",
  "67": "West Englewood", "68": "Englewood", "69": "Greater Grand Crossing",
  "70": "Ashburn", "71": "Auburn Gresham", "72": "Beverly",
  "73": "Washington Heights", "74": "Mount Greenwood", "75": "Morgan Park",
  "76": "O'Hare", "77": "Edgewater",
};

/**
 * Centroides por ZIP derivados do snapshot preventivo (moradas geocodificadas).
 * Fallback quando os leads daquela zona não trazem lat/lng — é o caso de Dallas,
 * cujos ZIPs quase nunca têm coordenadas na tabela `leads`.
 */
const ZIP_CENTROIDS: Record<string, Record<string, { lat: number; lng: number }>> = {};
for (const [city, data] of Object.entries(PREVENTIVE_SNAPSHOT.cities)) {
  const centroids: Record<string, { lat: number; lng: number }> = {};
  for (const zone of data.zones) {
    if (zone.lat !== null && zone.lng !== null) {
      centroids[zone.zip] = { lat: zone.lat, lng: zone.lng };
    }
  }
  ZIP_CENTROIDS[city] = centroids;
}

function titleCase(value: string): string {
  return value
    .toLowerCase()
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

export function buildLeadZones(
  city: string,
  groups: LeadGeoGroup[]
): LeadZone[] {
  const zones = new Map<string, DraftZone>();

  const add = (
    name: string,
    group: LeadGeoGroup,
    extra: { neighborhood?: string; zip?: string; noGeo?: boolean }
  ) => {
    const zone =
      zones.get(name) ??
      ({
        name,
        count: 0,
        lat: null,
        lng: null,
        neighborhoods: [],
        zips: [],
        noGeo: false,
        weight: 0,
        latSum: 0,
        lngSum: 0,
      } satisfies DraftZone);

    zone.count += group.n;
    if (extra.neighborhood && !zone.neighborhoods.includes(extra.neighborhood)) {
      zone.neighborhoods.push(extra.neighborhood);
    }
    if (extra.zip && !zone.zips.includes(extra.zip)) {
      zone.zips.push(extra.zip);
    }
    if (extra.noGeo) zone.noGeo = true;
    const fallback = extra.zip ? ZIP_CENTROIDS[city]?.[extra.zip] : undefined;
    const lat = group.lat ?? fallback?.lat ?? null;
    const lng = group.lng ?? fallback?.lng ?? null;
    if (lat !== null && lng !== null) {
      zone.latSum += lat * group.n;
      zone.lngSum += lng * group.n;
      zone.weight += group.n;
    }
    zones.set(name, zone);
  };

  for (const group of groups) {
    if (group.kind === "nb") {
      const name =
        city === "NYC"
          ? titleCase(group.key)
          : city === "Chicago"
            ? (CHICAGO_COMMUNITY_AREAS[group.key] ?? `Area ${group.key}`)
            : group.key;
      add(name, group, { neighborhood: group.key });
      continue;
    }
    if (group.kind === "zip") {
      if (city === "NYC") {
        const borough = nycBorough(group.key);
        add(borough, group, {
          neighborhood: borough.toUpperCase(),
          zip: group.key,
        });
      } else if (city === "Boston") {
        add(BOSTON_ZIP_LABELS[group.key] ?? `ZIP ${group.key}`, group, {
          zip: group.key,
        });
      } else if (city === "Dallas") {
        add(DALLAS_ZIP_LABELS[group.key] ?? OTHER_AREAS, group, {
          zip: group.key,
        });
      } else {
        add(`ZIP ${group.key}`, group, { zip: group.key });
      }
      continue;
    }
    add(OTHER_AREAS, group, { noGeo: true });
  }

  return Array.from(zones.values())
    .map((zone) => ({
      name: zone.name,
      count: zone.count,
      lat: zone.weight > 0 ? zone.latSum / zone.weight : null,
      lng: zone.weight > 0 ? zone.lngSum / zone.weight : null,
      neighborhoods: zone.neighborhoods,
      zips: zone.zips,
      noGeo: zone.noGeo,
    }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

export function zoneFilterPayload(zone: LeadZone) {
  return {
    neighborhoods: zone.neighborhoods,
    zips: zone.zips,
    noGeo: zone.noGeo,
  };
}
