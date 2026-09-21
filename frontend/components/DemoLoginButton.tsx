'use client';

import { useRouter } from "next/navigation";
import { useI18n } from "@/lib/i18n";
import { demoLogin } from "@/lib/api-client";

interface DemoLoginButtonProps {
  children: React.ReactNode;
  variant?: "primary" | "light";
  className?: string;
}

export function DemoLoginButton({ children, variant = "primary", className = "" }: DemoLoginButtonProps) {
  const router = useRouter();
  const { lang } = useI18n();

  const localePath = (href: string) => `/${lang}${href}`;

  const handleClick = async () => {
    await demoLogin();
    router.push(localePath("/dashboard"));
  };

  const base =
    "px-8 py-3 rounded-lg font-semibold transition inline-block active:scale-[0.98]";
  const styles =
    variant === "light"
      ? "bg-white text-indigo-700 hover:bg-gray-100"
      : "bg-primary hover:bg-primary/90 text-primary-foreground";

  return (
    <button onClick={handleClick} className={`${base} ${styles} ${className}`}>
      {children}
    </button>
  );
}