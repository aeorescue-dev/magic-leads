export type LegalLang = "pt" | "en" | "es";
export type LegalKind = "privacy" | "terms";

export type LegalSection = {
  id?: string;
  title: string;
  body?: string[];
  bullets?: string[];
};

export type LegalDoc = {
  label: string;
  title: string;
  updated: string;
  intro: string;
  back: string;
  contactTitle: string;
  contactBody: string;
  sections: LegalSection[];
};

const PT_PRIVACY: LegalDoc = {
  label: "Legal",
  title: "Política de Privacidade",
  updated: "Última atualização: 12 de novembro de 2026",
  intro:
    "Esta política explica como a Magic Leads coleta, usa e protege dados pessoais no site magicleads.app e nos serviços relacionados.",
  back: "Voltar ao site",
  contactTitle: "Fale com a gente",
  contactBody:
    "Dúvidas sobre privacidade ou solicitações de dados: contato@magicleads.app. Assunto: Privacidade.",
  sections: [
    {
      title: "Quem somos",
      body: [
        "A Magic Leads é operada por uma atividade empresarial individual registrada em New Jersey, EUA. Magic Leads e Magic Leads Technologies são nomes comerciais utilizados nesta plataforma. A identificação legal completa é fornecida às operadoras, processadores de pagamento e autoridades quando necessário.",
        "Para fins desta política, Magic Leads, nós e nosso se referem a esse titular.",
      ],
    },
    {
      title: "Dados que coletamos",
      body: [
        "Dados de conta: nome, e-mail, telefone, empresa, especialidade, cidade e ZIP, credenciais de acesso e preferências.",
        "Dados de uso: páginas acessadas, endereço IP, navegador, dispositivo, data e hora, e interações com o painel.",
        "Dados de oportunidades: informações sobre imóveis e proprietários usadas para entregar as oportunidades do serviço.",
        "Dados de comunicação e consentimento: mensagens de suporte, registros de chamadas e registros de opt-in e opt-out de SMS.",
        "Pagamentos: processados por um provedor de pagamento. Não armazenamos o número completo do cartão.",
      ],
    },
    {
      title: "Como usamos os dados",
      body: [
        "Para fornecer, operar e melhorar o serviço, incluindo reservas, revelações, alertas e suporte.",
        "Para processar pagamentos, prevenir fraudes, cumprir obrigações legais e aplicar nossos termos.",
        "Para enviar comunicações transacionais solicitadas por você.",
        "Não usamos os dados para enviar SMS de marketing ou cold SMS.",
      ],
    },
    {
      id: "sms",
      title: "SMS transacional e consentimento",
      body: [
        "O SMS da Magic Leads é transacional. Ele só é enviado depois que o destinatário pressiona 1 durante uma ligação ativa e solicita o link.",
        "Cada tecla 1 gera, no máximo, uma mensagem SMS com o link solicitado. Não há campanhas recorrentes de marketing por SMS.",
        "O consentimento é registrado com data e hora, número de telefone, identificação da chamada e versão do script.",
        "Podem aplicar-se tarifas de mensagem e dados. A frequência é de uma mensagem por solicitação.",
        "Responda STOP para cancelar o SMS. Responda HELP para obter ajuda ou envie um e-mail para contato@magicleads.app.",
        "Você também pode pressionar 2 durante uma ligação para ser removido da nossa lista de chamadas.",
        "O consentimento para SMS não é condição para compra.",
        "Não compartilhamos números de celular com terceiros ou afiliados para fins de marketing ou promoção.",
      ],
    },
    {
      title: "Compartilhamento",
      body: [
        "Compartilhamos dados com provedores de hospedagem, pagamento, comunicações, analytics e suporte, sempre sob contrato e apenas para operar o serviço.",
        "Podemos divulgar dados quando exigido por lei, ordem judicial ou para proteger direitos e segurança.",
        "Não vendemos dados pessoais.",
      ],
    },
    {
      title: "Cookies e analytics",
      body: [
        "Usamos cookies essenciais e, quando permitido, cookies de analytics para entender o uso do site.",
        "Você pode controlar cookies nas configurações do navegador.",
      ],
    },
    {
      title: "Retenção e segurança",
      body: [
        "Mantemos os dados pelo tempo necessário para operar o serviço, cumprir obrigações legais e resolver disputas.",
        "Aplicamos controles de acesso, criptografia em trânsito e outras medidas razoáveis. Nenhum sistema é totalmente seguro.",
      ],
    },
    {
      title: "Seus direitos",
      body: [
        "Você pode solicitar acesso, correção, exclusão ou portabilidade dos seus dados, além de cancelar comunicações.",
        "Para exercer esses direitos, envie um e-mail para contato@magicleads.app com o assunto Privacidade.",
        "Moradores da Califórnia e de outros estados podem ter direitos adicionais previstos na lei aplicável.",
      ],
    },
    {
      title: "Crianças",
      body: [
        "O serviço é destinado a maiores de 18 anos. Não coletamos intencionalmente dados de crianças.",
      ],
    },
    {
      title: "Alterações e contato",
      body: [
        "Podemos atualizar esta política. A data no topo indica a versão vigente.",
        "Dúvidas: contato@magicleads.app.",
      ],
    },
  ],
};

