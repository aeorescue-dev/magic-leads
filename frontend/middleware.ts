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

  // Check if pathname already has locale prefix
  const pathnameHasLocale = LOCALES.some(
    (locale) => pathname.startsWith(`/${locale}/`) || pathname === `/${locale}`
  );

  // If no locale in path
  if (!pathnameHasLocale) {
    const cookieLocale = request.cookies.get("NEXT_LOCALE")?.value;
    const locale =
      cookieLocale && (LOCALES as readonly string[]).includes(cookieLocale)
        ? (cookieLocale as string)
        : DEFAULT_LOCALE;

    // Root "/": ALWAYS rewrite to DEFAULT_LOCALE (en) invisibly, ignoring any cookie
    if (pathname === "/") {
      const rewriteUrl = new URL(`/${DEFAULT_LOCALE}`, request.url);
      const response = NextResponse.rewrite(rewriteUrl);
      response.headers.set("x-middleware-locale", DEFAULT_LOCALE);
      // Clear any stale NEXT_LOCALE cookie that might force pt
      response.cookies.set("NEXT_LOCALE", DEFAULT_LOCALE, {
        path: "/",
        maxAge: 60 * 60 * 24 * 365, // 1 year
        sameSite: "lax",
        secure: true,
      });
      return response;
    }

    // Other paths: explicit redirect using cookie or DEFAULT_LOCALE
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
    const accessCookie = request.cookies.get("garimpador_access");
    if (accessCookie && accessCookie.value === "blocked" && !pathAfterLocale.startsWith("/checkout")) {
      const checkoutUrl = new URL("//checkout", request.url);
      return NextResponse.redirect(checkoutUrl);
    }

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