"use client";

import { useEffect, useState } from "react";
import { Download, FileText, X } from "lucide-react";

export interface AttachmentCardProps {
  url: string;
  downloadUrl: string;
  filename: string;
  contentType: string | null;
  sizeBytes: number;
  compact?: boolean;
}

function sizeLabel(bytes: number): string {
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function AttachmentCard({
  url,
  downloadUrl,
  filename,
  contentType,
  sizeBytes,
  compact = false,
}: AttachmentCardProps) {
  const [open, setOpen] = useState(false);
  const isImage = (contentType || "").startsWith("image/");

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!isImage) {
    return (
      <div
        className={`flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-1.5 ${
          compact ? "" : "p-2"
        }`}
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-slate-50 text-slate-500 ring-1 ring-slate-200">
          <FileText className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[10px] font-bold text-slate-800">
            {filename}
          </span>
          <span className="block text-[8.5px] text-slate-500">
            {sizeLabel(sizeBytes)}
          </span>
        </span>
        <a
          href={downloadUrl}
          download={filename}
          aria-label={`Baixar ${filename}`}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 hover:border-emerald-300 hover:text-emerald-700"
        >
          <Download className="h-3.5 w-3.5" />
        </a>
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Abrir ${filename}`}
        className="group block w-full overflow-hidden rounded-lg border border-slate-200 bg-white text-left transition hover:border-emerald-300"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt={filename}
          className={`w-full object-cover ${
            compact ? "h-20" : "h-28"
          }`}
        />
        <span className="flex items-center justify-between gap-2 px-2 py-1.5">
          <span className="min-w-0 flex-1 truncate text-[9.5px] font-bold text-slate-800">
            {filename}
          </span>
          <span className="shrink-0 text-[8.5px] text-slate-500">
            {sizeLabel(sizeBytes)}
          </span>
        </span>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label={filename}
          onClick={() => setOpen(false)}
        >
          <div
            className="relative max-h-[92vh] w-full max-w-3xl rounded-2xl bg-white p-3 shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 pb-2">
              <p className="min-w-0 truncate text-[12px] font-bold text-slate-800">
                {filename}
              </p>
              <div className="flex shrink-0 items-center gap-1.5">
                <a
                  href={downloadUrl}
                  download={filename}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-bold text-slate-700 hover:border-emerald-300 hover:text-emerald-700"
                >
                  <Download className="h-3.5 w-3.5" />
                  Download
                </a>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  aria-label="Fechar pré-visualização"
                  className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 hover:border-rose-300 hover:text-rose-600"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={url}
              alt={filename}
              className="mx-auto max-h-[78vh] w-auto max-w-full rounded-lg object-contain"
            />
          </div>
        </div>
      )}
    </>
  );
}
