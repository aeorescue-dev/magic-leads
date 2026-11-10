"use client";

import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowRight,
  CheckCircle2,
  Flame,
  Loader2,
  Lock,
  Moon,
  Paperclip,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  createLpThread,
  fetchLpAvailability,
  fetchLpThread,
  lpAttachmentUrl,
  sendLpFollowUp,
  trackLpWidget,
  uploadLpAttachment,
  type LpAttachment,
  type LpAvailability,
} from "@/lib/lp-widget";
import {
  LP_CITIES,
  LP_FLOWS,
  LP_INTENTS,
  LP_SAMPLES,
  type LpIntentFlow,
  type LpIntentKey,
} from "./data";
import LpLanguagePicker from "./LpLanguagePicker";
import {
  INTENT_L10N,
  TRADE_OPTIONS,
  WIDGET_COPY,
  WIDGET_SOURCES,
  type WidgetLang,
} from "./i18n";

export interface LpDemoSubmission {
  intent: LpIntentKey;
  question: string;
  email: string;
  name: string;
  company: string;
  city: string;
  trade: string;
  source: string;
}

type Step = 1 | 2 | 3 | 4 | 5;

interface ThreadItem {
  id: string;
  role: "lead" | "team" | "system";
  text: string;
  at: number;
  messageId?: number;
}

