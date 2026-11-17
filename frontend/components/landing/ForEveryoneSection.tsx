"use client";

import { Building2, User, Users } from "lucide-react";

import { useI18n, type Lang } from "@/lib/i18n";

type ProfileCard = {
  tag: string;
  title: string;
  body: string;
  sample: string;
  icon: "user" | "users" | "building";
};

type Copy = {
  kicker: string;
  titleA: string;
  titleHl: string;
  sub: string;
  cards: ProfileCard[];
  note: string;
  noteSub: string;
  ticketNote: string;
  limitNote: string;
};

const COPY: Record<Lang, Copy> = {
  pt: {
    kicker: "PARA QUEM É",
    titleA: "Do pintor autônomo à construtora.",
    titleHl: "O painel é o mesmo.",
    sub: "Não existe plano pequeno nem plano enterprise. Existem oportunidades reais, um preço e o contato do dono, seja para um serviço de uma tarde ou uma obra de seis meses.",
    cards: [
      {
        tag: "1 pessoa",
        title: "Autônomo",
        body: "Pintura, mofo, porta, calha. Escolha o ofício e a região. Um serviço fechado paga várias semanas de plataforma.",
        sample: "ex. Pintura · Boston · $900",
        icon: "user",
      },
      {
        tag: "2 a 10 profissionais",
        title: "Pequena equipe",
        body: "Reformas residenciais e comerciais. Uma conta para toda a equipe, com reserva exclusiva de 60 minutos.",
        sample: "ex. Reforma · Chicago · $12k",
        icon: "users",
      },
      {
        tag: "Equipe grande",
        title: "Empreiteiro ou construtora",
        body: "Obras licenciadas, fachadas e multas. Briefing completo com dono, endereço e histórico antes da concorrência.",
        sample: "ex. Obra · New York · $140k",
        icon: "building",
      },
    ],
    note: "Sete planos semanais, do individual à equipa.",
    noteSub: "De $25,90 a $231 por semana. Cada plano inclui 10 cartas/visitas por dia.",
    ticketNote: "Valores ilustrativos de ticket. Não representam resultados.",
    limitNote: "A cota de telefones é diária e definida pelo plano (2 a 20/dia). Precisa de mais? Compre um add-on de 24h.",
  },
  en: {
    kicker: "WHO IT IS FOR",
    titleA: "From the solo painter to the builder.",
    titleHl: "Same panel.",
    sub: "There is no small plan and no enterprise plan. There are real opportunities, one price and the owner's contact, for a one-afternoon job or a six-month build.",
    cards: [
      {
        tag: "1 person",
        title: "Solo professional",
        body: "Paint, mould, doors, gutters. Pick your trade and your area. One closed job pays several weeks of the platform.",
        sample: "e.g. Painting · Boston · $900",
        icon: "user",
      },
      {
        tag: "2 to 10 people",
        title: "Small crew",
        body: "Residential and commercial remodels. One account for the whole crew, with an exclusive 60-minute hold.",
        sample: "e.g. Remodel · Chicago · $12k",
        icon: "users",
      },
      {
        tag: "Large team",
        title: "Contractor or builder",
        body: "Licensed work, facades and fines. Full brief with owner, address and history before the competition.",
        sample: "e.g. Build · New York · $140k",
        icon: "building",
      },
    ],
    note: "Seven weekly plans, from solo to a full crew.",
    noteSub: "From $25.90 to $231 per week. Every plan includes 10 letters/visits per day.",
    ticketNote: "Illustrative ticket values. Not a representation of results.",
    limitNote: "The phone quota is daily and set by your plan (2 to 20/day). Need more? Buy a 24h add-on.",
  },
  es: {
    kicker: "PARA QUIÉN ES",
    titleA: "Del pintor autónomo a la constructora.",
    titleHl: "El panel es el mismo.",
    sub: "No hay plan pequeño ni plan enterprise. Hay oportunidades reales, un precio y el contacto del dueño, ya sea para un servicio de una tarde o una obra de seis meses.",
    cards: [
      {
        tag: "1 persona",
        title: "Autónomo",
        body: "Pintura, moho, puerta, canaleta. Elige el oficio y la zona. Un servicio cerrado paga varias semanas de plataforma.",
        sample: "ej. Pintura · Boston · $900",
        icon: "user",
      },
      {
        tag: "2 a 10 profesionales",
        title: "Equipo pequeño",
        body: "Reformas residenciales y comerciales. Una cuenta para todo el equipo, con reserva exclusiva de 60 minutos.",
        sample: "ej. Reforma · Chicago · $12k",
        icon: "users",
      },
      {
        tag: "Equipo grande",
        title: "Contratista o constructora",
        body: "Obras con licencia, fachadas y multas. Informe completo con dueño, dirección e historial antes de la competencia.",
        sample: "ej. Obra · New York · $140k",
        icon: "building",
      },
    ],
    note: "Siete planes semanales, del individual al equipo completo.",
    noteSub: "De $25.90 a $231 por semana. Cada plan incluye 10 cartas/visitas al día.",
    ticketNote: "Valores ilustrativos de ticket. No representan resultados.",
    limitNote: "La cuota de teléfonos es diaria y la define tu plan (2 a 20/día). ¿Necesitas más? Compra un add-on de 24h.",
  },
};

