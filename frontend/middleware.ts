import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const LOCALES = ["pt", "en", "es"] as const;
const DEFAULT_LOCALE = "en";

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

  // Check if pathname already has locale prefix (aceita /pt, /pt/, /en, /en/, /es, /es/)
  const pathnameHasLocale = LOCALES.some(
    (locale) => pathname.startsWith(`/${locale}/`) || pathname === `/${locale}` || pathname === `/${locale}/`
  );

  // If no locale in path, redirect to the locale the USER chose (cookie NEXT_LOCALE),
  // falling back to the default. For root "/", rewrite to default locale invisibly
  // (no URL change). For other paths, redirect explicitly.
  if (!pathnameHasLocale) {
    const cookieLocale = request.cookies.get("NEXT_LOCALE")?.value;
    const locale =
      cookieLocale && (LOCALES as readonly string[]).includes(cookieLocale)
        ? (cookieLocale as string)
        : DEFAULT_LOCALE;

    // Root "/": rewrite to default locale invisibly (no URL change)
    if (pathname === "/") {
      const rewriteUrl = new URL(`/${locale}`, request.url);
      const response = NextResponse.rewrite(rewriteUrl);
      response.headers.set("x-middleware-locale", locale);
      return response;
    }

    // Other paths: explicit redirect to locale prefix
    const target = `/${locale}${pathname}`;
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