const PT_TERMS: LegalDoc = {
  label: "Legal",
  title: "Termos de Serviço",
  updated: "Última atualização: 12 de novembro de 2026",
  intro:
    "Estes termos regem o uso do site magicleads.app e dos serviços da Magic Leads. Ao usar o serviço, você concorda com estes termos.",
  back: "Voltar ao site",
  contactTitle: "Fale com a gente",
  contactBody: "Dúvidas sobre estes termos: contato@magicleads.app.",
  sections: [
    {
      title: "Quem somos",
      body: [
        "A Magic Leads é operada por uma atividade empresarial individual registrada em New Jersey, EUA. Magic Leads e Magic Leads Technologies são nomes comerciais utilizados nesta plataforma. A identificação legal completa é fornecida às operadoras, processadores de pagamento e autoridades quando necessário.",
      ],
    },
    {
      title: "O serviço",
      body: [
        "A Magic Leads oferece uma plataforma de inteligência de oportunidades para empreiteiros, com obras, informações de proprietário e canais de contato.",
        "A disponibilidade, quantidade e qualidade das oportunidades variam por cidade, especialidade e período.",
        "Não garantimos fechamento de contrato, faturamento ou volume específico.",
      ],
    },
    {
      title: "Conta e elegibilidade",
      body: [
        "Você deve ter 18 anos ou mais e fornecer informações verdadeiras.",
        "Você é responsável por manter a confidencialidade das suas credenciais e por todas as atividades na sua conta.",
      ],
    },
    {
      title: "Planos e pagamentos",
      body: [
        "O plano semanal custa $120 e libera 7 dias de acesso. No oitavo dia, o plano pausa automaticamente se não for renovado.",
        "Não há fidelidade nem comissão sobre suas obras.",
        "Os valores e condições aplicáveis são os exibidos no checkout.",
        "Pagamentos são processados por provedores terceirizados.",
      ],
    },
    {
      title: "Uso aceitável",
      body: [
        "Você concorda em não usar o serviço para fins ilegais, spam, cold SMS, assédio, fraude ou violação de direitos de terceiros.",
        "Não é permitido revender, copiar, raspar ou compartilhar o acesso e os dados com terceiros não autorizados.",
        "Você deve respeitar as leis de telemarketing, DNC e privacidade aplicáveis ao contatar proprietários.",
      ],
    },
    {
      title: "Oportunidades e dados",
      body: [
        "As oportunidades são fornecidas para uso legítimo no seu negócio.",
        "Telefones, nomes e endereços podem estar indisponíveis ou mudar. Não garantimos precisão absoluta.",
        "O uso de informações de proprietários para fins ilícitos é proibido.",
      ],
    },
    {
      id: "sms",
      title: "SMS transacional",
      body: [
        "O SMS é transacional e só é enviado após a tecla 1 em uma ligação ativa.",
        "Uma mensagem por solicitação. Sem marketing recorrente e sem cold SMS.",
        "Podem aplicar-se tarifas de mensagem e dados.",
        "Responda STOP para cancelar. Responda HELP para ajuda ou envie e-mail para contato@magicleads.app.",
        "Você também pode pressionar 2 durante uma ligação para ser removido da nossa lista de chamadas.",
        "O consentimento não é condição para compra.",
        "Não compartilhamos números de celular com terceiros ou afiliados para marketing.",
      ],
    },
    {
      title: "Propriedade intelectual",
      body: [
        "O site, a marca, o software e o conteúdo são de nossa propriedade ou de licenciantes. Você recebe uma licença limitada, não exclusiva e revogável para usar o serviço.",
      ],
    },
    {
      title: "Isenções",
      body: [
        "O serviço é fornecido no estado em que se encontra e conforme disponível.",
        "Não garantimos operação ininterrupta, ausência de erros ou resultados específicos.",
        "As informações não constituem aconselhamento jurídico, fiscal ou financeiro.",
      ],
    },
    {
      title: "Limitação de responsabilidade",
      body: [
        "Na máxima extensão permitida por lei, não somos responsáveis por danos indiretos, incidentais, especiais ou consequenciais.",
        "Nossa responsabilidade total fica limitada ao valor pago por você nos 3 meses anteriores ao evento.",
      ],
    },
    {
      title: "Indenização",
      body: [
        "Você concorda em indenizar a Magic Leads por reivindicações decorrentes do uso indevido do serviço ou violação destes termos.",
      ],
    },
    {
      title: "Lei aplicável e foro",
      body: [
        "Estes termos são regidos pelas leis do Estado de New Jersey, EUA.",
        "Disputas serão submetidas aos tribunais localizados no Condado de Hudson, New Jersey, salvo disposição legal em contrário.",
      ],
    },
    {
      title: "Alterações e contato",
      body: [
        "Podemos atualizar estes termos. A data no topo indica a versão vigente.",
        "Contato: contato@magicleads.app.",
      ],
    },
  ],
};

