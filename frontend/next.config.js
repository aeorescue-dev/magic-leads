/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
};

module.exports = nextConfig;