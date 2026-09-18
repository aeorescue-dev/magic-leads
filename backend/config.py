import json
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Core
    DEBUG: bool = False
    PROJECT_NAME: str = "Garimpador Leads API"
    VERSION: str = "0.1.0"

    # Supabase (não é mais obrigatório — MVP usa SQLite local).
    # Mantido para futura migração multi-tenant.
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Stripe (obrigatório apenas quando ativar cobrança)
    STRIPE_API_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID_PRO: str = "price_..."  # Configurar após criar produto no Stripe

    # Plano semanal (fonte da verdade do checkout)
    PLAN_NAME: str = "Pro"
    PLAN_INTERVAL: str = "week"
    PLAN_AMOUNT_CENTS: int = 7900      # $79.00 em centavos (Stripe)
    PLAN_AMOUNT_USD: float = 79.0
    PLAN_ANNUAL_USD: float = 4108.0    # 79 x 52 semanas
    TRIAL_DAYS: int = 7
    RESERVATION_MINUTES: int = 15      # Lead reservation hold time

    # APIs
    TRUTHFINDER_API_KEY: str = ""  # Optional, para skip tracing
    GOOGLE_GEOCODER_API_KEY: str = ""  # Optional
    GEMINI_API_KEY: str = ""  # Optional para visão

    # Scraper Config
    SOCRATA_APP_TOKEN: str = ""  # App Token Socrata (pool dedicado, cota maior)
    SOCRATA_DOMAINS: List[str] = [
        "data.cityofnewyork.us",
        "data.cityofchicago.org",
        "data.miamidade.gov"
    ]
    SCRAPER_KEYWORDS: List[str] = [
        "Roof", "Grass", "Overgrown", "Weed", "Vegetation", "Blight",
        "Plumbing", "Paint", "Structure", "Heat", "Hot Water", "Unsanitary",
        "Leak", "Door", "Window", "Electric", "Elevator", "Gas", "Rodent",
        "Pest", "Garbage", "Debris", "Mold", "Lead",
        "Code", "Permit", "Animal", "Graffiti"
    ]

    # Enriquecimento
    ENRICHMENT_DAILY_BUDGET: int = 300  # Máximo de lookups de owner por dia

    # Scheduler interno (independente do GH Actions — redundância no Railway)
    SCRAPER_SELF_SCHEDULED: bool = True   # True = scheduler interno roda a cada N horas
    SCRAPER_INTERVAL_HOURS: int = 6       # Intervalo em horas entre varreduras agendadas

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3005,https://magicleads-oficial.vercel.app,https://magic-leads-frontend-final.vercel.app"

    # E-mail de recuperação de senha — Gmail SMTP (100% gratuito).
    # Defaults prontos para Gmail. Para ATIVAR o envio real basta definir no Railway:
    #   SMTP_USER=helpmagicleads@gmail.com e SMTP_PASS=<App Password do Gmail>
    # (Gerar: Conta Google -> Segurança -> Senhas de app).
    # Sem SMTP_USER/SMTP_PASS a rota imprime o link nos logs (modo dev, zero custo).
    #
    # IMPORTANTE: o Railway BLOQUEIA egresso nas portas SMTP (465/587).
    # Por isso o envio via API HTTP (Resend, porta 443 liberada) tem PRIORIDADE:
    #   EMAIL_API_KEY=<Resend API Key> e EMAIL_FROM="Magic Leads <noreply@seudominio.com>"
    # (Resend: resend.com, plano grátis 3.000 e-mails/mês; exige domínio verificado).
    # O SMTP continua como fallback caso a API não esteja configurada.
    EMAIL_API_KEY: str = ""       # Resend API Key (HTTPS :443 — liberado no Railway)
    EMAIL_FROM: str = ""          # "Nome <email@dominio-verificado.com>"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 465          # 465 = SSL direto (SMTP_SSL) — Railway bloqueia egresso na 587
    SMTP_USER: str = ""           # helpmagicleads@gmail.com (Railway env)
    SMTP_PASS: str = ""           # App Password do Gmail (Railway env)
    SMTP_FROM: str = "helpmagicleads@gmail.com"

    @field_validator(
        "STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_ID_PRO",
        mode="before",
    )
    @classmethod
    def _strip_stripe_values(cls, v: object) -> object:
        # Railway max às vezes injeta \n ou espaços no fim — evita "No such price".
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator(
        "SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_FROM",
        "EMAIL_API_KEY",
        mode="before",
    )
    @classmethod
    def _strip_smtp_values(cls, v: object) -> object:
        # App Password do Gmail fica inválida se o Railway injetar \n/espaço no
        # fim (causa comum de 535 "Username and Password not accepted"). O mesmo
        # vale para API Keys (Resend rejeita chave com caracteres extras).
        if isinstance(v, str):
            return v.strip()
        return v

    @property
    def allowed_origins_list(self) -> List[str]:
        v = self.ALLOWED_ORIGINS
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(o).strip() for o in parsed if str(o).strip()]
            except Exception:
                pass
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # Web Push (VAPID)
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_CLAIMS_SUB: str = "mailto:admin@magicleads.com"

    # Cron (GitHub Actions chama com este header)
    CRON_SECRET: str = ""

    # Admin (rotas administrativas: requalify, enrich em lote, push de teste).
    # Se vazio, TODAS as rotas admin ficam bloqueadas (fail-closed).
    ADMIN_SECRET: str = ""

    # Webhook para alertas do scraper (Telegram/Slack/Email via n8n/Resend/etc)
    SCRAPER_WEBHOOK_URL: str = ""

    model_config = SettingsConfigDict(
        env_file = ".env",
        case_sensitive = True,
        extra = "ignore"
    )


settings = Settings()