const EN_PRIVACY: LegalDoc = {
  label: "Legal",
  title: "Privacy Policy",
  updated: "Last updated: November 12, 2026",
  intro:
    "This policy explains how Magic Leads collects, uses and protects personal data on magicleads.app and related services.",
  back: "Back to site",
  contactTitle: "Contact us",
  contactBody:
    "Privacy questions or data requests: contato@magicleads.app. Subject: Privacy.",
  sections: [
    {
      title: "Who we are",
      body: [
        "Magic Leads is operated by a sole proprietorship registered in New Jersey, USA. Magic Leads and Magic Leads Technologies are trade names used on this platform. Full legal identification is provided to carriers, payment processors and authorities when required.",
        "For purposes of this policy, Magic Leads, we and us refer to that holder.",
      ],
    },
    {
      title: "Information we collect",
      body: [
        "Account data: name, email, phone, company, trade, city and ZIP, login credentials and preferences.",
        "Usage data: pages visited, IP address, browser, device, date and time, and interactions with the dashboard.",
        "Opportunity data: property and owner information used to deliver the opportunities in the service.",
        "Communication and consent data: support messages, call records and SMS opt-in and opt-out records.",
        "Payments: processed by a payment provider. We do not store the full card number.",
      ],
    },
    {
      title: "How we use information",
      body: [
        "To provide, operate and improve the service, including reservations, reveals, alerts and support.",
        "To process payments, prevent fraud, comply with legal obligations and enforce our terms.",
        "To send transactional communications requested by you.",
        "We do not use the data to send marketing SMS or cold SMS.",
      ],
    },
    {
      id: "sms",
      title: "Transactional SMS and consent",
      body: [
        "Magic Leads SMS is transactional. It is sent only after the recipient presses 1 during an active call and requests the link.",
        "Each keypress 1 generates at most one SMS with the requested link. There are no recurring SMS marketing campaigns.",
        "Consent is recorded with a timestamp, phone number, call identifier and script version.",
        "Message and data rates may apply. Frequency is one message per request.",
        "Reply STOP to cancel SMS. Reply HELP for help or email contato@magicleads.app.",
        "You can also press 2 during a call to be removed from our call list.",
        "SMS consent is not a condition of purchase.",
        "No mobile information will be shared with third parties or affiliates for marketing or promotional purposes.",
      ],
    },
    {
      title: "Sharing",
      body: [
        "We share data with hosting, payment, communications, analytics and support providers, under contract and only to operate the service.",
        "We may disclose data when required by law, court order or to protect rights and security.",
        "We do not sell personal information.",
      ],
    },
    {
      title: "Cookies and analytics",
      body: [
        "We use essential cookies and, where permitted, analytics cookies to understand site usage.",
        "You can control cookies in your browser settings.",
      ],
    },
    {
      title: "Retention and security",
      body: [
        "We retain data for as long as needed to operate the service, comply with legal obligations and resolve disputes.",
        "We use access controls, encryption in transit and other reasonable measures. No system is completely secure.",
      ],
    },
    {
      title: "Your rights",
      body: [
        "You may request access, correction, deletion or portability of your data, and opt out of communications.",
        "To exercise these rights, email contato@magicleads.app with the subject Privacy.",
        "California residents and residents of other states may have additional rights under applicable law.",
      ],
    },
    {
      title: "Children",
      body: [
        "The service is intended for people 18 and older. We do not knowingly collect data from children.",
      ],
    },
    {
      title: "Changes and contact",
      body: [
        "We may update this policy. The date at the top indicates the current version.",
        "Questions: contato@magicleads.app.",
      ],
    },
  ],
};

