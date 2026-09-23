/**
 * Página raiz "/".
 *
 * Não forçamos default de idioma aqui: o middleware faz rewrite invisível
 * de "/" para "/en" (URL limpo, sem mudança na barra de endereços) e limpa
 * qualquer cookie NEXT_LOCALE antigo que force /pt.
 */
export default function RootPage() {
  return <></>;
}
