"use client";

import { useState } from "react";
import { CheckCircle2, RefreshCw, Sparkles } from "lucide-react";

import {
  LP_FLOWS,
  type LpIntentKey,
  type LpReplySuggestion,
} from "./data";
import type { LpDemoSubmission } from "./LpWidgetPanel";

interface Props {
  intent: LpIntentKey | null;
  submission: LpDemoSubmission | null;
  questionPreview?: string;
  onSendReply: (text: string) => void;
}

/**
 * Componente exclusivo da pré-visualização. Mostra o lado interno (PT-BR) e
 * permite simular a aprovação humana antes do envio em inglês. Não faz parte
 * do bundle da LP e não chama APIs.
 */
export default function LpWidgetInboxPreview({
  intent,
  submission,
  questionPreview = "",
  onSendReply,
}: Props) {
  const flow = intent ? LP_FLOWS[intent] : null;
  const [replyIndex, setReplyIndex] = useState(0);
  const [replyText, setReplyText] = useState(
    intent ? LP_FLOWS[intent].replies[0].pt : ""
  );
  const [sent, setSent] = useState(false);

  function chooseReply(index: number, suggestion: LpReplySuggestion) {
    setReplyIndex(index);
    setReplyText(suggestion.pt);
  }

  function send() {
    if (!flow || !submission || sent) return;
    onSendReply(flow.replies[replyIndex].en);
    setSent(true);
  }

  if (!flow) {
    return (
      <aside className="flex min-h-[420px] flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <p className="text-[10px] font-black uppercase tracking-[0.12em] text-violet-600">
          Inbox interna · PT-BR
        </p>
        <h2 className="mt-1 text-[15px] font-bold text-slate-900">
          Conversa #LP-1042
        </h2>
        <div className="flex flex-1 flex-col items-center justify-center py-12 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-50 text-xl">
            ✉️
          </span>
          <p className="mt-3 max-w-[240px] text-[11.5px] leading-relaxed text-slate-400">
            Nenhuma mensagem ainda. Escolha um tópico no widget para ver a
            tradução em PT-BR e as respostas sugeridas.
          </p>
        </div>
        <p className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-[9.5px] leading-relaxed text-emerald-800">
          <b className="block text-[8.5px] uppercase tracking-wide">
            Vocabulário aprovado
          </b>
          public records · verified property databases · proprietary monitoring
        </p>
      </aside>
    );
  }

  const custom = Boolean(
    (submission?.question || questionPreview) &&
      (submission?.question || questionPreview) !== flow.question
  );
  const effectiveQuestion =
    submission?.question || questionPreview || flow.question;

  return (
    <aside className="flex max-h-[calc(100vh-40px)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm lg:sticky lg:top-5">
      <header className="flex items-start justify-between gap-3 border-b border-slate-100 bg-gradient-to-b from-slate-50/70 to-white px-4 py-3">
        <div>
          <p className="text-[9px] font-black uppercase tracking-[0.12em] text-violet-600">
            Inbox interna · PT-BR
          </p>
          <h2 className="mt-0.5 text-[13.5px] font-bold text-slate-900">
            Conversa <span className="text-slate-400">#LP-1042</span>
          </h2>
          <p className="mt-0.5 text-[9.5px] text-slate-400">
            Lead nos EUA · EN → PT-BR · SLA 4 h úteis
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-1 text-[8px] font-black uppercase tracking-wide ${
            sent
              ? "bg-emerald-100 text-emerald-700"
              : submission
                ? "bg-amber-100 text-amber-800"
                : "bg-indigo-50 text-indigo-600"
          }`}
        >
          {sent ? "Respondido" : submission ? "Novo · SLA 4h" : "Pré-visualização"}
        </span>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        <div className="mb-2 flex flex-wrap gap-1">
          {submission?.trade && (
            <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[8.5px] font-bold text-slate-500">
              trade: {submission.trade}
            </span>
          )}
          {submission?.city && (
            <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[8.5px] font-bold text-slate-500">
              city: {submission.city}
            </span>
          )}
          {submission?.call && (
            <span className="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[8.5px] font-bold text-emerald-700">
              request: 15-min call
            </span>
          )}
          <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[8.5px] font-bold text-slate-500">
            source: LP widget
          </span>
        </div>

        <div className="rounded-xl border border-slate-200 p-2.5">
          <p className="flex items-center justify-between text-[8.5px] font-black uppercase tracking-wide text-slate-400">
            Original do lead <b className="text-violet-600">EN</b>
          </p>
          <p className="mt-1 text-[11.5px] leading-relaxed text-slate-600">
            {effectiveQuestion}
          </p>
        </div>

        <div className="mt-2 rounded-xl border border-violet-200 bg-violet-50/40 p-2.5">
          <p className="flex items-center justify-between text-[8.5px] font-black uppercase tracking-wide text-slate-400">
            <span className="flex items-center gap-1">
              <Sparkles className="h-3 w-3 text-violet-500" />
              Tradução · IA
            </span>
            <span className="flex gap-1">
              <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[8px] text-violet-700">
                {flow.confidence}
              </span>
              <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[8px] text-emerald-700">
                policy ✓
              </span>
            </span>
          </p>
          <p className="mt-1 text-[11.5px] leading-relaxed text-violet-950/80">
            {custom
              ? "Texto livre: em produção, a IA traduz esta mensagem para PT-BR em tempo real. Escolha um exemplo para ver a tradução completa neste protótipo."
              : flow.questionPt}
          </p>
        </div>

        <div className="mt-2 flex flex-wrap gap-1">
          {flow.tags.map((tag) => (
            <span
              key={tag}
              className="rounded bg-slate-100 px-1.5 py-0.5 text-[8px] font-bold text-slate-500"
            >
              {tag}
            </span>
          ))}
        </div>

        <div className="mt-3 flex items-center justify-between">
          <p className="text-[8.5px] font-black uppercase tracking-wide text-slate-400">
            Respostas sugeridas · PT-BR
          </p>
          <button
            type="button"
            onClick={() => {
              const next = (replyIndex + 1) % flow.replies.length;
              chooseReply(next, flow.replies[next]);
            }}
            className="flex items-center gap-1 rounded border border-slate-200 px-1.5 py-1 text-[8.5px] font-bold text-slate-500 hover:border-violet-300 hover:text-violet-700"
          >
            <RefreshCw className="h-2.5 w-2.5" />
            Outra opção
          </button>
        </div>

        <div className="mt-1.5 space-y-1.5">
          {flow.replies.map((suggestion, index) => (
            <button
              key={suggestion.pt}
              type="button"
              onClick={() => chooseReply(index, suggestion)}
              className={`w-full rounded-lg border p-2 text-left transition ${
                replyIndex === index
                  ? "border-emerald-400 bg-emerald-50/70 shadow-[0_0_0_3px_rgba(16,185,129,0.08)]"
                  : "border-slate-200 bg-white hover:border-emerald-200"
              }`}
            >
              <span className="text-[8px] font-black uppercase tracking-wide text-emerald-700">
                Opção {index + 1}
              </span>
              <span className="mt-0.5 block text-[10.5px] leading-relaxed text-slate-600">
                {suggestion.pt}
              </span>
            </button>
          ))}
        </div>

        <p className="mt-3 text-[8.5px] font-black uppercase tracking-wide text-slate-400">
          Resposta da equipa
        </p>
        <textarea
          value={replyText}
          onChange={(event) => setReplyText(event.target.value)}
          rows={3}
          className="mt-1 w-full resize-y rounded-lg border border-slate-200 px-2.5 py-2 text-[11px] leading-relaxed text-slate-700 outline-none focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
        />

        <div className="mt-2 flex gap-1.5">
          <button
            type="button"
            onClick={() => setReplyText(flow.replies[replyIndex].pt)}
            className="flex-1 rounded-lg border border-slate-200 bg-white py-2 text-[9.5px] font-bold text-slate-500 hover:border-violet-300 hover:text-violet-700"
          >
            Re-traduzir
          </button>
          <button
            type="button"
            onClick={send}
            disabled={!submission || sent}
            className="flex-1 rounded-lg bg-emerald-500 py-2 text-[9.5px] font-bold text-white transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {sent ? "Enviado ✓" : "Aprovar e enviar"}
          </button>
        </div>

        <p className="mt-1.5 text-center text-[8.5px] leading-relaxed text-slate-400">
          {submission
            ? "Revisão humana obrigatória antes do envio final em inglês."
            : "Aguarda o envio do visitante."}
        </p>

        {sent && (
          <div className="mt-2 rounded-lg border border-emerald-100 bg-emerald-50 px-2.5 py-2 text-[8.5px] leading-relaxed text-emerald-800">
            <p className="flex items-center gap-1 font-bold">
              <CheckCircle2 className="h-3 w-3" />
              Entrega concluída
            </p>
            Widget (instantâneo) + Email transacional (Resend). Original EN e
            resposta PT-BR preservados na auditoria.
          </div>
        )}
      </div>

      <footer className="border-t border-slate-100 px-4 py-2">
        <p className="rounded-lg border border-emerald-100 bg-emerald-50 px-2.5 py-1.5 text-[8.5px] leading-relaxed text-emerald-800">
          <b className="block text-[8px] uppercase tracking-wide">
            Vocabulário aprovado
          </b>
          public records · verified property databases · proprietary monitoring
        </p>
      </footer>
    </aside>
  );
}
