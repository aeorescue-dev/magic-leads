'use client';

import { usePathname } from "next/navigation";
import { NavbarNew } from "@/components/NavbarNew";
import { Footer } from "@/components/Footer";

export function ShellChrome() {
  const pathname = usePathname();
  const isLanding = pathname === "/";
  const isDashboard = pathname.startsWith("/dashboard");
  return (
    <>
      {!isLanding && !isDashboard && <NavbarNew />}
      {!isLanding && !isDashboard && <Footer />}
    </>
  );
}