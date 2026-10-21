/**
 * Selecção de interesses (categorias de alerta) — lógica pura.
 *
 * INVARIANTE (espelha o backend):
 *   O backend trata "sem interesses gravados" como "todas as categorias"
 *   (ver `db.py`, `OR NOT EXISTS (SELECT 1 FROM user_interests ...)`).
 *   Logo, um conjunto VAZIO nunca pode ser persistido como "zero": o
 *   utilizador voltaria a receber alertas de tudo.
 *
 *   Consequência no frontend (bug corrigido): o dashboard auto-persiste as
 *   16 categorias quando o servidor devolve lista vazia. Se o utilizador
 *   pudesse desmarcar todas, o PUT gravava vazio e, no reload seguinte, o
 *   auto-PUT repunha as 16 — a escolha do utilizador desaparecia sozinha.
 *
 *   Por isso a selecção NUNCA fica vazia: desmarcar a última categoria volta
 *   a marcar todas, que e' exactamente o que o backend faria com o vazio.
 */

/**
 * Alterna uma categoria na selecção actual.
 *
 * @param current  Categorias seleccionadas.
 * @param key      Categoria a alternar.
 * @param allKeys  Todas as categorias da plataforma (usado quando a
 *                  selecção ficaria vazia).
 * @returns O novo conjunto — nunca vazio.
 */
export function toggleInterestKey(
  current: Iterable<string>,
  key: string,
  allKeys: readonly string[]
): Set<string> {
  const next = new Set(current);
  if (next.has(key)) next.delete(key);
  else next.add(key);

  // Invariante: sem categorias == todas as categorias (ver backend).
  if (next.size === 0) return new Set(allKeys);
  return next;
}

/**
 * Decide se a selecção actual precisa de ser persistida.
 *
 * O dashboard auto-persiste as 16 categorias quando o servidor devolve lista
 * vazia (para tornar o estado explicito no backend). Isso so' faz sentido
 * para um utilizador que NUNCA configurou interesses.
 */
export function shouldSeedDefaultInterests(
  serverCategories: string[] | null | undefined,
  touchedByUser: boolean
): boolean {
  if (touchedByUser) return false;
  return !Array.isArray(serverCategories) || serverCategories.length === 0;
}
