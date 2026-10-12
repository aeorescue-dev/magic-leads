// Monta o caminho de destino de um redirect de locale PRESERVANDO a query
// string.
//
// Bug de produção (deep link das notificações push): o middleware redirecionava
// `/dashboard?lead=42` para `/{locale}/dashboard` reconstruindo o URL só com o
// pathname — a query string era descartada, pelo que o `?lead=42` (e qualquer
// outro parâmetro, como `?paid=1` ou `?fav=1`) desaparecia no redirect. O
// dashboard recebia a rota mas nunca o id do lead.
export function buildLocaleRedirectPath(
  pathname: string,
  locale: string,
  search: string = "",
): string {
  return `/${locale}${pathname}${search}`;
}
