import EN from "./en";
import ES from "./es";
import PT from "./pt";

type Lang = "pt" | "en" | "es";

export const DICTS: Record<Lang, Record<string, string>> = {
  pt: PT,
  en: EN,
  es: ES,
};
