import { DICTS, LANGS_VALID, Lang } from "@/lib/i18n";

export interface OutreachData {
  owner?: string;
  company?: string;
  city?: string;
  category?: string;
  lang?: Lang;
}

export interface OutreachMessage {
  whatsapp: string;
  sms: string;
  emailSubject: string;
  emailBody: string;
}

export const OUTREACH_DEFAULT_LANG: Lang = "en";
const FALLBACK_CATEGORY = "Other";

/** Substituto de {nome} quando o nome do proprietário não é conhecido. */
const GREETING_FALLBACK: Record<Lang, string> = { en: "there", pt: "", es: "" };

function template(D: Record<string, string>, key: string): string {
  const v = D[key];
  return typeof v === "string" && v.length > 0 ? v : "";
}

function pickLine(D: Record<string, string>, channel: "wa" | "sms" | "email", category: string): string {
  const direct = template(D, `outreach.${channel}.${category}`);
  if (direct) return direct;
  return template(D, `outreach.${channel}.${FALLBACK_CATEGORY}`);
}

/** Normaliza espaços e pontuação órfã deixados por um token removido. */
function tidy(s: string): string {
  return s
    .replace(/[ \t]+/g, " ")
    .replace(/ +([,.;:!?])/g, "$1")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function capitalizeFirst(s: string): string {
  return s ? s.charAt(0).toLocaleUpperCase() + s.slice(1) : s;
}

/**
 * Remove a frase (ou cláusula) que contém um token sem valor, em vez de
 * a substituir por texto vazio. Evita mensagens como "Hi there, this is ."
 * e o duplo travessão "this is  — free assessment".
 */
function stripEmptyClauses(s: string, tokens: string[], mode: "sentence" | "emdash"): string {
  if (tokens.length === 0) return s;
  const has = (part: string) => tokens.some((tk) => part.includes(tk));
  return s
    .split("\n\n")
    .map((para) => {
      const parts = mode === "emdash" ? para.split(/\s+—\s+/) : para.split(/(?<=[.!?])\s+/);
      const kept = parts.filter((p) => !has(p));
      return kept.join(mode === "emdash" ? " — " : " ");
    })
    .filter((para) => para.length > 0)
    .join("\n\n");
}

export function buildOutreachMessage(data: OutreachData): OutreachMessage {
  const lang: Lang =
    data.lang && LANGS_VALID.includes(data.lang) ? data.lang : OUTREACH_DEFAULT_LANG;
  const D = DICTS[lang] ?? DICTS.en;
  const owner = (data.owner || "").trim();
  const company = (data.company || "").trim();
  const city = (data.city || "").trim();
  const category = data.category || FALLBACK_CATEGORY;

  const waLine = pickLine(D, "wa", category);
  const smsLine = pickLine(D, "sms", category);
  const emailLine = pickLine(D, "email", category);

  // Tokens sem valor: o {nome} degrada para saudação neutra; {empresa}/{cidade}
  // fazem a frase que os contém ser removida por completo. A remoção tem de
  // ocorrer ANTES da substituição, enquanto o token ainda é identificável.
  const emptyTokens = [company ? "" : "{empresa}", city ? "" : "{cidade}"].filter(Boolean);

  const fill = (s: string, mode: "sentence" | "emdash" = "sentence") =>
    tidy(
      stripEmptyClauses(s, emptyTokens, mode)
        .replaceAll("{nome}", owner || GREETING_FALLBACK[lang])
        .replaceAll("{empresa}", company)
        .replaceAll("{cidade}", city)
    );

  const applyLine = (s: string, line: string) => {
    const filled = fill(s);
    // "{linha}" a seguir a uma vírgula continua a frase: "…, roof and gutter services."
    return filled.replaceAll("{linha}", (_match, offset: number) =>
      /,\s$/.test(filled.slice(0, offset))
        ? line.charAt(0).toLocaleLowerCase() + line.slice(1)
        : line
    );
  };

  return {
    whatsapp: applyLine(template(D, "outreach.whatsapp_body"), waLine),
    sms: applyLine(template(D, "outreach.sms_body"), smsLine),
    emailSubject: capitalizeFirst(fill(template(D, "outreach.email_subject"), "emdash")),
    emailBody: applyLine(template(D, "outreach.email_body"), emailLine),
  };
}