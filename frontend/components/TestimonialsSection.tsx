'use client';

import { Quote, Star, BadgeCheck } from "lucide-react";
import { useI18n } from "@/lib/i18n";

export function TestimonialsSection() {
  const { t } = useI18n();

  const testimonials = [
    {
      key: "1",
      quote: t("testimonials.quote.1"),
      name: t("testimonials.name.1"),
      role: t("testimonials.role.1"),
      metric: t("testimonials.metric.1"),
    },
    {
      key: "2",
      quote: t("testimonials.quote.2"),
      name: t("testimonials.name.2"),
      role: t("testimonials.role.2"),
      metric: t("testimonials.metric.2"),
    },
    {
      key: "3",
      quote: t("testimonials.quote.3"),
      name: t("testimonials.name.3"),
      role: t("testimonials.role.3"),
      metric: t("testimonials.metric.3"),
    },
    {
      key: "4",
      quote: t("testimonials.quote.4"),
      name: t("testimonials.name.4"),
      role: t("testimonials.role.4"),
      metric: t("testimonials.metric.4"),
    },
  ];

  return (
    <section className="section bg-slate-950/30" aria-labelledby="testimonials-title">
      <div className="container-custom">
        <div className="text-center mb-12">
          <span className="inline-flex items-center gap-2 rounded-full bg-emerald-500/10 text-emerald-400 px-4 py-1.5 text-xs font-semibold uppercase tracking-wide mb-4">
            <BadgeCheck className="h-3.5 w-3.5" /> {t("testimonials.badge")}
          </span>
          <h2 id="testimonials-title" className="section-title">
            {t("testimonials.title.1")}<span className="text-emerald-400"> {t("testimonials.title.2")}</span>
          </h2>
          <p className="section-subtitle">{t("testimonials.sub")}</p>
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          {testimonials.map((item) => (
            <article
              key={item.key}
              className="card p-6 md:p-8 relative overflow-hidden group card-hover"
            >
              <div className="absolute -top-4 -right-2 text-7xl font-extrabold text-emerald-500/10 group-hover:text-emerald-500/15 transition-colors">
                &ldquo;
              </div>

              <div className="flex items-center gap-1 mb-4">
                {[0, 1, 2, 3, 4].map((s) => (
                  <Star key={s} className="h-4 w-4 fill-amber-400 text-amber-400" />
                ))}
              </div>

              <Quote className="h-6 w-6 text-emerald-400/70 mb-3" />

              <p className="text-slate-300 leading-relaxed mb-6">
                {item.quote}
              </p>

              <div className="pt-4 border-t border-slate-800/50 flex items-center justify-between gap-3 flex-wrap">
                <div>
                  <p className="font-bold text-white">
                    {item.name}
                    <BadgeCheck className="h-4 w-4 text-emerald-400 inline ml-1.5 -mt-0.5" />
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">{item.role}</p>
                </div>
                <div className="text-right">
                  <p className="text-xs font-bold text-emerald-400 uppercase tracking-wide">
                    {item.metric}
                  </p>
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
