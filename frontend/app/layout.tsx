/**
 * Root layout — apenas um invólucro transparente.
 *
 * NÃO faças redirect("/pt") aqui: qualquer redirect forçado na raiz colide
 * com o middleware (que faz rewrite invisível para /en) e gera o loop
 * ERR_TOO_MANY_REDIRECTS. O layout de <html>/<body> vive em [locale]/layout.tsx,
 * que é quem resolve o locale e aplica o idioma escolhido pelo utilizador.
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
