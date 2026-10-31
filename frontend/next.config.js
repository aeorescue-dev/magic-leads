/** @type {import('next').NextConfig} */
const path = require("path");
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
        destination: 'https://magic-leads-production.up.railway.app/api/:path*',
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