import type { Metadata } from "next";

// Painel interno: PT-only, sem prefixo de locale (/admin, não /pt/admin).
export const metadata: Metadata = {
  title: "Admin · Magic Leads",
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt" className="dark">
      <body className="min-h-screen bg-[#0b0d12] text-slate-200 antialiased">{children}</body>
    </html>
  );
}