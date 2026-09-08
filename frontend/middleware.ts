import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Protege as rotas protegidas verificando a sessão (cookie).
 * Verifica tanto o cookie garimpador_auth (MVP) quanto o garimpador_token (httpOnly).
 */
const PROTECTED = ["/dashboard"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isProtected = PROTECTED.some((p) => pathname.startsWith(p));

  if (isProtected) {
    // Verifica cookie de autenticação (MVP) ou token httpOnly
    const authCookie = request.cookies.get("garimpador_auth");
    const tokenCookie = request.cookies.get("garimpador_token");
    
    if ((!authCookie || !authCookie.value) && (!tokenCookie || !tokenCookie.value)) {
      return NextResponse.redirect(new URL("/", request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*"],
};