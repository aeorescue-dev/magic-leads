"use client";

import { usePathname } from "next/navigation";
import { NavbarNew } from "@/components/NavbarNew";
import { Footer } from "@/components/Footer";

export function DashboardShell({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <NavbarNew />
      {children}
      <Footer />
    </>
  );
}