import type { LpIntentKey } from "./data";

export type WidgetLang = "en" | "pt" | "es";

export const WIDGET_LANGS: Array<{
  code: WidgetLang;
  label: string;
  native: string;
  flag: "us" | "br" | "es";
}> = [
  { code: "en", label: "English (US)", native: "English", flag: "us" },
  { code: "pt", label: "Português (BR)", native: "Português", flag: "br" },
  { code: "es", label: "Español (ES)", native: "Español", flag: "es" },
];

const EN = {
  language: "Language",
  searchLanguage: "Search language…",
  noLanguage: "No language found.",
  online: "Online · avg. reply under 4 business hours",
  close: "Close chat",
  q1: "Where are you losing money right now?",
  hint1: "Pick the one that hurts most. About 30 seconds.",
  ownPlaceholder: "Or type your question…",
  sendQuestion: "Send question",
  micro: "No contract · Cancel anytime · $120/week",
  q2: "Where do you work?",
  hint2: "This is how we check today's availability.",
  check: "Check availability",
  back: "← Back",
  q3: "Where should we send the answer?",
  hint3: "Edit your message if you want. We reply in writing.",
  message: "Your message",
  email: "Work email",
  firstName: "First name (optional)",
  company: "Company (optional)",
  consent:
    "I agree to receive a reply by email. No marketing spam, unsubscribe anytime.",
  send: "Send message",
  sending: "Sending…",
  private: "Private · No spam · Reply under 4 business hours",
  errMessage: "Write a short message so we can help.",
  errEmail: "Enter a valid work email.",
  errConsent: "Please confirm you agree to receive a reply by email.",
  conversation: "Conversation",
  reviewing: "A specialist is reviewing your message.",
  typing: "Magic Leads is typing…",
  delivered: "Reply delivered",
  widgetBadge: "Widget · instant",
  emailBadge: "Email · Resend",
  replySentTo: "The reply was also sent to",
  checkCity: "Check availability in my city →",
  startOver: "↺ Start over",
  noContract: "No contract · Cancel anytime · $120/week",
  systemAck:
    "Message received. A specialist will reply within 4 business hours.",
  networkError: "Could not send your message. Please try again.",
};

type Copy = { [K in keyof typeof EN]: string };

const PT: Copy = {
  language: "Idioma",
  searchLanguage: "Pesquisar idioma…",
  noLanguage: "Nenhum idioma encontrado.",
  online: "Online · resposta média em até 4 horas úteis",
  close: "Fechar conversa",
  q1: "Onde está a perder dinheiro agora?",
  hint1: "Escolha o que mais dói. Cerca de 30 segundos.",
  ownPlaceholder: "Ou escreva a sua pergunta…",
  sendQuestion: "Enviar pergunta",
  micro: "Sem contrato · Cancele quando quiser · $120/semana",
  q2: "Onde trabalha?",
  hint2: "É assim que verificamos a disponibilidade de hoje.",
  check: "Ver disponibilidade",
  back: "← Voltar",
  q3: "Para onde enviamos a resposta?",
  hint3: "Edite a mensagem se quiser. Respondemos por escrito.",
  message: "A sua mensagem",
  email: "E-mail profissional",
  firstName: "Nome (opcional)",
  company: "Empresa (opcional)",
  consent:
    "Concordo em receber uma resposta por e-mail. Sem spam, cancele quando quiser.",
  send: "Enviar mensagem",
  sending: "A enviar…",
  private: "Privado · Sem spam · Resposta em até 4 horas úteis",
  errMessage: "Escreva uma mensagem curta para podermos ajudar.",
  errEmail: "Introduza um e-mail profissional válido.",
  errConsent: "Confirme que aceita receber uma resposta por e-mail.",
  conversation: "Conversa",
  reviewing: "Um especialista está a rever a sua mensagem.",
  typing: "A Magic Leads está a escrever…",
  delivered: "Resposta entregue",
  widgetBadge: "Widget · instantâneo",
  emailBadge: "Email · Resend",
  replySentTo: "A resposta também foi enviada para",
  checkCity: "Ver disponibilidade na minha cidade →",
  startOver: "↺ Começar de novo",
  noContract: "Sem contrato · Cancele quando quiser · $120/semana",
  systemAck:
    "Mensagem recebida. Um especialista responde em até 4 horas úteis.",
  networkError: "Não foi possível enviar a mensagem. Tente novamente.",
};

