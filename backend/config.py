import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


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
        "Pest", "Garbage", "Debris", "Mold", "Lead"
    ]

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:3005"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v):
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

    model_config = SettingsConfigDict(
        env_file = ".env",
        case_sensitive = True,
        extra = "ignore"
    )


settings = Settings()
