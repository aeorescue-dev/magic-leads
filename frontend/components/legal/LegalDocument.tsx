"use client";

import { Fragment } from "react";
import Link from "next/link";
import { useI18n } from "@/lib/i18n";
import { LEGAL_CONTENT, type LegalKind } from "./content";

const EMAIL = "contato@magicleads.app";

function withEmail(text: string) {
  const parts = text.split(EMAIL);
  return parts.map((part, index) => (
    <Fragment key={`${part}-${index}`}>
      {part}
      {index < parts.length - 1 && (
        <a href={`mailto:${EMAIL}`} className="font-semibold text-[#0a8f65] hover:underline">
          {EMAIL}
        </a>
      )}
    </Fragment>
  ));
}

export default function LegalDocument({ kind }: { kind: LegalKind }) {
  const { lang } = useI18n();
  const doc = LEGAL_CONTENT[lang]?.[kind] ?? LEGAL_CONTENT.en[kind];

  return (
    <main className="surface-light min-h-[70vh] py-16 md:py-24">
      <div className="mx-auto max-w-4xl px-4 sm:px-6">
        <Link
          href={`/${lang}`}
          className="text-xs font-black uppercase tracking-[0.14em] text-[#0a8f65] transition hover:text-[#0b1220]"
        >
          ← {doc.back}
        </Link>

        <span className="eyebrow eyebrow-light mt-8">{doc.label}</span>
        <h1 className="font-display mt-5 text-[2.35rem] font-black leading-[0.98] tracking-[-0.03em] text-[#0b1220] sm:text-5xl">
          {doc.title}
        </h1>
        <p className="mt-4 text-xs font-semibold uppercase tracking-[0.1em] text-[#94a3b8]">{doc.updated}</p>
        <p className="mt-6 text-base leading-relaxed text-[#54617a] sm:text-lg">{doc.intro}</p>

        <div className="mt-10 space-y-9">
          {doc.sections.map((section) => (
            <section key={section.title} id={section.id} className="scroll-mt-24">
              <h2 className="font-display text-xl font-black tracking-[-0.02em] text-[#0b1220] sm:text-2xl">
                {section.title}
              </h2>
              {section.body?.map((paragraph) => (
                <p key={paragraph} className="mt-3 text-[15px] leading-relaxed text-[#54617a]">
                  {withEmail(paragraph)}
                </p>
              ))}
              {section.bullets?.length ? (
                <ul className="mt-3 list-disc space-y-2 pl-5 text-[15px] leading-relaxed text-[#54617a]">
                  {section.bullets.map((item) => (
                    <li key={item}>{withEmail(item)}</li>
                  ))}
                </ul>
              ) : null}
            </section>
          ))}
        </div>

        <div className="mt-12 rounded-2xl border border-[#10b981]/20 bg-white p-6">
          <p className="text-xs font-black uppercase tracking-[0.14em] text-[#0a8f65]">{doc.contactTitle}</p>
          <p className="mt-2 text-sm leading-relaxed text-[#54617a]">{withEmail(doc.contactBody)}</p>
        </div>
      </div>
    </main>
  );
}