const ES: Copy = {
  language: "Idioma",
  searchLanguage: "Buscar idioma…",
  noLanguage: "No se encontró el idioma.",
  online: "En línea · respuesta media en 4 horas hábiles",
  close: "Cerrar chat",
  q1: "¿Dónde estás perdiendo dinero ahora?",
  hint1: "Elige lo que más te duela. Unos 30 segundos.",
  ownPlaceholder: "O escribe tu pregunta…",
  sendQuestion: "Enviar pregunta",
  micro: "Sin contrato · Cancela cuando quieras · $120/semana",
  q2: "¿Dónde trabajas?",
  hint2: "Así comprobamos la disponibilidad de hoy.",
  check: "Ver disponibilidad",
  back: "← Volver",
  q3: "¿A dónde enviamos la respuesta?",
  hint3: "Edita el mensaje si quieres. Respondemos por escrito.",
  message: "Tu mensaje",
  email: "Correo de trabajo",
  firstName: "Nombre (opcional)",
  company: "Empresa (opcional)",
  consent:
    "Acepto recibir una respuesta por correo. Sin spam, cancela cuando quieras.",
  send: "Enviar mensaje",
  sending: "Enviando…",
  private: "Privado · Sin spam · Respuesta en 4 horas hábiles",
  errMessage: "Escribe un mensaje breve para que podamos ayudarte.",
  errEmail: "Introduce un correo de trabajo válido.",
  errConsent: "Confirma que aceptas recibir una respuesta por correo.",
  conversation: "Conversación",
  reviewing: "Un especialista está revisando tu mensaje.",
  typing: "Magic Leads está escribiendo…",
  delivered: "Respuesta entregada",
  widgetBadge: "Widget · instantáneo",
  emailBadge: "Email · Resend",
  replySentTo: "La respuesta también se envió a",
  checkCity: "Ver disponibilidad en mi ciudad →",
  startOver: "↺ Empezar de nuevo",
  noContract: "Sin contrato · Cancela cuando quieras · $120/semana",
  systemAck:
    "Mensaje recibido. Un especialista responderá en un plazo de 4 horas hábiles.",
  networkError: "No se pudo enviar el mensaje. Inténtalo de nuevo.",
};

export const WIDGET_COPY: Record<WidgetLang, Copy> = {
  en: EN,
  pt: PT,
  es: ES,
};

export interface IntentCopy {
  chip: string;
  sub: string;
  question: string;
}

export const INTENT_L10N: Record<
  Exclude<WidgetLang, "en">,
  Record<LpIntentKey, IntentCopy>
> = {
  pt: {
    vs_ads: {
      chip: "Pare de queimar $70–$200/dia em anúncios",
      sub: "Se os anúncios não convertem, veja a conta.",
      question:
        "Estou a gastar $70–$200 por dia em anúncios no Facebook e no Google e quase não converto. Porque é que isto é melhor?",
    },
    vs_angi: {
      chip: "Zero leilões vs Angi",
      sub: "Um lead. Um empreiteiro. 60 minutos.",
      question:
        "Qual é a diferença entre a Magic Leads e o Angi ou o HomeAdvisor? Os leads não são partilhados?",
    },
    phones: {
      chip: "Receba o telefone do proprietário — em exclusivo",
      sub: "Contacto direto no momento da necessidade.",
      question: "Como consigo números de telefone exclusivos do proprietário?",
    },
    price: {
      chip: "$120/semana. Sem contrato.",
      sub: "Cancele quando quiser. Sem taxa de adesão.",
      question: "O que recebo exatamente por $120 por semana? Existe contrato?",
    },
    area: {
      chip: "Ver leads na minha cidade e ofício",
      sub: "Veja a disponibilidade de hoje em 30 segundos.",
      question: "Vocês têm oportunidades na minha cidade e no meu ofício hoje?",
    },
    question: {
      chip: "Outra pergunta",
      sub: "Escreva a sua própria pergunta.",
      question: "Como funciona a reserva de 60 minutos?",
    },
  },
  es: {
    vs_ads: {
      chip: "Deja de quemar $70–$200/día en anuncios",
      sub: "Si los anuncios no convierten, aquí están las cuentas.",
      question:
        "Estoy gastando $70–$200 al día en anuncios de Facebook y Google y apenas convierto. ¿Por qué esto es mejor?",
    },
    vs_angi: {
      chip: "Cero subastas vs Angi",
      sub: "Un lead. Un contratista. 60 minutos.",
      question:
        "¿En qué se diferencia Magic Leads de Angi o HomeAdvisor? ¿Los leads no se comparten?",
    },
    phones: {
      chip: "Consigue el teléfono del propietario — en exclusiva",
      sub: "Contacto directo en el momento de la necesidad.",
      question: "¿Cómo consigo números de teléfono exclusivos del propietario?",
    },
    price: {
      chip: "$120/semana. Sin contrato.",
      sub: "Cancela cuando quieras. Sin cuota de alta.",
      question: "¿Qué recibo exactamente por $120 a la semana? ¿Hay contrato?",
    },
    area: {
      chip: "Ver leads en mi ciudad y oficio",
      sub: "Consulta la disponibilidad de hoy en 30 segundos.",
      question: "¿Tienen oportunidades en mi ciudad y mi oficio hoy?",
    },
    question: {
      chip: "Otra pregunta",
      sub: "Escribe tu propia pregunta.",
      question: "¿Cómo funciona la reserva de 60 minutos?",
    },
  },
};
