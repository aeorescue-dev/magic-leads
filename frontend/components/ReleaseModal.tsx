"use client";

import { useState } from "react";
import { AlertTriangle, Loader2, RefreshCcw, ShieldAlert, X } from "lucide-react";
import { RELEASE_REASONS, LeadResponse } from "@/lib/api-client";
import { useI18n } from "@/lib/i18n";

interface ReleaseModalProps {
  open: boolean;
  lead: LeadResponse | null;
  busy?: boolean;
  isDark?: boolean;
  suspiciousCount?: number;
  onClose: () => void;
  onRelease: (reason: string, note?: string) => void;
}

export default function ReleaseModal({
  open,
  lead,
  busy,
  isDark = true,
  suspiciousCount = 0,
  onClose,
  onRelease,
}: ReleaseModalProps) {
  const { t } = useI18n();
  const [reason, setReason] = useState<string>("");
  const [note, setNote] = useState<string>("");

  if (!open || !lead) return null;

  const selected = RELEASE_REASONS.find((r) => r.value === reason);
  const isSuspicious = selected && (selected as any).suspicious === true;
  const bg = isDark ? "#10121a" : "#ffffff";
  const text = isDark ? "text-slate-100" : "text-slate-900";
  const text2 = isDark ? "text-slate-400" : "text-slate-500";
  const border = isDark ? "border-white/10" : "border-slate-200";
  const inputBg = isDark ? "bg-white/5" : "bg-slate-100";

  const warnThreshold = suspiciousCount >= 3 ? "Você já acumulou " + suspiciousCount + " liberações suspeitas" : "Liberações suspeitas (mudei de ideia / sem tempo) podem reduzir sua prioridade e, com 10, suspendem a conta por 30 dias.";

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <div
        className="relative w-full max-w-md rounded-2xl border shadow-2xl p-6 space-y-4"
        style={{ backgroundColor: bg, borderColor: isDark ? "rgba(255,255,255,0.1)" : "#e2e8f0" }}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className={`h-10 w-10 rounded-xl flex items-center justify-center shrink-0 ${isDark ? "bg-rose-500/15" : "bg-rose-100"}`}>
              <RefreshCcw className={`h-5 w-5 ${isDark ? "text-rose-400" : "text-rose-600"}`} />
            </div>
            <div>
              <h3 className={`font-bold text-base ${text}`}>Liberar oportunidade</h3>
              <p className={`text-xs truncate max-w-[240px] ${text2}`}>{lead.address}</p>
            </div>
          </div>
          <button onClick={busy ? undefined : onClose} className={`${text2} hover:opacity-70 p-1`}>
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-2">
          <p className={`text-xs font-semibold uppercase tracking-wider ${text2}`}>Motivo da liberação</p>
          {RELEASE_REASONS.map((r: any) => (
            <button
              key={r.value}
              disabled={busy}
              onClick={() => setReason(r.value)}
              className={`w-full flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl border text-sm text-left transition ${
                reason === r.value
                  ? isDark
                    ? "border-rose-400 bg-rose-500/10 text-slate-100"
                    : "border-rose-500 bg-rose-50 text-slate-900"
                  : `${border} ${text} hover:opacity-80`
              } disabled:opacity-50`}
            >
              <span className={`h-4 w-4 rounded-full border shrink-0 flex items-center justify-center ${
                reason === r.value ? "border-rose-400" : border.replace("border-", "border-")
              }`}>
                {reason === r.value && <span className="h-2 w-2 rounded-full bg-rose-400" />}
              </span>
                <span className="flex-1">{t(r.key) || r.label}</span>
              {r.suspicious && <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0" />}
            </button>
          ))}
        </div>

        {isSuspicious && (
          <div className={`rounded-xl border p-3 text-xs leading-relaxed flex items-start gap-2 ${
            isDark ? "bg-amber-500/10 border-amber-500/30 text-amber-200" : "bg-amber-50 border-amber-200 text-amber-700"
          }`}>
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{warnThreshold}. Após 10, sua conta fica suspensa por 30 dias.</span>
          </div>
        )}

        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={busy}
          placeholder="Observações (opcional)"
          className={`w-full text-sm rounded-xl px-3 py-2.5 border outline-none ${border} ${inputBg} ${text} placeholder:opacity-50`}
          rows={2}
        />

        <div className="flex gap-2 pt-1">
          <button
            onClick={onClose}
            disabled={busy}
            className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold disabled:opacity-50 ${isDark ? "bg-white/10 hover:bg-white/15 text-slate-300" : "bg-slate-100 hover:bg-slate-200 text-slate-700"}`}
          >
            Cancelar
          </button>
          <button
            onClick={() => reason && onRelease(reason, note || undefined)}
            disabled={!reason || busy}
            className="flex-1 px-4 py-2.5 rounded-xl text-sm font-bold bg-rose-500 hover:bg-rose-400 text-white transition disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
            Liberar lead
          </button>
        </div>
      </div>
    </div>
  );
}