const EN_TERMS: LegalDoc = {
  label: "Legal",
  title: "Terms of Service",
  updated: "Last updated: November 12, 2026",
  intro:
    "These terms govern the use of magicleads.app and the Magic Leads services. By using the service, you agree to these terms.",
  back: "Back to site",
  contactTitle: "Contact us",
  contactBody: "Questions about these terms: contato@magicleads.app.",
  sections: [
    {
      title: "Who we are",
      body: [
        "Magic Leads is operated by a sole proprietorship registered in New Jersey, USA. Magic Leads and Magic Leads Technologies are trade names used on this platform. Full legal identification is provided to carriers, payment processors and authorities when required.",
      ],
    },
    {
      title: "The service",
      body: [
        "Magic Leads provides an opportunity intelligence platform for contractors, with jobs, owner information and contact channels.",
        "Availability, quantity and quality of opportunities vary by city, trade and period.",
        "We do not guarantee a closed contract, revenue or a specific volume.",
      ],
    },
    {
      title: "Account and eligibility",
      body: [
        "You must be 18 or older and provide accurate information.",
        "You are responsible for keeping your credentials confidential and for all activity on your account.",
      ],
    },
    {
      title: "Plans and payments",
      body: [
        "The weekly plan costs $120 and unlocks 7 days of access. On day 8, the plan pauses automatically if it is not renewed.",
        "There is no lock-in and no commission on your jobs.",
        "The applicable prices and conditions are shown at checkout.",
        "Payments are processed by third-party providers.",
      ],
    },
    {
      title: "Acceptable use",
      body: [
        "You agree not to use the service for illegal purposes, spam, cold SMS, harassment, fraud or violation of third-party rights.",
        "You may not resell, copy, scrape or share access and data with unauthorized third parties.",
        "You must comply with applicable telemarketing, DNC and privacy laws when contacting owners.",
      ],
    },
    {
      title: "Opportunities and data",
      body: [
        "Opportunities are provided for legitimate use in your business.",
        "Phones, names and addresses may be unavailable or change. We do not guarantee absolute accuracy.",
        "Using owner information for unlawful purposes is prohibited.",
      ],
    },
    {
      id: "sms",
      title: "Transactional SMS",
      body: [
        "SMS is transactional and is sent only after keypress 1 during an active call.",
        "One message per request. No recurring marketing and no cold SMS.",
        "Message and data rates may apply.",
        "Reply STOP to cancel. Reply HELP for help or email contato@magicleads.app.",
        "You can also press 2 during a call to be removed from our call list.",
        "Consent is not a condition of purchase.",
        "No mobile information will be shared with third parties or affiliates for marketing purposes.",
      ],
    },
    {
      title: "Intellectual property",
      body: [
        "The site, brand, software and content are owned by us or our licensors. You receive a limited, non-exclusive, revocable license to use the service.",
      ],
    },
    {
      title: "Disclaimers",
      body: [
        "The service is provided as is and as available.",
        "We do not guarantee uninterrupted operation, freedom from errors or specific results.",
        "The information is not legal, tax or financial advice.",
      ],
    },
    {
      title: "Limitation of liability",
      body: [
        "To the maximum extent permitted by law, we are not liable for indirect, incidental, special or consequential damages.",
        "Our total liability is limited to the amount you paid in the 3 months before the event.",
      ],
    },
    {
      title: "Indemnity",
      body: [
        "You agree to indemnify Magic Leads against claims arising from misuse of the service or violation of these terms.",
      ],
    },
    {
      title: "Governing law and venue",
      body: [
        "These terms are governed by the laws of the State of New Jersey, USA.",
        "Disputes will be submitted to courts located in Hudson County, New Jersey, unless applicable law requires otherwise.",
      ],
    },
    {
      title: "Changes and contact",
      body: [
        "We may update these terms. The date at the top indicates the current version.",
        "Contact: contato@magicleads.app.",
      ],
    },
  ],
};

