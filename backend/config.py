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
    PLAN_AMOUNT_CENTS: int = 12000      # $120.00 em centavos (Stripe)
    PLAN_AMOUNT_USD: float = 120.0
    PLAN_ANNUAL_USD: float = 6240.0    # 120 x 52 semanas
    TRIAL_DAYS: int = 7
    RESERVATION_MINUTES: int = 15      # Lead reservation hold time

    # Recuperacao de checkout abandonado (Prioridade A). So' acts sobre
    # utilizadores que JA' cliquem em pagar — e' transacional (Resend), nunca
    # prospeccao a frio (essa usa as caixas Gmail do outbound).
    CHECKOUT_RECOVERY_ENABLED: bool = True
    CHECKOUT_RECOVERY_INTERVAL_SECONDS: int = 900   # 15 min
    CHECKOUT_RECOVERY_AFTER_MINUTES: int = 90       # espera antes de lembrar
    CHECKOUT_RECOVERY_MAX_REMINDERS: int = 2

    # APIs
    TRUTHFINDER_API_KEY: str = ""  # Optional, para skip tracing
    GOOGLE_GEOCODER_API_KEY: str = ""  # Optional
    GEMINI_API_KEY: str = ""  # Optional para visão
    SEARCHBUG_API_KEY: str = ""  # Optional, API Key / Password para Searchbug
    SEARCHBUG_ACCOUNT_CODE: str = ""  # Optional, CO_CODE (Account Number) para Searchbug Contact Info API
    SEARCHBUG_BASE_URL: str = "https://data.searchbug.com"  # Base URL da API Contact Info
    # Timeout por tentativa ao Searchbug. 10s cobre o p95 observado (~3.1s) com
    # margem ampla. NAO aumentar sem medir: o Searchbug e a etapa PAGA e um
    # timeout curto demais pode abortar requests que a API ja contabilizou.
    SEARCHBUG_TIMEOUT_SECONDS: float = 10.0
    # Timeout de ligacao (TCP+TLS). Fixo e baixo porque o host e sempre o mesmo.
    SEARCHBUG_CONNECT_TIMEOUT_SECONDS: float = 5.0

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
    # 0 = ILIMITADO (Lookups de owner sem teto diário).
    # Para reativar um limite, define ENRICHMENT_DAILY_BUDGET=<n> na env var.
    ENRICHMENT_DAILY_BUDGET: int = 0  # Máximo de lookups de owner por dia

    # Scheduler interno (independente do GH Actions — redundância no Railway)
    SCRAPER_SELF_SCHEDULED: bool = True   # True = scheduler interno roda a cada N horas
    SCRAPER_INTERVAL_HOURS: int = 6       # Intervalo em horas entre varreduras agendadas
    # Sweep de holds/reveals dentro do processo. Independe do GitHub Actions, que
    # falhou 6 execucoes seguidas (canceladas na fila, 0 passos).
    HOLD_WATCHDOG_INTERVAL_MIN: int = 15

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3005,https://magicleads.app,https://www.magicleads.app,https://magicleads-oficial.vercel.app,https://magic-leads-frontend-final.vercel.app"
    # Vercel preview deployment patterns (git branch preview URLs)
    # Format: comma-separated base domains (without git branch suffix)
    # e.g., "magicleads-oficial.vercel.app,magic-leads-frontend-final.vercel.app"
    VERCEL_PREVIEW_BASE_DOMAINS: str = "magicleads-oficial.vercel.app,magic-leads-frontend-final.vercel.app"

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
        "SEARCHBUG_API_KEY", "SEARCHBUG_BASE_URL",
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
        "SNOV_CLIENT_ID", "SNOV_CLIENT_SECRET",
        "EMAILLISTVERIFY_API_KEY",
        "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
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

    @property
    def vercel_preview_base_domains_list(self) -> List[str]:
        v = self.VERCEL_PREVIEW_BASE_DOMAINS
        if isinstance(v, str):
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

    # ---------------------------------------------------------------- Outbound
    # Fase 2: enriquecimento de e-mail (Snov.io) e envio (Gmail API).
    # Sem SNOV_CLIENT_ID/SNOV_CLIENT_SECRET o enriquecimento fica fail-soft
    # (outcome=not_configured) e nada e' enfileirado. O envio continua
    # fail-closed por `send_enabled=0` na base de dados.
    SNOV_BASE_URL: str = "https://api.snov.io"
    SNOV_CLIENT_ID: str = ""
    SNOV_CLIENT_SECRET: str = ""
    SNOV_TIMEOUT_SECONDS: float = 20.0
    # Custo unitario usado na telemetria/orcamento do lote (o painel ja' usa 0.015).
    SNOV_PER_EMAIL_USD: float = 0.015
    # Maximo de verificacoes pagas por lead numa unica busca (anti-spam de custo).
    SNOV_MAX_VERIFICATIONS: int = 5

    # ---------------------------------------------------------------- Outbound (enriquecimento)
    # Fase 2: o enriquecimento de e-mail usa EmailListVerify (Pay-As-You-Go,
    # $6.99/1.000 creditos, sem mensalidade). Sem EMAILLISTVERIFY_API_KEY o
    # enriquecimento fica fail-soft (outcome=not_configured) e nada e'
    # enfileirado. O envio continua fail-closed por `send_enabled=0` na base.
    EMAILLISTVERIFY_BASE_URL: str = "https://api.emaillistverify.com"
    EMAILLISTVERIFY_VERIFY_URL: str = "https://apps.emaillistverify.com/api/verifyEmail"
    EMAILLISTVERIFY_API_KEY: str = ""
    EMAILLISTVERIFY_TIMEOUT_SECONDS: float = 20.0
    # Custo unitario por credito (usado na telemetria/orcamento do lote).
    EMAILLISTVERIFY_PER_CREDIT_USD: float = 0.00699
    # Creditos por operacao: verifyEmail=1, findContact (nome)=5, (dominio)=10.
    EMAILLISTVERIFY_VERIFY_CREDITS: int = 1
    EMAILLISTVERIFY_FIND_CREDITS_NAMED: int = 5
    EMAILLISTVERIFY_FIND_CREDITS_DOMAIN: int = 10

    # Gmail API (Google Workspace OAuth2). Cada caixa pode guardar as suas
    # credenciais em `sending_mailboxes.auth_ref` (JSON); estas env vars sao o
    # fallback global quando a caixa nao tem auth_ref proprio.
    GMAIL_CLIENT_ID: str = ""
    GMAIL_CLIENT_SECRET: str = ""
    GMAIL_REFRESH_TOKEN: str = ""
    GMAIL_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
    GMAIL_API_URL: str = "https://gmail.googleapis.com/gmail/v1"
    GMAIL_TIMEOUT_SECONDS: float = 20.0

    # Worker interno de outbound (esteira). O primeiro tick so' acontece depois
    # do intervalo; `send_enabled=0` mantem o envio bloqueado mesmo com o loop on.
    OUTBOUND_WORKER_ENABLED: bool = True
    OUTBOUND_WORKER_INTERVAL_SECONDS: int = 60
    OUTBOUND_WORKER_CHUNK: int = 10

    # Sequencia de e-mails (Prioridade D). Passo 1 = amostra (sem preco),
    # passo 2 = oferta ($120/semana). O passo 2 so' e' agendado para quem
    # recebeu o passo 1 e nao respondeu, se nao se desinscreveu e nao foi
    # suprimido.
    OUTBOUND_SEQUENCE_ENABLED: bool = True
    OUTBOUND_SEQUENCE_STEP2_DELAY_DAYS: int = 3
    OUTBOUND_SEQUENCE_MAX_STEP: int = 2

    # DLQ de notificações in-app. Ring buffer: impede acúmulo infinito em
    # disco quando o INSERT falha repetidamente. Os ficheiros mais antigos
    # (além do teto de ficheiros ou da idade máxima) são descartados e
    # contabilizados para o painel admin.
    NOTIF_DLQ_MAX_FILES: int = 500
    NOTIF_DLQ_TTL_DAYS: int = 7

    # Alert Planner: teto diário de alertas por utilizador. O orçamento é
    # COMBINADO (in-app + push): 1 alerta = 1 unidade. Faixa restrita 5-8.
    PUSH_DAILY_LIMIT: int = 6
    # O digest diário do excedente é extra e NÃO conta para o teto.
    ALERT_DIGEST_COUNTS_TOWARD_LIMIT: bool = False

    @field_validator("PUSH_DAILY_LIMIT")
    @classmethod
    def _clamp_push_daily_limit(cls, v: int) -> int:
        """Fail-safe: restringe o teto diário à faixa 5-8 (default 6)."""
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 6
        return max(5, min(8, v))

    model_config = SettingsConfigDict(
        env_file = ".env",
        case_sensitive = True,
        extra = "ignore"
    )


settings = Settings()
