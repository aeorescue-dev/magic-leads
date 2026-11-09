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
  Lock,
  MessageCircle,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";

import {
  createLpThread,
  fetchLpThread,
  trackLpWidget,
} from "@/lib/lp-widget";
import {
  LP_CITIES,
  LP_FLOWS,
  LP_INTENTS,
  LP_SAMPLES,
  LP_TRADES,
  type LpIntentFlow,
  type LpIntentKey,
} from "./data";
import LpLanguagePicker from "./LpLanguagePicker";
import {
  INTENT_L10N,
  WIDGET_COPY,
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
}

type Step = 1 | 2 | 3 | 4;

interface ThreadItem {
  id: string;
  role: "lead" | "team" | "system";
  text: string;
  at: number;
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

function now(): number {
  return Date.now();
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
  const panelRef = useRef<HTMLDivElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const demoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [lang, setLang] = useState<WidgetLang>("en");
  const [edited, setEdited] = useState(false);
  const [step, setStep] = useState<Step>(1);
  const [intent, setIntent] = useState<LpIntentKey | null>(null);
  const [trade, setTrade] = useState("");
  const [city, setCity] = useState("");
  const [question, setQuestion] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [sending, setSending] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [ownQuestion, setOwnQuestion] = useState("");

  const totalSteps = intent === "area" ? 3 : 2;
  const currentStep =
    step === 4 ? totalSteps : Math.min(step, totalSteps);

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
    if (mode !== "live" || !token || step !== 4) return;
    let stopped = false;
    const load = async () => {
      try {
        const data = await fetchLpThread(token);
        if (stopped) return;
        setThread(
          data.messages.map((message) => ({
            id: `${message.role}-${message.id}`,
            role: message.role,
            text: message.text,
            at: Number(new Date(message.created_at)) || now(),
          }))
        );
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
    return () => {
      if (demoTimer.current) clearTimeout(demoTimer.current);
    };
  }, []);

  function resetAll() {
    setStep(1);
    setIntent(null);
    setTrade("");
    setCity("");
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
    setOwnQuestion("");
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
    setStep(key === "area" ? 2 : 3);
    onIntentChange?.(key, nextCopy.question, nextCopy.question);
    trackLpWidget("lp_widget_intent", { intent: key });
  }

  function submitOwnQuestion() {
    const value = ownQuestion.trim();
    if (!value) return;
    setIntent("question");
    setQuestion(value);
    setEdited(true);
    setStep(3);
    onIntentChange?.(
      "question",
      value,
      flowCopy(LP_FLOWS.question).question
    );
    trackLpWidget("lp_widget_intent", { intent: "question", custom: true });
  }

  function backFromContact() {
    setStep(totalSteps === 3 ? 2 : 1);
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
    };

    setSending(true);
    setStep(4);
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
        consent_email: consent,
        locale:
          typeof document !== "undefined"
            ? document.documentElement.lang || "en"
            : "en",
        source_section: "landing_inline",
        website: "",
      });
      setToken(result.token);
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
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
            {copy.online}
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

            <form
              className="mt-3 flex gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                submitOwnQuestion();
              }}
            >
              <input
                value={ownQuestion}
                onChange={(event) => setOwnQuestion(event.target.value)}
                maxLength={300}
                placeholder={copy.ownPlaceholder}
                aria-label={copy.ownPlaceholder}
                className="min-w-0 flex-1 rounded-lg border border-slate-200 px-3 py-2.5 text-[12.5px] text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
              />
              <button
                type="submit"
                aria-label={copy.sendQuestion}
                className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-lg bg-slate-900 text-white transition hover:bg-slate-800"
              >
                <Send className="h-4 w-4" />
              </button>
            </form>
            <p className="mt-2 text-center text-[10px] text-slate-400">
              {copy.micro}
            </p>
          </div>
        )}

        {step === 2 && (
          <div>
            <p className="text-[15px] font-bold tracking-tight text-slate-900">
              {copy.q2}
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
              {copy.hint2}
            </p>

            <div className="mt-3 flex flex-wrap gap-1.5">
              {LP_TRADES.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setTrade(item)}
                  aria-pressed={trade === item}
                  className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold transition ${
                    trade === item
                      ? "border-emerald-500 bg-emerald-500 text-white"
                      : "border-slate-200 bg-white text-slate-600 hover:border-emerald-300"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>

            <div className="mt-2 flex flex-wrap gap-1.5">
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
              {copy.check}
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

        {step === 4 && (
          <div>
            <p className="text-[15px] font-bold tracking-tight text-slate-900">
              {copy.conversation}
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-500">
              {copy.reviewing}
            </p>

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

            <button
              type="button"
              onClick={checkAvailability}
              className="mt-3 w-full rounded-lg bg-emerald-500 py-2.5 text-[12.5px] font-bold text-white transition hover:bg-emerald-600"
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