const ES_PRIVACY: LegalDoc = {
  label: "Legal",
  title: "Política de Privacidad",
  updated: "Última actualización: 12 de noviembre de 2026",
  intro:
    "Esta política explica cómo Magic Leads recopila, usa y protege datos personales en magicleads.app y en los servicios relacionados.",
  back: "Volver al sitio",
  contactTitle: "Contáctanos",
  contactBody:
    "Preguntas sobre privacidad o solicitudes de datos: contato@magicleads.app. Asunto: Privacidad.",
  sections: [
    {
      title: "Quiénes somos",
      body: [
        "Magic Leads es operada por una actividad empresarial individual registrada en New Jersey, EE. UU. Magic Leads y Magic Leads Technologies son nombres comerciales utilizados en esta plataforma. La identificación legal completa se proporciona a operadoras, procesadores de pago y autoridades cuando sea necesario.",
        "A los fines de esta política, Magic Leads, nosotros y nos referimos a ese titular.",
      ],
    },
    {
      title: "Datos que recopilamos",
      body: [
        "Datos de cuenta: nombre, correo, teléfono, empresa, especialidad, ciudad y ZIP, credenciales de acceso y preferencias.",
        "Datos de uso: páginas visitadas, dirección IP, navegador, dispositivo, fecha y hora, e interacciones con el panel.",
        "Datos de oportunidades: información sobre inmuebles y propietarios usada para entregar las oportunidades del servicio.",
        "Datos de comunicación y consentimiento: mensajes de soporte, registros de llamadas y registros de opt-in y opt-out de SMS.",
        "Pagos: procesados por un proveedor de pago. No almacenamos el número completo de la tarjeta.",
      ],
    },
    {
      title: "Cómo usamos los datos",
      body: [
        "Para prestar, operar y mejorar el servicio, incluyendo reservas, revelaciones, alertas y soporte.",
        "Para procesar pagos, prevenir fraudes, cumplir obligaciones legales y aplicar nuestros términos.",
        "Para enviar comunicaciones transaccionales solicitadas por ti.",
        "No usamos los datos para enviar SMS de marketing ni cold SMS.",
      ],
    },
    {
      id: "sms",
      title: "SMS transaccional y consentimiento",
      body: [
        "El SMS de Magic Leads es transaccional. Solo se envía después de que el destinatario presiona 1 durante una llamada activa y solicita el enlace.",
        "Cada tecla 1 genera como máximo un SMS con el enlace solicitado. No hay campañas recurrentes de marketing por SMS.",
        "El consentimiento se registra con fecha y hora, número de teléfono, identificador de la llamada y versión del script.",
        "Pueden aplicarse tarifas de mensajes y datos. La frecuencia es de un mensaje por solicitud.",
        "Responde STOP para cancelar el SMS. Responde HELP para obtener ayuda o envía un correo a contato@magicleads.app.",
        "También puedes presionar 2 durante una llamada para que te quitemos de nuestra lista de llamadas.",
        "El consentimiento para SMS no es condición de compra.",
        "No compartimos números de celular con terceros o afiliados para fines de marketing o promoción.",
      ],
    },
    {
      title: "Compartir datos",
      body: [
        "Compartimos datos con proveedores de alojamiento, pago, comunicaciones, analytics y soporte, bajo contrato y solo para operar el servicio.",
        "Podemos divulgar datos cuando lo exija la ley, una orden judicial o para proteger derechos y seguridad.",
        "No vendemos datos personales.",
      ],
    },
    {
      title: "Cookies y analytics",
      body: [
        "Usamos cookies esenciales y, cuando está permitido, cookies de analytics para entender el uso del sitio.",
        "Puedes controlar las cookies en la configuración de tu navegador.",
      ],
    },
    {
      title: "Retención y seguridad",
      body: [
        "Conservamos los datos durante el tiempo necesario para operar el servicio, cumplir obligaciones legales y resolver disputas.",
        "Aplicamos controles de acceso, cifrado en tránsito y otras medidas razonables. Ningún sistema es completamente seguro.",
      ],
    },
    {
      title: "Tus derechos",
      body: [
        "Puedes solicitar acceso, corrección, eliminación o portabilidad de tus datos, además de cancelar comunicaciones.",
        "Para ejercer estos derechos, envía un correo a contato@magicleads.app con el asunto Privacidad.",
        "Los residentes de California y de otros estados pueden tener derechos adicionales según la ley aplicable.",
      ],
    },
    {
      title: "Menores",
      body: [
        "El servicio está destinado a mayores de 18 años. No recopilamos datos de menores de forma intencional.",
      ],
    },
    {
      title: "Cambios y contacto",
      body: [
        "Podemos actualizar esta política. La fecha en la parte superior indica la versión vigente.",
        "Preguntas: contato@magicleads.app.",
      ],
    },
  ],
};

