export type LpIntentKey =
  | "vs_ads"
  | "vs_angi"
  | "phones"
  | "price"
  | "area"
  | "question";

export interface LpReplySuggestion {
  pt: string;
  en: string;
}

export interface LpIntentFlow {
  key: LpIntentKey;
  chip: string;
  sub: string;
  question: string;
  questionPt: string;
  tags: string[];
  confidence: string;
  replies: LpReplySuggestion[];
}

export const LP_INTENTS: LpIntentFlow[] = [
  {
    key: "vs_ads",
    chip: "Stop burning $70–$200/day on Ads",
    sub: "If ads aren't converting, here's the math.",
    question:
      "I'm spending $70–$200 a day on Facebook and Google Ads and barely converting. Why is this better?",
    questionPt:
      "Estou a gastar $70–$200 por dia em anúncios no Facebook e no Google e quase não converto. Porque é que isto é melhor?",
    tags: [
      "intent: ad waste",
      "pain: $70–$200/day",
      "channels: Facebook + Google",
      "lang: en-US",
    ],
    confidence: "0.96",
    replies: [
      {
        pt: "Porque aqui não paga por cliques. Paga $120 por semana por oportunidades concretas, com proprietário identificado e telefone verificado — reservadas 60 minutos só para si. Se um único trabalho fechar, o passe pagou-se.",
        en: "Because here you don't pay for clicks. You pay $120 a week for concrete opportunities, with an identified owner and a verified phone — reserved for 60 minutes only for you. If a single job closes, the pass pays for itself.",
      },
      {
        pt: "A $70–$200 por dia, os anúncios compram impressões e contactos partilhados. Aqui vê a oportunidade antes de gastar tempo: morada, proprietário e telefone. Sem leilão e sem contrato.",
        en: "At $70–$200 a day, ads buy impressions and shared contacts. Here you see the opportunity before spending time: address, owner, and phone. No auction and no contract.",
      },
    ],
  },
  {
    key: "vs_angi",
    chip: "Zero bidding wars vs Angi",
    sub: "One lead. One contractor. 60 minutes.",
    question:
      "How is Magic Leads different from Angi or HomeAdvisor? Aren't the leads shared?",
    questionPt:
      "Qual é a diferença entre a Magic Leads e o Angi ou o HomeAdvisor? Os leads não são partilhados?",
    tags: [
      "intent: differentiation",
      "competitor: Angi / HomeAdvisor",
      "topic: exclusivity",
      "lang: en-US",
    ],
    confidence: "0.97",
    replies: [
      {
        pt: "No Angi ou no HomeAdvisor, o mesmo pedido pode ser revendido a vários empreiteiros. Aqui é o contrário: uma oportunidade, um profissional, 60 minutos de reserva. Não há leilão nem divisão do contacto.",
        en: "On Angi or HomeAdvisor, the same request can be resold to several contractors. Here it's the opposite: one opportunity, one professional, a 60-minute reservation. No auction and no split contact.",
      },
      {
        pt: "Não competimos por cliques. Recebe uma oportunidade concreta, com morada e proprietário identificado, e decide em 60 minutos se faz sentido. Sem guerra de lances.",
        en: "We don't compete for clicks. You get a concrete opportunity, with an address and an identified owner, and you decide in 60 minutes whether it's a fit. No bidding war.",
      },
    ],
  },
  {
    key: "phones",
    chip: "Get the owner's phone — exclusively",
    sub: "Direct contact at the moment of need.",
    question: "How do I get exclusive owner phone numbers?",
    questionPt: "Como consigo números de telefone exclusivos do proprietário?",
    tags: ["intent: access", "topic: owner phone", "lang: en-US"],
    confidence: "0.98",
    replies: [
      {
        pt: "Cada oportunidade inclui o contacto direto do proprietário, identificado no momento em que a necessidade aparece. O telefone é verificado antes de chegar ao painel e fica disponível só para quem reserva.",
        en: "Every opportunity includes the owner's direct contact, identified at the moment the need appears. The phone is verified before it reaches the dashboard and is only available to the contractor who reserves it.",
      },
      {
        pt: "Não é uma lista comprada. É o proprietário do imóvel, com morada e telefone verificados. Reserva e liga diretamente, sem intermediários.",
        en: "It's not a purchased list. It's the property owner, with a verified address and phone. Reserve and call directly, with no middlemen.",
      },
    ],
  },
  {
    key: "price",
    chip: "$120/week. No contract.",
    sub: "Cancel anytime. No setup fee.",
    question: "What exactly do I get for $120 per week? Is there a contract?",
    questionPt: "O que recebo exatamente por $120 por semana? Existe contrato?",
    tags: [
      "intent: pricing",
      "topic: contract",
      "plan: weekly",
      "lang: en-US",
    ],
    confidence: "0.97",
    replies: [
      {
        pt: "Por $120 por semana tem acesso ao painel com oportunidades da sua cidade e do seu ofício, com proprietário, morada e telefone verificados. Sem contrato: o passe é semanal e cancela quando quiser.",
        en: "For $120 a week you get access to the dashboard with opportunities in your city and trade, including the verified owner, address, and phone. No contract: the pass is weekly and you can cancel anytime.",
      },
      {
        pt: "Inclui a reserva exclusiva de 60 minutos por oportunidade e acesso contínuo ao painel. Sem taxa de adesão e sem cobrança por lead.",
        en: "It includes the exclusive 60-minute reservation per opportunity and continuous access to the dashboard. No setup fee and no per-lead charge.",
      },
    ],
  },
  {
    key: "area",
    chip: "Check leads in my city & trade",
    sub: "See today's availability in 30 seconds.",
    question: "Do you have leads in my city and trade today?",
    questionPt: "Vocês têm oportunidades na minha cidade e no meu ofício hoje?",
    tags: ["intent: coverage", "topic: city + trade", "lang: en-US"],
    confidence: "0.96",
    replies: [
      {
        pt: "Temos oportunidades novas todos os dias em Nova Iorque, Boston, Dallas e Chicago. Diga-me a cidade e o ofício e eu confirmo agora o que está disponível.",
        en: "We have new opportunities every day in New York, Boston, Dallas, and Chicago. Tell me your city and trade and I'll confirm what's available right now.",
      },
      {
        pt: "A cobertura cresce por cidade e por ofício. Envie a cidade e a categoria e eu verifico a disponibilidade de hoje — sem compromisso.",
        en: "Coverage grows by city and trade. Send your city and category and I'll check today's availability — no commitment.",
      },
    ],
  },
  {
    key: "question",
    chip: "Something else",
    sub: "Type your own question.",
    question: "How does the 60-minute reservation work?",
    questionPt: "Como funciona a reserva de 60 minutos?",
    tags: ["intent: question", "lang: en-US"],
    confidence: "0.95",
    replies: [
      {
        pt: "Claro — obrigado pela pergunta. Cada oportunidade é exclusiva, com proprietário identificado e telefone verificado, e fica reservada 60 minutos. Quer que eu confirme a cobertura da sua cidade?",
        en: "Of course — thanks for asking. Every opportunity is exclusive, with an identified owner and a verified phone, and it's reserved for 60 minutes. Would you like me to confirm coverage for your city?",
      },
      {
        pt: "Boa pergunta. Posso responder em detalhe por e-mail ou enviar 3 exemplos reais da sua cidade e do seu ofício ainda hoje. Qual prefere?",
        en: "Great question. I can answer in detail by email or send you 3 real examples from your city and trade today. Which do you prefer?",
      },
    ],
  },
];

export const LP_FLOWS: Record<LpIntentKey, LpIntentFlow> = LP_INTENTS.reduce(
  (acc, flow) => {
    acc[flow.key] = flow;
    return acc;
  },
  {} as Record<LpIntentKey, LpIntentFlow>
);

export const LP_TRADES = [
  "Roofing",
  "HVAC",
  "Plumbing",
  "Electrical",
  "Remodeling",
  "Painting",
  "Other",
];

export const LP_CITIES = [
  "New York",
  "Boston",
  "Dallas",
  "Chicago",
  "Another city",
];

export const LP_SAMPLES = [
  {
    en: "How does the 60-minute reservation work?",
    pt: "Como funciona a reserva de 60 minutos?",
  },
  {
    en: "Can I see a sample before I pay?",
    pt: "Posso ver uma amostra antes de pagar?",
  },
  {
    en: "How fast can I start?",
    pt: "Com que rapidez posso começar?",
  },
  {
    en: "Do you cover roofing in Boston?",
    pt: "Vocês cobrem telhados em Boston?",
  },
];
