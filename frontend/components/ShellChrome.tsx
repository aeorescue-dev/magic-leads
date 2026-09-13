'use client';

import { usePathname } from "next/navigation";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";

export function ShellChrome() {
  const pathname = usePathname();
  const isLanding = pathname === "/";
  const isDashboard = pathname.startsWith("/dashboard");
  return (
    <>
      {!isLanding && !isDashboard && <Navbar />}
      {!isLanding && !isDashboard && <Footer />}
    </>
  );
}