/** @type {import('next').NextConfig} */
const path = require("path");
// Alvo do proxy `/api`. Default: produção. Num preview de staging, definir
// API_PROXY_TARGET no build para o backend de staging, sem alterar a produção.
const API_PROXY_TARGET = (
  process.env.API_PROXY_TARGET ||
  "https://magic-leads-production.up.railway.app"
).replace(/\/$/, "");
const nextConfig = {
  reactStrictMode: true,
  // Evita que o tracing suba até C:\Users e apanhe package-lock alheios.
  outputFileTracingRoot: path.join(__dirname),
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "https://magic-leads-production.up.railway.app",
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${API_PROXY_TARGET}/api/:path*`,
      },
      {
        // Links branded da vitrine: www.magicleads.app/r/<token> -> backend.
        source: '/r/:path*',
        destination: 'https://magic-leads-production.up.railway.app/r/:path*',
      },
      {
        // Opt-out branded: www.magicleads.app/unsubscribe -> backend.
        source: '/unsubscribe',
        destination: 'https://magic-leads-production.up.railway.app/unsubscribe',
      },
    ];
  },
  async headers() {
    const securityHeaders = [
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'X-Frame-Options', value: 'DENY' },
      { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
      {
        key: 'Permissions-Policy',
        value: 'geolocation=(self), camera=(), microphone=()',
      },
      {
        // Não fixa script-src: o App Router usa scripts inline. Bloqueia
        // incorporação e plugins, que é o ganho imediato e sem risco.
        key: 'Content-Security-Policy',
        value: "frame-ancestors 'none'; object-src 'none'; base-uri 'self'",
      },
    ];
    return [{ source: '/(.*)', headers: securityHeaders }];
  },
};

module.exports = nextConfig;