export interface LpWidgetPanelProps {
  mode: "demo" | "live";
  onClose: () => void;
  onIntentChange?: (
    intent: LpIntentKey | null,
    question?: string,
    defaultQuestion?: string
  ) => void;
  onLanguageChange?: (lang: WidgetLang) => void;
  onDemoSubmit?: (submission: LpDemoSubmission) => void;
  teamReply?: { text: string; at: number } | null;
  className?: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function WidgetMessageAttachments({
  token,
  attachments,
}: {
  token: string;
  attachments: LpAttachment[];
}) {
  return (
    <div className="mt-1.5 space-y-1">
      {attachments.map((attachment) => {
        const url = lpAttachmentUrl(token, attachment.id);
        const isImage = (attachment.content_type || "").startsWith("image/");
        return (
          <a
            key={attachment.id}
            href={url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 rounded-lg border border-white/80 bg-white/80 p-1.5 transition hover:border-emerald-300"
          >
            {isImage ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={url}
                alt={attachment.filename}
                className="h-10 w-10 shrink-0 rounded object-cover ring-1 ring-slate-200"
              />
            ) : (
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-white text-slate-500 ring-1 ring-slate-200">
                <Paperclip className="h-3.5 w-3.5" />
              </span>
            )}
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[9.5px] font-bold text-slate-800">
                {attachment.filename}
              </span>
              <span className="block text-[8.5px] text-slate-500">
                {Math.max(1, Math.round(attachment.size_bytes / 1024))} KB
              </span>
            </span>
          </a>
        );
      })}
    </div>
  );
}

function now(): number {
  return Date.now();
}

function toThreadItems(
  messages: {
    id: number;
    role: "lead" | "team";
    text: string;
    created_at: string;
  }[]
): ThreadItem[] {
  return messages.map((message) => ({
    id: `${message.role}-${message.id}`,
    role: message.role,
    text: message.text,
    at: Number(new Date(message.created_at)) || now(),
    messageId: message.id,
  }));
}

export default function LpWidgetPanel({
  mode,
  onClose,
  onIntentChange,
  onLanguageChange,
  onDemoSubmit,
  teamReply,
  className = "",
}: LpWidgetPanelProps) {
  const titleId = useId();
  const followUpId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const demoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [lang, setLang] = useState<WidgetLang>("en");
  const [edited, setEdited] = useState(false);
  const [step, setStep] = useState<Step>(1);
  const [intent, setIntent] = useState<LpIntentKey | null>(null);
  const [trade, setTrade] = useState("");
  const [tradeCode, setTradeCode] = useState("");
  const [city, setCity] = useState("");
  const [source, setSource] = useState("");
  const [question, setQuestion] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [sending, setSending] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<LpAttachment[]>([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [attachmentError, setAttachmentError] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [followUpSending, setFollowUpSending] = useState(false);
  const [followUpError, setFollowUpError] = useState("");
  const [availability, setAvailability] = useState<LpAvailability | null>(null);

  useEffect(() => {
    if (mode !== "live") return;
    let active = true;
    const load = () => {
      fetchLpAvailability()
        .then((data) => {
          if (active) setAvailability(data);
        })
        .catch(() => {
          // Sem disponibilidade, o widget assume o estado normal (nunca bloqueia).
        });
    };
    load();
    const interval = window.setInterval(load, 60000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [mode]);

  const offline = availability?.status === "offline";

  const attachmentsByMessage = useMemo(() => {
    const map = new Map<number, LpAttachment[]>();
    for (const attachment of attachments) {
      if (attachment.message_id) {
        const list = map.get(attachment.message_id) || [];
        list.push(attachment);
        map.set(attachment.message_id, list);
      }
    }
    return map;
  }, [attachments]);

  const totalSteps = 4;
  const currentStep =
    step === 5 ? 4 : Math.min(step, 4);

  const displayThread = useMemo(() => {
    if (!teamReply) return thread;
    const id = `team-${teamReply.at}`;
    if (thread.some((item) => item.id === id)) return thread;
    return [
      ...thread,
      {
        id,
        role: "team" as const,
        text: teamReply.text,
        at: teamReply.at,
      },
    ];
  }, [thread, teamReply]);

  const replied = displayThread.some((item) => item.role === "team");

  const secondaryIntents = useMemo(
    () =>
      LP_INTENTS.filter(
        (item) => item.key !== "vs_ads" && item.key !== "question"
      ),
    []
  );

  const copy = WIDGET_COPY[lang];

  function flowCopy(flow: LpIntentFlow) {
    if (lang === "en") {
      return { chip: flow.chip, sub: flow.sub, question: flow.question };
    }
    return INTENT_L10N[lang][flow.key];
  }

  function changeLang(next: WidgetLang) {
    setLang(next);
    onLanguageChange?.(next);
    if (!intent) return;
    const nextDefault =
      next === "en"
        ? LP_FLOWS[intent].question
        : INTENT_L10N[next][intent].question;
    if (!edited) {
      setQuestion(nextDefault);
      onIntentChange?.(intent, nextDefault, nextDefault);
    } else {
      onIntentChange?.(intent, question, nextDefault);
    }
  }

  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    panelRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, []);

  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [displayThread, sending]);

  useEffect(() => {
    if (mode !== "live" || !token || step !== 5) return;
    let stopped = false;
    const load = async () => {
      try {
        const data = await fetchLpThread(token);
        if (stopped) return;
        setThread(toThreadItems(data.messages));
        setAttachments(data.attachments || []);
        if (data.messages.some((message) => message.role === "team")) {
          setSending(false);
        }
      } catch {
        // Polling silencioso: a UI mantém a última conversa conhecida.
      }
    };
    void load();
    const interval = window.setInterval(load, 5000);
    return () => {
      stopped = true;
      window.clearInterval(interval);
    };
  }, [mode, token, step]);

  useEffect(() => {
    if (mode !== "live") return;
    let stored: string | null = null;
    try {
      stored = window.sessionStorage.getItem("lp_widget_thread");
    } catch {
      return;
    }
    if (!stored) return;
    let active = true;
    fetchLpThread(stored)
      .then((data) => {
        if (!active) return;
        setToken(stored);
        setThread(toThreadItems(data.messages));
        setAttachments(data.attachments || []);
        setSending(false);
        setStep(5);
      })
      .catch((err) => {
        const status = (err as { status?: number } | null)?.status;
        if (status === 400 || status === 404) {
          try {
            window.sessionStorage.removeItem("lp_widget_thread");
          } catch {
            // sessão indisponível
          }
        }
      });
    return () => {
      active = false;
    };
  }, [mode]);

  useEffect(() => {
    return () => {
      if (demoTimer.current) clearTimeout(demoTimer.current);
    };
  }, []);

  function resetAll() {
    setStep(1);
    setIntent(null);
    setTrade("");
    setTradeCode("");
    setCity("");
    setSource("");
    setQuestion("");
    setEmail("");
    setName("");
    setCompany("");
    setConsent(false);
    setError("");
    setEdited(false);
    setThread([]);
    setSending(false);
    setToken(null);
    setAttachments([]);
    setFollowUp("");
    setFollowUpSending(false);
    setFollowUpError("");
    try {
      window.sessionStorage.removeItem("lp_widget_thread");
    } catch {
      // sessão indisponível
    }
    onIntentChange?.(null);
    trackLpWidget("lp_widget_reset");
  }

  function selectIntent(key: LpIntentKey) {
    const nextCopy = flowCopy(LP_FLOWS[key]);
    setIntent(key);
    setQuestion(nextCopy.question);
    setEdited(false);
    setError("");
    setThread([]);
    setToken(null);
    setAttachments([]);
    setStep(2);
    onIntentChange?.(key, nextCopy.question, nextCopy.question);
    trackLpWidget("lp_widget_intent", { intent: key });
  }

  function startCustom() {
    const nextCopy = flowCopy(LP_FLOWS.question);
    setIntent("question");
    setQuestion(nextCopy.question);
    setEdited(false);
    setError("");
    setThread([]);
    setToken(null);
    setAttachments([]);
    setStep(2);
    onIntentChange?.("question", nextCopy.question, nextCopy.question);
    trackLpWidget("lp_widget_intent", { intent: "question" });
  }

  function backFromContact() {
    setStep(3);
  }

  function validate(): boolean {
    if (!question.trim()) {
      setError(copy.errMessage);
      return false;
    }
    if (!EMAIL_RE.test(email.trim())) {
      setError(copy.errEmail);
      return false;
    }
    if (!consent) {
      setError(copy.errConsent);
      return false;
    }
    setError("");
    return true;
  }

  async function submit() {
    if (!intent || !validate()) return;
    const payload = {
      intent,
      question: question.trim(),
      email: email.trim(),
      name: name.trim(),
      company: company.trim(),
      city,
      trade,
      source,
    };

    setSending(true);
    setStep(5);
    setAttachments([]);
    setThread([
      {
        id: `lead-${now()}`,
        role: "lead",
        text: question.trim(),
        at: now(),
      },
      {
        id: `system-${now()}`,
        role: "system",
        text: copy.systemAck,
        at: now(),
      },
    ]);
    trackLpWidget("lp_widget_submit", {
      intent,
      city: city || undefined,
      trade: trade || undefined,
      source: source || undefined,
      mode,
    });

    if (mode === "demo") {
      onDemoSubmit?.(payload);
      if (demoTimer.current) clearTimeout(demoTimer.current);
      demoTimer.current = setTimeout(() => setSending(false), 900);
      return;
    }

    try {
      const result = await createLpThread({
        intent,
        message: payload.question,
        email: payload.email,
        name: payload.name,
        company: payload.company,
        city: payload.city,
        trade: payload.trade,
        trade_code: tradeCode,
        lead_source: source,
        consent_email: consent,
        locale:
          typeof document !== "undefined"
            ? document.documentElement.lang || "en"
            : "en",
        source_section: "landing_inline",
        website: "",
      });
      setToken(result.token);
      if (result.availability) setAvailability(result.availability);
      setSending(false);
      try {
        window.sessionStorage.setItem("lp_widget_thread", result.token);
      } catch {
        // sessão indisponível
      }
    } catch (err) {
      setSending(false);
      setError(
        err instanceof Error
          ? err.message
          : copy.networkError
      );
    }
  }

  function checkAvailability() {
    resetAll();
    selectIntent("area");
  }

  async function uploadAttachment(file: File) {
    if (!token) return;
    setUploadingAttachment(true);
    setAttachmentError("");
    try {
      const attachment = await uploadLpAttachment(token, file);
      setAttachments((prev) => [...prev, attachment]);
    } catch {
      setAttachmentError(copy.attachError);
    } finally {
      setUploadingAttachment(false);
    }
  }

  async function sendFollowUpMessage() {
    const text = followUp.trim();
    if (!token || !text || followUpSending) return;
    const optimisticId = `lead-local-${Date.now()}`;
    setFollowUpSending(true);
    setFollowUpError("");
    setFollowUp("");
    setThread((prev) => [
      ...prev,
      { id: optimisticId, role: "lead", text, at: now() },
    ]);
    try {
      await sendLpFollowUp(token, text);
      trackLpWidget("lp_widget_follow_up");
    } catch {
      setFollowUpError(copy.followUpError);
      setFollowUp(text);
      setThread((prev) => prev.filter((item) => item.id !== optimisticId));
    } finally {
      setFollowUpSending(false);
    }
  }

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      tabIndex={-1}
      className={`fixed bottom-4 right-4 z-[80] flex max-h-[min(760px,calc(100dvh-24px))] w-[calc(100vw-24px)] max-w-[430px] flex-col overflow-visible rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-slate-900/15 outline-none ${className}`}
    >
      <header className="flex items-center gap-2 rounded-t-2xl border-b border-slate-100 bg-white px-4 py-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-[11px] font-black text-emerald-700 ring-1 ring-emerald-100">
          ML
        </div>
        <div className="min-w-0 flex-1">
          <p id={titleId} className="truncate text-[13px] font-bold text-slate-900">
            Magic Leads
          </p>
          <p className="mt-0.5 flex items-center gap-1.5 truncate text-[10.5px] text-slate-500">
            <span
              className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                offline ? "bg-amber-500" : "bg-emerald-500"
              }`}
            />
            {offline ? copy.offlineStatus : copy.online}
          </p>
        </div>
        <LpLanguagePicker
          lang={lang}
          onChange={changeLang}
          title={copy.language}
          searchPlaceholder={copy.searchLanguage}
          emptyLabel={copy.noLanguage}
        />
        <button
          type="button"
          onClick={onClose}
          aria-label={copy.close}
          className="shrink-0 rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-50 hover:text-slate-700"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="flex gap-1.5 px-4 pt-3">
        {Array.from({ length: totalSteps }).map((_, index) => (
          <span
            key={index}
            className={`h-1 flex-1 rounded-full transition-colors ${
              index < currentStep ? "bg-emerald-500" : "bg-slate-100"
            }`}
          />
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-4 pt-3">
        {step === 1 && (
          <div>
            <p className="text-[15px] font-bold tracking-tight text-slate-900">
              {copy.q1}
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
              {copy.hint1}
            </p>

            <div className="mt-3 space-y-2">
              <button
                type="button"
                onClick={() => selectIntent("vs_ads")}
                className="group flex w-full items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50/60 p-3 text-left transition hover:border-emerald-300 hover:bg-emerald-50"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-amber-500 ring-1 ring-amber-100">
                  <Flame className="h-4 w-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[12.5px] font-bold leading-snug text-slate-900">
                    {flowCopy(LP_FLOWS.vs_ads).chip}
                  </span>
                  <span className="mt-0.5 block text-[10.5px] leading-snug text-slate-500">
                    {flowCopy(LP_FLOWS.vs_ads).sub}
                  </span>
                </span>
                <ArrowRight className="h-4 w-4 shrink-0 text-emerald-500 transition group-hover:translate-x-0.5" />
              </button>

              <div className="grid grid-cols-1 gap-2 min-[390px]:grid-cols-2">
                {secondaryIntents.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => selectIntent(item.key)}
                    className="group rounded-xl border border-slate-200 bg-white p-2.5 text-left transition hover:border-emerald-300 hover:bg-emerald-50/40"
                  >
                    <span className="block text-[11.5px] font-bold leading-snug text-slate-900">
                      {flowCopy(item).chip}
                    </span>
                    <span className="mt-1 flex items-center justify-between gap-2 text-[9.5px] leading-snug text-slate-500">
                      {flowCopy(item).sub}
                      <ArrowRight className="h-3 w-3 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-emerald-500" />
                    </span>
                  </button>
                ))}
              </div>
            </div>

            <button
              type="button"
              onClick={startCustom}
              className="mt-2 w-full py-1 text-center text-[10.5px] font-semibold text-emerald-700 underline underline-offset-2 hover:text-emerald-800"
            >
              {copy.somethingElse}
            </button>
            <p className="mt-2 text-center text-[10px] text-slate-400">
              {copy.micro}
            </p>
          </div>
        )}

        {step === 2 && (
          <div>
            <p className="text-[15px] font-bold tracking-tight text-slate-900">
              {copy.tradeTitle}
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
              {copy.tradeHint}
            </p>

            <div className="mt-3 grid max-h-56 grid-cols-2 gap-1.5 overflow-y-auto pr-1">
              {TRADE_OPTIONS.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => {
                    setTrade(option.en);
                    setTradeCode(option.key);
                  }}
                  aria-pressed={trade === option.en}
                  className={`rounded-lg border px-2.5 py-2 text-left text-[10.5px] font-semibold leading-tight transition ${
                    trade === option.en
                      ? "border-emerald-500 bg-emerald-500 text-white"
                      : "border-slate-200 bg-white text-slate-600 hover:border-emerald-300"
                  }`}
                >
                  {option[lang]}
                </button>
              ))}
            </div>

            <p className="mt-3 text-[9px] font-black uppercase tracking-wide text-slate-400">
              {copy.cityLabel}
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {LP_CITIES.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setCity(item)}
                  aria-pressed={city === item}
                  className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold transition ${
                    city === item
                      ? "border-emerald-500 bg-emerald-500 text-white"
                      : "border-slate-200 bg-white text-slate-600 hover:border-emerald-300"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>

            <button
              type="button"
              disabled={!trade || !city}
              onClick={() => setStep(3)}
              className="mt-4 w-full rounded-lg bg-emerald-500 py-2.5 text-[12.5px] font-bold text-white transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {copy.continue}
            </button>
            <button
              type="button"
              onClick={() => setStep(1)}
              className="mt-2 w-full py-1 text-[11px] font-semibold text-slate-400 hover:text-slate-600"
            >
              {copy.back}
            </button>
          </div>
        )}

        {step === 3 && (
          <div>
            <p className="text-[15px] font-bold tracking-tight text-slate-900">
              {copy.sourceTitle}
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
              {copy.sourceHint}
            </p>

            <div className="mt-3 space-y-2">
              {WIDGET_SOURCES.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => setSource(option.key)}
                  aria-pressed={source === option.key}
                  className={`flex w-full items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition ${
                    source === option.key
                      ? "border-emerald-500 bg-emerald-50"
                      : "border-slate-200 bg-white hover:border-emerald-300"
                  }`}
                >
                  <span
                    className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border ${
                      source === option.key
                        ? "border-emerald-500"
                        : "border-slate-300"
                    }`}
                  >
                    {source === option.key && (
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    )}
                  </span>
                  <span className="text-[11px] font-semibold leading-snug text-slate-800">
                    {option[lang]}
                  </span>
                </button>
              ))}
            </div>

            <button
              type="button"
              disabled={!source}
              onClick={() => setStep(4)}
              className="mt-4 w-full rounded-lg bg-emerald-500 py-2.5 text-[12.5px] font-bold text-white transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {copy.continue}
            </button>
            <button
              type="button"
              onClick={() => setStep(2)}
              className="mt-2 w-full py-1 text-[11px] font-semibold text-slate-400 hover:text-slate-600"
            >
              {copy.back}
            </button>
          </div>
        )}

        {step === 4 && (
          <div>
            <p className="text-[15px] font-bold tracking-tight text-slate-900">
              {copy.q3}
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
              {copy.hint3}
            </p>

            {intent === "question" && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {LP_SAMPLES.map((sample) => {
                  const sampleText = lang === "pt" ? sample.pt : sample.en;
                  return (
                    <button
                      key={sample.en}
                      type="button"
                      onClick={() => {
                        setQuestion(sampleText);
                        setEdited(false);
                        onIntentChange?.(
                          "question",
                          sampleText,
                          flowCopy(LP_FLOWS.question).question
                        );
                      }}
                      className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold transition ${
                        question === sampleText
                          ? "border-emerald-500 bg-emerald-50 text-emerald-700"
                          : "border-slate-200 bg-white text-slate-500 hover:border-emerald-300"
                      }`}
                    >
                      {sampleText}
                    </button>
                  );
                })}
              </div>
            )}

            <textarea
              value={question}
              onChange={(event) => {
                setQuestion(event.target.value);
                setEdited(true);
                if (intent) {
                  onIntentChange?.(
                    intent,
                    event.target.value,
                    flowCopy(LP_FLOWS[intent]).question
                  );
                }
              }}
              rows={3}
              maxLength={2000}
              aria-label={copy.message}
              className="mt-2 w-full resize-y rounded-lg border border-slate-200 px-3 py-2.5 text-[12.5px] leading-relaxed text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
            />

            <input
              type="email"
              inputMode="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder={copy.email}
              aria-label={copy.email}
              className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-[12.5px] text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
            />

            <div className="mt-2 grid grid-cols-1 gap-2 min-[390px]:grid-cols-2">
              <input
                type="text"
                autoComplete="given-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={copy.firstName}
                aria-label={copy.firstName}
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-[12.5px] text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
              />
              <input
                type="text"
                autoComplete="organization"
                value={company}
                onChange={(event) => setCompany(event.target.value)}
                placeholder={copy.company}
                aria-label={copy.company}
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-[12.5px] text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
              />
            </div>

            <label className="mt-2 flex items-start gap-2 text-[10.5px] leading-relaxed text-slate-500">
              <input
                type="checkbox"
                checked={consent}
                onChange={(event) => setConsent(event.target.checked)}
                className="mt-0.5 h-3.5 w-3.5 accent-emerald-500"
              />
              {copy.consent}
            </label>

            {error && (
              <p role="alert" className="mt-2 text-[11px] font-semibold text-rose-600">
                {error}
              </p>
            )}

            {offline && (
              <p className="mt-2 flex items-start gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-[10.5px] leading-relaxed text-amber-900">
                <Moon className="mt-0.5 h-3 w-3 shrink-0" />
                {copy.offlineStatus}
              </p>
            )}

            <button
              type="button"
              onClick={() => void submit()}
              disabled={sending}
              className="mt-3 w-full rounded-lg bg-emerald-500 py-2.5 text-[12.5px] font-bold text-white transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {sending ? copy.sending : copy.send}
            </button>

            <p className="mt-2 flex items-center justify-center gap-1 text-center text-[10px] text-slate-400">
              <Lock className="h-3 w-3" />
              {copy.private}
            </p>

            <button
              type="button"
              onClick={backFromContact}
              className="mt-2 w-full py-1 text-[11px] font-semibold text-slate-400 hover:text-slate-600"
            >
              {copy.back}
            </button>
          </div>
        )}

        {step === 5 && (
          <div>
            <p className="text-[15px] font-bold tracking-tight text-slate-900">
              {copy.conversation}
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
              {replied ? copy.chatOpen : copy.reviewing}
            </p>

            {offline && (
              <div className="mt-2 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5">
                <Moon className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                <div>
                  <p className="text-[11.5px] font-bold text-amber-900">
                    {copy.offlineTitle}
                  </p>
                  <p className="mt-0.5 text-[10.5px] leading-relaxed text-amber-900">
                    {copy.offlineNotice}
                  </p>
                </div>
              </div>
            )}

            <div
              ref={threadRef}
              role="log"
              aria-live="polite"
              className="mt-3 max-h-[300px] space-y-2 overflow-y-auto pr-1"
            >
              {displayThread.map((item) => {
                if (item.role === "system") {
                  return (
                    <p
                      key={item.id}
                      className="mx-auto max-w-[95%] rounded-lg bg-slate-50 px-2.5 py-2 text-center text-[10px] leading-relaxed text-slate-500"
                    >
                      {item.text}
                    </p>
                  );
                }
                return (
                  <div
                    key={item.id}
                    className={`max-w-[92%] rounded-xl px-3 py-2 text-[12px] leading-relaxed ${
                      item.role === "lead"
                        ? "rounded-bl-md bg-slate-100 text-slate-800"
                        : "ml-auto rounded-br-md bg-emerald-50 text-emerald-900"
                    }`}
                  >
                    <span className="mb-0.5 block text-[8.5px] font-bold uppercase tracking-wide opacity-50">
                      {item.role === "lead" ? "You · EN" : "Magic Leads · EN"}
                    </span>
                    {item.text}
                    {token &&
                      item.messageId &&
                      (attachmentsByMessage.get(item.messageId)?.length ?? 0) >
                        0 && (
                        <WidgetMessageAttachments
                          token={token}
                          attachments={
                            attachmentsByMessage.get(item.messageId) || []
                          }
                        />
                      )}
                  </div>
                );
              })}
              {sending && (
                <p className="flex items-center gap-1.5 px-1 text-[10px] text-slate-400">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400" />
                  {copy.typing}
                </p>
              )}
            </div>

            {replied && (
              <div className="mt-3 rounded-xl border border-emerald-100 bg-emerald-50/70 p-3">
                <p className="flex items-center gap-1.5 text-[11px] font-bold text-emerald-800">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {copy.delivered}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <span className="rounded bg-white px-1.5 py-0.5 text-[9px] font-bold text-emerald-700 ring-1 ring-emerald-100">
                    {copy.widgetBadge}
                  </span>
                  <span className="rounded bg-white px-1.5 py-0.5 text-[9px] font-bold text-emerald-700 ring-1 ring-emerald-100">
                    {copy.emailBadge}
                  </span>
                </div>
                <p className="mt-2 text-[10px] leading-relaxed text-emerald-800/70">
                  {copy.replySentTo} {email || "—"}.
                </p>
              </div>
            )}

            {mode === "live" && token && (
              <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50/40 p-3">
                <label
                  htmlFor={followUpId}
                  className="text-[10px] font-black uppercase tracking-wide text-slate-600"
                >
                  {copy.followUpLabel}
                </label>
                <div className="mt-1.5 flex items-end gap-2">
                  <textarea
                    id={followUpId}
                    value={followUp}
                    onChange={(event) => setFollowUp(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        void sendFollowUpMessage();
                      }
                    }}
                    rows={2}
                    maxLength={2000}
                    placeholder={copy.followUpPlaceholder}
                    className="min-h-[44px] flex-1 resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12.5px] leading-relaxed text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
                  />
                  <button
                    type="button"
                    onClick={() => void sendFollowUpMessage()}
                    disabled={!followUp.trim() || followUpSending}
                    aria-label={copy.followUpSend}
                    className="flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-lg bg-emerald-500 text-white transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {followUpSending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                  </button>
                </div>
                {followUpError && (
                  <p
                    role="alert"
                    className="mt-1.5 text-[10px] font-semibold text-rose-600"
                  >
                    {followUpError}
                  </p>
                )}
              </div>
            )}

            {mode === "live" && token && (
              <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[9px] font-black uppercase tracking-wide text-slate-400">
                    {copy.attachments}
                  </p>
                  <label
                    className={`cursor-pointer rounded-lg border border-slate-200 bg-white px-2 py-1 text-[9px] font-bold text-slate-600 hover:border-emerald-300 ${
                      uploadingAttachment ? "pointer-events-none opacity-50" : ""
                    }`}
                  >
                    {uploadingAttachment ? copy.uploading : copy.attach}
                    <input
                      type="file"
                      className="hidden"
                      disabled={uploadingAttachment}
                      accept="image/png,image/jpeg,image/gif,image/webp,image/bmp,.pdf,.doc,.docx,.xls,.xlsx,.txt,.csv"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void uploadAttachment(file);
                        event.currentTarget.value = "";
                      }}
                    />
                  </label>
                </div>
                {attachments.length === 0 ? (
                  <p className="mt-1.5 text-[9.5px] text-slate-400">—</p>
                ) : (
                  <div className="mt-1.5 space-y-1.5">
                    {attachments.map((attachment) => {
                      const url = lpAttachmentUrl(token, attachment.id);
                      const isImage = (attachment.content_type || "").startsWith(
                        "image/"
                      );
                      return (
                        <a
                          key={attachment.id}
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/50 p-1.5 hover:border-emerald-300"
                        >
                          {isImage ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={url}
                              alt={attachment.filename}
                              className="h-8 w-8 rounded object-cover ring-1 ring-slate-200"
                            />
                          ) : (
                            <span className="flex h-8 w-8 items-center justify-center rounded bg-white text-slate-400 ring-1 ring-slate-200">
                              📎
                            </span>
                          )}
                          <span className="min-w-0 flex-1 truncate text-[9.5px] font-semibold text-slate-600">
                            {attachment.filename}
                          </span>
                        </a>
                      );
                    })}
                  </div>
                )}
                {attachmentError && (
                  <p className="mt-1 text-[9px] font-semibold text-rose-600">
                    {attachmentError}
                  </p>
                )}
              </div>
            )}

            <button
              type="button"
              onClick={checkAvailability}
              className="mt-3 w-full rounded-lg border border-slate-200 bg-white py-2 text-[11px] font-semibold text-slate-600 transition hover:border-emerald-300 hover:text-emerald-700"
            >
              {copy.checkCity}
            </button>
            <button
              type="button"
              onClick={resetAll}
              className="mt-2 w-full py-1 text-[11px] font-semibold text-slate-400 hover:text-slate-600"
            >
              {copy.startOver}
            </button>
          </div>
        )}
      </div>

      <footer className="flex items-center justify-center gap-1.5 rounded-b-2xl border-t border-slate-100 bg-slate-50/50 px-4 py-2 text-[10px] font-semibold text-slate-500">
        <ShieldCheck className="h-3 w-3 text-emerald-600" />
        {copy.noContract}
      </footer>
    </div>
  );
}
