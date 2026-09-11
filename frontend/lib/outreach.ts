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

function template(D: Record<string, string>, key: string): string {
  const v = D[key];
  return typeof v === "string" && v.length > 0 ? v : "";
}

function pickLine(D: Record<string, string>, channel: "wa" | "sms" | "email", category: string): string {
  const direct = template(D, `outreach.${channel}.${category}`);
  if (direct) return direct;
  return template(D, `outreach.${channel}.${FALLBACK_CATEGORY}`);
}

export function buildOutreachMessage(data: OutreachData): OutreachMessage {
  const lang: Lang =
    data.lang && LANGS_VALID.includes(data.lang) ? data.lang : OUTREACH_DEFAULT_LANG;
  const D = DICTS[lang] ?? DICTS.en;
  const owner = (data.owner || "").trim() || "—";
  const company = (data.company || "").trim() || "—";
  const city = (data.city || "").trim();
  const category = data.category || FALLBACK_CATEGORY;

  const waLine = pickLine(D, "wa", category);
  const smsLine = pickLine(D, "sms", category);
  const emailLine = pickLine(D, "email", category);

  const fill = (s: string) =>
    s
      .replaceAll("{nome}", owner)
      .replaceAll("{empresa}", company)
      .replaceAll("{cidade}", city);
  const applyLine = (s: string, line: string) => fill(s).replaceAll("{linha}", line);

  return {
    whatsapp: applyLine(template(D, "outreach.whatsapp_body"), waLine),
    sms: applyLine(template(D, "outreach.sms_body"), smsLine),
    emailSubject: fill(template(D, "outreach.email_subject")),
    emailBody: applyLine(template(D, "outreach.email_body"), emailLine),
  };
}