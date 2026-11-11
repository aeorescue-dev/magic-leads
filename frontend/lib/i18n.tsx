"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";

import EN from "./i18n/en";

export type Lang = "pt" | "en" | "es";

export const LANGS: { code: Lang; label: string; native: string }[] = [
  { code: "pt", label: "Português", native: "🇧🇷 PT" },
  { code: "en", label: "English", native: "🇺🇸 EN" },
  { code: "es", label: "Español", native: "🇲🇽 ES" },
];

export const LANGS_VALID: Lang[] = ["pt", "en", "es"];

const STORAGE_KEY = "NEXT_LOCALE";
const COOKIE_KEY = "NEXT_LOCALE";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // 1 ano

function setLocaleCookie(l: Lang) {
  if (typeof document === "undefined") return;
  // Secure só em HTTPS (produção). Em dev local (HTTP) o cookie seria descartado.
  const secure = window.location.protocol === "https:" ? "; secure" : "";
  document.cookie = `${COOKIE_KEY}=${encodeURIComponent(l)}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax${secure}`;
}

function getLocaleCookie(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|; )NEXT_LOCALE=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : null;
}

type Dict = Record<string, string>;

interface I18nCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, values?: Record<string, string | number>) => string;
}

const Ctx = createContext<I18nCtx>({
  lang: "en",
  setLang: () => {},
  t: (k, _v?) => k,
});

/**
 * Resolve o idioma inicial. Prioridade: escolha explícita (localStorage) →
 * cookie de locale → idioma do browser → **EN** (mercado principal, EUA).
 * Nunca infere PT por omissão.
 */
export function pickLang(
  stored: string | null,
  cookie: string | null,
  navigatorLang: string | null
): Lang {
  if (stored && LANGS_VALID.includes(stored as Lang)) return stored as Lang;
  if (cookie && LANGS_VALID.includes(cookie as Lang)) return cookie as Lang;
  const nav = (navigatorLang || "").toLowerCase().slice(0, 2);
  if (LANGS_VALID.includes(nav as Lang)) return nav as Lang;
  return "en";
}

function getInitialLang(): Lang {
  if (typeof window === "undefined") return "en";
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    /* storage indisponível */
  }
  let nav: string | null = null;
  try {
    nav = navigator.language || null;
  } catch {
    /* ignore */
  }
  return pickLang(stored, getLocaleCookie(), nav);
}

function persistLocale(l: Lang) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, l);
  } catch {
    /* storage indisponível (ex.: modo privado) */
  }
  setLocaleCookie(l);
}

export function LanguageProvider({ children, initialLocale }: { children: ReactNode; initialLocale?: Lang }) {
  const [lang, setLangState] = useState<Lang>(initialLocale || "en");
  const [dict, setDict] = useState<Dict>(EN);

  useEffect(() => {
    const initial = initialLocale || getInitialLang();
    setLangState(initial);
    persistLocale(initial);
  }, [initialLocale]);

  useEffect(() => {
    let active = true;
    if (lang === "en") {
      setDict(EN);
      return () => {
        active = false;
      };
    }
    const loader = lang === "pt" ? import("./i18n/pt") : import("./i18n/es");
    loader
      .then((mod) => {
        if (active) setDict(mod.default as Dict);
      })
      .catch(() => {
        if (active) setDict(EN);
      });
    return () => {
      active = false;
    };
  }, [lang]);

  const setLang = (l: Lang) => {
    setLangState(l);
    persistLocale(l);
  };

  // ICU MessageFormat pluralization support
function formatPlural(text: string, values: Record<string, string | number>): string {
  // Handle ICU MessageFormat pluralization: {var, plural, one {...} other {...}}
  // Supports format: {var} word{var, plural, one {singular} other {plural}}
  
  // First, process all plural rules
  let result = text;
  // Match ICU MessageFormat plural syntax with nested braces support
  // Matches: {var, plural, one {singular} other {plural}}
  const pluralRegex = /\{(\w+),\s*plural\s*,\s*((?:[^{}]|\{[^{}]*\})*)\}/g;
  
  result = result.replace(pluralRegex, (match, variable, pluralRules) => {
    const value = values[variable];
    if (value === undefined) return match;
    
    const num = typeof value === 'string' ? parseInt(value, 10) : Number(value);
    if (isNaN(num)) return match;

    // Parse plural rules: one {...} other {...} (simplified for PT/EN/ES)
    const rules: Record<string, string> = {};
    const ruleRegex = /(\w+)\s+\{([^}]+)\}/g;
    let ruleMatch;
    while ((ruleMatch = ruleRegex.exec(pluralRules)) !== null) {
      rules[ruleMatch[1]] = ruleMatch[2];
    }

    // Determine plural category (simplified for PT/EN/ES)
    let category = 'other';
    if (num === 1) category = 'one';
    else if (num === 0) category = 'zero';
    else if (num === 2) category = 'two';
    else if (num >= 3 && num <= 10) category = 'few';
    else if (num >= 11 && num <= 99) category = 'many';

    const selectedRule = rules[category] || rules['other'];
    if (!selectedRule) return match;

    // Return the selected plural form
    return selectedRule;
  });

  // After processing plural rules, replace remaining {var} with actual values
  for (const [key, value] of Object.entries(values)) {
    result = result.replace(new RegExp(`\\{${key}\\}`, 'g'), String(value));
  }

  return result;
}

const t = (key: string, values?: Record<string, string | number>) => {
  const translation = dict[key] ?? key;
  if (values && Object.keys(values).length > 0) {
    return formatPlural(translation, values);
  }
  return translation;
};

  return (
    <Ctx.Provider value={{ lang, setLang, t }}>{children}</Ctx.Provider>
  );
}

export function useI18n() {
  return useContext(Ctx);
}
