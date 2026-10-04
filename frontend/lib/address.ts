/**
 * Formatacao de endereco para exibicao.
 *
 * Modulo propositadamente sem dependencias: e usado por componentes cliente
 * (mapa, cartoes, modal) que nao precisam do dicionario de i18n.
 *
 * Porquê o dedupe: o `address` gravado pelo scraper embebe a cidade e o estado
 * ("854 EAST NEW YORK AVENUE, NYC, NY") e a cidade existe tambem como coluna
 * propria. Concatenar os dois sem verificacao produzia
 * "854 EAST NEW YORK AVENUE, NYC, NY, NYC" em 100% dos leads. A cidade so e
 * acrescentada quando o address nao a contem, o que da o resultado correcto
 * tanto para os dados legados (address com cidade embutida) como para os novos
 * (address so com a rua).
 */

/** minusculas, sem acentos, para comparar cidade dentro do address. */
function normalise(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

/**
 * Address completo para exibicao, sem repetir a cidade.
 *
 *   buildFullAddress("854 EAST NEW YORK AVENUE, NYC, NY", "NYC")
 *     -> "854 EAST NEW YORK AVENUE, NYC, NY"
 *   buildFullAddress("2008 HALSTED", "Chicago")
 *     -> "2008 HALSTED, Chicago"
 */
export function buildFullAddress(address?: string | null, city?: string | null): string {
  const street = (address || "").trim().replace(/,\s*$/, "");
  const place = (city || "").trim();
  if (!place) return street;
  if (!street) return place;
  const alreadyThere = normalise(street).includes(normalise(place));
  return alreadyThere ? street : `${street}, ${place}`;
}