const ES_TERMS: LegalDoc = {
  label: "Legal",
  title: "Términos del Servicio",
  updated: "Última actualización: 12 de noviembre de 2026",
  intro:
    "Estos términos rigen el uso de magicleads.app y de los servicios de Magic Leads. Al usar el servicio, aceptas estos términos.",
  back: "Volver al sitio",
  contactTitle: "Contáctanos",
  contactBody: "Preguntas sobre estos términos: contato@magicleads.app.",
  sections: [
    {
      title: "Quiénes somos",
      body: [
        "Magic Leads es operada por una actividad empresarial individual registrada en New Jersey, EE. UU. Magic Leads y Magic Leads Technologies son nombres comerciales utilizados en esta plataforma. La identificación legal completa se proporciona a operadoras, procesadores de pago y autoridades cuando sea necesario.",
      ],
    },
    {
      title: "El servicio",
      body: [
        "Magic Leads ofrece una plataforma de inteligencia de oportunidades para contratistas, con obras, información de propietarios y canales de contacto.",
        "La disponibilidad, cantidad y calidad de las oportunidades varían por ciudad, especialidad y período.",
        "No garantizamos la firma de un contrato, ingresos ni un volumen específico.",
      ],
    },
    {
      title: "Cuenta y elegibilidad",
      body: [
        "Debes tener 18 años o más y proporcionar información veraz.",
        "Eres responsable de mantener la confidencialidad de tus credenciales y de toda actividad en tu cuenta.",
      ],
    },
    {
      title: "Planes y pagos",
      body: [
        "El plan semanal cuesta $120 y libera 7 días de acceso. El día 8, el plan se pausa automáticamente si no se renueva.",
        "No hay permanencia ni comisión sobre tus obras.",
        "Los precios y condiciones aplicables se muestran en el checkout.",
        "Los pagos son procesados por proveedores externos.",
      ],
    },
    {
      title: "Uso aceptable",
      body: [
        "Aceptas no usar el servicio para fines ilegales, spam, cold SMS, acoso, fraude o violación de derechos de terceros.",
        "No está permitido revender, copiar, raspar o compartir el acceso y los datos con terceros no autorizados.",
        "Debes cumplir las leyes de telemarketing, DNC y privacidad aplicables al contactar propietarios.",
      ],
    },
    {
      title: "Oportunidades y datos",
      body: [
        "Las oportunidades se proporcionan para uso legítimo en tu negocio.",
        "Los teléfonos, nombres y direcciones pueden no estar disponibles o cambiar. No garantizamos precisión absoluta.",
        "El uso de información de propietarios para fines ilícitos está prohibido.",
      ],
    },
    {
      id: "sms",
      title: "SMS transaccional",
      body: [
        "El SMS es transaccional y solo se envía después de la tecla 1 durante una llamada activa.",
        "Un mensaje por solicitud. Sin marketing recurrente y sin cold SMS.",
        "Pueden aplicarse tarifas de mensajes y datos.",
        "Responde STOP para cancelar. Responde HELP para ayuda o envía un correo a contato@magicleads.app.",
        "También puedes presionar 2 durante una llamada para que te quitemos de nuestra lista de llamadas.",
        "El consentimiento no es condición de compra.",
        "No compartimos números de celular con terceros o afiliados para marketing.",
      ],
    },
    {
      title: "Propiedad intelectual",
      body: [
        "El sitio, la marca, el software y el contenido son de nuestra propiedad o de licenciantes. Recibes una licencia limitada, no exclusiva y revocable para usar el servicio.",
      ],
    },
    {
      title: "Exenciones",
      body: [
        "El servicio se proporciona tal como está y según disponibilidad.",
        "No garantizamos operación ininterrumpida, ausencia de errores ni resultados específicos.",
        "La información no constituye asesoramiento legal, fiscal o financiero.",
      ],
    },
    {
      title: "Limitación de responsabilidad",
      body: [
        "En la máxima medida permitida por la ley, no somos responsables de daños indirectos, incidentales, especiales o consecuentes.",
        "Nuestra responsabilidad total se limita al importe pagado por ti en los 3 meses anteriores al evento.",
      ],
    },
    {
      title: "Indemnización",
      body: [
        "Aceptas indemnizar a Magic Leads por reclamaciones derivadas del uso indebido del servicio o de la violación de estos términos.",
      ],
    },
    {
      title: "Ley aplicable y jurisdicción",
      body: [
        "Estos términos se rigen por las leyes del Estado de New Jersey, EE. UU.",
        "Las disputas se someterán a los tribunales ubicados en el Condado de Hudson, New Jersey, salvo que la ley aplicable disponga otra cosa.",
      ],
    },
    {
      title: "Cambios y contacto",
      body: [
        "Podemos actualizar estos términos. La fecha en la parte superior indica la versión vigente.",
        "Contacto: contato@magicleads.app.",
      ],
    },
  ],
};

export const LEGAL_CONTENT: Record<LegalLang, Record<LegalKind, LegalDoc>> = {
  pt: { privacy: PT_PRIVACY, terms: PT_TERMS },
  en: { privacy: EN_PRIVACY, terms: EN_TERMS },
  es: { privacy: ES_PRIVACY, terms: ES_TERMS },
};