function ProfileIcon({ icon }: { icon: ProfileCard["icon"] }) {
  if (icon === "user") return <User className="h-5 w-5" />;
  if (icon === "users") return <Users className="h-5 w-5" />;
  return <Building2 className="h-5 w-5" />;
}

export default function ForEveryoneSection() {
  const { lang } = useI18n();
  const copy = COPY[lang] ?? COPY.pt;

  return (
    <section id="para-quem" className="relative bg-white py-16 sm:py-20">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between lg:gap-12">
          <div className="max-w-3xl">
            <span className="eyebrow eyebrow-light">
              <span className="dot" />
              {copy.kicker}
            </span>
            <h2 className="font-display mt-5 text-[2rem] font-black leading-[0.99] tracking-[-0.03em] text-[#0b1220] sm:text-[2.7rem]">
              {copy.titleA} <span className="hl">{copy.titleHl}</span>
            </h2>
          </div>
          <p className="max-w-md text-[15px] leading-relaxed text-[#54617a] lg:pb-2">{copy.sub}</p>
        </div>

        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {copy.cards.map((card, index) => (
            <article key={card.title} className="bento-light relative flex h-full flex-col p-6 sm:p-7">
              <span className="mono-data absolute right-6 top-6 text-[10px] font-bold tracking-widest text-[#94a3b8]">
                0{index + 1}
              </span>
              <span className="grid h-12 w-12 place-items-center rounded-2xl border border-[#e6ebf2] bg-white text-[#0a8f65] shadow-inner">
                <ProfileIcon icon={card.icon} />
              </span>
              <p className="mt-5 text-[9.5px] font-black uppercase tracking-[0.14em] text-[#94a3b8]">
                {card.tag}
              </p>
              <h3 className="font-display mt-1.5 text-[1.35rem] font-black tracking-[-0.02em] text-[#0b1220]">
                {card.title}
              </h3>
              <p className="mt-3 flex-1 text-[14.5px] leading-relaxed text-[#54617a]">{card.body}</p>
              <p className="mt-6 inline-flex items-center gap-2 self-start rounded-full border border-[#e6ebf2] bg-white px-3 py-1.5 font-mono text-[9.5px] font-bold uppercase tracking-[0.04em] text-[#64748b]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#10b981]" />
                {card.sample}
              </p>
            </article>
          ))}
        </div>

        <div className="mt-5 rounded-2xl border border-[#e6ebf2] bg-[#f7f9fc] px-5 py-4">
          <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[13.5px] font-bold text-[#0b1220]">{copy.note}</p>
            <p className="text-[13px] text-[#64748b]">{copy.noteSub}</p>
          </div>
          <div className="mt-2.5 flex flex-col items-start gap-1.5 border-t border-[#e6ebf2] pt-2.5 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[10.5px] font-semibold text-[#94a3b8]">{copy.ticketNote}</p>
            <p className="text-[10.5px] font-semibold text-[#64748b]">{copy.limitNote}</p>
          </div>
        </div>
      </div>
    </section>
  );
}
