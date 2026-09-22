import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const LOCALES = ["pt", "en", "es"] as const;
const DEFAULT_LOCALE = "pt";

const PROTECTED_PATHS = ["/dashboard"];

export function middleware(request: NextRequest) {
  let { pathname } = request.nextUrl;
  pathname = pathname.replace(/\/+$/, "") || "/";

  // Skip static files, API routes, internal paths
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/static") ||
    pathname.includes(".") ||
    pathname === "/favicon.ico" ||
    pathname === "/manifest.json" ||
    pathname === "/robots.txt" ||
    pathname === "/sitemap.xml"
  ) {
    return NextResponse.next();
  }

  // Check if pathname already has locale prefix
  const pathnameHasLocale = LOCALES.some(
    (locale) => pathname.startsWith(`/${locale}/`) || pathname === `/${locale}`
  );

  // If no locale in path, redirect to default locale (sem barra final -> evita loop /pt/ <-> /pt)
  if (!pathnameHasLocale) {
    const locale = DEFAULT_LOCALE;
    const target = `/${locale}${pathname === "/" ? "" : pathname}`;
    if (target === pathname) return NextResponse.next();
    const redirectUrl = new URL(target, request.url);
    return NextResponse.redirect(redirectUrl);
  }

  // Extract locale from path
  const locale = pathname.split("/")[1];

  // Check if path is protected (after locale)
  const pathAfterLocale = pathname.slice(locale.length + 1) || "/";
  const isProtected = PROTECTED_PATHS.some((p) => pathAfterLocale.startsWith(p));

  if (isProtected) {
    const authCookie = request.cookies.get("garimpador_auth");
    const tokenCookie = request.cookies.get("garimpador_token");

    if ((!authCookie || !authCookie.value) && (!tokenCookie || !tokenCookie.value)) {
      const loginUrl = new URL(`/${locale}/`, request.url);
      return NextResponse.redirect(loginUrl);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|manifest.json|api/).*)",
  ],
};