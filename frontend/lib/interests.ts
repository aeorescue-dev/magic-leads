/**
 * Selecção de interesses (categorias de alerta) — lógica pura.
 *
 * INVARIANTE (espelha o backend):
 *   O backend trata "sem interesses gravados" como "todas as categorias"
 *   (ver `db.py`, `OR NOT EXISTS (SELECT 1 FROM user_interests ...)`).
 *   Logo, um conjunto VAZIO nunca pode ser persistido como "zero": o
 *   utilizador voltaria a receber alertas de tudo.
 *
 *   Consequência no frontend: a selecção NUNCA fica vazia — desmarcar a
 *   última categoria volta a marcar todas. Quem ainda não escolheu nada é
 *   encaminhado para o Onboarding Wizard (`needsOnboarding` em
 *   `lib/categories.ts`), em vez de receber o default silenciosamente.
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
