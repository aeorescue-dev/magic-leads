import type { Metadata } from "next";
import AdminNav from "@/components/admin/AdminNav";

// Painel interno: PT-only, sem prefixo de locale (/admin, não /pt/admin).
// Importa o CSS global (Tailwind base + componentes) para que o painel tenha estilos em produção.
import "../globals.css";

export const metadata: Metadata = {
  title: "Admin · Magic Leads",
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt" className="dark">
      <body className="min-h-screen bg-[#080a0f] text-slate-200 antialiased">
        <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(900px_500px_at_10%_-10%,rgba(16,185,129,0.10),transparent),radial-gradient(800px_500px_at_90%_0%,rgba(56,189,248,0.08),transparent)]" />
        <AdminNav />
        {children}
      </body>
    </html>
  );
}
