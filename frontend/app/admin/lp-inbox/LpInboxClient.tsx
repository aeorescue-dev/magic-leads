"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import useSWR from "swr";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Inbox,
  Loader2,
  Mail,
  MapPin,
  MessageSquare,
  Paperclip,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Upload,
  User,
  Wrench,
} from "lucide-react";

import {
  AdminApiError,
  enrichLpThread,
  fetchLpThread,
  fetchLpThreads,
  replyLpThread,
  saveLpTranslation,
  setLpThreadStatus,
  translateLpDraft,
  uploadLpAttachment,
  lpAttachmentUrl,
  type LpAdminMessage,
  type LpAdminThreadDetail,
  type LpAdminThreadSummary,
} from "@/lib/admin-api";

const INTENT_LABEL: Record<string, string> = {
  vs_ads: "Anúncios",
  vs_angi: "Angi / HomeAdvisor",
  phones: "Telefone do proprietário",
  price: "Preço / contrato",
  area: "Cidade + ofício",
  question: "Pergunta livre",
};

function cls(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function fmtDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusLabel(status: string): string {
  if (status === "new") return "Novo";
  if (status === "replied") return "Respondido";
  if (status === "archived") return "Arquivado";
  if (status === "closed") return "Fechado";
  return status;
}

function statusClass(status: string): string {
  if (status === "new") return "bg-amber-100 text-amber-800";
  if (status === "replied") return "bg-emerald-100 text-emerald-700";
  if (status === "archived") return "bg-slate-200 text-slate-600";
  return "bg-slate-100 text-slate-600";
}

function isOverdue(value?: string | null): boolean {
  if (!value) return false;
  return new Date(value).getTime() < Date.now();
}

const COVERED_CITIES = new Set(["new york", "boston", "dallas", "chicago"]);

function cityCovered(city?: string | null): boolean {
  return !!city && COVERED_CITIES.has(city.trim().toLowerCase());
}

const SOURCE_LABEL: Record<string, string> = {
  google: "Google / Search",
  social: "Social Media",
  referral: "Referral / Word of Mouth",
  outreach: "Automated Call / Direct Outreach",
};

function toSummary(thread: LpAdminThreadDetail): LpAdminThreadSummary {
  const last = thread.messages[thread.messages.length - 1];
  return {
    id: thread.id,
    email: thread.email,
    name: thread.name,
    company: thread.company,
    city: thread.city,
    trade: thread.trade,
    trade_code: thread.trade_code,
    lead_source: thread.lead_source,
    intent: thread.intent,
    status: thread.status,
    created_at: thread.created_at,
    last_message_at: thread.last_message_at,
    sla_due_at: thread.sla_due_at,
    last_message: last ? last.body_en || last.body : null,
    message_count: thread.messages.length,
  };
}

function makeDemoThread(): LpAdminThreadDetail {
  const now = new Date().toISOString();
  return {
    id: 1042,
    email: "owner@example.com",
    name: "Mike",
    company: "Mike Roofing",
    city: "Dallas",
    trade: "Roofing",
    trade_code: "Roof",
    lead_source: "google",
    intent: "vs_ads",
    status: "new",
    locale: "en",
    lead_lang: "en",
    ai_status: "ready",
    ai_provider: "demo",
    ai_updated_at: now,
    draft_pt:
      "Porque aqui não paga por cliques. Paga $120 por semana por oportunidades concretas, com proprietário identificado e telefone verificado — reservadas 60 minutos só para si. Se um único trabalho fechar, o passe pagou-se.",
    draft_out:
      "Because here you don't pay for clicks. You pay $120 a week for concrete opportunities, with an identified owner and a verified phone — reserved for 60 minutes only for you. If a single job closes, the pass pays for itself.",
    draft_out_lang: "en",
    source_section: "landing_widget",
    created_at: now,
    updated_at: now,
    last_message_at: now,
    sla_due_at: new Date(Date.now() + 4 * 3600 * 1000).toISOString(),
    messages: [
      {
        id: 1,
        direction: "inbound",
        channel: "widget",
        body: "I'm spending $70–$200 a day on Facebook and Google Ads and barely converting. Why is this better?",
        body_pt:
          "Estou a gastar $70–$200 por dia em anúncios no Facebook e no Google e quase não converto. Porque é que isto é melhor?",
        body_en: null,
        lang: "en",
        author_type: "lead",
        author_id: null,
        email_status: null,
        created_at: now,
      },
    ],
  };
}

export default function LpInboxClient() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [period, setPeriod] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [demo, setDemo] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [demoThread, setDemoThread] = useState<LpAdminThreadDetail | null>(null);

  const {
    data: list,
    error: listError,
    isLoading: listLoading,
    mutate: mutateList,
  } = useSWR(
    demo ? null : ["lp-inbox-threads", statusFilter, period],
    () =>
      fetchLpThreads({
        status: statusFilter,
        period,
        limit: 100,
      }),
    {
      refreshInterval: 5000,
      revalidateOnFocus: true,
      shouldRetryOnError: false,
    }
  );

  const threads = list?.threads ?? [];
  const activeId = selectedId ?? threads[0]?.id ?? null;

  const {
    data: thread,
    error: threadError,
    isLoading: threadLoading,
    mutate: mutateThread,
  } = useSWR(
    demo ? null : activeId ? ["lp-inbox-thread", activeId] : null,
    () => fetchLpThread(activeId as number),
    { refreshInterval: 5000, revalidateOnFocus: true, shouldRetryOnError: false }
  );

  const authError =
    listError instanceof AdminApiError &&
    (listError.status === 401 || listError.status === 403);
  const apiDisabled =
    listError instanceof AdminApiError && listError.status === 404;
  const apiError = Boolean(listError) && !authError && !apiDisabled;

  const summary = demo && demoThread ? toSummary(demoThread) : null;
  const activeThreads = demo ? (summary ? [summary] : []) : threads;
  const activeThread = demo ? demoThread : thread;
  const activeThreadId = demo ? demoThread?.id ?? null : activeId;

  async function refresh() {
    if (refreshing) return;
    setRefreshing(true);
    const started = Date.now();
    try {
      if (!demo) {
        await Promise.allSettled([mutateList(), mutateThread()]);
      }
    } finally {
      const elapsed = Date.now() - started;
      if (elapsed < 450) {
        await new Promise((resolve) => setTimeout(resolve, 450 - elapsed));
      }
      setRefreshing(false);
    }
  }

  function startDemo() {
    setDemoThread(makeDemoThread());
    setDemo(true);
  }

  async function handleArchive(threadId: number, status: "new" | "archived") {
    await setLpThreadStatus(threadId, status);
    await Promise.all([mutateList(), mutateThread()]);
  }

  async function handleSend(
    threadId: number,
    bodyPt: string,
    bodyEn: string
  ): Promise<{ email_sent: boolean; simulated?: boolean }> {
    if (demo) {
      const now = new Date().toISOString();
      setDemoThread((prev) =>
        prev
          ? {
              ...prev,
              status: "replied",
              updated_at: now,
              last_message_at: now,
              messages: [
                ...prev.messages,
                {
                  id: Date.now(),
                  direction: "outbound",
                  channel: "widget+email",
                  body: bodyEn,
                  body_pt: bodyPt,
                  body_en: bodyEn,
                  lang: "en",
                  author_type: "team",
                  author_id: null,
                  email_status: "simulated",
                  created_at: now,
                },
              ],
            }
          : prev
      );
      return { email_sent: true, simulated: true };
    }

    const result = await replyLpThread(threadId, bodyPt, bodyEn);
    await refresh();
    return { email_sent: result.email_sent };
  }

  async function handleSaveTranslation(
    threadId: number,
    messageId: number,
    bodyPt: string
  ): Promise<{ ok: boolean }> {
    if (demo) {
      setDemoThread((prev) =>
        prev
          ? {
              ...prev,
              messages: prev.messages.map((message) =>
                message.id === messageId
                  ? { ...message, body_pt: bodyPt }
                  : message
              ),
            }
          : prev
      );
      return { ok: true };
    }
    const result = await saveLpTranslation(threadId, messageId, bodyPt);
    await mutateThread();
    return { ok: result.ok };
  }

  return (
    <div
      className="min-h-screen bg-slate-50 text-slate-900"
      style={{ colorScheme: "light" }}
    >
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3">
          <Link
            href="/admin"
            className="flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-bold text-slate-600 hover:bg-slate-50 hover:text-slate-900"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Admin
          </Link>
          <span className="h-4 w-px bg-slate-200" />
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100">
              <Inbox className="h-4 w-4" />
            </span>
            <div>
              <h1 className="text-[15px] font-black tracking-tight">LP Inbox</h1>
              <p className="text-[10.5px] font-semibold text-slate-600">
                Widget de captação · revisão humana PT-BR
              </p>
            </div>
          </div>
          <span className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[12px] font-black uppercase tracking-wide text-slate-600">
            Fase 1b
          </span>
          <div className="ml-auto flex items-center gap-2">
            <span className="flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[12px] font-black uppercase tracking-wide text-emerald-700">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              Polling 5 s
            </span>
            <span
              className={cls(
                "rounded-full px-2.5 py-1 text-[12px] font-black uppercase tracking-wide",
                demo
                  ? "bg-violet-100 text-violet-700"
                  : apiDisabled
                    ? "bg-slate-200 text-slate-600"
                    : listError
                      ? "bg-rose-100 text-rose-700"
                      : "bg-emerald-100 text-emerald-700"
              )}
            >
              {demo ? "Demo" : apiDisabled ? "API off" : listError ? "Erro" : "Live"}
            </span>
            <button
              type="button"
              onClick={() => void refresh()}
              aria-busy={refreshing}
              aria-label="Atualizar conversas"
              className="flex items-center gap-1.5 rounded-lg border border-slate-300 bg-slate-900 px-3 py-1.5 text-[10.5px] font-bold text-white shadow-sm transition hover:bg-slate-800 active:bg-slate-700"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
              />
              {refreshing ? "A atualizar…" : "Atualizar"}
            </button>
          </div>
        </div>
      </header>

      {demo && (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-[10.5px] font-semibold text-amber-900">
          <AlertTriangle className="mr-1 inline h-3 w-3" />
          Modo demonstração: dados locais, sem chamadas ao backend, ao Resend ou
          ao widget real. Nada é enviado.
        </div>
      )}

      <main className="mx-auto max-w-7xl px-4 py-4">
        {authError ? (
          <div className="mx-auto mt-10 max-w-xl rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm">
            <ShieldCheck className="mx-auto h-8 w-8 text-slate-600" />
            <h2 className="mt-3 text-[15px] font-black">Sessão admin necessária</h2>
            <p className="mt-1 text-[12.5px] leading-relaxed text-slate-600">
              Esta página exige uma sessão real com <code>users.is_admin = 1</code>.
            </p>
            <Link
              href="/auth?next=/admin/lp-inbox"
              className="mt-4 inline-block rounded-lg bg-slate-900 px-4 py-2 text-[12px] font-bold text-white"
            >
              Entrar
            </Link>
            <button
              type="button"
              onClick={startDemo}
              className="mt-2 block w-full text-[12px] font-bold text-slate-600 underline underline-offset-2 hover:text-slate-600"
            >
              Ver com dados de demonstração
            </button>
          </div>
        ) : apiDisabled && !demo ? (
          <div className="mx-auto mt-10 max-w-xl rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm">
            <Inbox className="mx-auto h-8 w-8 text-slate-600" />
            <h2 className="mt-3 text-[15px] font-black">API do widget desligada</h2>
            <p className="mt-1 text-[12.5px] leading-relaxed text-slate-600">
              O backend está com <code>LP_WIDGET_ENABLED=false</code>. A inbox real
              só responde quando a flag estiver ligada em staging.
            </p>
            <button
              type="button"
              onClick={startDemo}
              className="mt-4 rounded-lg bg-emerald-500 px-4 py-2 text-[12px] font-bold text-white hover:bg-emerald-600"
            >
              Ver com dados de demonstração
            </button>
            <p className="mt-3 text-[10.5px] text-slate-600">
              Nenhum dado de produção é lido ou alterado.
            </p>
          </div>
        ) : apiError && !demo ? (
          <div className="mx-auto mt-10 max-w-xl rounded-2xl border border-rose-200 bg-white p-6 text-center shadow-sm">
            <AlertTriangle className="mx-auto h-8 w-8 text-rose-500" />
            <h2 className="mt-3 text-[15px] font-black">
              Não foi possível ligar à API
            </h2>
            <p className="mt-1 text-[12.5px] leading-relaxed text-slate-600">
              {listError instanceof Error
                ? listError.message
                : "Verifica a ligação ao backend."}
            </p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
              <button
                type="button"
                onClick={startDemo}
                className="rounded-lg bg-emerald-500 px-4 py-2 text-[12px] font-bold text-white hover:bg-emerald-600"
              >
                Ver com dados de demonstração
              </button>
              <button
                type="button"
                onClick={() => void refresh()}
                className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-[12px] font-bold text-slate-600 hover:border-slate-300"
              >
                Tentar novamente
              </button>
            </div>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)] lg:items-start">
            <aside className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="flex items-center justify-between border-b border-slate-100 px-3.5 py-3">
                <div>
                  <p className="text-[12px] font-black uppercase tracking-[0.12em] text-slate-600">
                    Conversas
                  </p>
                  <p className="mt-0.5 text-[12px] font-bold">
                    {activeThreads.length} fio(s)
                  </p>
                </div>
                <MessageSquare className="h-4 w-4 text-slate-300" />
              </div>

              <div className="space-y-1.5 border-b border-slate-100 px-3 py-2">
                <div className="flex flex-wrap gap-1">
                  {[
                    { value: "", label: "Tudo" },
                    { value: "today", label: "Hoje" },
                    { value: "week", label: "Semana" },
                    { value: "month", label: "Mês" },
                  ].map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setPeriod(option.value)}
                      className={`rounded-full border px-2 py-0.5 text-[9.5px] font-bold ${
                        period === option.value
                          ? "border-slate-900 bg-slate-900 text-white"
                          : "border-slate-200 bg-white text-slate-600"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <div className="flex flex-wrap gap-1">
                  {[
                    { value: "", label: "Todos" },
                    { value: "new", label: "Novo" },
                    { value: "replied", label: "Respondido" },
                    { value: "archived", label: "Arquivado" },
                  ].map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setStatusFilter(option.value)}
                      className={`rounded-full border px-2 py-0.5 text-[9.5px] font-bold ${
                        statusFilter === option.value
                          ? "border-emerald-600 bg-emerald-600 text-white"
                          : "border-slate-200 bg-white text-slate-600"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              {listLoading && !demo ? (
                <div className="flex items-center justify-center gap-2 px-4 py-10 text-[12px] text-slate-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  A carregar…
                </div>
              ) : activeThreads.length === 0 ? (
                <div className="px-4 py-10 text-center text-[12px] leading-relaxed text-slate-600">
                  Nenhuma conversa ainda.
                  <br />
                  O widget cria o primeiro fio quando um lead envia.
                </div>
              ) : (
                <ul className="max-h-[calc(100vh-180px)] overflow-y-auto p-1.5">
                  {activeThreads.map((item) => {
                    const selected = item.id === activeThreadId;
                    const overdue = isOverdue(item.sla_due_at);
                    return (
                      <li key={item.id}>
                        <button
                          type="button"
                          onClick={() => {
                            if (!demo) setSelectedId(item.id);
                          }}
                          className={cls(
                            "w-full rounded-xl border p-2.5 text-left transition",
                            selected
                              ? "border-emerald-400 bg-emerald-50/70 shadow-[0_0_0_3px_rgba(16,185,129,0.08)]"
                              : "border-transparent hover:border-slate-200 hover:bg-slate-50"
                          )}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="truncate text-[12.5px] font-bold text-slate-900">
                                {item.name || item.email}
                              </p>
                              <p className="truncate text-[10.5px] text-slate-600">
                                {item.email}
                              </p>
                            </div>
                            <span
                              className={cls(
                                "shrink-0 rounded-full px-1.5 py-0.5 text-[9.5px] font-black uppercase tracking-wide",
                                statusClass(item.status)
                              )}
                            >
                              {statusLabel(item.status)}
                            </span>
                          </div>
                          <p className="mt-1.5 truncate text-[12px] text-slate-600">
                            {item.last_message || "—"}
                          </p>
                          <div className="mt-1.5 flex flex-wrap items-center gap-1 text-[9.5px] font-bold text-slate-600">
                            <span className="rounded bg-slate-100 px-1.5 py-0.5">
                              {INTENT_LABEL[item.intent] || item.intent}
                            </span>
                            {item.city ? (
                              <span className="flex items-center gap-0.5">
                                <span
                                  className={`h-1.5 w-1.5 rounded-full ${
                                    cityCovered(item.city)
                                      ? "bg-emerald-500"
                                      : "bg-rose-500"
                                  }`}
                                  title={
                                    cityCovered(item.city)
                                      ? "Dentro da cobertura"
                                      : "Fora da cobertura"
                                  }
                                />
                                <MapPin className="h-2.5 w-2.5" />
                                {item.city}
                              </span>
                            ) : (
                              <span className="flex items-center gap-0.5">
                                <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
                                Sem cidade
                              </span>
                            )}
                            {item.trade && (
                              <span className="flex items-center gap-0.5">
                                <Wrench className="h-2.5 w-2.5" />
                                {item.trade}
                              </span>
                            )}
                            <span className="ml-auto">
                              {fmtDate(item.last_message_at || item.created_at)}
                            </span>
                          </div>
                          {overdue && (
                            <p className="mt-1 flex items-center gap-1 text-[9.5px] font-black uppercase tracking-wide text-rose-600">
                              <Clock className="h-2.5 w-2.5" />
                              SLA vencido
                            </p>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </aside>

            <section className="min-w-0">
              {threadLoading && !demo ? (
                <div className="flex items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-16 text-[12px] text-slate-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  A carregar conversa…
                </div>
              ) : threadError && !demo ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-[12px] text-rose-700">
                  Erro ao carregar a conversa.{" "}
                  {threadError instanceof Error ? threadError.message : ""}
                </div>
              ) : activeThread ? (
                <ThreadDetail
                  key={
                    demo
                      ? "demo"
                      : `${activeThread.id}-${activeThread.ai_updated_at ?? "none"}`
                  }
                  thread={activeThread}
                  demo={demo}
                  onSend={handleSend}
                  onSaveTranslation={handleSaveTranslation}
                  onRefresh={() => void mutateThread()}
                  onOpenThread={(id) => setSelectedId(id)}
                  onArchive={() =>
                    void handleArchive(
                      activeThread.id,
                      activeThread.status === "archived" ? "new" : "archived"
                    )
                  }
                />
              ) : (
                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-16 text-center text-[12.5px] text-slate-600">
                  Selecione uma conversa à esquerda.
                </div>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

function ThreadDetail({
  thread,
  demo,
  onSend,
  onSaveTranslation,
  onRefresh,
  onOpenThread,
  onArchive,
}: {
  thread: LpAdminThreadDetail;
  demo: boolean;
  onSend: (
    threadId: number,
    bodyPt: string,
    bodyEn: string
  ) => Promise<{ email_sent: boolean; simulated?: boolean }>;
  onSaveTranslation: (
    threadId: number,
    messageId: number,
    bodyPt: string
  ) => Promise<{ ok: boolean }>;
  onRefresh: () => void;
  onOpenThread: (id: number) => void;
  onArchive: () => void;
}) {
  const overdue = isOverdue(thread.sla_due_at);
  const [enriching, setEnriching] = useState(false);
  const [enrichError, setEnrichError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const aiStatus = thread.ai_status || "pending";
  const aiLabel =
    aiStatus === "ready"
      ? "IA pronta"
      : aiStatus === "needs_key"
        ? "IA sem chave"
        : aiStatus === "failed"
          ? "IA falhou"
          : "IA a preparar";
  const aiClass =
    aiStatus === "ready"
      ? "bg-emerald-100 text-emerald-700"
      : aiStatus === "failed"
        ? "bg-rose-100 text-rose-700"
        : "bg-amber-100 text-amber-800";

  async function handleEnrich() {
    setEnriching(true);
    setEnrichError("");
    try {
      const result = await enrichLpThread(thread.id);
      if (!result.ok) {
        setEnrichError(result.error || "A IA não conseguiu concluir.");
      }
      onRefresh();
    } catch (err) {
      setEnrichError(
        err instanceof Error ? err.message : "Falha ao executar a IA."
      );
    } finally {
      setEnriching(false);
    }
  }

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadError("");
    try {
      await uploadLpAttachment(thread.id, file);
      onRefresh();
    } catch (err) {
      setUploadError(
        err instanceof Error ? err.message : "Não foi possível anexar."
      );
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[15px] font-black tracking-tight">
                {thread.name || thread.email}
              </h2>
              <span
                className={cls(
                  "rounded-full px-2 py-0.5 text-[9.5px] font-black uppercase tracking-wide",
                  statusClass(thread.status)
                )}
              >
                {statusLabel(thread.status)}
              </span>
              <span
                className={cls(
                  "rounded-full px-2 py-0.5 text-[9.5px] font-black uppercase tracking-wide",
                  aiClass
                )}
              >
                {aiLabel}
              </span>
              {overdue && (
                <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[9.5px] font-black uppercase tracking-wide text-rose-700">
                  SLA vencido
                </span>
              )}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-slate-600">
              <span className="flex items-center gap-1">
                <Mail className="h-3 w-3" />
                {thread.email}
              </span>
              {thread.company && (
                <span className="flex items-center gap-1">
                  <User className="h-3 w-3" />
                  {thread.company}
                </span>
              )}
              <span className="flex items-center gap-1">
                <span
                  className={`h-2 w-2 rounded-full ${
                    cityCovered(thread.city) ? "bg-emerald-500" : "bg-rose-500"
                  }`}
                />
                <MapPin className="h-3 w-3" />
                {thread.city || "Sem cidade"}
                <span
                  className={
                    cityCovered(thread.city)
                      ? "font-bold text-emerald-700"
                      : "font-bold text-rose-700"
                  }
                >
                  {cityCovered(thread.city) ? "Coberto" : "Fora da cobertura"}
                </span>
              </span>
              {thread.trade && (
                <span className="flex items-center gap-1">
                  <Wrench className="h-3 w-3" />
                  {thread.trade}
                </span>
              )}
              <span className="flex items-center gap-1">
                <MessageSquare className="h-3 w-3" />
                {INTENT_LABEL[thread.intent] || thread.intent}
              </span>
              {thread.lead_source && (
                <span className="flex items-center gap-1">
                  Origem: {SOURCE_LABEL[thread.lead_source] || thread.lead_source}
                </span>
              )}
              {thread.history && thread.history.length > 0 && (
                <span className="font-bold text-emerald-700">
                  Cliente recorrente
                </span>
              )}
            </div>
          </div>
          <div className="text-right text-[10.5px] text-slate-600">
            <p>Criado {fmtDate(thread.created_at)}</p>
            <p>SLA {fmtDate(thread.sla_due_at)}</p>
            <p className="mt-0.5 font-bold text-slate-600">
              {thread.messages.length} mensagem(ns)
            </p>
            {aiStatus !== "ready" && !demo && (
              <button
                type="button"
                onClick={() => void handleEnrich()}
                disabled={enriching}
                className="mt-1.5 inline-flex items-center gap-1 rounded-lg border border-violet-200 bg-white px-2 py-1 text-[12px] font-bold text-violet-700 hover:border-violet-300 disabled:opacity-50"
              >
                {enriching ? "A gerar…" : "Gerar com IA"}
              </button>
            )}
            <button
              type="button"
              onClick={onArchive}
              className="mt-1.5 inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[12px] font-bold text-slate-600 hover:border-slate-300"
            >
              {thread.status === "archived" ? "Reabrir" : "Arquivar"}
            </button>
          </div>
        </div>
        {!demo && aiStatus !== "ready" && (thread.ai_error || enrichError) && (
          <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-[10.5px] leading-relaxed text-amber-800">
            {enrichError || thread.ai_error}
          </p>
        )}
      </div>

      <div className="space-y-2.5">
        {thread.messages.map((message) =>
          message.direction === "inbound" ? (
            <InboundMessage
              key={`${message.id}-${message.body_pt ? "pt" : "pending"}`}
              threadId={thread.id}
              message={message}
              demo={demo}
              onSave={onSaveTranslation}
            />
          ) : (
            <OutboundMessage key={message.id} message={message} />
          )
        )}
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[12px] font-black uppercase tracking-[0.12em] text-slate-600">
            Anexos · {thread.attachments?.length ?? 0}
          </p>
          <label
            className={`inline-flex cursor-pointer items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10.5px] font-bold text-slate-600 hover:border-emerald-300 ${
              uploading ? "pointer-events-none opacity-50" : ""
            }`}
          >
            <Upload className="h-3 w-3" />
            {uploading ? "A enviar…" : "Anexar"}
            <input
              type="file"
              className="hidden"
              disabled={uploading}
              accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt,.csv"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void handleUpload(file);
                event.currentTarget.value = "";
              }}
            />
          </label>
        </div>

        {(thread.attachments?.length ?? 0) === 0 ? (
          <p className="mt-2 text-[10.5px] text-slate-600">
            Nenhum ficheiro. Imagens, PDF, Word, Excel, TXT ou CSV até 10 MB.
          </p>
        ) : (
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {thread.attachments?.map((attachment) => {
              const url = lpAttachmentUrl(thread.id, attachment.id);
              const isImage = (attachment.content_type || "").startsWith(
                "image/"
              );
              return (
                <a
                  key={attachment.id}
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/50 p-2 transition hover:border-emerald-300 hover:bg-emerald-50/40"
                >
                  {isImage ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={url}
                      alt={attachment.filename}
                      className="h-9 w-9 shrink-0 rounded object-cover ring-1 ring-slate-200"
                    />
                  ) : (
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-white text-slate-600 ring-1 ring-slate-200">
                      <Paperclip className="h-3.5 w-3.5" />
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[10.5px] font-bold text-slate-700">
                      {attachment.filename}
                    </span>
                    <span className="block text-[9.5px] text-slate-600">
                      {attachment.direction === "inbound" ? "Lead" : "Equipa"} ·{" "}
                      {Math.max(1, Math.round(attachment.size_bytes / 1024))} KB
                    </span>
                  </span>
                </a>
              );
            })}
          </div>
        )}
        {uploadError && (
          <p className="mt-2 text-[10.5px] font-semibold text-rose-600">
            {uploadError}
          </p>
        )}
      </div>

      {thread.history && thread.history.length > 0 && (
        <details className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          <summary className="cursor-pointer px-4 py-3 text-[12px] font-bold text-slate-700">
            Histórico deste e-mail · {thread.history.length} conversa(s)
          </summary>
          <div className="space-y-1.5 border-t border-slate-100 p-3">
            {thread.history.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onOpenThread(item.id)}
                className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-left transition hover:border-emerald-300 hover:bg-emerald-50/40"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-[10.5px] font-bold text-slate-700">
                    #{item.id}
                    <span
                      className={cls(
                        "rounded-full px-1.5 py-0.5 text-[9.5px] font-black uppercase tracking-wide",
                        statusClass(item.status)
                      )}
                    >
                      {statusLabel(item.status)}
                    </span>
                  </span>
                  <span className="text-[9.5px] text-slate-600">
                    {fmtDate(item.created_at)}
                  </span>
                </div>
                <p className="mt-0.5 truncate text-[12px] text-slate-600">
                  {item.last_message || "—"}
                </p>
              </button>
            ))}
          </div>
        </details>
      )}

      <ReplyComposer
        thread={thread}
        onSend={onSend}
        initialPt={thread.draft_pt || ""}
        initialOut={thread.draft_out || ""}
        leadLang={thread.lead_lang || "en"}
      />
    </div>
  );
}

function InboundMessage({
  threadId,
  message,
  demo,
  onSave,
}: {
  threadId: number;
  message: LpAdminMessage;
  demo: boolean;
  onSave: (
    threadId: number,
    messageId: number,
    bodyPt: string
  ) => Promise<{ ok: boolean }>;
}) {
  const [pt, setPt] = useState(message.body_pt || "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    if (!pt.trim()) return;
    setSaving(true);
    setError("");
    try {
      await onSave(threadId, message.id, pt.trim());
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Não foi possível guardar."
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2 text-[12px] font-black uppercase tracking-wide text-slate-600">
        <span className="flex items-center gap-1.5 text-slate-600">
          <User className="h-3 w-3" />
          Lead · {message.lang.toUpperCase()}
        </span>
        <span>{fmtDate(message.created_at)}</span>
      </div>
      <p className="mt-2 rounded-xl bg-slate-50 px-3 py-2.5 text-[12.5px] leading-relaxed text-slate-800">
        {message.body}
      </p>

      <div className="mt-3 rounded-xl border border-violet-200 bg-violet-50/40 p-3">
        <div className="flex items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-[12px] font-black uppercase tracking-wide text-violet-700">
            <Sparkles className="h-3 w-3" />
            Tradução PT-BR
          </p>
          <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[9.5px] font-black uppercase tracking-wide text-violet-700">
            {demo
              ? "demo"
              : message.body_pt
                ? "IA · pré-preenchido"
                : "revisão humana"}
          </span>
        </div>
        <textarea
          value={pt}
          onChange={(event) => setPt(event.target.value)}
          rows={3}
          placeholder="Traduza ou reveja a mensagem do lead em PT-BR…"
          className="mt-2 w-full resize-y rounded-lg border border-violet-200 bg-white px-2.5 py-2 text-[12.5px] leading-relaxed text-slate-900 outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
        />
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <span className="text-[12px] text-slate-600">
            {saved ? "Tradução guardada." : "O original permanece intacto."}
          </span>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || !pt.trim()}
            className="rounded-lg border border-violet-200 bg-white px-2.5 py-1.5 text-[10.5px] font-bold text-violet-700 hover:border-violet-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? "A guardar…" : "Guardar tradução"}
          </button>
        </div>
        {error && (
          <p className="mt-1 text-[10.5px] font-semibold text-rose-600">{error}</p>
        )}
      </div>
    </article>
  );
}

function OutboundMessage({ message }: { message: LpAdminMessage }) {
  return (
    <article className="ml-auto max-w-[92%] rounded-2xl border border-emerald-200 bg-emerald-50/60 p-3.5 shadow-sm">
      <div className="flex items-center justify-between gap-2 text-[12px] font-black uppercase tracking-wide text-emerald-800">
        <span className="flex items-center gap-1.5">
          <CheckCircle2 className="h-3 w-3" />
          Equipa · {message.lang.toUpperCase()} enviado
        </span>
        <span>{fmtDate(message.created_at)}</span>
      </div>
      <p className="mt-1.5 text-[12.5px] leading-relaxed text-emerald-950">
        {message.body_en || message.body}
      </p>
      {message.body_pt && (
        <div className="mt-2 rounded-lg border border-emerald-200/70 bg-white/70 px-2.5 py-2">
          <p className="text-[9.5px] font-black uppercase tracking-wide text-emerald-700">
            Versão interna PT-BR
          </p>
          <p className="mt-0.5 text-[10.5px] leading-relaxed text-slate-600">
            {message.body_pt}
          </p>
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-1.5 text-[9.5px] font-bold">
        <span className="rounded bg-white px-1.5 py-0.5 text-emerald-700 ring-1 ring-emerald-100">
          Widget · polling 5 s
        </span>
        <span className="rounded bg-white px-1.5 py-0.5 text-emerald-700 ring-1 ring-emerald-100">
          Email · Resend · {message.email_status || "—"}
        </span>
      </div>
    </article>
  );
}

function ReplyComposer({
  thread,
  onSend,
  initialPt = "",
  initialOut = "",
  leadLang = "en",
}: {
  thread: LpAdminThreadDetail;
  onSend: (
    threadId: number,
    bodyPt: string,
    bodyEn: string
  ) => Promise<{ email_sent: boolean; simulated?: boolean }>;
  initialPt?: string;
  initialOut?: string;
  leadLang?: string;
}) {
  const [pt, setPt] = useState(initialPt);
  const [en, setEn] = useState(initialOut);
  const [sending, setSending] = useState(false);
  const [translating, setTranslating] = useState(false);
  const translatingRef = useRef(false);
  const [translateError, setTranslateError] = useState("");
  const lastTranslatedRef = useRef(initialPt);
  const [result, setResult] = useState<{
    email_sent: boolean;
    simulated?: boolean;
  } | null>(null);
  const [error, setError] = useState("");
  const finalLabel = (leadLang || "en").toUpperCase();

  async function translate(): Promise<string | null> {
    if (!pt.trim() || translatingRef.current) return null;
    translatingRef.current = true;
    setTranslating(true);
    setTranslateError("");
    try {
      const out = await translateLpDraft(thread.id, pt.trim());
      setEn(out.body_out);
      lastTranslatedRef.current = pt;
      return out.body_out;
    } catch (err) {
      setTranslateError(
        err instanceof Error ? err.message : "Não foi possível traduzir."
      );
      return null;
    } finally {
      translatingRef.current = false;
      setTranslating(false);
    }
  }

  async function handlePtBlur() {
    if (pt.trim() && (pt !== lastTranslatedRef.current || !en.trim())) {
      await translate();
    }
  }

  async function send() {
    if (!pt.trim() || sending) return;
    let finalText = en.trim();
    if (!finalText || pt.trim() !== lastTranslatedRef.current) {
      const out = await translate();
      if (!out) return;
      finalText = out;
    }
    if (!finalText) return;
    setSending(true);
    setError("");
    setResult(null);
    try {
      const response = await onSend(thread.id, pt.trim(), finalText);
      setResult(response);
      setPt("");
      setEn("");
      lastTranslatedRef.current = "";
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Não foi possível enviar."
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[12px] font-black uppercase tracking-[0.12em] text-slate-600">
            Resposta da equipa
          </p>
          <p className="mt-0.5 text-[12px] font-bold text-slate-900">
            Rascunho PT-BR + versão {finalLabel}
          </p>
        </div>
        <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[9.5px] font-black uppercase tracking-wide text-emerald-700">
          Widget + Resend
        </span>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div>
          <label className="text-[12px] font-black uppercase tracking-wide text-slate-600">
            Rascunho PT-BR (interno)
          </label>
          <textarea
            value={pt}
            onChange={(event) => setPt(event.target.value)}
            onBlur={() => void handlePtBlur()}
            rows={5}
            placeholder="Escreva a resposta em português para revisão…"
            className="mt-1 w-full resize-y rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-[12.5px] leading-relaxed text-slate-900 outline-none focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          />
        </div>
        <div>
          <div className="flex items-center justify-between gap-2">
            <label className="text-[12px] font-black uppercase tracking-wide text-slate-600">
              Versão {finalLabel} (enviada ao lead)
            </label>
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => void translate()}
              disabled={translating || !pt.trim()}
              className="rounded border border-violet-200 bg-white px-1.5 py-1 text-[9.5px] font-bold text-violet-700 hover:border-violet-300 disabled:opacity-40"
            >
              {translating ? "A traduzir…" : "Traduzir PT →"}
            </button>
          </div>
          <textarea
            value={en}
            onChange={(event) => setEn(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                event.preventDefault();
                void send();
              }
            }}
            rows={5}
            placeholder={`Write the final ${finalLabel} reply…`}
            className="mt-1 w-full resize-y rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-[12.5px] leading-relaxed text-slate-900 outline-none focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          />
        </div>
      </div>

      {translateError && (
        <p className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-2 text-[12px] font-semibold text-rose-700">
          {translateError}
        </p>
      )}

      <p className="mt-2 text-[12px] leading-relaxed text-slate-600">
        A IA pré-preenche e traduz o rascunho PT-BR para {finalLabel}. Edita a
        versão final e revê antes de aprovar. O original PT-BR fica na auditoria.
      </p>

      {error && (
        <p className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-2 text-[12px] font-semibold text-rose-700">
          {error}
        </p>
      )}

      {result && (
        <div
          className={cls(
            "mt-2 rounded-lg border px-2.5 py-2 text-[12px] leading-relaxed",
            result.email_sent
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-amber-200 bg-amber-50 text-amber-800"
          )}
        >
          {result.email_sent ? (
            <>
              <CheckCircle2 className="mr-1 inline h-3 w-3" />
              Resposta guardada e entregue. Widget (polling 5 s) + Email
              (Resend){result.simulated ? " · simulado em demo" : ""}.
            </>
          ) : (
            <>
              <AlertTriangle className="mr-1 inline h-3 w-3" />
              Resposta guardada, mas o Resend recusou o e-mail. O widget continua
              a mostrar a resposta; verifica <code>EMAIL_API_KEY</code>/
              <code>EMAIL_FROM</code>.
            </>
          )}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[12px] text-slate-600">
          Atalho: <kbd className="rounded bg-slate-100 px-1">⌘</kbd> +{" "}
          <kbd className="rounded bg-slate-100 px-1">↵</kbd> no campo EN.
        </p>
        <button
          type="button"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => void send()}
          disabled={sending || !pt.trim() || !en.trim()}
          className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-2 text-[12px] font-bold text-white transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {sending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Send className="h-3.5 w-3.5" />
          )}
          {sending ? "A enviar…" : "Aprovar e enviar"}
        </button>
      </div>
    </div>
  );
}
