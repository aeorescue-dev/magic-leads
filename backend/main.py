import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone

import anyio
import httpx
import stripe
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from .config import settings
from .models.schemas import (
    ALLOWED_ACCESS_GRANT_REASONS,
    AccessGrantRequest,
    AccessRevokeRequest,
    AuthResponse,
    BaseLocationUpdate,
    ContactLeadRequest,
    EnrichedLead,
    HistoryEvent,
    InterestPushUpdate,
    InterestsUpdate,
    IssueCategory,
    LeadHoldResponse,
    LeadResponse,
    LeadsListResponse,
    LeadStatsResponse,
    LeadStatusResponse,
    LeadUpdate,
    NoteCreate,
    NoteResponse,
    NotificationResponse,
    OnboardingUpdate,
    PushEnabledUpdate,
    PushPreferencesUpdate,
    PushSubscribeRequest,
    PushUnsubscribeRequest,
    RejectLeadRequest,
    ReleaseLeadRequest,
    ReserverLeadRequest,
    SendTestPushRequest,
    SourceType,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from .scrapers.socrata_311 import socrata_scraper
from .scrapers.socrata_discovery import socrata_discovery
from .services import (
    alert_planner,
    control_tower,
    enrichment_queue,
    freshness,
    geo_lookup,
    inbox_sync,
    lifecycle_push,
    notifier,
    outbound_templates,
    security,
)
from .services.db import (  # noqa: F401  — usados nos filtros de qualificação
    _OPEN_STATUSES,
    _TRADE_CATEGORIES,
    _address_where,
    _category_where,
    _junk_where,
    _not_junk_where,
    _qualified_where,
    _trigger_where,
    db_service,
)
from .services.enrichment import owner_enrichment
from .services.lead_rules import (
    charges_credit,
    classify,
    get_owner_class,
    missing_critical_fields,
    phone_confidence,
    will_call_provider,
    will_charge_if_phone_found,
)
from .services.lead_rules import (
    is_corporate as is_corporate_lead,
)
from .services.metrics import push_metrics, searchbug_metrics
from .services.outbound_engine import outbound_engine
from .services.privacy import sanitize_lead, scrub
from .services.push_click import verify_click
from .services.push_service import push_service
from .services.searchbug import searchbug_service
from .services.translations import render as _render_notification
from .utils.logger import logger
from .utils.time import utcnow


def _map_category(complaint_type: str) -> IssueCategory:
    """Mapeia complaint_type do 311 para IssueCategory do produto."""
    t = (complaint_type or "").lower()
    if "roof" in t:
        return IssueCategory.ROOF
    if "paint" in t or "lead" in t:
        return IssueCategory.PAINT
    if "plumb" in t or "water leak" in t or "sewer" in t:
        return IssueCategory.PLUMBING
    if "structure" in t or "foundation" in t or "collaps" in t or "building" in t:
        return IssueCategory.STRUCTURE
    if "grass" in t or "weed" in t or "overgrown" in t or "vegetation" in t or "blight" in t:
        return IssueCategory.GRASS
    if "permit" in t or "construction" in t or "illegal" in t:
        return IssueCategory.PERMIT_REJECTED
    return IssueCategory.STRUCTURE  # fallback razoável para contractors


def _to_iso_utc(value):
    """Normaliza datetimes guardados como "YYYY-MM-DD HH:MM:SS" (UTC) para ISO UTC.

    O SQLite guarda o prazo das fases sem fuso; emitido tal-qual, o JS do cliente
    faz Date.parse("2026-10-07 13:31:57") como hora LOCAL e o countdown do ciclo
    de vida fica errado por todo o desvio de fuso entre o browser e o servidor.
    """
    if not value:
        return value
    raw = str(value)
    if len(raw) == 19 and raw[10] == " ":
        return f"{raw[0:10]}T{raw[11:19]}Z"
    return raw


PHONE_STATS_MIN_SAMPLES = 30
PHONE_STATS_TTL_S = 600
# Cache por (cidade, classe de proprietario). O feed repete o mesmo segmento em
# dezenas de cartoes: sem isto eram N consultas iguais por pedido.
_phone_stats_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _phone_confidence_stats(city, owner_class) -> dict:
    """Percentagem real de sucesso do telefone, com >=30 amostras (P2).

    Hierarquia: (cidade, classe) -> (classe, todas as cidades). Nunca mistura
    classes diferentes: a taxa de uma pessoa privada nao se aplica a uma
    corporativa. Sem 30 amostras devolve `pct=None` e o numero de amostras
    disponiveis (a UI mostra "sob consulta", sem inventar uma percentagem).
    """
    key = ((city or "").strip().upper(), (owner_class or "unknown"))
    now = time.monotonic()
    cached = _phone_stats_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]

    result = {"pct": None, "samples": 0, "scope": "none"}
    try:
        svc = db_service._service
        for scope_city, scope_name in ((city, "city"), (None, "class")):
            stats = svc.get_phone_success_stats(scope_city, owner_class)
            if result["samples"] == 0:
                result["samples"] = stats["samples"]
            if stats["samples"] >= PHONE_STATS_MIN_SAMPLES:
                result = {
                    "pct": round(stats["successes"] * 100 / stats["samples"]),
                    "samples": stats["samples"],
                    "scope": scope_name,
                }
                break
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PHONE-STATS] falhou: %s", exc)

    _phone_stats_cache[key] = (now + PHONE_STATS_TTL_S, result)
    return result


def _to_lead_response(lead: dict) -> LeadResponse:
    """Converte linha do SQLite (id int) para LeadResponse (id str)."""
    # Build visibility fields
    lead_status = lead.get("lead_status", "available")
    reserved_by = lead.get("reserved_by")
    reserved_until = lead.get("reserved_until")
    reserved_by_name = lead.get("reserved_by_name")
    stage_expires_at = _to_iso_utc(lead.get("stage_expires_at") or reserved_until)
    owns = bool(lead.get("_owns") or lead.get("is_mine"))
    engaged = lead_status in ("reserved", "contacted", "in_negotiation")

    visibility_status = "available"
    reserved_by_me = None
    reserved_by_other = None

    if engaged and reserved_by:
        # Posse (não lead_status=='reserved'): um lead contactado/em negociação
        # do PRÓPRIO utilizador é "reserved_by_me" — nunca "available".
        if owns:
            visibility_status = "reserved_by_me"
            reserved_by_me = {
                "created_at": lead.get("reserved_created_at"),
                "expires_at": stage_expires_at,
                "hours_remaining": lead.get("hours_remaining")
            }
        else:
            visibility_status = "reserved_by_other"
            reserved_by_other = {
                "contractor_id": reserved_by,
                "contractor_name": reserved_by_name,
                "expires_at": stage_expires_at
            }
    elif lead_status == "converted" and owns:
        # Conversão é terminal: o lead sai do feed de descoberta pública e fica
        # guardado nos "Meus Leads" (ainda aparece como "reserved_by_me").
        visibility_status = "reserved_by_me"
        reserved_by_me = {
            "created_at": lead.get("reserved_created_at") or lead.get("converted_at"),
            "expires_at": None,
            "hours_remaining": None
        }

    # Proteção de dados do proprietário: só usuários com reveal ativo
    # (consentimento) veem owner_name/owner_phone/owner_email/mailing_address.
    # Sem reveal, os campos vêm mascarados (None) na response.
    show_owner = bool(lead.get("_revealed", False))

    # Regra A avaliada sobre os dados GUARDADOS, nao sobre os mascarados acima:
    # e o que a reserva vai efetivamente cobrar. Avaliar sobre os mascarados daria
    # corporate=false em todos os leads por revelar, e a UI mostraria "1 credito"
    # (e bloquearia a reserva com a cota diaria esgotada) num lead cuja reserva e
    # gratuita. Nao expoe dados do proprietario, so o veredito.
    rules = classify(lead)
    phone_stats = _phone_confidence_stats(
        lead.get("city"), get_owner_class(lead.get("owner_name"))
    )

    # Regra de ouro de IP: nada da fonte/arquitetura chega ao cliente. Os campos
    # de texto sao limpos e `source`/`department` sao anulados; o admin le os
    # dados crus por endpoints proprios.
    safe = sanitize_lead(lead)

    return LeadResponse(
        id=str(lead["id"]),
        external_id=safe.get("external_id") or lead["external_id"],
        source_type=safe.get("source_type"),
        signal_type=lead.get("signal_type"),
        signal_status=lead.get("signal_status") or "unknown",
        repeat_365=int(lead.get("repeat_365") or 0),
        open_cases=int(lead.get("open_cases") or 0),
        oldest_open_days=lead.get("oldest_open_days"),
        last_case_at=lead.get("last_case_at"),
        address=lead["address"],
        city=lead["city"],
        issue_category=lead["issue_category"],
        issue_description=safe.get("issue_description") or "",
        owner_name=lead.get("owner_name") if show_owner else None,
        owner_phone=lead.get("owner_phone") if show_owner else None,
        phone_verified=bool(lead.get("phone_verified")) if show_owner else False,
        # O selo nunca pode denunciar um telefone que o utilizador ainda nao
        # revelou: sem reveal, avalia-se a resolubilidade (high/medium), nao a
        # existencia do numero em cache.
        phone_confidence=phone_confidence(
            lead if show_owner else {**lead, "owner_phone": None}
        ),
        phone_success_pct=phone_stats["pct"],
        phone_sample_size=phone_stats["samples"],
        owner_email=lead.get("owner_email") if show_owner else None,
        date_reported=lead["date_reported"],
        urgency_level=lead["urgency_level"],
        image_url=lead.get("image_url"),
        status=lead.get("status") or "new",
        favorited=bool(lead.get("favorited")),
        # Address details
        state=lead.get("state"),
        zip_code=lead.get("zip_code"),
        lat=lead.get("lat"),
        lng=lead.get("lng"),
        address_unit=lead.get("address_unit"),
        address_type=lead.get("address_type"),
        address_street=lead.get("address_street"),
        address_city=lead.get("address_city"),
        address_state=lead.get("address_state"),
        address_zip=lead.get("address_zip"),
        # Historical details from 311 systems
        case_title=safe.get("case_title"),
        subject=safe.get("subject"),
        reason=safe.get("reason"),
        type=safe.get("type"),
        queue=safe.get("queue"),
        department=safe.get("department"),
        closure_reason=safe.get("closure_reason"),
        case_status=safe.get("case_status"),
        on_time=lead.get("on_time"),
        sla_target_dt=lead.get("sla_target_dt"),
        closed_dt=lead.get("closed_dt"),
        submitted_photo=lead.get("submitted_photo"),
        closed_photo=lead.get("closed_photo"),
        source=safe.get("source"),
        neighborhood=lead.get("neighborhood"),
        ward=lead.get("ward"),
        precinct=lead.get("precinct"),
        descriptor=safe.get("descriptor"),
        resolution_description=safe.get("resolution_description"),
        resolution_action_updated_date=lead.get("resolution_action_updated_date"),
        # Owner mailing address (protegido até o reveal)
        mailing_address=lead.get("mailing_address") if show_owner else None,
        # Visibility fields
        visibility_status=visibility_status,
        reserved_by_me=reserved_by_me,
        reserved_by_other=reserved_by_other,
        revealed=show_owner,
        my_status=lead.get("_my_status"),
        stage=lead_status if (owns and (engaged or lead_status == "converted")) else None,
        stage_expires_at=stage_expires_at if (owns and engaged) else None,
        server_now=utcnow().isoformat() + "Z",
        corporate=rules["corporate"],
        institutional=rules["institutional"],
        owner_class=rules.get("owner_class", "unknown"),
        owner_kind=rules.get("owner_kind"),
        address_resolvable=rules["address_resolvable"],
        unresolvable=rules["unresolvable"],
        complete_delivery=rules["complete_delivery"],
        incomplete_delivery=rules["incomplete_delivery"],
        charged=rules["charged"],
        # Freshness fields (WS1 dual labels)
        first_seen=lead.get("date_first_seen") or lead.get("created_at"),
        last_synced=lead.get("updated_at") or lead.get("created_at"),
    )


# ------------------------------------------------------------------
# Filtro de QUALIFICAÇÃO (endereço + 16 ofícios + gatilho preditivo + ruído).
# A implementação canónica importa-se de backend/services/db.py (ver import no
# topo deste módulo). Antes existiam DUAS cópias quase iguais aqui e em db.py,
# com duas divergências reais:
#   * o gatilho daqui incluía 'hpd_violation' mas o de db.py não (3858 leads
#     qualificados na aba Oportunidades e descartados do dashboard);
#   * o filtro de ruído daqui varria 5 colunas (case_title, resolution e
#     department incluídas) mas o de db.py só varria 3.
# Unificamos em db.py para o dashboard e as listas contarem o mesmo conjunto.
# ------------------------------------------------------------------

# Datasets que nao sao 311 mas usam o mesmo scraper generico. Sem esta tabela
# o source_type fica "311" e o lead nunca aparece no filtro de obrigacao legal.
_SOURCE_TYPE_BY_ENTRY = {
    "hpd_violations": "hpd_violation",
    "dob_violations": "dob_violation",
    "dob_permits": "permit",
    "chi_permits": "permit",
    "la_permits": "permit",
}


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    debug=settings.DEBUG,
    # Documentacao desativada em producao: /openapi.json listava as 89 rotas
    # por completo (incluindo as 22 de admin/cron/scraper) — um mapa da API
    # publico para concorrentes e atacantes. Em dev (DEBUG=True) mantem-se.
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# CORS
# Allowlist EXPLICITA de origens. Nao reintroduzir allow_origin_regex com
# curingas tipo "https://.*.vercel.app": com allow_credentials=True isso daria
# acesso autenticado a API a qualquer dominio Vercel registavel por terceiros.
# Previews do Vercel só são aceites pelo dominio BASE EXATO (sem wildcard de
# branch/utilizador): qualquer sufixo é registável por terceiros.
_ALLOWED_ORIGINS = settings.allowed_origins_list
_VERCEL_PREVIEW_BASE_DOMAINS = settings.vercel_preview_base_domains_list
if not _ALLOWED_ORIGINS:
    logger.error(
        "ALLOWED_ORIGINS vazio — nenhuma origem sera aceite. "
        "Definir ALLOWED_ORIGINS no ambiente antes de expor a API."
    )
else:
    logger.info(f"CORS allowlist ativa ({len(_ALLOWED_ORIGINS)} origens estaticas)")
    if _VERCEL_PREVIEW_BASE_DOMAINS:
        logger.info(f"Vercel base domains exatos: {_VERCEL_PREVIEW_BASE_DOMAINS}")

# Custom CORS middleware: origens estáticas + domínio base Vercel EXATO.
# Preview branches devem ser adicionadas explicitamente a ALLOWED_ORIGINS.

class VercelAwareCORSMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: list[str], vercel_preview_base_domains: list[str]):
        super().__init__(app)
        self.allowed_origins = set(allowed_origins)
        self.vercel_preview_base_domains = set(vercel_preview_base_domains)

    def _is_origin_allowed(self, origin: str) -> bool:
        """Aceita a origem apenas se for allowlist exata ou o base Vercel exato."""
        if not origin:
            return False
        if origin in self.allowed_origins:
            return True
        if not origin.startswith("https://") or not origin.endswith(".vercel.app"):
            return False
        host = origin.removeprefix("https://")
        # Sem `-git-`, sem `-<user>`: apenas o domínio base registado.
        return host in self.vercel_preview_base_domains

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")

        # Preflight (OPTIONS) - sempre responde com headers CORS se origin permitido
        if request.method == "OPTIONS":
            if origin and self._is_origin_allowed(origin):
                return StarletteResponse(
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Credentials": "true",
                        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
                        "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept, Origin, X-Requested-With",
                        "Access-Control-Max-Age": "86400",
                    }
                )
            return StarletteResponse(status_code=400, content="Origin not allowed")

        # Requisição normal
        response = await call_next(request)

        # Adiciona headers CORS se origin permitido
        if origin and self._is_origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"

        return response

app.add_middleware(VercelAwareCORSMiddleware, allowed_origins=_ALLOWED_ORIGINS, vercel_preview_base_domains=_VERCEL_PREVIEW_BASE_DOMAINS)


# Headers de segurança mínimos, aplicados a TODAS as respostas (incl. OPTIONS).
# CSP fica restrita a frame-ancestors/object/base para não bloquear scripts
# inline do Next; o endurecimento de script-src exige nonces (fase própria).
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=()",
    "Content-Security-Policy": "frame-ancestors 'none'; object-src 'none'; base-uri 'self'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            if key not in response.headers:
                response.headers[key] = value
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ------------------------------------------------------------------
# Sessões via banco de dados (controle de concorrência: máx. 2 por usuário)
# ------------------------------------------------------------------
# Sessões são persistidas exclusivamente em `user_sessions` (A2).


def _hash_token(token: str) -> str:
    """Gera hash SHA-256 do token para armazenamento seguro no banco."""
    return hashlib.sha256(token.encode()).hexdigest()


async def _get_user_id_from_token(token: str) -> int | None:
    """Valida o token no banco de dados e retorna o user_id se válido."""
    token_hash = _hash_token(token)
    return await db_service.validate_user_session(token_hash)


async def _resolve_session(token: str) -> dict:
    """Estado da sessão: 'valid' | 'expired' | 'missing' (A2)."""
    return await db_service.validate_session(_hash_token(token))


async def _get_current_user(
    authorization: str | None = Header(None),
    garimpador_token: str | None = Cookie(None),
) -> dict:
    """Obtém o usuário autenticado a partir do token (Authorization header ou cookie)."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
    elif garimpador_token:
        token = garimpador_token

    if not token:
        raise HTTPException(
            status_code=401, detail="Autenticação necessária"
        )

    # Valida no banco de dados (fonte da verdade — a evicção FIFO de
    # sessões concorrentes só tem efeito se a checagem for feita aqui).
    session = await _resolve_session(token)

    if session.get("status") == "expired":
        raise HTTPException(
            status_code=401,
            detail={
                "error": "session_expired",
                "message": "A sua sessão expirou. Entre novamente.",
            },
        )

    if session.get("status") != "valid":
        raise HTTPException(
            status_code=401,
            detail={
                "error": "session_expired_concurrent_login",
                "message": "Você foi deslogado pois sua conta foi acessada em outro dispositivo."
            }
        )
    return {"id": session["user_id"]}


async def _get_optional_user(
    authorization: str | None = Header(None),
    garimpador_token: str | None = Cookie(None),
) -> dict | None:
    """Como _get_current_user, mas retorna None quando não há sessão
    (para endpoints públicos que enriquecem a resposta com visibilidade)."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
    elif garimpador_token:
        token = garimpador_token

    if not token:
        return None

    session = await _resolve_session(token)

    if session.get("status") != "valid":
        return None
    return {"id": session["user_id"]}


def _require_admin(x_admin_secret: str | None = Header(None)) -> bool:
    """Exige o header X-Admin-Secret nas rotas administrativas.

    Fail-closed: se ADMIN_SECRET não estiver configurado, TODAS as rotas admin
    são negadas (nunca ficam abertas em produção).
    """
    expected = settings.ADMIN_SECRET
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_SECRET não configurado no servidor")
    if not x_admin_secret or not secrets.compare_digest(x_admin_secret, expected):
        raise HTTPException(status_code=401, detail="Não autorizado: admin secret inválido")
    return True


async def _get_optional_admin_user(
    authorization: str | None = Header(None),
    garimpador_token: str | None = Cookie(None),
) -> dict | None:
    """Resolve a sessão e devolve o user só se for admin. NUNCA levanta.

    Para endpoints que são públicos mas que devem dar mais detalhe a quem
    tem legitimately o papel de admin (sem fechar o acesso público).
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
    elif garimpador_token:
        token = garimpador_token
    if not token:
        return None
    try:
        user_id = await _get_user_id_from_token(token)
        if not user_id:
            return None
        user = await db_service.get_user_by_id(user_id)
        if not user or not user.get("is_admin"):
            return None
        return {"id": user["id"], "email": user.get("email")}
    except Exception:
        return None


async def _require_active_access(user: dict) -> None:
    """Gate de assinatura para qualquer ação de valor (A5).

    Devolve **402 Payment Required** (semântica correta para "renove") com
    `action: REDIRECT_TO_CHECKOUT`. A mesma resposta é usada em reservar,
    revelar e no ciclo de vida — antes só reservar/revelar estavam protegidos
    (e com 403, que não comunica "renove" ao cliente).
    """
    sub = await db_service.get_user_subscription_status(user["id"])
    if not sub.get("can_access", False):
        raise HTTPException(
            status_code=402,
            detail={
                "error": "subscription_required",
                "status": sub.get("status", "expired"),
                "message": sub.get("message") or "Assinatura necessária para continuar.",
                "action": "REDIRECT_TO_CHECKOUT",
            },
        )


async def _require_admin_user(
    authorization: str | None = Header(None),
    garimpador_token: str | None = Cookie(None),
) -> dict:
    """Gate de role-based para o painel /admin.

    Diferente de `_require_admin` (secret partilhado, só para cron/scripts),
    aqui exigimos uma sessão REAL de utilizador E `users.is_admin = 1`. É o
    que permite "login e senha de admin" em vez de um segredo global.

    Fail-closed em todos os ramos: sem token -> 401; token inválido -> 401;
    utilizador inexistente ou sem is_admin -> 403.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
    elif garimpador_token:
        token = garimpador_token
    if not token:
        raise HTTPException(status_code=401, detail="Não autorizado: autenticação necessária")

    user_id = await _get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autorizado: sessão inválida ou expirada")

    user = await db_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Não autorizado: sessão inválida ou expirada")
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return {"id": user["id"], "email": user.get("email")}


def _check_cron_secret(x_cron_secret: str | None) -> None:
    """Valida o header X-Cron-Secret. Fail-closed (antes aceitava requisições sem secret)."""
    expected = settings.CRON_SECRET
    if not expected or not x_cron_secret or not secrets.compare_digest(x_cron_secret, expected):
        raise HTTPException(status_code=401, detail="Não autorizado: CRON_SECRET inválido")


def _my_status_for(lead_status: str, owns: bool) -> str | None:
    """Status de pipeline do próprio utilizador (feed/badges), baseado em posse."""
    if not owns:
        return None
    if lead_status == "reserved":
        return "reserved"
    if lead_status in ("contacted", "in_negotiation"):
        return "negotiating"
    if lead_status == "converted":
        return "converted"
    return None


def _filter_public_leads(leads: list, user: dict | None) -> list:
    """Feed de descoberta = só o que NÃO está ocupado por terceiros.

    - Convertido: sai do feed para TODOS (fica nos "Meus Leads" do dono).
    - Engajado (reserved/contacted/in_negotiation) por OUTRO: oculto.
    - O próprio utilizador continua vendo os leads que tem em andamento.
    """
    user_id = user["id"] if (user and user.get("id")) else None
    out = []
    for lead in leads:
        ls = lead.get("lead_status", "available")
        if ls == "converted":
            continue
        if ls == "available":
            out.append(lead)
            continue
        if user_id and lead.get("reserved_by") == user_id:
            out.append(lead)
    return out


async def _annotate_visibility(leads: list, user: dict | None) -> None:
    """Marca is_mine/hours_remaining/favorited/_revealed nos leads para o _to_lead_response."""
    user_id = user["id"] if user else None

    # Pre-fetch user favorites for batch lookup (via thread pool — evita travar o event loop)
    user_fav_ids = set()
    if user_id:
        try:
            user_fav_ids = set(await db_service.get_user_favorites(user_id))
        except Exception:
            pass

    # Pre-fetch reveal ativo do usuário (decide se dados do dono vêm mascarados)
    revealed_ids: set = set()
    if user_id and leads:
        try:
            revealed_ids = await db_service.get_revealed_ids(user_id, [ld.get("id") for ld in leads])
        except Exception:
            pass

    for lead in leads:
        reserved_by = lead.get("reserved_by")
        converted_by = lead.get("converted_by")
        owns = bool(user_id) and (reserved_by == user_id or converted_by == user_id)
        lead["is_mine"] = owns
        lead["_owns"] = owns
        # Per-user favorite status
        lead["favorited"] = 1 if lead.get("id") in user_fav_ids else 0
        # Dados do proprietário só para quem revelou o lead (consentimento)
        revealed_ids = revealed_ids or set()
        lead["_revealed"] = bool(user_id) and lead.get("id") in revealed_ids
        lead_status = lead.get("lead_status", "available")
        stage_expires_at = lead.get("stage_expires_at") or lead.get("reserved_until")
        lead["_my_status"] = _my_status_for(lead_status, owns)
        if stage_expires_at and owns and lead_status in ("reserved", "contacted", "in_negotiation"):
            try:
                expires = datetime.fromisoformat(str(stage_expires_at).replace("Z", "+00:00"))
                if expires.tzinfo is not None:
                    expires = expires.replace(tzinfo=None)
                hours_left = int((expires - utcnow()).total_seconds() / 3600)
                lead["hours_remaining"] = max(0, hours_left)
            except Exception:
                lead["hours_remaining"] = 0
        else:
            lead["hours_remaining"] = 0


async def _mark_revealed(leads: list, user: dict | None) -> None:
    """Marca `_revealed` para que _to_lead_response exponha os dados do proprietário.

    _to_lead_response mascara owner_name/owner_phone/owner_email quando
    `_revealed` é falsy (gate de consentimento em main.py:111). Esse flag é
    preenchido por _annotate_visibility, que só é chamada nos endpoints de
    listagem de leads. "Meus Leads" (/api/me/history e /api/me/taken-leads)
    serializava as linhas direto, sem o flag — logo o utilizador via os campos
    do proprietário mascarados ("sem dados") apesar de o reveal estar ativo e o
    crédito já debitado, enquanto o modal mostrava os dados porque vinha da
    resposta do POST /reserve (lead já enriquecido em memória).

    Usa exatamente o mesmo predicado de get_revealed_ids, para que a máscara
    seja consistente entre a listagem e "Meus Leads".
    """
    user_id = user["id"] if user else None
    if not user_id or not leads:
        return
    try:
        revealed_ids = await db_service.get_revealed_ids(user_id, [ld.get("id") for ld in leads])
    except Exception:
        logger.exception("Falha ao calcular reveals ativos para _mark_revealed")
        revealed_ids = set()
    for lead in leads:
        lead["_revealed"] = lead.get("id") in revealed_ids


@app.get("/")
async def root():
    return {
        "status": "ok",
        "version": settings.VERSION,
        "project": settings.PROJECT_NAME
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# Endpoint para Frontend puxar leads
def _signal_type_from_filter(value) -> str | None:
    """Mapeia o filtro 'Tipo' (novo sinal ou valores legados) para signal_type."""
    if not value:
        return None
    raw = str(value).strip().lower()
    if raw in ("legal_obligation", "authorized_work", "open_request"):
        return raw
    if "hpd_violation" in raw or "dob_violation" in raw or "tax_delinquency" in raw:
        return "legal_obligation"
    if "permit" in raw:
        return "authorized_work"
    if "311" in raw:
        return "open_request"
    return None


@app.get("/api/leads", response_model=LeadsListResponse)
@limiter.limit("120/minute")
async def get_leads(
    request: Request,
    city: str = "NYC",
    category: str = None,
    type: str = None,
    page: int = 1,
    per_page: int = 20,
    include_closed: bool = False,
    user: dict = Depends(_get_current_user),
):
    """Retorna o feed qualificado com filtros e total reais em SQL (P0-B).

    A1: exige conta. Antes era `_get_optional_user` sem rate limit e com
    `offset` livre — a base inteira (85k leads) era percorrível em ~425
    pedidos anónimos. O `per_page` é limitado a 200 em `get_leads_feed`.
    """
    try:
        signal_type = _signal_type_from_filter(type)
        user_id = user["id"]
        # Teto explícito também na resposta (o DB já limita as linhas a 200).
        per_page = max(1, min(int(per_page), 200))
        page = max(1, int(page))
        leads, total = await db_service.get_leads_feed(
            city=city,
            signal_type=signal_type,
            category=category,
            include_closed=include_closed,
            user_id=user_id,
            limit=per_page,
            offset=(max(1, page) - 1) * per_page,
        )
        await _annotate_visibility(leads, user)

        return LeadsListResponse(
            total=total,
            page=page,
            per_page=per_page,
            leads=[_to_lead_response(lead) for lead in leads],
        )

    except Exception as e:
        logger.error(f"Erro ao buscar leads: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar leads")


# Busca global por endereço/nome/telefone
@app.get("/api/leads/search", response_model=LeadsListResponse)
@limiter.limit("120/minute")
async def search_leads(
    request: Request,
    q: str = "",
    per_page: int = 50,
    user: dict = Depends(_get_current_user),
):
    """Busca leads por endereço, nome do dono ou telefone — A1.

    Exige conta: era o vetor mais direto para varrer a base (busca vazia +
    `per_page`) sem rate limit.
    """
    try:
        per_page = max(1, min(int(per_page), 200))
        results = await db_service.search_leads(q, limit=per_page)

        results = _filter_public_leads(results, user)
        await _annotate_visibility(results, user)

        return LeadsListResponse(
            total=len(results),
            page=1,
            per_page=per_page,
            leads=[_to_lead_response(lead) for lead in results],
        )
    except Exception as e:
        logger.error(f"Erro na busca: {e}")
        raise HTTPException(status_code=500, detail="Erro na busca")


# Leads recentes de todas as cidades (para prévia ao vivo na home)
@app.get("/api/leads/recent", response_model=LeadsListResponse)
@limiter.limit("30/minute")
async def recent_leads(
    request: Request, limit: int = 12, user: dict | None = Depends(_get_optional_user)
):
    """Amostra pública dos leads recentes (landing) — A1.

    Continua pública de propósito (é a montra), mas com rate limit e teto de
    20 itens: não serve para paginar a base. Os dados do proprietário já saem
    mascarados sem sessão.
    """
    limit = max(1, min(int(limit), 20))
    try:
        from backend.services import db as dbmod
        conn = dbmod.get_connection()
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM leads
                WHERE {_qualified_where()}
                ORDER BY date_reported DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        results = [dict(r) for r in rows]

        await _annotate_visibility(results, user)

        return LeadsListResponse(
            total=len(results),
            page=1,
            per_page=limit,
            leads=[_to_lead_response(lead) for lead in results],
        )
    except Exception as e:
        logger.error(f"Erro ao buscar leads recentes: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar leads recentes")


# Demandas do dia (lote mais recente de todas as cidades) — feed "ver tudo"
@app.get("/api/leads/today", response_model=LeadsListResponse)
@limiter.limit("120/minute")
async def leads_today(
    request: Request,
    limit: int = 60,
    page: int = 1,
    city: str = None,
    type: str = None,
    category: str = None,
    urgency: str = None,
    include_closed: bool = False,
    user: dict = Depends(_get_current_user),
):
    """Feed dos últimos 7 dias — filtros, total e exclusão de fechados em SQL.

    P0-B: usa o MESMO predicado do `/api/leads`; `total` == linhas que o feed
    pode mostrar. `include_closed=True` (toggle do painel) mostra encerrados.

    A1: exige conta (antes era anónimo com `page` livre e 60/página).
    """
    try:
        signal_type = _signal_type_from_filter(type)
        user_id = user["id"]
        limit = max(1, min(int(limit), 200))
        page = max(1, int(page))
        leads, total = await db_service.get_leads_feed(
            city=city,
            signal_type=signal_type,
            category=category,
            urgency=urgency,
            include_closed=include_closed,
            days=7,
            user_id=user_id,
            limit=limit,
            offset=(max(1, page) - 1) * limit,
        )
        await _annotate_visibility(leads, user)

        return LeadsListResponse(
            total=total,
            page=page,
            per_page=limit,
            leads=[_to_lead_response(lead) for lead in leads],
        )
    except Exception as e:
        logger.error(f"Erro ao buscar demandas do dia: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao buscar demandas do dia")


# KPIs / estatísticas do painel
@app.get("/api/leads/stats", response_model=LeadStatsResponse)
async def lead_stats():
    try:
        return await db_service.get_stats()
    except Exception as e:
        logger.error(f"Erro ao calcular stats: {e}")
        raise HTTPException(status_code=500, detail="Erro ao calcular stats")


# Cidades com leads (para o filtro dinâmico do dashboard)
@app.get("/api/leads/cities")
async def lead_cities():
    try:
        return await db_service.get_cities()
    except Exception as e:
        logger.error(f"Erro ao listar cidades: {e}")
        raise HTTPException(status_code=500, detail="Erro ao listar cidades")


# Cidades com contagens (para filtro dinâmico com números)
@app.get("/api/leads/cities-with-counts")
async def lead_cities_with_counts(filtered: bool = True):
    try:
        if filtered:
            return await db_service.get_cities_with_counts_filtered()
        return await db_service.get_cities_with_counts()
    except Exception as e:
        logger.error(f"Erro ao listar cidades com contagens: {e}")
        raise HTTPException(status_code=500, detail="Erro ao listar cidades")


# Contagem de leads por interesses do usuário
@app.get("/api/users/{user_id}/interest-count")
async def user_interest_count(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    try:
        categories = await db_service.get_user_interests(user_id)
        if not categories:
            return {"count": 0, "categories": []}
        count = await db_service.count_leads_by_interests(categories)
        return {"count": count, "categories": categories}
    except Exception as e:
        logger.error(f"Erro ao contar leads por interesse: {e}")
        raise HTTPException(status_code=500, detail="Erro ao contar leads")


# Subscription Status
@app.get("/api/users/{user_id}/subscription-status")
async def user_subscription_status(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    try:
        return await db_service.get_user_subscription_status(user_id)
    except Exception as e:
        logger.error(f"Erro ao buscar status da subscription: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar status da subscription")


# Credit balance/ledger do próprio utilizador (sidebar e settings). O frontend
# já chamava estes caminhos mas só existia a versão /api/admin/*: cada poll
# gerava 404 no console e o saldo da sidebar ficava vazio.
@app.get("/api/users/{user_id}/credit-balance")
async def user_credit_balance(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    balance = await db_service.get_credit_balance(user_id)
    by_type = balance.get("by_type", {})
    return {
        "user_id": user_id,
        "balance": balance.get("balance", 0),
        # `counts` é o nome usado pelo frontend; `by_type` mantém paridade com
        # o endpoint admin.
        "counts": by_type,
        "by_type": by_type,
    }


@app.get("/api/users/{user_id}/credit-ledger")
async def user_credit_ledger(
    user_id: int,
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(_get_current_user),
):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    return await db_service.get_credit_ledger(user_id, limit, offset)


# Daily Stats (limit 10/day)
@app.get("/api/users/{user_id}/daily-stats")
async def user_daily_stats(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    try:
        # Sweep watchdog de reveals (notificação 30/45min, retorno ao pool 60min).
        # Expiram-se primeiro os holds: um reveal cujo hold ja morreu tem de ser
        # fechado, nao notificado como se ainda estivesse vivo.
        try:
            await db_service.expire_holds()
        except Exception as e:
            logger.error(f"Erro a expirar holds: {e}")
        try:
            await db_service.check_reveal_watchdogs()
        except Exception as e:
            logger.error(f"Erro no watchdog de reveals: {e}")
        return await db_service.get_daily_leads_used(user_id)
    except Exception as e:
        logger.error(f"Erro ao buscar stats diários: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar stats diários")


# Stats do feed (contagens por cidade, últimas 24h, últimas 7d)
@app.get("/api/leads/stats/feed")
async def feed_stats(city: str = None):
    try:
        today_count = await db_service.count_leads_last_24h()
        week_count = await db_service.count_leads_last_7d_filtered(city)
        cities = await db_service.get_cities_with_counts_filtered()
        return {
            "today": today_count,
            "week": week_count,
            "cities": cities,
            "selected_city": city,
        }
    except Exception as e:
        logger.error(f"Erro ao buscar stats do feed: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar stats do feed")


# Serviços por categoria (apenas leads com dados completos e status aberto)
@app.get("/api/leads/services")
async def lead_services(limit: int = 50):
    """Agrupa os serviços (descriptors) por categoria de interesse.

    REGRA FIXA: apenas leads QUALIFICADOS (endereço + 16 ofícios + gatilho
    preditivo) e status ABERTO (não encerrado/concluído). Nunca mostrar leads
    não-qualificados.
    """
    try:
        from backend.services import db as dbmod
        conn = dbmod.get_connection()
        try:
            rows = conn.execute(
                f"""
                SELECT issue_category,
                       COALESCE(NULLIF(TRIM(descriptor), ''), NULLIF(TRIM(case_title), ''), NULLIF(TRIM(issue_description), '')) AS service,
                       COUNT(*) AS cnt
                FROM leads
                WHERE COALESCE(NULLIF(TRIM(descriptor), ''), NULLIF(TRIM(case_title), ''), NULLIF(TRIM(issue_description), '')) != ''
                  AND LOWER(COALESCE(case_status, '')) NOT IN ('closed', 'resolved', 'solved', 'archived', 'duplicated')
                  AND {_qualified_where()}
                GROUP BY issue_category, service
                HAVING service IS NOT NULL AND service != ''
                ORDER BY issue_category ASC, cnt DESC
                LIMIT ?
                """,
                (limit * 5,),
            ).fetchall()
        finally:
            conn.close()
        # monta estrutura por categoria
        services = {}
        for r in rows:
            cat = (r["issue_category"] or "").strip() or "Structure"
            svc = (r["service"] or "").strip()
            services.setdefault(cat, []).append({
                "service": svc,
                "count": r["cnt"],
            })
        return {
            "categories": services,
            "counts": {k: sum(x["count"] for x in v) for k, v in services.items()},
        }
    except Exception as e:
        logger.error(f"Erro ao listar serviços por categoria: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao listar serviços por categoria")


# Hierarquia de localizações: país → estado → cidade
@app.get("/api/leads/locations")
async def lead_locations():
    try:
        return await db_service.get_locations_hierarchy()
    except Exception as e:
        logger.error(f"Erro ao listar hierarquia de localizações: {e}")
        raise HTTPException(status_code=500, detail="Erro ao listar localizações")


# Dashboard Summary - estatísticas reais para o Pro Dashboard (DEVE vir antes de /{lead_id})
@app.get("/api/leads/dashboard-summary")
async def leads_dashboard_summary(user: dict | None = Depends(_get_optional_user)):
    """Retorna estatísticas reais do banco para o Pro Dashboard."""
    try:
        # Pega interesses do usuário logado
        interest_categories = None
        if user:
            categories = await db_service.get_user_interests(user["id"])
            if categories:
                interest_categories = categories

        summary = await db_service.get_dashboard_summary(interest_categories)
        return summary
    except Exception as e:
        logger.error(f"Erro ao buscar dashboard summary: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar resumo do dashboard")


# Métricas públicas - Fonte Única da Verdade para contadores da Landing Page e Dashboard
@app.get("/api/metrics/public")
async def public_metrics():
    """Retorna contadores públicos unificados (total/owner/cidades + última varredura).

    Chave canônica: last_scrape.novas_oportunidades — usada tanto na Landing
    quanto no card 'Última Varredura' do Dashboard para evitar divergência.
    """
    try:
        return await db_service.get_public_metrics()
    except Exception as e:
        logger.error(f"Erro ao buscar métricas públicas: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar métricas públicas")


# Detalhe de um lead
@app.get("/api/leads/{lead_id}", response_model=LeadResponse)
@limiter.limit("120/minute")
async def get_lead(
    request: Request, lead_id: int, user: dict = Depends(_get_current_user)
):
    """Detalhe do lead — exige conta (A1).

    Os IDs são sequenciais: com acesso anónimo, a base inteira podia ser
    enumerada (`/api/leads/1..85873`) sem rate limit. O frontend só usa esta
    rota dentro do dashboard autenticado.
    """
    lead = await db_service.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    await _annotate_visibility([lead], user)
    return _to_lead_response(lead)


# Atualizar status / telefone do dono
@app.patch("/api/leads/{lead_id}", response_model=LeadResponse)
async def update_lead(lead_id: int, payload: LeadUpdate, user: dict = Depends(_get_current_user)):
    if payload.status:
        ok = await db_service.update_lead_status(lead_id, payload.status)
        if not ok:
            raise HTTPException(status_code=404, detail="Lead não encontrado")
        lead = await db_service.get_lead_by_id(lead_id)
        if lead:
            await db_service.add_notification(
                "status_change",
                "Status da oportunidade atualizado",
                f"A oportunidade em {lead.get('address') or 'endereço não informado'}, {lead.get('city') or ''} agora está '{payload.status}' (categoria {lead.get('issue_category') or 'N/I'})",
                lead_id=lead_id,
                msg_key="status_change",
                msg_params={
                    "addr": lead.get("address") or "N/I",
                    "city": lead.get("city") or "N/I",
                    "status": payload.status,
                    "category": lead.get("issue_category") or "N/I",
                },
            )
        await _annotate_visibility([lead], user)
        return _to_lead_response(lead)
    if payload.owner_phone is not None:
        await db_service.update_owner_phone(lead_id, payload.owner_phone)
    lead = await db_service.get_lead_by_id(lead_id)
    await _annotate_visibility([lead], user)
    return _to_lead_response(lead)


# Favoritar / desfavoritar
@app.post("/api/leads/{lead_id}/favorite", response_model=LeadResponse)
async def toggle_favorite(lead_id: int, user: dict = Depends(_get_current_user)):
    result = await db_service.toggle_favorite_for_user(user["id"], lead_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    lead = await db_service.get_lead_by_id(lead_id)
    lead_dict = dict(lead) if lead else {}
    lead_dict["favorited"] = 1 if result else 0
    await _annotate_visibility([lead_dict], user)
    return _to_lead_response(lead_dict)


# Registrar contato (SMS / WhatsApp / Call / Email)
# Handler moderno abaixo (com auth + contact_count): ver /api/leads/{lead_id}/contact


# Notas do lead
@app.get("/api/leads/{lead_id}/notes", response_model=list[NoteResponse])
async def get_lead_notes(lead_id: int, user: dict = Depends(_get_current_user)):
    notes = await db_service.get_notes(lead_id)
    return notes


@app.post("/api/leads/{lead_id}/notes", response_model=NoteResponse)
async def add_lead_note(lead_id: int, body: NoteCreate, user: dict = Depends(_get_current_user)):
    if not body.note or not body.note.strip():
        raise HTTPException(status_code=422, detail="Nota vazia")
    created = await db_service.add_note(lead_id, body.note.strip(), user["id"])
    if not created:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    return created


@app.delete("/api/leads/{lead_id}/notes/{note_id}")
async def delete_lead_note(lead_id: int, note_id: int, user: dict = Depends(_get_current_user)):
    ok = await db_service.delete_note(note_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Nota não encontrada")
    return {"status": "ok"}


# ------------------------------------------------------------------
# Notificações (com filtro de "recentes" para o painel)
# ------------------------------------------------------------------
def _localize_notification(row: dict, locale: str | None) -> dict:
    """Aplica o texto localizado a uma linha de notificação, se houver msg_key.

    O title/message gravados servem de fallback; quando existe
    msg_key + msg_params renderizamos no locale do utilizador na leitura.
    """
    item = dict(row)
    msg_key = item.get("msg_key")
    if not msg_key:
        return item
    params: dict = {}
    raw = item.get("msg_params")
    if raw:
        try:
            params = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (ValueError, TypeError):
            params = {}
    rendered = _render_notification(msg_key, locale, **params)
    if rendered:
        item["title"] = rendered["title"]
        item["message"] = rendered["message"]
    return item


@app.get("/api/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    user: dict = Depends(_get_current_user),
    filter: str = "recent",
    limit: int = 50,
    unread: int = None,
):
    """Lista notificações do usuário autenticado.
    - filter: 'recent' (7 dias, padrão) | 'unread' | 'all'
    - unread: 1 força o filtro para não lidas (conveniência do frontend)
    """
    try:
        if unread == 1:
            filter = "unread"
        user_row = await db_service.get_user_by_id(user["id"]) or {}
        locale = user_row.get("locale")
        rows = await db_service.get_notifications_for_user(user["id"], filter=filter, limit=limit)
        out = []
        for r in rows:
            item = _localize_notification(r, locale)
            out.append(NotificationResponse(
                id=item["id"],
                type=item["type"],
                # Regra de ouro: o sino nunca mostra a marca da fonte. Cobre
                # tambem notificacoes antigas gravadas antes desta politica.
                title=scrub(item["title"]) or item["title"],
                message=scrub(item["message"]) or item["message"],
                lead_id=item.get("lead_id"),
                created_at=item["created_at"],
                read=bool(item.get("read")),
            ))
        return out
    except Exception as e:
        logger.error(f"Erro ao listar notificações: {e}")
        raise HTTPException(status_code=500, detail="Erro ao listar notificações")


@app.get("/api/notifications/unread-count")
async def notifications_unread_count(user: dict = Depends(_get_current_user)):
    """Retorna o total de notificações não lidas do usuário (badge do sino)."""
    try:
        return {"unread": await db_service.count_unread_notifications_for_user(user["id"])}
    except Exception as e:
        logger.error(f"Erro ao contar notificações: {e}")
        raise HTTPException(status_code=500, detail="Erro")


@app.post("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int, user: dict = Depends(_get_current_user)):
    ok = await db_service.mark_notification_read_for_user(notification_id, user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Notificação não encontrada")
    return {"status": "ok"}


@app.post("/api/notifications/read-all")
async def mark_all_notifications_read(user: dict = Depends(_get_current_user)):
    marked = await db_service.mark_all_notifications_read_for_user(user["id"])
    return {"status": "ok", "marked": marked}


# Push Notification Endpoints
@app.get("/api/push/vapid-public-key")
async def get_vapid_public_key():
    """Retorna a chave pública VAPID para o frontend se inscrever."""
    public_key = push_service._vapid_public_key
    if not public_key:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"public_key": public_key}


def _push_device_label(user_agent: str) -> str:
    """Rotulo legivel do dispositivo para o painel de higiene (B1)."""
    ua = (user_agent or "").lower()
    if "crios" in ua:
        browser = "Chrome"
    elif "edg" in ua:
        browser = "Edge"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "chrome" in ua:
        browser = "Chrome"
    elif "safari" in ua:
        browser = "Safari"
    else:
        browser = "Browser"
    if "android" in ua:
        os_name = "Android"
    elif "iphone" in ua:
        os_name = "iPhone"
    elif "ipad" in ua:
        os_name = "iPad"
    elif "windows" in ua:
        os_name = "Windows"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Device"
    return f"{browser} · {os_name}"


@app.post("/api/push/subscribe")
async def subscribe_push(
    payload: PushSubscribeRequest,
    request: Request,
    user: dict = Depends(_get_current_user),
):
    """Registra uma push subscription para o usuário.

    B1: guarda o user-agent e um rotulo do dispositivo, atualiza `last_seen_at`
    e mantem no maximo 5 dispositivos ativos (os mais antigos sao desativados).
    """
    try:
        ua = (request.headers.get("user-agent") or "")[:300]
        label = _push_device_label(ua)
        ok = await db_service.add_push_subscription(
            user["id"], payload.endpoint, payload.p256dh, payload.auth, ua, label
        )
        if ok:
            await db_service.set_user_push_enabled(user["id"], True)
        return {"status": "ok", "subscribed": ok}
    except Exception as e:
        logger.error(f"Erro ao inscrever push: {e}")
        raise HTTPException(status_code=500, detail="Erro ao inscrever")


@app.get("/api/push/click")
@limiter.limit("120/minute")
async def push_click(request: Request, nid: int, sig: str):
    """Regista o clique num alerta (assinado por HMAC, sem sessao).

    O Service Worker nao tem acesso ao token; a assinatura impede que um
    terceiro infle o CTR. Idempotente: o primeiro clique conta.
    """
    if not verify_click(nid, sig):
        raise HTTPException(status_code=403, detail="Assinatura inválida")
    recorded = await db_service.mark_notification_clicked(nid)
    return {"status": "ok", "recorded": recorded}

@app.post("/api/push/unsubscribe")
async def unsubscribe_push(
    payload: PushUnsubscribeRequest,
    user: dict = Depends(_get_current_user),
):
    """Remove uma push subscription do usuário."""
    ok = await db_service.remove_push_subscription(user["id"], payload.endpoint)
    # Se não restarem subscriptions, marca push_enabled = false (sanitização
    # atómica: evita o estado zumbi flag=1 sem dispositivo subscrito).
    await db_service.disable_push_if_no_subscriptions(user["id"])
    return {"status": "ok", "unsubscribed": ok}


@app.patch("/api/push/enabled")
async def update_push_enabled(
    payload: PushEnabledUpdate,
    user: dict = Depends(_get_current_user),
):
    """Define manualmente o flag push_enabled do usuário.

    Ativar push sem nenhuma subscription registada criaria um estado zumbi
    (flag=1, nenhum dispositivo), que gera `no_subscriptions` a cada run.
    Nesse caso a ativação é recusada.
    """
    if payload.enabled:
        subs = await db_service.get_user_push_subscriptions(user["id"])
        if not subs:
            return {
                "status": "ok",
                "push_enabled": False,
                "updated": False,
                "error": "no_subscriptions",
            }
    ok = await db_service.set_user_push_enabled(user["id"], payload.enabled)
    return {"status": "ok", "push_enabled": payload.enabled, "updated": ok}


@app.get("/api/push/subscriptions")
async def list_push_subscriptions(user: dict = Depends(_get_current_user)):
    """Lista as push subscriptions do usuário."""
    subs = await db_service.get_user_push_subscriptions(user["id"])
    return {"subscriptions": subs}


@app.post("/api/push/test")
async def test_push_notification(user_id: int, _admin: bool = Depends(_require_admin)):
    """Envia uma notificação de teste para o usuário (rota administrativa)."""
    if not push_service.is_configured():
        raise HTTPException(status_code=503, detail="Push notifications not configured")

    sent = await push_service.send_to_user(user_id, {
        "title": "Magic Leads - Teste",
        "body": "Esta é uma notificação de teste. Push notifications funcionando!",
        "tag": "test_notification",
        "url": "/dashboard"
    })
    return {"status": "ok", "sent": sent}


@app.post("/api/push/send-test")
async def send_test_push(payload: SendTestPushRequest, _admin: bool = Depends(_require_admin)):
    """Dispara um push real via Web Push (pywebpush) para teste (rota administrativa).

    Sem user_id, faz broadcast para todas as subscriptions ativas.
    """
    if not push_service.is_configured():
        raise HTTPException(status_code=503, detail="Push notifications not configured")

    push_payload = {
        "title": payload.title,
        "body": payload.body,
        "tag": payload.tag,
        "url": payload.url,
        "icon": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
        "badge": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg"
    }

    if payload.user_id is not None:
        sent = await push_service.send_to_user(payload.user_id, push_payload)
        return {"status": "ok", "sent": sent, "configured": True}

    if payload.debug:
        return await push_service.send_to_all_debug(push_payload, ttl=payload.ttl)

    sent = await push_service.send_to_all(push_payload)

    return {"status": "ok", "sent": sent, "configured": True}


# Webhook para rodar scraper manualmente
# Estado dos runs do scraper (background — o Railway corta conexões longas)
_scrape_runs: dict = {}
_MAX_SCRAPE_RUNS = 50


def _remember_scrape_run(state: dict) -> None:
    """Guarda o run em memória com poda (o processo pode viver semanas)."""
    run_id = state.get("run_id")
    if not run_id:
        return
    _scrape_runs[run_id] = state
    if len(_scrape_runs) > _MAX_SCRAPE_RUNS:
        old = sorted(
            _scrape_runs,
            key=lambda k: (_scrape_runs[k].get("started_at") or ""),
        )[: len(_scrape_runs) - _MAX_SCRAPE_RUNS]
        for key in old:
            _scrape_runs.pop(key, None)


@app.post("/api/scraper/run")
@limiter.limit("10/hour")
async def run_scraper(
    request: Request,
    max_cities: int = 8,
    hours: int = None,
    x_cron_secret: str | None = Header(None),
):
    """Dispara o scraper nacional em background e responde na hora (o run leva 15min+).

    Requer header X-Cron-Secret para execução via cron externo (GitHub Actions, Railway Cron).
    Parâmetro 'hours' opcional: janela de horas para buscar dados (ex: 120 para catch-up noturno).
    """
    # Autenticação por CRON_SECRET (obrigatório — fail-closed)
    _check_cron_secret(x_cron_secret)

    for run in _scrape_runs.values():
        if run.get("running"):
            return JSONResponse(status_code=409, content={
                "status": "already_running",
                "run_id": run.get("run_id"),
                "note": "Scraper já em execução; inserts são incrementais/reentrantes (dedupe).",
            })
    run_id = uuid.uuid4().hex[:12]
    _remember_scrape_run({
        "run_id": run_id, "running": True,
        "started_at": utcnow().isoformat(),
        "inserted": 0, "total_raw": 0, "status": "running", "error": None,
    })
    asyncio.create_task(_run_scrape_guarded(run_id, max_cities, hours_override=hours))
    return JSONResponse(status_code=202, content={
        "status": "started", "run_id": run_id,
        "note": "Run em background; acompanhe em GET /api/scraper/status",
    })


@app.get("/api/scraper/status")
async def scraper_status(_admin: dict | None = Depends(_get_optional_admin_user)):
    """Última atualização dos dados para o feed (usado na landing e no dashboard).

    PÚBLICO E MINIMALISTA por decisão de segurança: este endpoint é chamado
    por páginas públicas (HeroSection) e não pode revelar a operação interna.
    Antes devolvia `city_health` (failure_count, circuit_open_until,
    anomaly_counter por cidade) e o dict `running` com erros — ou seja,
    qualquer visitante via saber exatamente que scrapers estao a falhar e
    que cidades estao com o circuit breaker aberto. Isso foi removido.

    Quem precisa do diagnóstico completo usa `/api/admin/sources`
    (sessão + is_admin), que devolve city_health e o last_run inteiro.
    """
    active = {rid: r for rid, r in _scrape_runs.items() if r.get("running")}
    last = None
    for r in reversed(list(_scrape_runs.values())):
        if not r.get("running"):
            last = r
            break
    if last is None:
        persisted = await db_service.get_last_scrape_run()
        if persisted:
            last = persisted

    # Só o mínimo para o "Dados atualizados" da landing/dashboard.
    public_last = None
    if last:
        public_last = {
            "finished_at": last.get("finished_at"),
            "status": last.get("status"),
        }

    payload = {"active": bool(active), "last_run": public_last}

    # Admin autenticado recebe o detalhe sem precisar de outro endpoint.
    if _admin:
        payload["running"] = active
        payload["city_health"] = await db_service.get_city_health_for_scraper_status()
        if last:
            payload["last_run"] = {
                "run_id": last.get("run_id"),
                "started_at": last.get("started_at"),
                "finished_at": last.get("finished_at"),
                "status": last.get("status"),
                "inserted": last.get("inserted"),
                "total_raw": last.get("total_raw"),
                "cities_covered": last.get("cities_covered"),
                "error": last.get("error"),
                "note": last.get("note"),
            }
    return payload


@app.get("/api/system/alerts")
async def system_alerts(limit: int = 20, _admin: bool = Depends(_require_admin)):
    """Auditoria de anomalias de fluxo (Dead Man's Switch). Rota administrativa."""
    limit = max(1, min(int(limit), 100))
    alerts = await db_service.get_recent_system_alerts(limit)
    return {"alerts": alerts, "count": len(alerts)}


@app.post("/api/system/alerts/{alert_id}/ack")
async def acknowledge_system_alert(alert_id: int, _admin: bool = Depends(_require_admin)):
    """Marca um alerta de auditoria como reconhecido. Rota administrativa."""
    alert = await db_service.acknowledge_system_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")
    return {"ok": True, "alert": alert}


# ============================================================
# ADMIN PANEL (/admin) — Torre de controlo interna
#
# Gate: _require_admin_user (sessão real + users.is_admin). Não usar
# _require_admin (secret global) aqui: o painel é login+password.
# ============================================================

@app.get("/api/admin/overview")
async def admin_overview(_admin: dict = Depends(_require_admin_user)):
    """KPIs de topo: leads, utilizadores, reveals, créditos e alertas."""
    return await db_service.admin_get_overview()


@app.get("/api/admin/sessions")
async def admin_sessions(limit: int = 100, _admin: dict = Depends(_require_admin_user)):
    """Sessões ativas (A2): quem, dispositivo, IP e até quando.

    A fonte é `user_sessions.expires_at` (TTL deslizante de 30 dias). As
    expiradas já são podadas no arranque e nunca aparecem aqui.
    """
    sessions = await db_service.admin_list_sessions(limit)
    return {"sessions": sessions, "count": len(sessions)}


@app.delete("/api/admin/sessions/{session_id}")
async def admin_revoke_session(session_id: int, _admin: dict = Depends(_require_admin_user)):
    """Revoga uma sessão específica (o cliente cai no próximo pedido com 401)."""
    ok = await db_service.admin_revoke_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return {"revoked": True, "session_id": session_id}


@app.delete("/api/admin/users/{user_id}/sessions")
async def admin_revoke_user_sessions(user_id: int, _admin: dict = Depends(_require_admin_user)):
    """Revoga todas as sessões de um utilizador (ex.: conta comprometida)."""
    count = await db_service.admin_revoke_user_sessions(user_id)
    return {"revoked_count": count, "user_id": user_id}


# ---------------------------------------------------------------- acesso
# Override de assinatura (cortesia). Escreve users.subscription_status +
# users.plan_until — a mesma fonte que o Stripe — e audita em admin_audit_log.


@app.get("/api/admin/users/lookup")
async def admin_user_lookup(
    email: str, _admin: dict = Depends(_require_admin_user)
):
    """Pré-visualização de uma conta pelo e-mail (para a concessão de acesso)."""
    normalized = (email or "").strip().lower()
    if not normalized or "@" not in normalized:
        raise HTTPException(status_code=400, detail="E-mail inválido")
    user = await db_service.get_user_by_email(normalized)
    if not user:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    access = await db_service.get_user_subscription_status(user["id"])
    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "company_name": user.get("company_name"),
            "plan": user.get("plan"),
            "subscription_status": user.get("subscription_status"),
            "plan_until": user.get("plan_until"),
            "is_admin": bool(user.get("is_admin")),
            "created_at": user.get("created_at"),
        },
        "access": access,
    }


@app.post("/api/admin/access/grant")
@limiter.limit("30/hour")
async def admin_grant_access(
    request: Request,
    payload: AccessGrantRequest,
    admin: dict = Depends(_require_admin_user),
):
    """Concede (soma) `days` de acesso ativo a uma conta, com auditoria."""
    if payload.reason not in ALLOWED_ACCESS_GRANT_REASONS:
        raise HTTPException(status_code=400, detail="Motivo inválido")
    if payload.reason == "other" and not (payload.note or "").strip():
        raise HTTPException(
            status_code=400, detail="Nota obrigatória quando o motivo é 'Outro'"
        )

    email = str(payload.email).strip().lower()
    user = await db_service.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="Conta não encontrada")

    result = await db_service.admin_grant_access(
        user["id"],
        payload.days,
        admin_id=admin["id"],
        admin_email=admin.get("email") or "",
        reason=payload.reason,
        note=(payload.note or "").strip() or None,
        idempotency_key=payload.idempotency_key,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    if result.get("error") == "invalid_days":
        raise HTTPException(status_code=400, detail="Dias inválidos")
    if result.get("error") == "user_not_found":
        raise HTTPException(status_code=404, detail="Conta não encontrada")

    # Watchdog: concessões sensíveis ficam também nos alertas de auditoria.
    is_sensitive = bool(user.get("is_admin")) or payload.days > 90
    if is_sensitive and not result.get("duplicate"):
        await db_service.record_system_alert(
            level="warn",
            code="ADMIN_ACCESS_GRANT",
            message=(
                f"Concessão manual de {payload.days} dia(s) a {user['email']} "
                f"por {admin.get('email') or admin['id']} ({payload.reason})."
            ),
            context={
                "audit_id": result.get("audit_id"),
                "target_user_id": user["id"],
                "target_is_admin": bool(user.get("is_admin")),
                "days": payload.days,
                "reason": payload.reason,
                "before": result.get("before"),
                "after": result.get("after"),
            },
        )
    return result


@app.post("/api/admin/access/revoke")
async def admin_revoke_access(
    request: Request,
    payload: AccessRevokeRequest,
    admin: dict = Depends(_require_admin_user),
):
    """Reverte uma concessão, se a expiração não mudou desde então."""
    result = await db_service.admin_revoke_access(
        payload.audit_id,
        admin_id=admin["id"],
        admin_email=admin.get("email") or "",
        reason=(payload.reason or "").strip() or None,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    error = result.get("error")
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Concessão não encontrada")
    if error == "already_revoked":
        raise HTTPException(status_code=409, detail="Concessão já revertida")
    if error == "changed_since_grant":
        raise HTTPException(
            status_code=409,
            detail=(
                "A expiração mudou desde a concessão (pagamento ou outra concessão). "
                "Revisão manual necessária."
            ),
        )
    if error == "user_not_found":
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    return result


@app.get("/api/admin/access/audit")
async def admin_access_audit(
    limit: int = 50, _admin: dict = Depends(_require_admin_user)
):
    """Histórico append-only de concessões/revogações de acesso."""
    entries = await db_service.admin_list_access_audit(limit)
    return {"entries": entries, "count": len(entries)}


@app.get("/api/admin/sources")
async def admin_sources(_admin: dict = Depends(_require_admin_user)):
    """Saúde das fontes de dados: circuit breaker por cidade + último run.

    Lê `city_health`/`scraper_runs` (persistidos) em vez do dict em memória
    `_scrape_runs`, que se perde a cada restart da Railway.
    """
    city_health = await db_service.get_city_health_for_scraper_status()
    last_run = await db_service.get_last_scrape_run()
    return {"city_health": city_health, "last_run": last_run}


@app.get("/api/admin/scraper/runs")
async def admin_scraper_runs(limit: int = 50, _admin: dict = Depends(_require_admin_user)):
    """Histórico de runs do scraper (sobrevive a restart/deploy)."""
    runs = await db_service.admin_get_recent_scraper_runs(limit)
    return {"runs": runs, "count": len(runs)}


@app.get("/api/admin/reveals")
async def admin_reveals(
    limit: int = 50,
    returned_only: bool = False,
    _admin: dict = Depends(_require_admin_user),
):
    """Auditoria de reveals: sucesso vs. retorno ao pool vs. estorno.

    `returned_only=true` devolve a fila de trabalho para recuperação de
    acesso e eventual estorno (reincidência do incidente 'dados pagos
    ficaram invisíveis').
    """
    rows = await db_service.admin_get_recent_reveals(limit, returned_only)
    return {"reveals": rows, "count": len(rows)}


@app.get("/api/admin/searchbug")
async def admin_searchbug(
    days: int = 7,
    recent_limit: int = 50,
    _admin: dict = Depends(_require_admin_user),
):
    """Fase 2: custo e fiabilidade das consultas pagas a Searchbug.

    `ghost_charges` e a metrica de dinheiro: consultas que chegaram ao
    provider e nao devolveram telefoneutilizavel. `buffer` expoe o estado
    do writer assincrono para que telemetria perdida apareca como numero.
    """
    data = await db_service.admin_get_searchbug_metrics(days, recent_limit)
    data["buffer"] = searchbug_metrics.stats()
    return data


@app.get("/api/admin/digest-ab")
async def admin_digest_ab(
    days: int = 30,
    _admin: dict = Depends(_require_admin_user),
):
    """B3: CTR do digest por variante de copy (A/B)."""
    return await db_service.admin_get_digest_ab(days)


@app.get("/api/admin/geo-coverage")
async def admin_geo_coverage(_admin: dict = Depends(_require_admin_user)):
    """B3: cobertura de coordenadas no feed (com/sem BBL resolvível)."""
    return await db_service.count_leads_missing_coords()


@app.post("/api/admin/backfill-dob-coords")
async def admin_backfill_dob_coords(
    batch: int = 500,
    max_batches: int = 40,
    _admin: dict = Depends(_require_admin_user),
):
    """B3: preenche lat/lng dos leads com BBL via PLUTO (idempotente).

    Duas fases: (1) recupera o BBL dos leads DOB antigos a partir do dataset de
    origem; (2) resolve BBL -> coordenadas no PLUTO. Sem custo (dados abertos) e
    com cache local. Chamadas repetidas continuam de onde pararam.
    """
    bbl = await geo_lookup.backfill_dob_bbl_from_source(
        batch=max(50, min(int(batch), 1000)),
        max_batches=max(1, min(int(max_batches), 200)),
    )
    coords = await geo_lookup.backfill_missing_coords(
        batch=max(50, min(int(batch), 2000)),
        max_batches=max(1, min(int(max_batches), 200)),
    )
    return {
        "bbl": bbl,
        "coords": coords,
        "coverage": await db_service.count_leads_missing_coords(),
    }


@app.get("/api/admin/phone-sample-progress")
async def admin_phone_sample_progress(
    days: int = 90,
    _admin: dict = Depends(_require_admin_user),
):
    """P2: progresso da amostra por segmento ate' aos 30 necessarios.

    Mostra contagens mesmo abaixo do limiar (e' um painel de operacao), mas a
    percentagem so aparece quando o segmento ja' e' publicavel — a mesma regra
    que o cartao do cliente usa.
    """
    data = await db_service.admin_get_phone_sample_progress(days)

    def _enrich(row: dict) -> dict:
        samples = int(row.get("samples") or 0)
        successes = int(row.get("successes") or 0)
        ready = samples >= PHONE_STATS_MIN_SAMPLES
        return {
            **row,
            "samples": samples,
            "successes": successes,
            "pct": round(successes * 100 / samples) if ready and samples else None,
            "ready": ready,
            "needed": max(0, PHONE_STATS_MIN_SAMPLES - samples),
        }

    segments = [_enrich(r) for r in data["segments"]]
    by_class = [_enrich(r) for r in data["by_class"]]
    return {
        "days": data["days"],
        "min_samples": PHONE_STATS_MIN_SAMPLES,
        "segments": segments,
        "by_class": by_class,
        "ready_segments": sum(1 for s in segments if s["ready"]),
        "total_segments": len(segments),
        "total_samples": sum(s["samples"] for s in segments),
    }


@app.get("/api/admin/push")
async def admin_push(
    days: int = 7,
    recent_limit: int = 50,
    _admin: dict = Depends(_require_admin_user),
):
    """Fase 2: saúde das entregas de push notification.

    `accepted` é o serviço de push a aceitar a mensagem, NÃO prova de
    entrega ao utilizador. `expired` (404/410) são subscrições mortas que
    foram removidas — é a métrica que diz quanto foi para o vazio.
    """
    data = await db_service.admin_get_push_metrics(days, recent_limit)
    data["buffer"] = push_metrics.stats()
    return data


@app.post("/api/admin/push/test")
async def admin_push_test(
    payload: SendTestPushRequest | None = None,
    admin: dict = Depends(_require_admin_user),
):
    """Envia um push de teste PARA O PRÓPRIO ADMIN autenticado (via sessão).

    Diferente de `/api/push/send-test` (que exige o X-Admin-Secret e pode
    fazer broadcast), esta rota usa a sessão do painel `/admin` e entrega
    apenas para os dispositivos do admin que está a clicar no botão — é a
    forma correta de o admin validar o próprio dispositivo.

    Devolve `sent` = número de subscrições para as quais o Web Push foi
    aceite (`accepted`, não prova de entrega).
    """
    if not push_service.is_configured():
        raise HTTPException(status_code=503, detail="Push notifications not configured")

    subs = await db_service.get_user_push_subscriptions(admin["id"])
    if not subs:
        raise HTTPException(
            status_code=404,
            detail="Nenhum dispositivo subscrito para este admin. "
            "Ative as notificações neste browser primeiro.",
        )

    req = payload or SendTestPushRequest()
    push_payload = {
        "title": req.title,
        "body": req.body,
        "tag": req.tag,
        "url": req.url,
        "icon": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
        "badge": "https://magicleads-oficial.vercel.app/icons/magicleads-brand.svg",
    }
    sent = await push_service.send_to_user(admin["id"], push_payload)
    return {"status": "ok", "sent": sent, "subscriptions": len(subs), "configured": True}


# ------------------------------------------------- Outbound (frio) — Fase 2
#
# O motor de envio REAL vive em `services/outbound_engine.py` (EmailListVerify + Gmail).
# Este bloco expoe ao painel:
#   1) leitura/escrita da config isolada por cidade (toggles do admin);
#   2) simulacao dry-run (preview: contagem, custo estimado, template);
#   3) envio real fail-closed: so' corre com `send_enabled=1`, promove o lote
#      (dry_run=0) e materializa `outbound_messages` apenas com e-mails `valid`;
#   4) estado operacional (fila, tetos, caixas, warm-up).
# Com `send_enabled=0` (default) nada e' enfileirado nem enviado.

# Estimativas para o simulador. O scrape e' gratis (pedidos HTTP proprios);
# so' o fallback pago (Snov) tem custo por e-mail encontrado. A taxa e' a
# fraccao estimada de leads que o scrape NAO resolve e cai para o Snov.
_SNOV_PER_EMAIL_USD = 0.015
_SNOV_FALLBACK_RATE = 0.7

# Idioma OBRIGATORIO: todo o copy outbound e' ingles comercial americano
# (en-US), independentemente do idioma da plataforma. Os templates vivem em
# `services/outbound_templates.py`, que se auto-valida no import (sem acentos
# nem termos PT). Placeholders {company_name}/{city}/... sao preenchidos com
# dados REAIS antes de o admin aprovar o lote.
_OUTBOUND_LANGUAGE = "en-US"


def _estimate_outbound_cost(batch_size: int) -> dict:
    """Estima o custo do enriquecimento de um lote (scrape gratis + Snov pago).

    Devolve o detalhe para o painel mostrar de onde vem o numero — nao e' um
    orcamento, e' uma heuristica conservadora para o admin decidir.
    """
    size = max(0, int(batch_size))
    snov_hits = round(size * _SNOV_FALLBACK_RATE)
    snov_cost = round(snov_hits * _SNOV_PER_EMAIL_USD, 2)
    return {
        "batch_size": size,
        "scrape_cost_usd": 0.0,
        "snov_emails": snov_hits,
        "snov_per_email_usd": _SNOV_PER_EMAIL_USD,
        "snov_fallback_rate": _SNOV_FALLBACK_RATE,
        "snov_cost_usd": snov_cost,
        "total_usd": snov_cost,
    }


class OutboundSimulateRequest(BaseModel):
    city: str
    batch_size: int | None = None
    niche: str | None = None


class OutboundPreviewRequest(BaseModel):
    city: str
    niche: str | None = None


class OutboundSendRequest(BaseModel):
    batch_id: int
    city: str | None = None


class OutboundConfigUpdateRequest(BaseModel):
    send_enabled: bool | None = None
    enrich_enabled: bool | None = None
    city: str | None = None


class OutboundImportItem(BaseModel):
    email: str
    company_name: str
    city: str
    category: str | None = "General Contractors"
    contact_name: str | None = None
    domain: str | None = None
    state: str | None = None


class OutboundImportRequest(BaseModel):
    leads: list[OutboundImportItem]


def _build_outbound_preview(
    city: str,
    niche: str,
    count: int,
    sample: dict | None,
    contact: dict | None = None,
) -> dict:
    """Monta o e-mail REAL (dados reais + template do nicho) para o painel.

    Destinatario (empresa/contacto) vem de `outbound_contacts` quando ha
    enriquecimento; caso contrario cai no `owner_name` do lead (stand-in).
    A oportunidade (endereco/categoria) vem sempre do lead real. `render_email`
    corre `assert_english_only`, garantindo en-US tambem apos edicao.
    """
    context = outbound_templates.build_context(
        sample, city, niche, count, contact=contact
    )
    rendered = outbound_templates.render_email(niche, context)
    if contact and (contact.get("company_name") or contact.get("email")):
        sample_source = "enriched_contact"
    else:
        sample_source = "lead_owner_fallback"
    return {
        "niche": niche,
        "niche_label": outbound_templates.NICHES.get(
            niche, outbound_templates.NICHES[outbound_templates.DEFAULT_NICHE]
        )["label"],
        "language": _OUTBOUND_LANGUAGE,
        "template": outbound_templates.get_template(niche),
        "placeholders": sorted(context.keys()),
        "context": context,
        "sample_source": sample_source,
        "recipient_sample": contact,
        "opportunity_sample": sample,
        "preview": rendered,
    }


@app.get("/api/admin/outbound/diagnostics")
async def admin_outbound_diagnostics(
    city: str = "NYC",
    niche: str = "",
    _admin: dict = Depends(_require_admin_user),
):
    """Radiografia do funil outbound: leads x e-mails x enfileiraveis.

    Responde em producao (SQLite do volume) sem precisar de shell: quantos
    leads existem na cidade, quantos tem e-mail, quantos vieram de import B2B,
    quantos contactos estao `valid`/`verified` e quantos podem entrar na fila.
    """
    city = (city or "").strip().upper()
    if not city:
        raise HTTPException(status_code=400, detail="Cidade obrigatoria")
    niche = (niche or "").strip() or outbound_templates.DEFAULT_NICHE
    if niche not in outbound_templates.NICHES:
        raise HTTPException(status_code=400, detail="Nicho invalido")

    categories = outbound_templates.niche_categories(niche)
    data = await db_service.outbound_diagnostics(city)
    pool = await db_service.list_outbound_leads(city, categories, 200)
    data.update(
        {
            "niche": niche,
            "qualified_available": await db_service.count_qualified_contractors_in_city(
                city, categories
            ),
            "batch_pool_200": len(pool),
        }
    )
    return data


@app.get("/api/admin/outbound/config")
async def admin_outbound_config(_admin: dict = Depends(_require_admin_user)):
    """Config isolada por cidade + global, para o selector do painel (dinâmico)."""
    cities = await db_service.get_available_outbound_cities()
    per_city = {}
    for city in cities:
        per_city[city] = await db_service.get_outbound_config(city)
    global_config = await db_service.get_outbound_config()
    dynamic_cats = await db_service.get_available_outbound_categories()
    return {
        "cities": cities,
        "global": global_config,
        "per_city": per_city,
        "send_enabled": global_config.get("send_enabled") == "1",
        "niches": outbound_templates.niche_options(),
        "dynamic_categories": dynamic_cats,
        "default_niche": outbound_templates.DEFAULT_NICHE,
        "language": _OUTBOUND_LANGUAGE,
    }


@app.post("/api/admin/outbound/config")
async def admin_outbound_update_config(
    payload: OutboundConfigUpdateRequest,
    admin: dict = Depends(_require_admin_user),
):
    """Liga/desliga o envio real e o enriquecimento (toggles do admin).

    Escopo isolado: grava em `outbound_config` (global ou override por cidade).
    Desligar `send_enabled` e' sempre permitido e para imediatamente o worker.
    """
    city = (payload.city or "").strip().upper()
    if city:
        available = await db_service.get_available_outbound_cities()
        if city not in available:
            raise HTTPException(status_code=400, detail="Cidade sem leads/contactos")
    if payload.send_enabled is None and payload.enrich_enabled is None:
        raise HTTPException(status_code=400, detail="Nada para atualizar")

    if payload.send_enabled is not None:
        await db_service.set_outbound_config(
            "send_enabled", "1" if payload.send_enabled else "0", city
        )
    if payload.enrich_enabled is not None:
        await db_service.set_outbound_config(
            "enrich_enabled", "1" if payload.enrich_enabled else "0", city
        )
    logger.info(
        "[OUTBOUND] Config atualizada por admin=%s city=%s send=%s enrich=%s",
        (admin or {}).get("id"),
        city or "GLOBAL",
        payload.send_enabled,
        payload.enrich_enabled,
    )
    config = (
        await db_service.get_outbound_config(city) if city else await db_service.get_outbound_config()
    )
    return {
        "status": "ok",
        "city": city or None,
        "send_enabled": config.get("send_enabled") == "1",
        "enrich_enabled": config.get("enrich_enabled") == "1",
        "config": config,
    }


@app.get("/api/admin/outbound/status")
async def admin_outbound_status(_admin: dict = Depends(_require_admin_user)):
    """Estado operacional do motor: fila, tetos do dia, caixas e warm-up."""
    return await outbound_engine.status()


@app.post("/api/admin/outbound/replied")
async def admin_outbound_mark_replied(
    contact_id: int, _admin: dict = Depends(_require_admin_user)
):
    """Marca um contacto como tendo respondido (trava a sequencia).

    A deteccao automatica de respostas exige o scope `gmail.readonly` (ver
    docs/OUTBOUND-DOMAIN-AND-MAILBOXES.md, secao 5). Sem ele, esta rota e' a
    forma de impedir que o passo 2 (oferta) vá para quem ja' respondeu.
    """
    if contact_id <= 0:
        raise HTTPException(status_code=400, detail="contact_id invalido")
    ok = await db_service.mark_outbound_contact_replied(contact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Contacto nao encontrado")
    return {"status": "ok", "contact_id": contact_id, "replied_at": _now_iso()}


@app.post("/api/admin/outbound/worker")
async def admin_outbound_worker(
    limit: int | None = None,
    _admin: dict = Depends(_require_admin_user),
):
    """Dispara um tick manual do worker (envio imediato, respeitando travas).

    Util para validar o pipeline por demanda sem esperar pelo loop do processo.
    Devolve {sent, skipped, failed, status}. `status='disabled'` se
    `send_enabled=0`; `status='quiet_hours'` fora da janela de envio.
    """
    return await outbound_engine.process_queue(limit=limit)


@app.get("/api/admin/outbound/batches")
async def admin_outbound_batches(
    limit: int = 10,
    _admin: dict = Depends(_require_admin_user),
):
    """Lotes recentes com contagem por estado (visibilidade da fila)."""
    svc = db_service._service
    return {
        "batches": await anyio.to_thread.run_sync(
            svc.list_outbound_batches_with_counts, limit
        )
    }


@app.get("/api/admin/outbound/messages")
async def admin_outbound_messages(
    batch_id: int,
    limit: int = 100,
    _admin: dict = Depends(_require_admin_user),
):
    """Mensagens de um lote: destinatario, estado, provider_id e erro."""
    svc = db_service._service
    return {
        "batch_id": batch_id,
        "messages": await anyio.to_thread.run_sync(
            svc.list_batch_messages, batch_id, limit
        ),
    }


@app.post("/api/admin/outbound/enrich/jobs")
async def admin_enrich_jobs_create(
    city: str,
    nicho: str = "general_contractors",
    limit: int = 200,
    _admin: dict = Depends(_require_admin_user),
):
    """Enfileira enriquecimento de e-mails para uma cidade (nao bloqueia).

    Grava jobs `pending`; o loop de background drena-os com retry/backoff.
    Devolve contadores imediatos — o progresso consulta-se em
    `GET /api/admin/outbound/enrich/jobs/status`.
    """
    if nicho not in outbound_templates.NICHES:
        raise HTTPException(status_code=400, detail="Nicho invalido")
    result = await enrichment_queue.enqueue_city(city, nicho, limit)
    logger.info(
        "[ENRICH-QUEUE] city=%s niche=%s limit=%s -> created=%s pending=%s",
        result.get("city"), nicho, limit,
        result.get("jobs_created"), result.get("pending_total"),
    )
    return result


@app.post("/api/admin/outbound/inbox/sync")
async def admin_outbound_inbox_sync(_admin: dict = Depends(_require_admin_user)):
    """Forca uma leitura da caixa (respostas/bounces) - uso manual."""
    return await inbox_sync.sync_inbox()


@app.get("/api/admin/outbound/health")
async def admin_outbound_health(_admin: dict = Depends(_require_admin_user)):
    """Ultimo snapshot de saude do motor + digest textual (sem enviar)."""
    return {
        "checks": control_tower.latest_health(),
        "digest": control_tower.build_digest(),
    }


@app.post("/api/admin/outbound/backup")
async def admin_outbound_backup_now(_admin: dict = Depends(_require_admin_user)):
    """Forca backup + teste de restauro (uso manual)."""
    result = await control_tower.backup_database()
    verify = (
        await control_tower.verify_latest_backup()
        if result.get("status") == "ok"
        else None
    )
    return {"backup": result, "verify": verify}


@app.get("/api/admin/outbound/enrich/jobs/status")
async def admin_enrich_jobs_status(
    city: str | None = None,
    _admin: dict = Depends(_require_admin_user),
):
    """Estado da fila de enriquecimento + total de contactos com e-mail."""
    return await enrichment_queue.stats(city)


@app.post("/api/admin/outbound/enrich/run")
async def admin_enrich_run_once(
    batch: int | None = None,
    _admin: dict = Depends(_require_admin_user),
):
    """Processa um punhado de jobs agora (util para testar sem esperar o loop)."""
    return await enrichment_queue.run_worker_once(batch or enrichment_queue.CLAIM_BATCH)


@app.post("/api/admin/outbound/preview")
async def admin_outbound_preview(
    payload: OutboundPreviewRequest,
    _admin: dict = Depends(_require_admin_user),
):
    """Gera dinamicamente a previa do e-mail para um nicho — com dados REAIS.

    Nao cria lote nem envia nada. Conta as oportunidades da cidade para o
    nicho, escolhe uma linha real da BD e devolve o e-mail ja preenchido
    (ingles americano), pronto a rever/editar no painel antes de aprovar.
    """
    city = (payload.city or "").strip().upper()
    available_cities = await db_service.get_available_outbound_cities()
    if city not in available_cities:
        raise HTTPException(status_code=400, detail="Cidade sem leads/contactos")

    niche = (payload.niche or "").strip() or outbound_templates.DEFAULT_NICHE
    if niche not in outbound_templates.NICHES:
        raise HTTPException(status_code=400, detail="Nicho invalido")

    categories = outbound_templates.niche_categories(niche)
    count = await db_service.count_qualified_contractors_in_city(city, categories)
    sample = await db_service.get_outbound_sample_lead(city, categories)
    contact = await db_service.get_outbound_sample_contact(city)

    preview = _build_outbound_preview(city, niche, count, sample, contact)
    preview.update({"city": city, "count": count})
    return preview


@app.post("/api/admin/outbound/simulate")
async def admin_outbound_simulate(
    payload: OutboundSimulateRequest,
    admin: dict = Depends(_require_admin_user),
):
    """Simulacao dry-run de um lote: NAO envia nem cria mensagens.

    Devolve o inventario de leads qualificados da cidade, o tamanho de lote
    efetivo, a estimativa de custo e o template editavel. Grava um lote em
    RASCUNHO (`dry_run=1`, status='previewed') so' para auditoria.
    """
    city = (payload.city or "").strip().upper()
    available_cities = await db_service.get_available_outbound_cities()
    if city not in available_cities:
        raise HTTPException(status_code=400, detail="Cidade sem leads/contactos")

    niche = (payload.niche or "").strip() or outbound_templates.DEFAULT_NICHE
    if niche not in outbound_templates.NICHES:
        raise HTTPException(status_code=400, detail="Nicho invalido")

    categories = outbound_templates.niche_categories(niche)
    config = await db_service.get_outbound_config(city)
    qualified = await db_service.count_qualified_contractors_in_city(city, categories)
    # Inventario != destinatarios: so' estes podem entrar na fila hoje.
    sendable_recipients = await db_service.count_outbound_recipients(city)

    try:
        configured = int(config.get("batch_size") or 0)
    except (TypeError, ValueError):
        configured = 0
    requested = payload.batch_size if (payload.batch_size and payload.batch_size > 0) else configured
    batch_size = max(0, min(requested, qualified))

    cost = _estimate_outbound_cost(batch_size)

    sample = await db_service.get_outbound_sample_lead(city, categories)
    contact = await db_service.get_outbound_sample_contact(city)
    preview = _build_outbound_preview(city, niche, qualified, sample, contact)

    # Reutiliza o rascunho do mesmo (city, filtros): antes cada clique criava
    # um lote novo e a BD acumulava lotes `previewed` sem uso.
    batch = await db_service.create_or_reuse_draft_batch(
        city=city,
        name=f"[DRY-RUN] {city} - {niche} - {batch_size} leads",
        filters_json=json.dumps(
            {"city": city, "niche": niche, "batch_size": batch_size, "dry_run": True}
        ),
        created_by=admin.get("id"),
        kind="email",
    )
    if batch and batch.get("id"):
        batch = await db_service.mark_outbound_batch_previewed(
            batch["id"], batch_size, cost["total_usd"]
        )

    max_spend = config.get("max_spend_per_batch_usd")
    try:
        over_budget = cost["total_usd"] > float(max_spend or 0)
    except (TypeError, ValueError):
        over_budget = False

    return {
        "city": city,
        "niche": niche,
        "qualified_available": qualified,
        "sendable_recipients": sendable_recipients,
        "batch_size": batch_size,
        "configured_batch_size": configured,
        "config": config,
        "cost_estimate": cost,
        "over_budget": over_budget,
        "max_spend_per_batch_usd": max_spend,
        "language": _OUTBOUND_LANGUAGE,
        "niche_label": preview["niche_label"],
        "template": preview["template"],
        "placeholders": preview["placeholders"],
        "preview": preview["preview"],
        "context": preview["context"],
        "sample_source": preview["sample_source"],
        "recipient_sample": preview["recipient_sample"],
        "opportunity_sample": preview["opportunity_sample"],
        "send_enabled": config.get("send_enabled") == "1",
        "batch": batch,
        "dry_run": True,
    }


@app.post("/api/admin/outbound/send")
async def admin_outbound_send(
    payload: OutboundSendRequest,
    _admin: dict = Depends(_require_admin_user),
):
    """Promove um lote a REAL e enfileira os destinatarios validos.

    Fail-closed: recusa (409) enquanto `send_enabled=0` (default). Com o envio
    ligado, exige um lote existente (404) e ainda nao iniciado (409), promove-o
    (`dry_run=0`, status='sending') e delega no motor o enriquecimento/validacao.
    O worker assincrono e' quem envia, respeitando tetos e quiet hours.
    """
    city = (payload.city or "").strip().upper()
    config = await db_service.get_outbound_config(city or None)
    if config.get("send_enabled") != "1":
        raise HTTPException(
            status_code=409,
            detail="Envio desligado (send_enabled=0). Ative o envio real no painel.",
        )

    batch = await db_service.get_outbound_batch(payload.batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Lote nao encontrado")
    if batch.get("status") in ("sending", "sent"):
        raise HTTPException(status_code=409, detail="Lote ja iniciado/enviado")
    if not batch.get("dry_run"):
        raise HTTPException(status_code=409, detail="Lote nao e' um rascunho dry-run")

    promoted = await db_service.start_outbound_batch(batch["id"])
    if not promoted:
        raise HTTPException(status_code=500, detail="Falha ao promover o lote")
    result = await outbound_engine.enqueue_batch(promoted, config=config)
    logger.info(
        "[OUTBOUND] Lote %s promovido: %s enfileirado(s), %s sem e-mail",
        batch["id"],
        result.get("queued"),
        result.get("no_email"),
    )
    return {
        "status": "queued",
        "batch_id": batch["id"],
        "batch": await db_service.get_outbound_batch(batch["id"]),
        **result,
    }


@app.post("/api/admin/outbound/import")
async def admin_outbound_import(
    payload: OutboundImportRequest,
    _admin: dict = Depends(_require_admin_user),
):
    """Importa leads B2B diretamente com e-mail e domínio preenchidos (Opção 1)."""
    if not payload.leads:
        raise HTTPException(status_code=400, detail="Lista de leads vazia")
    imported = 0
    failed = 0
    for item in payload.leads:
        if not item.email or not item.company_name or not item.city:
            failed += 1
            continue
        res = await db_service.import_b2b_lead(
            email=item.email,
            company_name=item.company_name,
            city=item.city,
            category=item.category or "General Contractors",
            contact_name=item.contact_name,
            domain=item.domain,
            state=item.state,
        )
        if res:
            imported += 1
        else:
            failed += 1
    return {
        "status": "ok",
        "imported": imported,
        "failed": failed,
        "total": len(payload.leads),
    }


@app.get("/api/admin/planner")
async def admin_planner(
    day: str | None = None,
    _admin: dict = Depends(_require_admin_user),
):
    """Alert Planner: telemetria do orçamento diário de alertas.

    Cruza `alert_usage` (consumo por utilizador/categoria, teto
    `PUSH_DAILY_LIMIT`) com as notificações de excedente (`type='digest'`,
    que NÃO contam para o teto). `day` em UTC (YYYY-MM-DD); default = hoje.
    """
    return await db_service.admin_get_alert_planner_metrics(day)


# ------------------------------------------------- Fase 3: credit ledger

@app.get("/api/admin/credit-ledger")
async def admin_credit_ledger(
    user_id: int,
    limit: int = 100,
    offset: int = 0,
    _admin: dict = Depends(_require_admin_user),
):
    """Fase 3: ledger de créditos de um utilizador.

    Lista eventos append-only (grant_daily, grant_plan, consume_reveal,
    refund_reveal, searchbug_cost, stripe_payment) com saldo derivado.
    """
    ledger = await db_service.get_credit_ledger(user_id, limit, offset)
    balance = await db_service.get_credit_balance(user_id)
    return {"user_id": user_id, "ledger": ledger, "balance": balance}


@app.get("/api/admin/credit-balance")
async def admin_credit_balance(
    user_id: int,
    _admin: dict = Depends(_require_admin_user),
):
    """Fase 3: saldo de créditos derivado do ledger."""
    balance = await db_service.get_credit_balance(user_id)
    return {"user_id": user_id, **balance}


@app.post("/api/admin/credit-backfill")
async def admin_credit_backfill(_admin: dict = Depends(_require_admin_user)):
    """Fase 3: backfill completo do ledger a partir do estado atual.

    Reconstrói grant_daily, grant_plan, consume_reveal, refund_reveal,
    searchbug_cost e stripe_payment em ordem cronológica.
    """
    result = await db_service.backfill_credit_ledger()
    return result


@app.post("/api/admin/credit-reconcile")
async def admin_credit_reconcile(
    user_id: int = 0,
    _admin: dict = Depends(_require_admin_user),
):
    """Fase 3: reconciliação de créditos.

    Verifica discrepâncias entre ledger e estado real:
    - saldo do ledger vs quota diária
    - ghost charges Searchbug vs pagamentos Stripe
    - quota diária excedida
    """
    uid = user_id if user_id > 0 else None
    result = await db_service.reconcile_credits(uid)
    return result


@app.post("/api/admin/normalize-addresses")
def admin_normalize_addresses(
    apply: bool = False,
    merge_duplicates: bool = False,
    limit: int = 0,
    _ok: bool = Depends(_require_admin),
):
    """Normaliza `leads.address` e funde prédios duplicados.

    Só faz sentido correr DENTRO do servidor: a base de produção é um ficheiro
    SQLite num volume do Railway, e a migração tem de operar sobre esse
    ficheiro — corrê-la a partir de uma máquina externa não a tocaria.

    `apply` é false por omissão: o default é dry-run, que só relata o que faria.
    `apply=true` escreve (irreversível sem o backup) e `merge_duplicates=true`
    apaga linhas, exigindo `apply=true`.
    """
    from backend.scripts import normalize_addresses as mig

    summary = mig.run(
        apply=apply,
        merge_duplicates=merge_duplicates,
        limit=limit,
        log=lambda *a, **k: logger.info("normalize_addresses: %s", " ".join(str(x) for x in a)),
    )
    # `run()` ja nao devolve None (ver o return do apply em normalize_addresses),
    # mas a rota nao deve rebentar com 500 se isso voltar a acontecer: a
    # migracao ja pode ter aplicado e commitado quando este ponto e alcancado,
    # e um 500 faz o cliente (e o operador) achar que a escrita falhou.
    if summary is None:
        logger.error("normalize_addresses: run() devolveu None; a migração pode ter aplicado.")
        raise HTTPException(
            status_code=500,
            detail="migration_returned_no_summary",
        )
    if not summary.get("ok"):
        # dry-run sem --apply é um erro de uso, não uma falha do servidor.
        raise HTTPException(status_code=400, detail=summary.get("error", "migration_failed"))
    return summary


@app.post("/api/admin/purge-city")
def admin_purge_city(
    city: str,
    apply: bool = False,
    _ok: bool = Depends(_require_admin),
):
    """Apaga os leads de uma cidade que deixou de ser servida (Norfolk).

    A fonte de Norfolk e um cadastro fiscal de predios: nunca passou o filtro de
    qualidade, mas as linhas ficaram na base e `/api/metrics/public` anunciava
    `cities_count: 5`. A rota da acesso ao volume do Railway, que uma execucao
    remota nao alcancaria.

    Dry-run por omissao. So apaga uma cidade da allow-list do script e nunca toca
    em linhas com valor comercial (reserva/conversao/reveal), que ficam intactas.
    """
    from backend.scripts import purge_city as purge

    try:
        summary = purge.run(
            city,
            apply=apply,
            log=lambda *a, **k: logger.info("purge_city: %s", " ".join(str(x) for x in a)),
        )
    except ValueError as e:
        # cidade fora da allow-list: erro de uso, nao falha do servidor.
        raise HTTPException(status_code=400, detail=str(e))
    if summary is None:
        logger.error("purge_city: run() devolveu None; a limpeza pode ter aplicado.")
        raise HTTPException(status_code=500, detail="purge_returned_no_summary")
    if not summary.get("ok"):
        raise HTTPException(status_code=400, detail=summary.get("error", "purge_failed"))
    return summary


@app.get("/api/admin/alerts")
async def admin_alerts(limit: int = 50, _admin: dict = Depends(_require_admin_user)):
    """Alertas de auditoria (Dead Man's Switch), incluindo reconhecidos."""
    alerts = await db_service.get_recent_system_alerts(limit)
    return {"alerts": alerts, "count": len(alerts)}


# ============================================================
# DLQ (Dead Letter Queue) Helpers
# ============================================================
DLQ_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "dlq")

def _ensure_dlq_dir() -> None:
    os.makedirs(DLQ_DIR, exist_ok=True)

def _dlq_save(run_id: str, city: str, leads: list, error: str) -> str:
    """Salva batch falho no DLQ para reprocessamento posterior."""
    _ensure_dlq_dir()
    filename = f"{run_id}_{city}_{utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    path = os.path.join(DLQ_DIR, filename)
    payload = {
        "run_id": run_id,
        "city": city,
        "leads": leads,
        "error": error,
        "saved_at": utcnow().isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.warning(f"DLQ: {city} salvo em {filename} ({len(leads)} leads)")
    return path

async def _dlq_reprocess(run_id: str) -> int:
    """Reprocessa arquivos DLQ pendentes. Retorna qtd de leads reinseridos."""
    _ensure_dlq_dir()
    if not os.path.exists(DLQ_DIR):
        return 0
    reprocessed = 0
    for filename in os.listdir(DLQ_DIR):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(DLQ_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            leads = payload.get("leads", [])
            if not leads:
                os.remove(path)
                continue
            # Tenta reinserir
            inserted = 0
            for raw_lead in leads:
                enriched = EnrichedLead(
                    external_id=raw_lead.get("external_id"),
                    source_type=SourceType(raw_lead.get("source_type")) if raw_lead.get("source_type") else SourceType.SERVICE_311,
                    address=raw_lead.get("address"),
                    city=raw_lead.get("city"),
                    state=raw_lead.get("state"),
                    zip_code=raw_lead.get("zip_code"),
                    lat=raw_lead.get("lat"),
                    lng=raw_lead.get("lng"),
                    county=None,
                    issue_category=raw_lead.get("issue_category"),
                    issue_description=raw_lead.get("issue_description"),
                    urgency_level=socrata_scraper._infer_urgency(raw_lead.get("issue_description", "")),
                    owner_name=None,
                    owner_phone=None,
                    owner_email=None,
                    owner_status=None,
                    date_reported=raw_lead.get("created_at"),
                    image_url=None,
                    source_url=None,
                    case_title=raw_lead.get("case_title"),
                    subject=raw_lead.get("subject"),
                    reason=raw_lead.get("reason"),
                    type=raw_lead.get("type"),
                    queue=raw_lead.get("queue"),
                    department=raw_lead.get("department"),
                    closure_reason=raw_lead.get("closure_reason"),
                    case_status=raw_lead.get("case_status"),
                    on_time=raw_lead.get("on_time"),
                    sla_target_dt=raw_lead.get("sla_target_dt"),
                    closed_dt=raw_lead.get("closed_dt"),
                    submitted_photo=raw_lead.get("submitted_photo"),
                    closed_photo=raw_lead.get("closed_photo"),
                    source=raw_lead.get("source"),
                    neighborhood=raw_lead.get("neighborhood"),
                    ward=raw_lead.get("ward"),
                    precinct=raw_lead.get("precinct"),
                    descriptor=raw_lead.get("descriptor"),
                    resolution_description=raw_lead.get("resolution_description"),
                    resolution_action_updated_date=raw_lead.get("resolution_action_updated_date"),
                    bbl=raw_lead.get("bbl"),
                )
                new_lead = await db_service.insert_lead_new(enriched)
                if new_lead:
                    inserted += 1
                    # Enriquecimento
                    try:
                        enrich_result = await owner_enrichment.enrich(
                            raw_lead.get("address", ""),
                            raw_lead.get("city", ""),
                            bbl=raw_lead.get("bbl"),
                        )
                        owner_name_val = (enrich_result or {}).get("owner_name")
                        if owner_name_val:
                            await db_service.update_owner(new_lead["id"], owner_name_val)
                    except Exception:
                        pass
            if inserted > 0:
                logger.info(f"DLQ reprocessado: {filename} -> {inserted} leads reinseridos")
                reprocessed += inserted
            os.remove(path)
        except Exception as e:
            logger.error(f"Erro ao reprocessar DLQ {filename}: {e}")
    return reprocessed


# ============================================================
# Webhook Alert Helper
# ============================================================
async def _send_scraper_webhook(run_id: str, city_results: dict, dlq_reprocessed: int, inserted: int, total_raw: int, hours_override: int = None, notified: int = None) -> bool:
    """Envia relatório consolidado do scraper para webhook configurado (Telegram/Slack/Email).

    Retorna True se enviado com sucesso, False caso contrário.
    """
    webhook_url = settings.SCRAPER_WEBHOOK_URL
    if not webhook_url:
        logger.debug("SCRAPER_WEBHOOK_URL não configurado — pulando envio de webhook")
        return False

    # Monta resumo por cidade
    city_lines = []
    anomalies = []
    circuit_breakers = []

    for city, result in city_results.items():
        if result.get("skipped"):
            city_lines.append(f"  {city}: ⏭️ PULADO (circuit breaker aberto até {result.get('error', 'N/A')})")
            circuit_breakers.append(city)
        elif result.get("error"):
            city_lines.append(f"  {city}: [ERRO] ERRO — {result['error'][:100]}")
        else:
            count = len(result.get("leads", []))
            city_lines.append(f"  {city}: {count} leads {'[OK]' if count > 0 else '🔴 ZERADO'}")
            if count == 0:
                anomalies.append(city)

    # Verifica anomalias (cidade ativa zerou 2x+)
    anomaly_lines = []
    for city in anomalies:
        health = await db_service.get_city_health(city)
        anomaly_count = health.get("anomaly_counter", 0)
        if anomaly_count >= 2:
            anomaly_lines.append(f"[AVISO]️ **ANOMALIA**: {city} zerou {anomaly_count} execuções consecutivas!")
        elif anomaly_count == 1:
            anomaly_lines.append(f"⚡ Atenção: {city} zerou 1 execução (monitorando)")

    # Circuit breakers ativos
    cb_lines = []
    if circuit_breakers:
        cb_lines.append("🔴 **Circuit Breakers Ativos**:")
        for cb in circuit_breakers:
            health = await db_service.get_city_health(cb)
            open_until = health.get("circuit_open_until", "desconhecido")
            cb_lines.append(f"  {cb}: aberto até {open_until}")

    # Monta mensagem
    hours_info = f" (janela: {hours_override}h)" if hours_override else ""
    trigger = "scheduler" if "scheduler" in run_id else "manual"

    lines = [
        f"📊 **Scraper Run `{run_id}`** {hours_info}",
        f"🕐 {utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC | Trigger: {trigger}",
        "",
        f"📥 **Total bruto**: {total_raw} | [OK] **Inseridos**: {inserted} | 🔄 **DLQ reprocessado**: {dlq_reprocessed}",
    ]
    if notified is not None:
        lines.append(f"🔔 **Notificações criadas**: {notified}")
    if inserted > 0 and notified == 0:
        lines.insert(0, "🚨🚨 **BLOQUEIO DE NOTIFICAÇÕES: leads inseridos, fan-out = 0** 🚨🚨")
    lines.extend([
        "",
        "🏙️ **Por Cidade**:",
        *city_lines,
    ])

    if anomaly_lines:
        lines.extend(["", "🚨 **Anomalias Detectadas**:", *anomaly_lines])

    if cb_lines:
        lines.extend(["", *cb_lines])

    message = "\n".join(lines)

    # Envia webhook (formato genérico JSON - compatível com Telegram/Slack/Discord/n8n)
    payload = {
        "text": message,
        "parse_mode": "Markdown",
        "run_id": run_id,
        "inserted": inserted,
        "total_raw": total_raw,
        "dlq_reprocessed": dlq_reprocessed,
        "notified": notified,
        "anomalies": anomaly_lines,
        "circuit_breakers": circuit_breakers,
        "city_results": city_results,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.info(f"Webhook enviado com sucesso para {webhook_url[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Falha ao enviar webhook: {e}")
        return False


async def _scrape_worker(run_id: str, max_cities: int = 8, hours_override: int = None):
    """Executa o scrape nacional (worker em background) com Circuit Breaker, DLQ e City Health."""
    state = _scrape_runs[run_id]
    try:
        logger.info(f"Iniciando scraper nacional 311... [run {run_id}]")

        # 1. Reprocessa DLQ pendente antes de buscar novos
        dlq_reprocessed = await _dlq_reprocess(run_id)
        if dlq_reprocessed:
            logger.info(f"DLQ: {dlq_reprocessed} leads reprocessados no início do run")

        # 2. Carrega city_health para circuit breaker
        city_health = await db_service.get_all_city_health()

        # 3. Define cidades-alvo (base + dinâmicas se max_cities permitir)
        base_cities = [
            {"domain": "data.cityofnewyork.us", "dataset": "erm2-nwe9", "city": "NYC", "state": "NY", "hours": 96, "limit": 5000, "fields": ["unique_key", "created_date", "closed_date", "due_date", "complaint_type", "descriptor", "incident_address", "street_name", "intersection_street_1", "cross_street_1", "incident_zip", "latitude", "longitude", "status", "agency_name", "borough", "bbl", "community_board", "council_district", "police_precinct", "resolution_description", "open_data_channel_type"]},
            {"domain": "data.cityofnewyork.us", "dataset": "wvxf-dwi5", "city": "NYC", "state": "NY", "hours": 120, "type": "hpd_violations", "fields": ["violationid", "buildingid", "inspectiondate", "approveddate", "housenumber", "lowhousenumber", "highhousenumber", "streetname", "boro", "zip", "apartment", "latitude", "longitude", "novtype", "novdescription", "violationstatus", "currentstatus", "novissueddate", "communityboard", "councildistrict", "bbl", "block", "lot"]},  # HPD Housing Maintenance Code Violations
            {"domain": "data.cityofchicago.org", "dataset": "v6vf-nfxy", "city": "Chicago", "state": "IL", "hours": 48, "fields": ["sr_number", "created_date", "sr_type", "street_address", "zip_code", "latitude", "longitude", "status"]},  # id= sr_number
            # Chicago Building Permits: fonte NOVA (medido: 2.817 registos por
            # janela de 30 dias, com oficio classificado a partir de
            # `work_description` — 1.114 electricos, 214 telhados, 83
            # canalizacoes, 233 roedores, 199 portas/Janelas). E' a unica fonte
            # de Chicago que nao seja 311 e traz obra a serio (remodelacao,
            # substituicao electrica, telhado) — que e' o que o contractor
            # consegue fechar.
            {"domain": "data.cityofchicago.org", "dataset": "ydr8-5enu", "city": "Chicago", "state": "IL", "hours": 720, "type": "chi_permits", "limit": 5000, "fields": ["id", "issue_date", "work_description", "permit_type", "permit_status", "street_number", "street_name", "latitude", "longitude", "community_area", "ward", "application_start_date"]},
            {"domain": "www.dallasopendata.com", "dataset": "d7e7-envw", "city": "Dallas", "state": "TX", "hours": 48, "fields": ["service_request_number", "created_date", "service_request_type", "address", "lat_location", "status"]},
        ]

        # Aplica hours_override se fornecido (ex: cron noturno com hours=120)
        for entry in base_cities:
            if hours_override:
                entry["hours"] = hours_override

        # Boston (CKAN) - mantém hours=72 fixo
        boston_entry = {"city": "Boston", "state": "MA", "hours": 72}
        if hours_override:
            boston_entry["hours"] = hours_override

        # NYC DOB Violations + Permits
        dob_violations_entry = {"city": "NYC", "state": "NY", "hours": hours_override or 48, "type": "dob_violations"}
        dob_permits_entry = {"city": "NYC", "state": "NY", "hours": hours_override or 48, "type": "dob_permits"}

        all_entries = base_cities + [boston_entry, dob_violations_entry, dob_permits_entry]

        # 4. Executa fetch por cidade com Circuit Breaker isolado
        all_raw = []
        # P0-A: watermarks so' sao aplicados DEPOIS dos inserts; se o run cair a
        # meio, o proximo volta a buscar a mesma janela (idempotente).
        pending_watermarks: dict[str, str] = {}
        city_results = {}  # {city: {"leads": [...], "error": None/str, "skipped": bool}}
        city_ok: dict[str, int] = {}   # fontes que responderam por cidade
        city_err: dict[str, list] = {} # fontes que falharam por cidade

        for entry in all_entries:
            city = entry["city"]
            health = city_health.get(city, {})
            _failure_count = health.get("failure_count", 0)
            circuit_open_until = health.get("circuit_open_until")

            # Circuit Breaker: pula cidade se circuit breaker aberto
            if circuit_open_until and utcnow().isoformat() < circuit_open_until:
                logger.warning(f"Circuit Breaker ATIVO para {city} até {circuit_open_until} — pulando")
                # Nao sobrescrever leads ja obtidos por outra fonte da cidade.
                _slot = city_results.setdefault(
                    city, {"leads": [], "error": None, "skipped": False}
                )
                if not _slot["leads"]:
                    _slot["skipped"] = True
                    _slot["error"] = "circuit_breaker_open"
                continue

            try:
                leads = []

                if entry.get("type") == "dob_violations":
                    # NYC DOB Violations
                    import backend.models.schemas as _sch
                    from backend.scrapers.socrata_311 import socrata_scraper as _s
                    domain = "data.cityofnewyork.us"
                    dataset = "3h2n-5cm9"
                    boro_map = {"1": "MANHATTAN", "2": "BRONX", "3": "BROOKLYN", "4": "QUEENS", "5": "STATEN ISLAND"}
                    keywords_or = " OR ".join([f"lower(description) like '%{kw.lower()}%'" for kw in settings.SCRAPER_KEYWORDS])
                    where = f"(disposition_date IS NULL OR disposition_date = '') AND ({keywords_or})"
                    logger.info(f"DOB Violations: fetching from {domain}/{dataset}")
                    rows = await _s._fetch_all_pages(
                        domain=domain, dataset=dataset,
                        select="violation_number, issue_date, house_number, street, boro, block, lot, bin, description, violation_type, violation_category, ecb_number, disposition_date, disposition_comments",
                        where=where, order="issue_date DESC",
                        page_size=5000, max_pages=10, date_col="issue_date",
                    )
                    logger.info(
                        f"DOB Violations: got {len(rows)} raw rows from Socrata "
                        f"({_s.last_meta})"
                    )
                    out = []
                    bbl_by_external: dict = {}
                    for row in rows:
                        try:
                            number = str(row.get("violation_number") or "").strip() or str(row.get("ecb_number") or "").strip()
                            if not number:
                                continue
                            desc = str(row.get("description") or "").strip()
                            if not desc:
                                continue
                            house = str(row.get("house_number") or "").strip()
                            street = str(row.get("street") or "").strip()
                            boro = boro_map.get(str(row.get("boro") or "").strip(), str(row.get("boro") or "").strip())
                            addr = f"{house} {street}".strip()
                            # B3: BBL a partir de boro/block/lot (o dataset nao traz lat/lng).
                            bbl = geo_lookup.compose_bbl(
                                row.get("boro"), row.get("block"), row.get("lot")
                            )
                            issue = row.get("issue_date")
                            created = None
                            try:
                                created = datetime.strptime(str(issue).strip(), "%Y%m%d")
                            except Exception:
                                try:
                                    created = datetime.fromisoformat(str(issue).replace("Z", "+00:00").replace("+00:00:00", "+00:00"))
                                except Exception:
                                    pass
                            if created is None or not addr:
                                continue
                            out.append(_sch.RawLead311(
                                external_id=number,
                                address=f"{addr}, {boro}, NY" if addr and boro else ("NYC, NY" if not addr else f"{addr}, NYC, NY"),
                                city="NYC", state="NY",
                                issue_description=desc,
                                created_at=created,
                                issue_category=_s._infer_category(desc),
                                source_type="dob_violation",
                                case_title=desc,
                                descriptor=row.get("violation_type") or None,
                                department="DOB",
                                case_status="Open",
                                source=f"{domain}/{dataset}",
                                neighborhood=boro or None,
                                resolution_description=row.get("disposition_comments") or None,
                                bbl=bbl,
                            ))
                            if bbl:
                                bbl_by_external[number] = bbl
                        except Exception as e:
                            logger.warning(f"DOB Violations row error: {e}")
                            continue

                    # B3: coordenadas via BBL -> PLUTO (custo zero, cache local).
                    if bbl_by_external:
                        try:
                            coords = await geo_lookup.resolve_bbl_coords(
                                list(set(bbl_by_external.values()))
                            )
                            filled = 0
                            for lead in out:
                                bbl = bbl_by_external.get(lead.external_id)
                                coord = coords.get(bbl) if bbl else None
                                if coord:
                                    lead.lat, lead.lng = coord
                                    filled += 1
                            logger.info(
                                "DOB Violations GEO: %s/%s lead(s) com coordenadas via PLUTO",
                                filled, len(out),
                            )
                        except Exception as e:
                            logger.warning("DOB Violations GEO falhou: %s", e)
                    leads = out

                elif entry.get("type") == "dob_permits":
                    # NYC DOB Permits
                    import backend.models.schemas as _sch
                    from backend.scrapers.socrata_311 import socrata_scraper as _s
                    domain = "data.cityofnewyork.us"
                    dataset = "rbx6-tga4"
                    logger.info(f"DOB Permits: fetching from {domain}/{dataset}")
                    try:
                        rows = await _s._fetch_all_pages(
                            domain=domain, dataset=dataset,
                            select="job_filing_number, work_permit, house_no, street_name, borough, zip_code, latitude, longitude, approved_date, issued_date, job_description, work_type, permit_status, applicant_first_name, applicant_last_name, applicant_business_name, owner_name, owner_business_name, nta, council_district",
                            where=None, order="approved_date DESC",
                            page_size=5000, max_pages=6, date_col="approved_date",
                        )
                        logger.info(
                            f"DOB Permits: got {len(rows)} raw rows from Socrata "
                            f"({_s.last_meta})"
                        )
                    except Exception as e:
                        logger.error(f"DOB Permits: fetch failed: {e}")
                        # Propagar: engolir aqui registava NYC como sucesso com 0
                        # leads de DOB, mascarando a fonte como morta.
                        raise

                    def _norm(s):
                        return "".join((s or "").lower().split())

                    core_kws = ["roof", "roofing", "plumbing", "water", "paint", "facade", "boiler", "heating", "sprinkler", "sewer", "electrical", "leak", "mold", "chimney", "siding", "foundation"]

                    out = []
                    total_fetched = len(rows)
                    filtered_status = 0
                    filtered_date = 0
                    filtered_kws = 0
                    filtered_business = 0
                    filtered_owner = 0
                    filtered_other = 0

                    for row in rows:
                        try:
                            if str(row.get("permit_status") or "") != "Permit Issued":
                                filtered_status += 1
                                continue
                            app_date = row.get("approved_date") or row.get("issued_date")
                            if app_date:
                                try:
                                    ad = datetime.fromisoformat(str(app_date).replace("Z", "+00:00").replace("+00:00:00", "+00:00"))
                                    if ad < datetime.now() - timedelta(days=60):
                                        filtered_date += 1
                                        continue
                                except Exception:
                                    pass
                            desc = str(row.get("job_description") or "").strip().lower()
                            if not any(kw in desc for kw in core_kws):
                                filtered_kws += 1
                                continue

                            # RELAXED: applicant_business_name filter
                            # Original blocked ALL rows with applicant_business_name != ("-", "none", "n/a")
                            # Now: only block if it's clearly a large corporation (not individual contractor)
                            a_b = _norm(row.get("applicant_business_name"))
                            if a_b and a_b not in ("-", "none", "n/a", ""):
                                # Check if it looks like an individual contractor (name-like) vs corporation
                                # Allow if business name contains person-name patterns
                                name_indicators = ["inc", "llc", "corp", "corporation", "ltd", "enterprises", "contracting", "construction", "building", "home improvement"]
                                if not any(ind in a_b for ind in name_indicators):
                                    # Looks like a real person's name or small contractor - ALLOW
                                    pass
                                else:
                                    filtered_business += 1
                                    continue

                            # RELAXED: owner/applicant name matching
                            # Original required exact match of last name (and optionally first name)
                            # Now: allow if either owner_name or applicant name has reasonable overlap
                            a_f, a_l = _norm(row.get("applicant_first_name")), _norm(row.get("applicant_last_name"))
                            owner = _norm(row.get("owner_name"))
                            if not owner and not a_l:
                                filtered_owner += 1
                                continue
                            # If we have both owner and applicant names, check for reasonable overlap
                            if owner and a_l:
                                # Allow if last name matches OR first name matches OR owner contains applicant name parts
                                name_match = (
                                    a_l in owner or
                                    (a_f and a_f in owner) or
                                    owner in a_l or  # owner name might be shorter
                                    any(part in owner for part in [a_f, a_l] if part)
                                )
                                if not name_match:
                                    filtered_owner += 1
                                    continue
                            elif not owner and a_l:
                                # No owner name but have applicant last name - allow (common in permits)
                                pass
                            elif owner and not a_l:
                                # Have owner name but no applicant last name - allow
                                pass

                            job_no = str(row.get("job_filing_number") or "").strip()
                            if not job_no:
                                filtered_other += 1
                                continue
                            if "not yet issued" in str(row.get("work_permit") or "").lower():
                                filtered_other += 1
                                continue
                            house = " ".join(str(row.get("house_no") or "").split())
                            street = " ".join(str(row.get("street_name") or "").split())
                            if not (house and street):
                                filtered_other += 1
                                continue
                            boro = str(row.get("borough") or "").strip()
                            zipc = str(row.get("zip_code") or "").strip() or None
                            wp = str(row.get("work_permit") or "").strip()
                            try:
                                created = datetime.fromisoformat(str(app_date).replace("Z", "+00:00").replace("+00:00:00", "+00:00"))
                            except Exception:
                                created = datetime.now()
                            out.append(_sch.RawLead311(
                                external_id=f"{job_no}~{wp}" if wp else job_no,
                                address=f"{house} {street}, {boro}, NY {zipc}" if zipc else f"{house} {street}, {boro}, NY",
                                city="NYC", state="NY",
                                zip_code=zipc,
                                issue_description=desc,
                                created_at=created,
                                lat=float(row["latitude"]) if row.get("latitude") is not None else None,
                                lng=float(row["longitude"]) if row.get("longitude") is not None else None,
                                issue_category=_s._infer_category(desc),
                                source_type="permit",
                                case_title=desc,
                                type=row.get("work_type") or None,
                                department="DOB",
                                case_status="Approved",
                                source=f"{domain}/{dataset}",
                                neighborhood=row.get("nta") or None,
                                ward=str(row.get("council_district")) if row.get("council_district") is not None else None,
                                closed_dt=row.get("issued_date") or None,
                            ))
                        except Exception as e:
                            logger.warning(f"DOB Permits row error: {e}")
                            filtered_other += 1
                            continue

                    # DETAILED LOGGING for debugging
                    logger.info(
                        f"DOB Permits FILTER STATS: fetched={total_fetched}, "
                        f"status={filtered_status}, date={filtered_date}, kws={filtered_kws}, "
                        f"business={filtered_business}, owner={filtered_owner}, other={filtered_other}, "
                        f"PASSED={len(out)}"
                    )
                    leads = out

                elif city != "Boston":
                    # Socrata 311 genérico (NYC, Chicago, Dallas, etc.)
                    fields = entry["fields"]
                    city_hours = entry["hours"]
                    # Fonte que nao e 311 (ex: HPD violations) precisa de source_type
                    # proprio, senao cai em "311" e some do filtro de obrigacao legal.
                    src_type = _SOURCE_TYPE_BY_ENTRY.get(entry.get("type"))
                    wm_key = f"{entry['domain']}/{entry['dataset']}"
                    wm = await db_service.get_scraper_watermark(wm_key)
                    leads = await socrata_scraper.fetch_from_dataset(
                        entry["domain"], entry["dataset"], entry["city"], entry["state"],
                        field_names=fields, hours=city_hours, limit=entry.get("limit", 2000),
                        source_type=src_type, watermark=wm, overlap_hours=6, max_pages=10,
                    )
                    meta = dict(socrata_scraper.last_meta or {})
                    logger.info(
                        "[P0-A] %s: %s linhas, %s pagina(s), truncado=%s, wm=%s",
                        wm_key, meta.get("rows"), meta.get("pages"),
                        meta.get("truncated"), wm,
                    )
                    if not meta.get("truncated") and meta.get("max_date"):
                        pending_watermarks[wm_key] = meta["max_date"]

                # Boston (CKAN) - caso especial
                if city == "Boston":
                    from backend.scrapers.socrata_311 import socrata_scraper as _s
                    try:
                        import httpx as _h

                        resource_id = "1a0b420d-99f1-4887-9851-990b2a5a6e17"
                        wm_key = f"data.boston.gov/{resource_id}"
                        wm = await db_service.get_scraper_watermark(wm_key)
                        if wm:
                            try:
                                since = datetime.fromisoformat(str(wm)[:10]) - timedelta(hours=6)
                            except (ValueError, TypeError):
                                since = datetime.now() - timedelta(hours=entry["hours"])
                        else:
                            since = datetime.now() - timedelta(hours=entry["hours"])

                        def _parse_open(value):
                            parsed = datetime.fromisoformat(
                                str(value).replace("Z", "+00:00").replace("T", " ")
                            )
                            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed

                        page_size = 5000
                        max_pages = 5
                        records = []
                        truncated = False
                        async with _h.AsyncClient(timeout=60) as client:
                            for page in range(max_pages):
                                resp = await client.get(
                                    "https://data.boston.gov/api/3/action/datastore_search",
                                    params={
                                        "resource_id": resource_id,
                                        "limit": page_size,
                                        "offset": page * page_size,
                                        "sort": "open_dt DESC",
                                    },
                                )
                                logger.info(
                                    "Boston CKAN: page %s HTTP %s, bytes=%s",
                                    page + 1, resp.status_code, len(resp.text),
                                )
                                data = resp.json()
                                if not data.get("success"):
                                    logger.warning(
                                        f"Boston CKAN: success=FALSE -> {str(data.get('error'))[:300]}"
                                    )
                                    records = []
                                    break
                                chunk = data["result"]["records"]
                                records.extend(chunk)
                                if len(chunk) < page_size:
                                    break
                                # Ordenado DESC: se a pagina ja' passou do `since`,
                                # nao vale a pena pedir mais.
                                try:
                                    oldest = _parse_open(chunk[-1].get("open_dt"))
                                    if oldest < since:
                                        break
                                except Exception:
                                    pass
                            else:
                                truncated = True

                        out = []
                        max_open = None
                        for rec in records:
                            od = rec.get("open_dt")
                            if not od:
                                continue
                            try:
                                odo = _parse_open(od)
                            except Exception:
                                continue
                            if odo < since:
                                continue
                            eid = str(rec.get("case_enquiry_id") or rec.get("_id") or "")
                            if not eid:
                                continue
                            address = rec.get("location") or rec.get("location_street_name") or "Boston, MA"
                            desc = rec.get("case_title") or rec.get("reason") or rec.get("type") or ""
                            raw_zip = str(rec.get("location_zipcode") or "").strip()
                            if raw_zip.isdigit() and len(raw_zip) == 4:
                                raw_zip = raw_zip.zfill(5)
                            import backend.models.schemas as _sch
                            out.append(_sch.RawLead311(
                                external_id=eid,
                                address=f"{address}, Boston, MA" if address else "Boston, MA",
                                city="Boston",
                                state="MA",
                                zip_code=raw_zip or None,
                                issue_description=desc,
                                created_at=odo,
                                lat=rec.get("latitude"),
                                lng=rec.get("longitude"),
                                issue_category=_s._infer_category(desc),
                                case_title=rec.get("case_title") or None,
                                subject=rec.get("subject") or None,
                                reason=rec.get("reason") or None,
                                type=rec.get("type") or None,
                                queue=rec.get("queue") or None,
                                department=rec.get("department") or None,
                                closure_reason=rec.get("closure_reason") or None,
                                case_status=rec.get("case_status") or None,
                                on_time=rec.get("on_time") or None,
                                sla_target_dt=rec.get("sla_target_dt") or None,
                                closed_dt=rec.get("closed_dt") or None,
                                source=rec.get("source") or None,
                                neighborhood=rec.get("neighborhood") or None,
                                ward=rec.get("ward") or None,
                                precinct=rec.get("precinct") or None,
                                resolution_description=rec.get("closure_reason") or None,
                            ))
                            if max_open is None or odo > max_open:
                                max_open = odo
                        leads = out
                        logger.info(
                            "[P0-A] Boston: %s registos, %s aceites, truncado=%s",
                            len(records), len(out), truncated,
                        )
                        if not truncated and max_open is not None:
                            pending_watermarks[wm_key] = max_open.date().isoformat()
                    except Exception as e:
                        logger.warning(f"Boston CKAN fetch error: {e}")
                        # Propagar: antes Boston ficava verde no city_health
                        # mesmo com a fonte CKAN em baixo.
                        raise

                # Sucesso desta fonte. A saúde da cidade e' decidida no fim do
                # loop: uma cidade tem varias entradas (NYC tem 4) e o erro de
                # uma nao pode apagar o resultado das outras nem marcar a cidade
                # como morta quando ela continua a devolver leads.
                _slot = city_results.setdefault(
                    city, {"leads": [], "error": None, "skipped": False}
                )
                _slot["leads"].extend(leads)
                _slot["skipped"] = False
                city_ok[city] = city_ok.get(city, 0) + 1
                all_raw.extend(leads)
                logger.info(f"{city}: {len(leads)} leads obtidos")

            except Exception as e:
                # Falha isolada: não derruba outras cidades
                logger.error(f"Erro ao buscar {city}: {e}", exc_info=True)
                _slot = city_results.setdefault(
                    city, {"leads": [], "error": None, "skipped": False}
                )
                _src = entry.get("type") or entry.get("dataset") or "fonte"
                city_err.setdefault(city, []).append(f"{_src}: {e}")
                city_ok[city] = city_ok.get(city, 0)

        # Saúde por cidade: so fica verde se pelo menos uma fonte respondeu.
        # Antes cada entrada marcava success/failure isoladamente, e um fetch que
        # devolvia [] por erro HTTP deixava a cidade verde com 0 leads.
        for city, _n_ok in city_ok.items():
            _errors = city_err.get(city)
            if _n_ok == 0 and _errors:
                await db_service.record_city_failure(city, _errors[0])
                city_results[city]["error"] = " | ".join(_errors)
            else:
                await db_service.record_city_success(city)
                await db_service.reset_anomaly_counter(city)
                if _errors:
                    # Respondeu em parte: verde, mas o erro viaja no webhook.
                    city_results[city]["error"] = "PARCIAL — " + " | ".join(_errors)
                    logger.warning(f"{city}: sucesso parcial, fontes com erro: {_errors}")

        logger.info(f"Total bruto 311 (todas cidades): {len(all_raw)}")

        # 5. Inserção com DLQ fallback
        inserted = 0
        newly_added: list[dict] = []
        # P0-B: historico por ocorrencia + reincidencia por imovel.
        history_batch: list[dict] = []
        history_lead_ids: set[int] = set()
        addr_to_id: dict[tuple[str, str], int] = {}

        for raw_lead in all_raw:
            enriched = EnrichedLead(
                external_id=raw_lead.external_id,
                source_type=SourceType(raw_lead.source_type) if raw_lead.source_type else SourceType.SERVICE_311,
                address=raw_lead.address,
                city=raw_lead.city,
                state=raw_lead.state,
                zip_code=raw_lead.zip_code,
                lat=raw_lead.lat,
                lng=raw_lead.lng,
                county=None,
                issue_category=raw_lead.issue_category,
                issue_description=raw_lead.issue_description,
                urgency_level=socrata_scraper._infer_urgency(raw_lead.issue_description),
                owner_name=None,
                owner_phone=None,
                owner_email=None,
                owner_status=None,
                date_reported=raw_lead.created_at,
                image_url=None,
                source_url=None,
                case_title=getattr(raw_lead, "case_title", None),
                subject=getattr(raw_lead, "subject", None),
                reason=getattr(raw_lead, "reason", None),
                type=getattr(raw_lead, "type", None),
                queue=getattr(raw_lead, "queue", None),
                department=getattr(raw_lead, "department", None),
                closure_reason=getattr(raw_lead, "closure_reason", None),
                case_status=getattr(raw_lead, "case_status", None),
                on_time=getattr(raw_lead, "on_time", None),
                sla_target_dt=getattr(raw_lead, "sla_target_dt", None),
                closed_dt=getattr(raw_lead, "closed_dt", None),
                submitted_photo=getattr(raw_lead, "submitted_photo", None),
                closed_photo=getattr(raw_lead, "closed_photo", None),
                source=getattr(raw_lead, "source", None),
                neighborhood=getattr(raw_lead, "neighborhood", None),
                ward=getattr(raw_lead, "ward", None),
                precinct=getattr(raw_lead, "precinct", None),
                descriptor=getattr(raw_lead, "descriptor", None),
                resolution_description=getattr(raw_lead, "resolution_description", None),
                resolution_action_updated_date=getattr(raw_lead, "resolution_action_updated_date", None),
                bbl=getattr(raw_lead, "bbl", None),
            )
            new_lead = await db_service.insert_lead_new(enriched)

            # P0-B: guarda a ocorrencia (mesmo quando a morada ja' existe e o
            # lead foi atualizado). O `lead_id` vem do insert novo ou da morada.
            lead_id = new_lead["id"] if new_lead else None
            if not lead_id:
                addr_key = ((raw_lead.address or "").upper(), raw_lead.city or "")
                lead_id = addr_to_id.get(addr_key)
                if not lead_id:
                    lead_id = await db_service.get_lead_id_by_address(
                        raw_lead.address, raw_lead.city
                    )
                    if lead_id:
                        addr_to_id[addr_key] = lead_id
            if lead_id:
                history_batch.append({
                    "lead_id": lead_id,
                    "external_id": raw_lead.external_id,
                    "case_title": getattr(raw_lead, "case_title", None),
                    "descriptor": getattr(raw_lead, "descriptor", None),
                    "subject": getattr(raw_lead, "subject", None),
                    "reason": getattr(raw_lead, "reason", None),
                    "case_status": getattr(raw_lead, "case_status", None),
                    "issue_category": getattr(
                        raw_lead.issue_category, "value", str(raw_lead.issue_category)
                    ),
                    "department": getattr(raw_lead, "department", None),
                    "opened_at": raw_lead.created_at.isoformat() if raw_lead.created_at else None,
                    "closed_at": getattr(raw_lead, "closed_dt", None),
                    "resolution_description": getattr(raw_lead, "resolution_description", None),
                    "closure_reason": getattr(raw_lead, "closure_reason", None),
                    "source": getattr(raw_lead, "source", None),
                    "source_url": None,
                })
                history_lead_ids.add(lead_id)
                if len(history_batch) >= 500:
                    await db_service.append_case_occurrences(history_batch)
                    history_batch.clear()

            if new_lead:
                inserted += 1
                newly_added.append(new_lead)
                # Enriquecimento automático APENAS em leads estritamente novos
                try:
                    enrich_result = await owner_enrichment.enrich(
                        raw_lead.address, raw_lead.city, bbl=getattr(raw_lead, "bbl", None)
                    )
                    owner_name_val = (enrich_result or {}).get("owner_name")
                    if owner_name_val:
                        await db_service.update_owner(new_lead["id"], owner_name_val)
                except Exception as e:
                    logger.warning(
                        f"[INGEST] Falha ao enriquecer owner do lead {new_lead.get('id')} "
                        f"(address={raw_lead.address!r}, city={raw_lead.city!r}, "
                        f"has_bbl={bool(getattr(raw_lead, 'bbl', None))}): {e}"
                    )

        # P0-B: flush do historico + recalculo da reincidencia dos leads tocados.
        if history_batch:
            await db_service.append_case_occurrences(history_batch)
        if history_lead_ids:
            refreshed = await db_service.refresh_lead_history(sorted(history_lead_ids))
            logger.info(
                "[P0-B] historico: %s leads com reincidencia recalculada",
                refreshed,
            )

        # P0-A: so' agora, com todos os inserts do run concluidos, os
        # watermarks avancam. Uma falha a meio nao salta a janela.
        if pending_watermarks:
            for wm_key, wm_date in pending_watermarks.items():
                await db_service.set_scraper_watermark(wm_key, wm_date)
            logger.info("[P0-A] watermarks aplicados: %s", pending_watermarks)

        # 6. Fan-out + Anomalia detection por categoria
        notified_total = 0
        audience_total = 0
        added_by_cat: dict = {}
        if inserted > 0:
            for nl in newly_added:
                cat = (nl.get("issue_category") or "Structure").strip()
                added_by_cat.setdefault(cat, []).append(nl)
            report = await alert_planner.plan_and_dispatch(newly_added)
            notified_total = int(report.created or 0)
            audience_total = int(report.audience or 0)

            # Dead Man's Switch: alerta só quando NÃO houver nenhum elegível
            # (cap diário atingido é saudável e não dispara).
            await notifier.guard_silent_fanout(
                inserted=inserted,
                notified=notified_total,
                audience=audience_total,
                candidates=int(report.candidates or 0),
                city_filtered=bool(report.city_filtered),
                context={
                    "run_id": run_id,
                    "inserted": inserted,
                    "notified": notified_total,
                    "audience": audience_total,
                    "candidates": int(report.candidates or 0),
                    "city_filtered": bool(report.city_filtered),
                    "categories": {c: len(v) for c, v in added_by_cat.items()},
                },
            )
            logger.info(
                f"Fan-out [run {run_id}]: {notified_total} notificação(ões) criada(s) "
                f"para {inserted} lead(s) em {len(added_by_cat)} categoria(s) "
                f"(audiência elegível: {audience_total})"
            )

        # 7. Anomalia: cidades ativas que zeraram leads
        for city, result in city_results.items():
            if not result["skipped"] and len(result["leads"]) == 0:
                anomaly_count = await db_service.increment_anomaly_counter(city)
                if anomaly_count >= 2:
                    logger.warning(f"ANOMALIA: {city} zerou {anomaly_count} execuções consecutivas")
            elif not result["skipped"] and len(result["leads"]) > 0:
                await db_service.reset_anomaly_counter(city)

        # 8. Envia webhook de alerta consolidado
        await _send_scraper_webhook(run_id, city_results, dlq_reprocessed, inserted, len(all_raw), hours_override, notified=notified_total)

        # Uma cidade que falhou por completo nao conta como coberta. O run
        # anterior reportava status="success" e cities_covered=4 com Chicago
        # morta ha ~29h: o verde do run escondia uma cidade que nao produzia
        # nada, e o verde chegava ate ao gate do GitHub Actions que so olha
        # para o status global. Passamos a contar so cidades que responderam
        # de facto, e a rebaixar o run quando alguma falha por completo.
        cities_ok = [
            c for c, r in city_results.items()
            if not r["skipped"] and not r["error"] and len(r["leads"]) > 0
        ]
        cities_degraded = [
            c for c, r in city_results.items()
            if r["error"] and not r["error"].startswith("PARCIAL")
        ]
        cities_skipped = [c for c, r in city_results.items() if r["skipped"]]
        cities_bad = sorted(set(cities_degraded) | set(cities_skipped))

        if cities_bad:
            logger.error(
                f"Scraper [run {run_id}] DEGRADADO: {len(cities_bad)}/{len(city_results)} "
                f"cidade(s) sem producao neste run: {', '.join(cities_bad)}. "
                f"O run e marcado 'partial', nao 'success'."
            )
            run_status = "partial"
            _nota = (
                f"311 multi-cidade com Circuit Breaker + DLQ + City Health + Webhook | "
                f"DEGRADADO: {', '.join(cities_bad)}"
            )
        else:
            run_status = "success"
            _nota = "311 multi-cidade com Circuit Breaker + DLQ + City Health + Webhook"

        logger.info(
            f"Scraper completo [run {run_id}]: {inserted} leads inseridos "
            f"({len(cities_ok)}/{len(city_results)} cidade(s) com producao)"
        )
        state.update(
            status=run_status, inserted=inserted,
            total_raw=len(all_raw), cities_covered=len(cities_ok),
            note=_nota,
            running=False, finished_at=utcnow().isoformat(),
        )
        await db_service.record_scrape_run(state)

    except Exception as e:
        logger.error(f"Erro no scraper [run {run_id}]: {e}", exc_info=True)
        state.update(status="error", error=str(e), running=False, finished_at=utcnow().isoformat())
        await db_service.record_scrape_run(state)


async def _run_scrape_guarded(
    run_id: str, max_cities: int = 8, hours_override: int = None
) -> None:
    """Executa `_scrape_worker` com timeout duro e auto-recuperação.

    Um run que não termina (fonte pendurada, deadlock, tarefa zombie) deixa o
    scheduler permanentemente em "já está a correr". Ao exceder
    `SCRAPER_MAX_HOURS`, cancelamos, marcamos `error`, gravamos um system_alert
    CRITICAL e disparamos a Control Tower (alerta vermelho imediato).
    """
    timeout_h = max(0.25, float(getattr(settings, "SCRAPER_MAX_HOURS", 3) or 3))
    try:
        await asyncio.wait_for(
            _scrape_worker(run_id, max_cities, hours_override=hours_override),
            timeout=timeout_h * 3600,
        )
    except asyncio.TimeoutError:
        state = _scrape_runs.get(run_id) or {
            "run_id": run_id,
            "trigger": "unknown",
            "started_at": utcnow().isoformat(),
            "inserted": 0,
            "total_raw": 0,
        }
        state.update(
            status="error",
            error=f"timeout após {timeout_h:g}h sem concluir",
            running=False,
            finished_at=utcnow().isoformat(),
        )
        _remember_scrape_run(state)
        message = (
            f"SCRAPER TIMEOUT: run {run_id} excedeu {timeout_h:g}h e foi "
            "cancelado. Scheduler libertado; verificar fonte/BD."
        )
        logger.critical(message)
        try:
            await db_service.record_scrape_run(state)
        except Exception as e:  # noqa: BLE001
            logger.error("Falha ao persistir run em timeout: %s", e)
        try:
            await db_service.record_system_alert(
                level="critical",
                code="SCRAPER_TIMEOUT",
                message=message,
                context={
                    "run_id": run_id,
                    "timeout_hours": timeout_h,
                    "inserted": state.get("inserted"),
                    "started_at": state.get("started_at"),
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Falha ao registar alerta de timeout: %s", e)
        try:
            # Reavalia a saúde já: o check de ingestão passa a fail (run error)
            # e a Control Tower envia o alerta vermelho imediato.
            await control_tower.run_health_checks()
        except Exception as e:  # noqa: BLE001
            logger.warning("Control Tower não conseguiu avaliar o timeout: %s", e)
    except asyncio.CancelledError:
        raise


# ------------------------------------------------------------------
# Scheduler interno — robustez no Railway (independe do GH Actions).
# Roda a varredura a cada SCRAPER_INTERVAL_HOURS horas, reutilizando
# a mesma fila de runs (_scrape_runs) do endpoint manual.
# ------------------------------------------------------------------
def _scheduled_scrape(max_cities: int = 8, hours_override: int = None):
    # Validação de secret do scheduler interno (fail-closed)
    if settings.CRON_SECRET:
        logger.debug("Scheduler: secret válido, prosseguindo")
    else:
        logger.warning("Scheduler: CRON_SECRET não configurado — execução permitida (modo desenvolvimento)")

    for run in _scrape_runs.values():
        if run.get("running"):
            logger.info("Scheduler: run do scraper já ativo, pulando")
            return
    run_id = uuid.uuid4().hex[:12]
    _remember_scrape_run({
        "run_id": run_id, "running": True,
        "started_at": utcnow().isoformat(),
        "inserted": 0, "total_raw": 0, "status": "running", "error": None,
        "trigger": "scheduler",
    })
    asyncio.create_task(_run_scrape_guarded(run_id, max_cities, hours_override=hours_override))
    logger.info(f"Scheduler: varredura disparada [run {run_id}]" + (f" com hours={hours_override}" if hours_override else ""))


async def _scheduler_loop():
    """Loop do scheduler interno: espera o intervalo e dispara a varredura.

    Executa varredura normal a cada SCRAPER_INTERVAL_HOURS horas.
    Executa varredura estendida (hours=120) às 02:00 UTC para catch-up noturno.
    """
    interval_seconds = max(300, settings.SCRAPER_INTERVAL_HOURS * 3600)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # Verifica se é hora da varredura noturna estendida (02:00 UTC)
            now_utc = utcnow()
            if now_utc.hour == 2 and now_utc.minute < (interval_seconds // 60):
                logger.info("Scheduler: disparando varredura noturna estendida (hours=120)")
                _scheduled_scrape(max_cities=12, hours_override=120)
            else:
                _scheduled_scrape(max_cities=8)
        except Exception as e:
            logger.error(f"Erro no scheduler interno: {e}", exc_info=True)


@contextlib.asynccontextmanager
async def _lifespan(app):
    _scheduler_task = None
    _watchdog_task = None
    _outbound_task = None
    _freshness_task = None

    # Fase 2: o writer de telemetria arranca com o processo. Sem isto o
    # buffer acumula em memoria ate limite e perde eventos sem nunca
    # persistir nada.
    await searchbug_metrics.start()
    await push_metrics.start()

    # Alert Planner: semeia o orçamento de alertas de hoje a partir dos alertas
    # new_lead já enviados (idempotente por dia). Impede que um deploy a meio
    # do dia atribua um orçamento extra a quem já recebeu os seus 6 alertas.
    try:
        seeded = await db_service.seed_alert_usage_from_notifications()
        if seeded:
            logger.info(f"Alert Planner: {seeded} linha(s) de orçamento semeada(s)")
    except Exception as e:
        logger.warning(f"Falha no seed do orçamento de alertas: {e}")

    # A2: limpeza de sessoes expiradas no arranque. O TTL e' aplicado em cada
    # validacao; isto so evita acumular linhas mortas na BD.
    try:
        pruned = await db_service.prune_expired_sessions()
        if pruned:
            logger.info("Sessoes expiradas removidas: %s", pruned)
    except Exception as e:
        logger.warning("Falha ao limpar sessoes expiradas: %s", e)

    # Fase E: runs do scraper presos em 'running' após restart/OOM. Sem isto
    # a linha ficava eternamente "em curso" no painel/status.
    try:
        stale_runs = await db_service.mark_stale_scraper_runs(180)
        if stale_runs:
            logger.warning("Runs do scraper presos em running fechados: %s", stale_runs)
    except Exception as e:
        logger.warning("Falha ao fechar runs presos do scraper: %s", e)

    # B1: higiene de dispositivos push (limite de 5). Corrige o estado legado
    # (utilizadores com 9 browsers) sem esperar por um novo subscribe.
    try:
        trimmed = await db_service.enforce_push_device_limit()
        if trimmed:
            logger.info("Push: %s dispositivo(s) desativado(s) (limite de 5)", trimmed)
    except Exception as e:
        logger.warning("Falha na higiene de dispositivos push: %s", e)

    # Validação de VAPID keys no startup
    if not settings.VAPID_PUBLIC_KEY or not settings.VAPID_PRIVATE_KEY:
        logger.critical("[ERRO] VAPID keys NÃO CONFIGURADAS — Push notifications DESABILITADAS!")
        if settings.SCRAPER_WEBHOOK_URL:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(settings.SCRAPER_WEBHOOK_URL, json={
                        "text": "🚨 **ALERTA CRÍTICO**: VAPID keys não configuradas no Railway/Vercel!\nPush notifications **DESABILITADAS** para todos usuários.\nConfigure `VAPID_PUBLIC_KEY` e `VAPID_PRIVATE_KEY` nas env vars.",
                        "parse_mode": "Markdown"
                    })
            except Exception as e:
                logger.error(f"Falha ao enviar alerta de VAPID keys ausentes: {e}")
    else:
        logger.info("[OK] VAPID keys configuradas — Push notifications ATIVAS")

    if settings.SCRAPER_SELF_SCHEDULED:
        _scheduler_task = asyncio.create_task(_scheduler_loop())
        logger.info(f"Scheduler interno ativo (a cada {settings.SCRAPER_INTERVAL_HOURS}h)")

    # Sweep de holds/reveals no proprio processo. O cron do GitHub Actions esta a
    # falhar de forma sistematica (cancelado antes de correr um passo), portanto
    # esta e agora a cobertura garantida, independente de trafego e de terceiros.
    _watchdog_task = asyncio.create_task(_hold_watchdog_loop())

    # P1: frescura diaria HPD/DOB + reincidencia. Dorme primeiro para nao
    # competir com o arranque/deploy.
    if getattr(settings, "FRESHNESS_ENABLED", True):
        _freshness_task = asyncio.create_task(_freshness_loop())
        logger.info(
            "Frescor HPD/DOB ativo (atraso inicial %s min, cada %sh)",
            settings.FRESHNESS_INITIAL_DELAY_MIN,
            settings.FRESHNESS_INTERVAL_HOURS,
        )

    # Worker do Outbound Frio (Fase 2). Dorme primeiro para nao disparar durante
    # os testes nem na arrancagem. Fail-closed por dentro: com `send_enabled=0`
    # o tick e' um no-op, portanto ativar a task em si nao envia nada.
    if getattr(settings, "OUTBOUND_WORKER_ENABLED", True):
        _outbound_task = asyncio.create_task(_outbound_worker_loop())
        logger.info(
            "Outbound worker ativo (a cada %ss) — envio real so' com send_enabled=1",
            getattr(settings, "OUTBOUND_WORKER_INTERVAL_SECONDS", 60),
        )
    else:
        logger.info("[OUTBOUND] Worker desativado por OUTBOUND_WORKER_ENABLED=0")

    # Control Tower (Etapa 1): saude a cada 15 min, backup diario off-site e
    # digest diario. Fail-soft: qualquer falha aqui nunca derruba a app.
    if getattr(settings, "CONTROL_TOWER_ENABLED", True):
        _health_task = asyncio.create_task(_control_tower_loop())
        logger.info("Control Tower ativa (saude 15min, backup+digest diarios)")

    # Inbox sync (gmail.readonly): respostas, bounces e reclamacoes ->
    # supressao automatica. Fail-soft: sem o scope devolve no_permission.
    if getattr(settings, "INBOX_SYNC_ENABLED", True):
        _inbox_task = asyncio.create_task(_inbox_sync_loop())
        logger.info("Inbox sync ativa (5min) — requer scope gmail.readonly")

    # Fila de enriquecimento (Fase 1): tira a descoberta/validacao do request
    # HTTP. Fail-closed: sem VPS configurada cada job fica `no_email`/`failed`.
    if getattr(settings, "ENRICH_QUEUE_ENABLED", True):
        _enrich_task = asyncio.create_task(enrichment_queue.worker_loop())
    else:
        logger.info("[ENRICH-QUEUE] Desativada por ENRICH_QUEUE_ENABLED=0")

    # Recuperacao de checkout abandonado (Prioridade A). Fail-closed: sem
    # EMAIL_API_KEY/EMAIL_FROM nao envia nada; so' actua sobre utilizadores que
    # ja' iniciaram um pagamento e ainda nao pagaram.
    if getattr(settings, "CHECKOUT_RECOVERY_ENABLED", True):
        _checkout_recovery_task = asyncio.create_task(_checkout_recovery_loop())
        logger.info(
            "Recuperacao de checkout ativa (a cada %ss, apos %s min) — canal: %s",
            getattr(settings, "CHECKOUT_RECOVERY_INTERVAL_SECONDS", 900),
            getattr(settings, "CHECKOUT_RECOVERY_AFTER_MINUTES", 90),
            "Resend" if settings.EMAIL_API_KEY and settings.EMAIL_FROM else "(sem canal)",
        )
    else:
        logger.info("[CHECKOUT] Recuperacao desativada por CHECKOUT_RECOVERY_ENABLED=0")

    # Diagnóstico de e-mail no startup
    if settings.EMAIL_API_KEY:
        logger.info(
            f"[EMAIL-STARTUP] Canal ATIVO: Resend HTTP (HTTPS :443) — "
            f"from={settings.EMAIL_FROM or '(não definido — usar domínio verificado)'}"
        )
    elif settings.SMTP_USER and settings.SMTP_PASS:
        logger.info(
            f"[EMAIL-STARTUP] Canal ATIVO: SMTP — host={settings.SMTP_HOST}, "
            f"port={settings.SMTP_PORT}, user={settings.SMTP_USER}"
        )
    else:
        logger.info(
            "[EMAIL-STARTUP] Modo logs (sem EMAIL_API_KEY nem SMTP_USER/PASS) — "
            "links de reset impressos nos logs"
        )

    # Validação Stripe no startup
    if settings.STRIPE_API_KEY and settings.STRIPE_PRICE_ID_PRO and settings.STRIPE_WEBHOOK_SECRET:
        if settings.STRIPE_API_KEY.startswith("sk_live_"):
            logger.info("[OK] Stripe LIVE configurado — pagamentos em PRODUÇÃO")
        elif settings.STRIPE_API_KEY.startswith("sk_test_"):
            logger.warning("[AVISO]️ Stripe TEST configurado — pagamentos em MODO TESTE (não use em produção)")
        else:
            logger.warning(f"[AVISO]️ Stripe key prefixo desconhecido: {settings.STRIPE_API_KEY[:12]}...")
        logger.info(f"[OK] Stripe PRICE_ID: {settings.STRIPE_PRICE_ID_PRO}")
    else:
        logger.warning("[AVISO]️ Stripe NÃO configurado completamente — checkout usará mock")
    yield
    for name, task in (
        ("scheduler", _scheduler_task),
        ("watchdog", _watchdog_task),
        ("outbound", _outbound_task),
        ("freshness", _freshness_task),
    ):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Erro ao parar a task {name}: {e}")
    # Flush final: escreve o que ficou em memoria antes de o processo
    # morrer. Cada buffer tem o seu proprio try: se o flush da Searchbug
    # levantar, o da Push ainda tem de correr. Se falhar, o buffer e
    # descartado - telemetria nunca pode impedir o shutdown.
    for name, buf in (("searchbug", searchbug_metrics), ("push", push_metrics)):
        try:
            await buf.stop()
        except Exception as e:
            logger.warning(f"Erro no flush final de telemetria ({name}): {e}")
    # Fecha o client httpx partilhado do phone lookup (keep-alive abertos).
    try:
        await searchbug_service.aclose()
    except Exception as e:
        logger.warning(f"Erro ao fechar client HTTP do phone lookup: {e}")
    # Fecha os clients HTTP do outbound (Gmail + EmailListVerify).
    try:
        await outbound_engine.aclose()
    except Exception as e:
        logger.warning(f"Erro ao fechar clients do outbound: {e}")


async def _hold_watchdog_loop():
    """Sweep de holds/reveals dentro do processo, a cada HOLD_WATCHDOG_INTERVAL_MIN.

    Substitui a dependencia de `/api/cron/expire-holds` ser chamado de fora: o
    GitHub Actions falhou 6 vezes seguidas (cancelado na fila, 0 passos) e a
    unica cobertura que restava era o sweep inline em `daily-stats`, que so
    corre com trafego de utilizadores. Este loop nao depende de nenhum dos dois.

    Chama `db_service` directamente em vez de um HTTP request a localhost: nao ha
    rota de saida nem CORS no caminho, e o resultado fica nos logs do container.
    """
    interval_s = max(60, settings.HOLD_WATCHDOG_INTERVAL_MIN * 60)
    logger.info(
        "Watchdog de holds ativo (a cada %ss) — independente do GitHub Actions",
        interval_s,
    )
    while True:
        try:
            await asyncio.sleep(interval_s)
            expired = await db_service.expire_holds()
            reveals = await db_service.check_reveal_watchdogs()
            if expired or reveals:
                logger.info(
                    "Watchdog de holds: %s hold(s) expirado(s), %s reveal(s) processado(s)",
                    expired, reveals,
                )
            # B2: promove os avisos de ciclo de vida a push (opt-in).
            try:
                pushed_life = await lifecycle_push.dispatch_lifecycle_pushes()
                if pushed_life:
                    logger.info("Lifecycle push: %s aviso(s) enviado(s)", pushed_life)
            except Exception as e:
                logger.warning("Lifecycle push falhou: %s", e)
            else:
                logger.debug("Watchdog de holds: nada a expirar")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Uma falha aqui nao pode matar o loop: o proximo ciclo volta a tentar.
            logger.error(f"Erro no watchdog de holds: {e}", exc_info=True)


async def _freshness_loop():
    """P1: re-verificacao diaria HPD/DOB + consolidacao da reincidencia."""
    await asyncio.sleep(max(60, int(settings.FRESHNESS_INITIAL_DELAY_MIN) * 60))
    while True:
        try:
            result = await freshness.run_freshness()
            logger.info("[FRESHNESS] %s", result)
        except Exception as e:  # noqa: BLE001
            logger.error("[FRESHNESS] falhou: %s", e, exc_info=True)
        await asyncio.sleep(max(3600, int(settings.FRESHNESS_INTERVAL_HOURS) * 3600))


async def _inbox_sync_loop():
    """Le a inbox a cada 5 min; nunca derruba a app."""
    await asyncio.sleep(120)
    while True:
        try:
            res = await inbox_sync.sync_inbox()
            if res.get("status") != "ok" or any(
                res.get(k) for k in ("replies", "bounces", "complaints")
            ):
                logger.info("[INBOX] %s", res)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[INBOX] sync falhou: %s", exc)
        await asyncio.sleep(5 * 60)


async def _control_tower_loop():
    """Saude a cada 15 min; backup + digest no maximo 1x/dia.

    `maybe_backup` so' corre se o ultimo backup tiver >20h, portanto um deploy
    a meio do dia nao gera copias extra.
    """
    await asyncio.sleep(30)
    while True:
        try:
            res = await control_tower.maybe_backup()
            if res:
                logger.info("[CONTROL-TOWER] backup: %s", res)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CONTROL-TOWER] backup falhou: %s", exc)
        try:
            await control_tower.run_health_checks()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CONTROL-TOWER] health falhou: %s", exc)
        try:
            res = await control_tower.maybe_send_digest()
            if res:
                logger.info("[CONTROL-TOWER] digest: %s", res)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CONTROL-TOWER] digest falhou: %s", exc)
        await asyncio.sleep(15 * 60)


async def _outbound_worker_loop():
    """Tick periodico do motor de envio real (Outbound Frio - Fase 2).

    Respeita sempre o estado global `send_enabled`: com o envio desligado o
    process_queue devolve `status='disabled'` e nao faz nada. A quiet hours e'
    avaliada em UTC pelo proprio motor, portanto este loop pode correr a
    qualquer hora.
    """
    interval_s = max(10, int(getattr(settings, "OUTBOUND_WORKER_INTERVAL_SECONDS", 60) or 60))
    while True:
        try:
            # Dorme primeiro: evita disparos na arrancagem e nos testes.
            await asyncio.sleep(interval_s)
            result = await outbound_engine.process_queue()
            # Heartbeat: a Control Tower usa isto para detectar worker morto.
            try:
                control_tower.kv_set(
                    control_tower.KV_LAST_TICK,
                    control_tower._iso(control_tower._now()),
                )
            except Exception:  # noqa: BLE001
                pass
            if result.get("sent") or result.get("failed") or result.get("skipped"):
                logger.info("[OUTBOUND] Worker tick: %s", result)
            elif result.get("status") not in ("idle", "disabled", "quiet_hours"):
                logger.debug("[OUTBOUND] Worker tick: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Uma falha nao pode matar o loop: no proximo ciclo volta a tentar.
            logger.error(f"Erro no outbound worker: {e}", exc_info=True)


# ------------------------------------------------------------------
# Recuperacao de checkout abandonado (Prioridade A)
# ------------------------------------------------------------------

def _now_iso() -> str:
    """Timestamp UTC no formato do SQLite (YYYY-MM-DD HH:MM:SS)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def _send_checkout_recovery_email(
    to_email: str, company_name: str, checkout_url: str
) -> bool:
    """Envia o e-mail de recuperacao (transacional) via Resend.

    Fail-soft: sem `EMAIL_API_KEY`/`EMAIL_FROM` nao envia e devolve False.
    """
    if not settings.EMAIL_API_KEY or not settings.EMAIL_FROM:
        return False
    subject = "Your Magic Leads list is still waiting"
    body = (
        f"Hi {company_name or 'there'},\n\n"
        "You started a Magic Leads checkout but did not finish. Your access to "
        "this week's opportunities is still open:\n\n"
        f"{checkout_url}\n\n"
        "Magic Leads gives you 300 exclusive opportunities per week - one "
        "contractor per address, with the contact details and the exact service "
        "needed. $120 for 7 days, cancel anytime.\n\n"
        "If you did not start this checkout, you can ignore this email.\n\n"
        "— Magic Leads"
    )
    try:
        resp = await anyio.to_thread.run_sync(
            lambda: httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.EMAIL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.EMAIL_FROM,
                    "to": [to_email],
                    "subject": subject,
                    "text": body,
                },
                timeout=15,
            )
        )
        if resp.status_code == 200:
            logger.info("[CHECKOUT] E-mail de recuperacao enviado para %s", to_email)
            return True
        logger.warning(
            "[CHECKOUT] Resend recusou o recuperacao (HTTP %s) para %s",
            resp.status_code,
            to_email,
        )
        return False
    except Exception as e:
        logger.warning("[CHECKOUT] Falha no e-mail de recuperacao para %s: %s", to_email, e)
        return False


async def _checkout_recovery_loop():
    """Lembra utilizadores que iniciaram o checkout e nao pagaram.

    Corre a cada `CHECKOUT_RECOVERY_INTERVAL_SECONDS`. Fail-closed: sem canal de
    e-mail configurado nao faz nada. Nunca toca em quem ja' tem plano activo.
    """
    interval_s = max(120, int(getattr(settings, "CHECKOUT_RECOVERY_INTERVAL_SECONDS", 900)))
    after_minutes = max(10, int(getattr(settings, "CHECKOUT_RECOVERY_AFTER_MINUTES", 90)))
    max_reminders = max(1, int(getattr(settings, "CHECKOUT_RECOVERY_MAX_REMINDERS", 2)))
    while True:
        try:
            await asyncio.sleep(interval_s)
            if not getattr(settings, "CHECKOUT_RECOVERY_ENABLED", True):
                continue
            if not settings.EMAIL_API_KEY or not settings.EMAIL_FROM:
                continue
            cutoff = (
                datetime.now(timezone.utc) - timedelta(minutes=after_minutes)
            ).strftime("%Y-%m-%d %H:%M:%S")
            rows = await db_service.list_recoverable_checkout_sessions(
                cutoff, max_reminders=max_reminders, limit=50
            )
            sent = 0
            for row in rows:
                # Ja' tem plano activo? Nao ha nada a recuperar.
                plan_until = (row.get("plan_until") or "").strip()
                if plan_until:
                    try:
                        if datetime.strptime(
                            plan_until.replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S"
                        ) > datetime.now(timezone.utc).replace(tzinfo=None):
                            continue
                    except ValueError:
                        pass
                email = (row.get("email") or row.get("user_email") or "").strip()
                url = (row.get("url") or "").strip()
                if not email or not url:
                    continue
                ok = await _send_checkout_recovery_email(
                    email, row.get("company_name") or "", url
                )
                await db_service.mark_checkout_reminded(row["session_id"])
                if ok:
                    sent += 1
            if sent:
                logger.info("[CHECKOUT] Recuperacao: %s e-mail(s) enviado(s)", sent)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Erro no loop de recuperacao de checkout: {e}", exc_info=True)


@app.get("/api/admin/billing/funnel")
async def admin_billing_funnel(_admin: dict = Depends(_require_admin_user)):
    """Funil de checkout: criado -> abriu (com email) -> pagou.

    Sem isto nao ha forma de saber onde esta' a perda: 'nao klikou', 'chegou ao
    Stripe e desistiu' ou 'pagou e nao recebeu acesso'.
    """
    stats = await db_service.checkout_funnel_stats()
    recent = await db_service.list_recoverable_checkout_sessions(
        "9999-12-31 23:59:59", max_reminders=99, limit=20
    )
    return {
        "funnel": stats,
        "recovery": {
            "enabled": bool(getattr(settings, "CHECKOUT_RECOVERY_ENABLED", True)),
            "channel_configured": bool(settings.EMAIL_API_KEY and settings.EMAIL_FROM),
            "after_minutes": int(getattr(settings, "CHECKOUT_RECOVERY_AFTER_MINUTES", 90)),
            "max_reminders": int(getattr(settings, "CHECKOUT_RECOVERY_MAX_REMINDERS", 2)),
        },
        "open_sessions": len(recent),
    }


app.router.lifespan_context = _lifespan


# Lista o que o framework nacional descobriu (estados/mercados cobertos)
@app.get("/api/scraper/discover")
async def discover_available(_admin: bool = Depends(_require_admin)):
    """Retorna os datasets/mercados descobertos nacionalmente (311, permits, tax).

    ADMIN-ONLY: a resposta mapeia os 847 datasets (dominio + id + nome) que a
    ferramenta de expansao cobre — exatamente o segredo de negocio de que
    fontes o scraper leria. Publica, qualquer concorrente baixava o catalogo
    inteiro num unico GET. O frontend nao consome esta rota (so /api/scraper/status).
    """
    try:
        data = await socrata_discovery.discover_all()
        # Resumo por tema
        summary = {}
        for theme, items in data.items():
            summary[theme] = [
                {"domain": d["domain"], "id": d["id"], "name": d["name"]}
                for d in items
            ]
        return {"catalog": summary}
    except Exception as e:
        logger.error(f"Erro no discovery: {e}")
        # Generico: nao devolver texto de excecao a quem chama (mesmo admin),
        # detalhe fica nos logs do servidor.
        raise HTTPException(status_code=500, detail="Erro no discovery")


# Enriquecimento em lote: preenche owner_name = nome do proprietário (registro público)
@app.post("/api/scraper/enrich")
@limiter.limit("5/hour")
async def enrich_leads(
    request: Request,
    city: str = "NYC",
    limit: int = 500,
    _admin: dict = Depends(_require_admin_user),
):
    """Enriquecimento em lote — operação administrativa (sessão + is_admin).

    Antes exigia apenas login: qualquer conta (incluindo demo) podia disparar
    até 500 consultas externas numa única request. Não é usada pela UI.
    """
    try:
        limit = max(1, min(int(limit), 500))
        from backend.services import db as dbmod

        # pega leads sem owner_name
        conn = dbmod.get_connection()
        rows = conn.execute(
            "SELECT id, address, city, bbl FROM leads "
            "WHERE (owner_name IS NULL OR owner_name = '') AND city = ? "
            "ORDER BY date_reported DESC LIMIT ?",
            (city, limit),
        ).fetchall()
        conn.close()

        logger.info(f"Enriquecendo {len(rows)} leads de {city}...")
        updated = 0
        found = 0
        for row in rows:
            enrich_result = await owner_enrichment.enrich(
                row["address"], row["city"], bbl=row["bbl"] if "bbl" in row.keys() and row["bbl"] else None
            )
            if enrich_result and enrich_result.get("owner_name"):
                await db_service.update_owner(row["id"], enrich_result["owner_name"])
                found += 1
            updated += 1
            await asyncio.sleep(0.15)  # throttling Socrata API

        logger.info(f"Enriquecimento: {found} donos encontrados de {updated} leads")
        if found > 0:
            await db_service.add_notification(
                "owner_enriched",
                "Novos proprietários identificados",
                f"{found} novo(s) proprietário(s) encontrado(s) em {city}",
                msg_key="owner_enriched",
                msg_params={"n": found, "city": city},
            )
        return {
            "status": "success",
            "processed": updated,
            "owners_found": found,
        }
    except Exception as e:
        logger.error(f"Erro no enriquecimento: {e}")
        raise HTTPException(status_code=500, detail="Erro interno. Detalhe registado nos logs do servidor.")


# Enriquecimento completo em lote: owner_name + mailing_address + skip_trace (phone/email)
@app.post("/api/scraper/enrich-all")
@limiter.limit("5/hour")
async def enrich_all_leads(request: Request, limit_per_city: int = 200, _admin: bool = Depends(_require_admin)):
    """
    Roda enriquecimento completo em TODAS as cidades:
    1. Owner name + mailing_address (via assessor/property records)
    2. Skip trace para phone/email (fontes gratuitas)
    """
    try:
        from backend.services import db as dbmod
        from backend.services.skip_trace import skip_trace_service

        cities = await db_service.get_cities()
        total_processed = 0
        total_owners_found = 0
        total_mailing_found = 0
        total_phones_found = 0
        total_emails_found = 0
        results_by_city = {}

        for city in cities:
            logger.info(f"Enriquecendo {city}...")

            # Pega leads sem owner_name OU sem mailing_address OU sem phone/email
            conn = dbmod.get_connection()
            rows = conn.execute(
                "SELECT id, address, city, bbl FROM leads "
                "WHERE city = ? "
                "AND (owner_name IS NULL OR owner_name = '' "
                "   OR mailing_address IS NULL OR mailing_address = '' "
                "   OR owner_phone IS NULL OR owner_phone = '' "
                "   OR owner_email IS NULL OR owner_email = '') "
                "ORDER BY date_reported DESC LIMIT ?",
                (city, limit_per_city),
            ).fetchall()
            conn.close()

            if not rows:
                results_by_city[city] = {"processed": 0, "message": "No leads to enrich"}
                continue

            city_processed = 0
            city_owners = 0
            city_mailing = 0
            city_phones = 0
            city_emails = 0

            # Prepare address-city pairs for batch enrichment
            address_city_pairs = [(row["address"], row["city"], row["bbl"]) if "bbl" in row.keys() else (row["address"], row["city"]) for row in rows]

            # Batch owner enrichment
            enrichment_results = await owner_enrichment.enrich_batch(address_city_pairs)

            for row in rows:
                key = f"{row['city']}:{row['address']}"
                enrich_result = enrichment_results.get(key)

                updates = {}
                if enrich_result and enrich_result.get("owner_name"):
                    updates["owner_name"] = enrich_result["owner_name"]
                    city_owners += 1
                if enrich_result and enrich_result.get("mailing_address"):
                    updates["mailing_address"] = enrich_result["mailing_address"]
                    city_mailing += 1

                # Skip trace for phone/email (only if we have owner_name)
                if enrich_result and enrich_result.get("owner_name"):
                    phone = await skip_trace_service.find_owner_phone(
                        row["address"], enrich_result["owner_name"], row["city"]
                    )
                    email = await skip_trace_service.find_owner_email(
                        row["address"], enrich_result["owner_name"], row["city"]
                    )
                    if phone:
                        updates["owner_phone"] = phone
                        city_phones += 1
                    if email:
                        updates["owner_email"] = email
                        city_emails += 1

                if updates:
                    # Apply all updates
                    for field, value in updates.items():
                        if field == "owner_name":
                            await db_service.update_owner(row["id"], value)
                        elif field == "mailing_address":
                            await db_service.update_mailing_address(row["id"], value)
                        elif field == "owner_phone":
                            await db_service.update_owner_phone(row["id"], value)
                        elif field == "owner_email":
                            await db_service.update_owner_email(row["id"], value)
                    city_processed += 1

                total_processed += 1

            # Also add owner_email update to db
            # (We'll need to add this method)

            results_by_city[city] = {
                "processed": city_processed,
                "owners_found": city_owners,
                "mailing_found": city_mailing,
                "phones_found": city_phones,
                "emails_found": city_emails,
            }

            total_owners_found += city_owners
            total_mailing_found += city_mailing
            total_phones_found += city_phones
            total_emails_found += city_emails

        if total_owners_found > 0 or total_mailing_found > 0 or total_phones_found > 0 or total_emails_found > 0:
            await db_service.add_notification(
                "enrichment_complete",
                "Enriquecimento de dados concluído",
                f"Identificados: {total_owners_found} proprietários, {total_mailing_found} endereços de correspondência, {total_phones_found} telefones, {total_emails_found} e-mails",
                msg_key="enrichment_complete",
                msg_params={
                    "owners": total_owners_found,
                    "mailing": total_mailing_found,
                    "phones": total_phones_found,
                    "emails": total_emails_found,
                },
            )

        return {
            "status": "success",
            "total_processed": total_processed,
            "total_owners_found": total_owners_found,
            "total_mailing_found": total_mailing_found,
            "total_phones_found": total_phones_found,
            "total_emails_found": total_emails_found,
            "by_city": results_by_city,
        }
    except Exception as e:
        logger.error(f"Erro no enriquecimento completo: {e}")
        raise HTTPException(status_code=500, detail="Erro interno. Detalhe registado nos logs do servidor.")


# Reclassificação dos leads existentes para o novo modelo (16 ofícios + gatilhos preditivos)
@app.post("/api/admin/requalify")
async def admin_requalify_leads(request: Request, _admin: bool = Depends(_require_admin)):
    """
    Reclassifica todos os leads existentes no banco para o novo modelo:
    - _infer_category aprimorado (16 ofícios, fallback Permit_Rejected para fontes legais)
    - Retorna estatísticas antes/depois do filtro qualificado
    """
    try:
        from backend.scrapers.socrata_311 import socrata_scraper
        from backend.services import db as dbmod

        conn = dbmod.get_connection()
        conn.row_factory = sqlite3.Row

        # 1. Estatísticas ANTES (filtro legado: essenciais + junk antigo)
        old_junk_terms = [
            "sanitation", "garbage", "trash", "refuse", "litter", "debris", "dumping",
            "rodent", "rat", "mouse", "pest", "vermin", "roach", "insect",
            "parking", "traffic", "signal", "sign", "street light", "pothole",
            "sidewalk", "curb", "graffiti", "noise", "animal", "dog", "cat",
            "dead animal", "abandoned vehicle", "towing", "tpw", "transportation",
            "water leak", "hydrant", "sewer backup", "catch basin", "storm drain",
            "illegal dumping", "bulk item", "recycling", "organics", "yard waste",
        ]

        def old_qualified_where(prefix=""):
            conds = [
                f"{prefix}department IS NOT NULL AND TRIM({prefix}department) != ''",
                f"{prefix}case_status IS NOT NULL AND TRIM({prefix}case_status) != ''",
                f"{prefix}descriptor IS NOT NULL AND TRIM({prefix}descriptor) != ''",
                f"{prefix}neighborhood IS NOT NULL AND TRIM({prefix}neighborhood) != ''",
            ]
            for t in old_junk_terms:
                for col in (f"{prefix}issue_category", f"{prefix}issue_description", f"{prefix}descriptor"):
                    conds.append(f"LOWER(COALESCE({col}, '')) NOT LIKE '%{t}%'")
            return " AND ".join(conds)

        old_total = conn.execute(f"SELECT COUNT(*) FROM leads WHERE {old_qualified_where()}").fetchone()[0]
        old_7d = conn.execute(f"SELECT COUNT(*) FROM leads WHERE date_reported IS NOT NULL AND date(date_reported)>=date('now','-7 days') AND {old_qualified_where()}").fetchone()[0]
        old_24h = conn.execute(f"SELECT COUNT(*) FROM leads WHERE created_at>=datetime('now','-1 day') AND {old_qualified_where()}").fetchone()[0]

        # 2. Reclassificação
        rows = conn.execute("SELECT id, issue_category, source_type, case_title, issue_description, descriptor FROM leads").fetchall()
        changes = {}
        kept = 0

        for r in rows:
            text = (r["case_title"] or r["issue_description"] or r["descriptor"] or "") or ""
            new_cat = socrata_scraper._infer_category(text, r["source_type"])
            new_cat = new_cat.value if hasattr(new_cat, "value") else str(new_cat)
            old = r["issue_category"]
            if new_cat != old:
                changes[f"{old}->{new_cat}"] = changes.get(f"{old}->{new_cat}", 0) + 1
                conn.execute("UPDATE leads SET issue_category=? WHERE id=?", (new_cat, r["id"]))
            else:
                kept += 1

        conn.commit()

        # 3. Estatísticas DEPOIS (filtro qualificado novo)
        from backend.services.db import _qualified_where

        new_total = conn.execute(f"SELECT COUNT(*) FROM leads WHERE {_qualified_where()}").fetchone()[0]
        new_7d = conn.execute(f"SELECT COUNT(*) FROM leads WHERE date_reported IS NOT NULL AND date(date_reported)>=date('now','-7 days') AND {_qualified_where()}").fetchone()[0]
        new_24h = conn.execute(f"SELECT COUNT(*) FROM leads WHERE created_at>=datetime('now','-1 day') AND {_qualified_where()}").fetchone()[0]

        # Por cidade (novo)
        city_rows = conn.execute(f"SELECT city, COUNT(*) c FROM leads WHERE {_qualified_where()} GROUP BY city ORDER BY c DESC").fetchall()
        by_city = {r["city"]: r["c"] for r in city_rows}

        # Por ofício (novo)
        cat_rows = conn.execute(f"SELECT issue_category, COUNT(*) c FROM leads WHERE {_qualified_where()} GROUP BY issue_category ORDER BY c DESC").fetchall()
        by_category = {r["issue_category"]: r["c"] for r in cat_rows}

        conn.close()

        return {
            "status": "success",
            "reclassified": sum(changes.values()),
            "kept": kept,
            "changes": changes,
            "before": {
                "total": old_total,
                "last_7d": old_7d,
                "last_24h": old_24h,
            },
            "after": {
                "total": new_total,
                "last_7d": new_7d,
                "last_24h": new_24h,
                "by_city": by_city,
                "by_category": by_category,
            },
            "delta": {
                "total": new_total - old_total,
                "last_7d": new_7d - old_7d,
                "last_24h": new_24h - old_24h,
            },
        }
    except Exception as e:
        logger.error(f"Erro na reclassificação: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno. Detalhe registado nos logs do servidor.")


# Enriquecimento/consulta do dono de um único lead
@app.post("/api/leads/{lead_id}/enrich")
@limiter.limit("10/hour")
async def enrich_single_lead(
    request: Request,
    lead_id: int,
    _admin: dict = Depends(_require_admin_user),
):
    """Consulta o nome do proprietário de um lead (operação administrativa)."""
    try:
        lead = await db_service.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead não encontrado")
        owner = await owner_enrichment.enrich(
            lead["address"], lead["city"], bbl=lead.get("bbl") if hasattr(lead, "get") else None
        )
        owner_name = owner.get("owner_name") if owner else None
        if owner_name:
            await db_service.update_owner(lead_id, owner_name)
        return {"lead_id": lead_id, "owner_name": owner_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao enriquecer lead {lead_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno. Detalhe registado nos logs do servidor.")


# ------------------------------------------------------------------
# Autenticação e usuários
# ------------------------------------------------------------------
def _user_response(u: dict) -> UserResponse:
    """Serializa o utilizador com todas as preferências (fonte única).

    Existe para que login, registo, /auth/me e updates devolvam exatamente o
    mesmo contrato — sem isto, editar a empresa apagava no cliente a base
    geográfica e as preferências de privacidade até ao próximo reload.
    """
    return UserResponse(
        id=u["id"],
        email=u["email"],
        company_name=u.get("company_name"),
        plan=u.get("plan"),
        subscription_status=u.get("subscription_status"),
        plan_until=u.get("plan_until"),
        score=u.get("score") or 0,
        leads_taken=u.get("leads_taken") or 0,
        conversions=u.get("conversions") or 0,
        push_enabled=bool(u.get("push_enabled")),
        locale=u.get("locale") or "en",
        is_admin=bool(u.get("is_admin")),
        created_at=u.get("created_at"),
        cities_filter=u.get("cities_filter"),
        base_lat=u.get("base_lat"),
        base_lng=u.get("base_lng"),
        base_source=u.get("base_source"),
        base_label=u.get("base_label"),
        show_address_in_push=bool(u.get("show_address_in_push", 1)),
        digest_enabled=bool(u.get("digest_enabled", 1)),
        lifecycle_push_enabled=bool(u.get("lifecycle_push_enabled", 0)),
        chime_enabled=bool(u.get("chime_enabled", 1)),
    )


@app.post("/api/auth/register", response_model=AuthResponse)
@limiter.limit("3/minute")
async def register_user(request: Request, payload: UserCreate, response: Response = None):
    try:
        pwd_hash = security.hash_password(payload.password)
        user = await db_service.create_user(
            payload.email.lower(), pwd_hash, payload.company_name, plan="free",
            subscription_status="expired", plan_until=None,
            locale=payload.locale if payload.locale else "en",
        )
        if not user:
            raise HTTPException(status_code=409, detail="Email já cadastrado")
        token = security.new_session_token()
        # Registra a sessão no banco (aplica limite de 2 sessões por usuário - FIFO)
        await db_service.create_user_session(user["id"], _hash_token(token), "Signup", None)

        # Define httpOnly cookie com o token
        if response:
            response.set_cookie(
                key="garimpador_token",
                value=token,
                httponly=True,
                secure=not settings.DEBUG,  # False em dev (HTTP), True em prod (HTTPS)
                samesite="lax",
                max_age=max(1, int(getattr(settings, "SESSION_TTL_DAYS", 30) or 30)) * 24 * 60 * 60,
                path="/",
            )

        return AuthResponse(
            token=token,
            user=_user_response(user),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro no registro: {e}")
        raise HTTPException(status_code=500, detail="Erro no registro")


@app.post("/api/auth/login", response_model=AuthResponse)
@limiter.limit("5/minute")
async def login_user(request: Request, payload: UserLogin, response: Response = None):
    try:
        user = await db_service.get_user_by_email(payload.email.lower())
        if not user or not security.verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Email ou senha inválidos")
        token = security.new_session_token()

        # Registra a sessão no banco (aplica limite de 2 sessões por usuário - FIFO)
        device_info = request.headers.get("user-agent", "")
        ip_address = request.client.host if request.client else None
        await db_service.create_user_session(user["id"], _hash_token(token), device_info, ip_address)

        # Define httpOnly cookie com o token
        if response:
            response.set_cookie(
                key="garimpador_token",
                value=token,
                httponly=True,
                secure=not settings.DEBUG,  # False em dev (HTTP), True em prod (HTTPS)
                samesite="lax",
                max_age=max(1, int(getattr(settings, "SESSION_TTL_DAYS", 30) or 30)) * 24 * 60 * 60,
                path="/",
            )

        return AuthResponse(
            token=token,
            user=_user_response(user),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro no login: {e}")
        raise HTTPException(status_code=500, detail="Erro no login")


@app.get("/api/auth/me", response_model=UserResponse)
async def me(user: dict = Depends(_get_current_user)):
    full = await db_service.get_user_by_id(user["id"])
    if not full:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return _user_response(full)


@app.patch("/api/users/{user_id}/company", response_model=UserResponse)
async def update_user_company(user_id: int, payload: UserUpdate, user: dict = Depends(_get_current_user)):
    try:
        if int(user["id"]) != int(user_id):
            raise HTTPException(status_code=403, detail="Sem permissão para editar este usuário")
        name = (payload.company_name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Nome da empresa é obrigatório")
        if len(name) > 120:
            raise HTTPException(status_code=422, detail="Nome muito longo (máx. 120 caracteres)")
        full = await db_service.update_user_company(int(user_id), name)
        if not full:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        return _user_response(full)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao atualizar empresa do usuário {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao atualizar empresa")


@app.patch("/api/users/{user_id}/locale", response_model=UserResponse)
async def update_user_locale(user_id: int, payload: UserUpdate, user: dict = Depends(_get_current_user)):
    try:
        if int(user["id"]) != int(user_id):
            raise HTTPException(status_code=403, detail="Sem permissão para editar este usuário")
        locale = (payload.locale or "").strip().lower()
        if locale not in ("pt", "en", "es"):
            raise HTTPException(status_code=422, detail="Idioma inválido (use pt, en ou es)")
        full = await db_service.update_user_locale(int(user_id), locale)
        if not full:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        return _user_response(full)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao atualizar empresa do usuário {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro ao atualizar empresa")


@app.post("/api/user/welcome-popup")
async def mark_welcome_popup_shown(user: dict = Depends(_get_current_user)):
    """Marca o welcome popup como visto pelo usuário."""
    try:
        full = await db_service.update_user_welcome_popup(user["id"])
        if not full:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        return {"status": "ok", "welcome_popup_shown": full.get("welcome_popup_shown", True)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao marcar welcome popup: {e}")
        raise HTTPException(status_code=500, detail="Erro ao atualizar preferência")


@app.post("/api/auth/logout")
async def logout_user(authorization: str | None = Header(None), response: Response = None):
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
        # Remove do banco
        await db_service.remove_user_session(_hash_token(token))

    # Limpa o cookie
    if response:
        response.delete_cookie(
            key="garimpador_token",
            path="/",
        )

    return {"status": "ok"}


@app.post("/api/auth/demo", response_model=AuthResponse)
@limiter.limit("10/hour")
async def demo_login(request: Request, response: Response = None):
    import os
    demo_email = os.getenv("DEMO_EMAIL", "demo@magicleads.app")
    demo_password = (os.getenv("DEMO_PASSWORD") or "").strip()
    if not demo_password:
        # Fail-closed: sem password explícita não há conta demo pública.
        raise HTTPException(
            status_code=503,
            detail="Demo desativado: DEMO_PASSWORD não configurado no servidor",
        )
    try:
        user = await db_service.get_user_by_email(demo_email.lower())
        if not user:
            pwd_hash = security.hash_password(demo_password)
            user = await db_service.create_user(
                demo_email.lower(), pwd_hash, "Contratante Demo", plan="free",
                subscription_status="expired", plan_until=None,
            )
            if not user:
                raise HTTPException(status_code=500, detail="Erro ao criar conta demo")
            token = security.new_session_token()
        else:
            if not security.verify_password(demo_password, user["password_hash"]):
                raise HTTPException(status_code=500, detail="Demo account configuration error")
            token = security.new_session_token()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro no demo login: {e}")
        raise HTTPException(status_code=500, detail="Erro no demo login")

    # Registra a sessão no banco
    token_hash = _hash_token(token)
    await db_service.create_user_session(user["id"], token_hash, "Demo Login", None)

    # Define httpOnly cookie com o token
    if response:
        response.set_cookie(
            key="garimpador_token",
            value=token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=max(1, int(getattr(settings, "SESSION_TTL_DAYS", 30) or 30)) * 24 * 60 * 60,
            path="/",
        )

    logger.info(f"Demo login successful for user {user['id']}")
    return AuthResponse(
        token=token,
        user=_user_response(user),
    )


# ===== PASSWORD RESET =====

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str

@app.post("/api/auth/forgot-password")
@limiter.limit("10/hour")
async def forgot_password(request: Request, payload: ForgotPasswordRequest):
    """Solicita reset de senha - envia token por email (mock)."""
    try:
        token = await db_service.create_password_reset_token(payload.email, expires_hours=1)
        if token:
            await db_service.send_password_reset_email(payload.email, token)
        # Sempre retorna sucesso para não revelar se email existe
        return {"status": "ok", "message": "Se o email estiver cadastrado, você receberá instruções para redefinir a senha."}
    except Exception as e:
        logger.error(f"Erro no forgot-password: {e}")
        raise HTTPException(status_code=500, detail="Erro ao processar solicitação")

@app.post("/api/auth/reset-password")
@limiter.limit("10/hour")
async def reset_password(request: Request, payload: ResetPasswordRequest):
    """Valida token e define nova senha."""
    try:
        if payload.new_password != payload.confirm_password:
            raise HTTPException(status_code=422, detail="As senhas não coincidem.")
        if len(payload.new_password) < 6:
            raise HTTPException(status_code=422, detail="A senha deve ter pelo menos 6 caracteres.")

        user_id = await db_service.validate_password_reset_token(payload.token)
        if not user_id:
            raise HTTPException(status_code=400, detail="Token inválido ou expirado.")

        pwd_hash = security.hash_password(payload.new_password)
        success = await db_service.consume_password_reset_token(payload.token, pwd_hash)
        if not success:
            raise HTTPException(status_code=400, detail="Token inválido ou expirado.")

        return {"status": "ok", "message": "Senha redefinida com sucesso! Faça login com sua nova senha."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro no reset-password: {e}")
        raise HTTPException(status_code=500, detail="Erro ao redefinir senha")


# ------------------------------------------------------------------
# Billing: checkout Stripe (ou mock local) + ativação de semana
# ------------------------------------------------------------------
def _plan_payload() -> dict:
    return {
        "name": settings.PLAN_NAME,
        "interval": settings.PLAN_INTERVAL,
        "amount_cents": settings.PLAN_AMOUNT_CENTS,
        "amount_usd": settings.PLAN_AMOUNT_USD,
        "annual_usd": settings.PLAN_ANNUAL_USD,
        "price_id": settings.STRIPE_PRICE_ID_PRO,
    }


def _stripe_configured() -> bool:
    return bool(
        settings.STRIPE_API_KEY
        and settings.STRIPE_PRICE_ID_PRO
        and settings.STRIPE_PRICE_ID_PRO != "price_..."
    )


async def _create_stripe_checkout_session(
    user_id: int, locale: str = "auto", email: "str | None" = None
) -> tuple:
    """Cria sessão Stripe de PAGAMENTO AVULSO (sem recorrência) de 7 dias.

    Retorna (mock: bool, checkout_url: Optional[str]). Pagamento único em USD;
    o acesso é liberado pelo webhook (checkout.session.completed) por 7 dias.

    Prioridade A (funil de checkout):
      * `customer_email` pre-preenche o e-mail do cliente e FAZ O STRIPE
        registar a intenção — sem isto não há como distinguir "não foi ao
        checkout" de "chegou ao checkout e desistiu", porque antes ninguém
        preenchia email nenhum (`customer_details` vazio em 100% das sessões).
      * IDEMPOTENCIA: no máximo uma sessão ABERTA por utilizador. Cliques
        repetidos no botão de pagar já criaram 9 sessões órfãs num único
        utilizador; agora reutiliza-se a sessão aberta (ou expira-se a
        antiga e cria-se uma nova), acabando com a pilha de sessões mortas.
    """
    has_stripe = _stripe_configured()
    if not has_stripe:
        return True, None

    # Map frontend locale to Stripe supported locales
    stripe_locale_map = {
        "pt": "pt",
        "en": "en",
        "es": "es",
    }
    stripe_locale = stripe_locale_map.get(locale, "auto")

    stripe.api_key = settings.STRIPE_API_KEY
    # Build cancel_url with locale prefix to return user to dashboard (not landing page)
    if locale and locale != "auto":
        cancel_path = f"/{locale}/dashboard"
    else:
        cancel_path = "/dashboard"
    cancel_url = f"{settings.FRONTEND_URL.rstrip('/')}{cancel_path}"
    success_url = f"{settings.FRONTEND_URL.rstrip('/')}/dashboard?paid=1"

    clean_email = (email or "").strip().lower() or None

    # --- Idempotência: reaproveita (ou recicla) a sessão aberta do utilizador.
    try:
        existing = stripe.checkout.Session.list(
            client_reference_id=str(user_id), status="open", limit=3
        )
        open_sessions = list(getattr(existing, "data", []) or [])
    except Exception as e:
        logger.warning("Stripe: nao foi possivel listar sessoes abertas (%s)", e)
        open_sessions = []

    if open_sessions:
        # Ordena por mais recente e devolve a URL da mais nova.
        def _created(s):
            return getattr(s, "created", 0) or 0

        newest = max(open_sessions, key=_created)
        newest_id = getattr(newest, "id", None)
        # Expira as restantes para nao deixar pilha de sessoes mortas.
        for s in open_sessions:
            sid = getattr(s, "id", None)
            if sid and sid != newest_id:
                try:
                    stripe.checkout.Session.expire(sid)
                except Exception:
                    pass
        if newest_id:
            url = getattr(newest, "url", None)
            if url:
                await_record = await db_service.record_checkout_session(
                    user_id,
                    newest_id,
                    clean_email,
                    settings.PLAN_AMOUNT_CENTS,
                    "usd",
                    url,
                )
                logger.info(
                    "Stripe: reutilizada sessao aberta %s para user %s (nova=%s)",
                    newest_id,
                    user_id,
                    await_record,
                )
                return False, url

    session = stripe.checkout.Session.create(
        mode="payment",
        currency="usd",
        line_items=[{"price": settings.STRIPE_PRICE_ID_PRO, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(user_id),
        customer_email=clean_email,
        locale=stripe_locale,
        metadata={
            "user_id": str(user_id),
            "access": "7_days",
            "plan": settings.PLAN_NAME.lower(),
        },
    )
    try:
        await db_service.record_checkout_session(
            user_id,
            session.id,
            clean_email,
            settings.PLAN_AMOUNT_CENTS,
            "usd",
            session.url,
        )
    except Exception as e:
        logger.warning("Falha ao registar sessao de checkout: %s", e)
    return False, session.url


@app.post("/api/billing/checkout")
async def create_checkout(request: Request, user: dict = Depends(_get_current_user)):
    """Cria sessão de checkout do acesso de 7 dias ($120, pagamento avulso).

    Se STRIPE_API_KEY + STRIPE_PRICE_ID_PRO estiverem configurados, cria uma
    sessão real no Stripe (hosted) e o acesso é libertado pelo webhook
    (checkout.session.completed).

    Se o Stripe NÃO estiver configurado, devolve mock=True / checkout_url=None.
    Isso é intencionalmente fail-closed: o frontend mostra erro de pagamento e
    NENHUM acesso é concedido. A ativação de plano ocorre exclusivamente via
    webhook Stripe verificado — nunca via um endpoint de mock.
    """
    full = await db_service.get_user_by_id(user["id"])
    if not full:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Extract locale from Accept-Language header (sent by frontend)
    accept_language = request.headers.get("accept-language", "").lower()
    locale = "auto"
    if accept_language.startswith("pt"):
        locale = "pt"
    elif accept_language.startswith("en"):
        locale = "en"
    elif accept_language.startswith("es"):
        locale = "es"

    try:
        mock, checkout_url = await _create_stripe_checkout_session(
            user["id"], locale, full.get("email")
        )
    except Exception as e:
        logger.error(f"Erro ao criar checkout Stripe: {type(e).__name__}: {e}")
        # Include Stripe error details if available
        detail = "Falha ao iniciar checkout"
        if hasattr(e, 'user_message'):
            detail = f"Stripe: {e.user_message}"
        elif hasattr(e, 'code'):
            detail = f"Stripe error ({e.code}): {e}"
        raise HTTPException(status_code=502, detail=detail)

    return {"mock": mock, "checkout_url": checkout_url, "plan": _plan_payload()}


@app.post("/api/stripe/create-checkout")
async def stripe_create_checkout(request: Request, user: dict = Depends(_get_current_user)):
    """Alias autenticado para o checkout de pagamento avulso (7 dias)."""
    full = await db_service.get_user_by_id(user["id"])
    if not full:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Extract locale from Accept-Language header (sent by frontend)
    accept_language = request.headers.get("accept-language", "").lower()
    locale = "auto"
    if accept_language.startswith("pt"):
        locale = "pt"
    elif accept_language.startswith("en"):
        locale = "en"
    elif accept_language.startswith("es"):
        locale = "es"

    try:
        mock, checkout_url = await _create_stripe_checkout_session(
            user["id"], locale, full.get("email")
        )
    except Exception as e:
        logger.error(f"Erro ao criar checkout Stripe: {type(e).__name__}: {e}")
        detail = "Falha ao iniciar checkout"
        if hasattr(e, 'user_message'):
            detail = f"Stripe: {e.user_message}"
        elif hasattr(e, 'code'):
            detail = f"Stripe error ({e.code}): {e}"
        raise HTTPException(status_code=502, detail=detail)
    return {
        "mock": mock,
        "checkout_url": checkout_url,
        "plan": _plan_payload(),
        "mode": "payment",
        "currency": "usd",
        "access_days": 7,
    }


@app.post("/api/billing/mock-activate", include_in_schema=False)
async def mock_activate_disabled(user: dict = Depends(_get_current_user)):
    """Rota DESATIVADA.

    Existia para ambiente de desenvolvimento e concedia +1 semana de plano Pro
    sem qualquer verificacao de pagamento no Stripe. Qualquer utilizador
    autenticado podia auto-assinar. Removida em favor do webhook Stripe, que
    valida a assinatura e e a unica via de ativacao de plano.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "Endpoint desativado. A subscricao e ativada exclusivamente via "
            "Stripe (webhook checkout.session.completed)."
        ),
    )


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(None)):
    """Webhook do Stripe: valida assinatura e libera 7 dias de acesso (idempotente).

    Fluxo (pagamento avulso, SEM recorrência):
      1. Valida Stripe-Signature com STRIPE_WEBHOOK_SECRET (fail-closed).
      2. Em checkout.session.completed: registra event_id (idempotência) e
         estende o acesso do user_id (metadata) em +7 dias.
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET não configurado — webhook recusado")
        return JSONResponse(status_code=503, content={"status": "not_configured"})
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Header Stripe-Signature ausente")

    payload = await request.body()
    try:
        stripe.api_key = settings.STRIPE_API_KEY
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        logger.warning(f"Stripe webhook: assinatura inválida ({e})")
        raise HTTPException(status_code=400, detail="Assinatura inválida")

    event_id = event.get("id")
    event_type = event.get("type")
    if not event_id:
        raise HTTPException(status_code=400, detail="Evento sem id")

    # Idempotência: nunca processa o mesmo evento duas vezes.
    # EXCEPÇÃO (Sprint 1): um `checkout.session.completed` registado mas SEM
    # acesso concedido (`granted=0`) tem de ser REPROCESSADO — o retry do
    # Stripe é a única forma de o cliente receber o acesso que pagou. Antes,
    # o evento era gravado ANTES do `extend_access` e um crash a meio
    # significava "cliente pagou e nunca recebeu acesso", em silencio.
    existing = await db_service.get_stripe_event(event_id)
    try:
        already_granted = int((existing or {}).get("granted", 1)) == 1
    except (TypeError, ValueError):
        already_granted = True
    if existing and (
        already_granted or event_type != "checkout.session.completed"
    ):
        return {"status": "received", "handled": True, "idempotent": True}
    if existing and event_type == "checkout.session.completed":
        logger.info(
            "Stripe %s: retoma concessao de acesso (evento visto sem efeito)",
            event_id,
        )

    if event_type == "checkout.session.completed":
        session_obj = (event.get("data") or {}).get("object") or {}
        meta = session_obj.get("metadata") or {}
        user_id_raw = meta.get("user_id") or session_obj.get("client_reference_id")
        if not user_id_raw:
            await db_service.record_stripe_event(event_id, event_type, None)
            logger.warning(f"Stripe {event_id}: checkout sem user_id — ignorado")
            return {"status": "received", "handled": False, "reason": "missing_user_id"}
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            await db_service.record_stripe_event(event_id, event_type, None)
            return {"status": "received", "handled": False, "reason": "invalid_user_id"}

        if not existing:
            # Fica com `granted=0`: só é marcado como concedido DEPOIS de o
            # acesso ser estendido (ver `mark_stripe_event_granted`).
            recorded = await db_service.record_stripe_event(
                event_id, event_type, user_id, granted=0
            )
            if not recorded:
                return {"status": "received", "handled": True, "idempotent": True}

        # Funil de checkout: fecha a sessao como paga.
        session_id = session_obj.get("id")
        if session_id:
            try:
                await db_service.update_checkout_session(
                    session_id, status="completed", completed_at=_now_iso()
                )
            except Exception as e:
                logger.warning("Falha ao marcar checkout como completed: %s", e)

        try:
            updated = await db_service.extend_access(user_id, days=7)
        except Exception as e:
            # A base pode estar busy: o evento fica com granted=0 e o retry do
            # Stripe volta a tentar. O cliente NAO fica sem acesso.
            logger.error(
                "Stripe %s: falha ao estender acesso do user %s (%s) — "
                "o retry do Stripe vai reprocessar",
                event_id, user_id, e,
            )
            return {"status": "received", "handled": False, "reason": "extend_access_failed"}
        if updated is None:
            logger.error(f"Stripe {event_id}: user {user_id} não encontrado")
            return {"status": "received", "handled": False, "reason": "user_not_found"}

        # O efeito foi aplicado: agora sim, o evento fica como processado.
        await db_service.mark_stripe_event_granted(event_id)

        customer_id = session_obj.get("customer")
        if customer_id:
            try:
                await db_service.set_user_stripe(user_id, customer_id, None)
            except Exception as e:
                logger.warning(f"Stripe: falha ao salvar customer {customer_id}: {e}")

        logger.info(f"Stripe: acesso +7 dias liberado para user {user_id} (event {event_id})")
        return {
            "status": "received",
            "handled": True,
            "idempotent": False,
            "user_id": user_id,
            "plan_until": updated.get("plan_until"),
        }

    # Demais eventos: registra para idempotência e ignora.
    await db_service.record_stripe_event(event_id, event_type, None)
    # Funil de checkout: uma sessao que expirou SEM pagamento e' o ponto de
    # perda que o e-mail de recuperacao tem de atacar.
    if event_type == "checkout.session.expired":
        expired_id = ((event.get("data") or {}).get("object") or {}).get("id")
        if expired_id:
            try:
                await db_service.update_checkout_session(expired_id, status="expired")
            except Exception as e:
                logger.warning("Falha ao marcar checkout como expired: %s", e)
    return {"status": "received", "handled": False}


@app.get("/api/users/me/interests")
async def get_my_interests(user: dict = Depends(_get_current_user)):
    """Interesses do utilizador autenticado (atalho para o onboarding)."""
    return {
        "categories": await db_service.get_user_interests(user["id"]),
        "cities": await db_service.get_user_cities_filter(user["id"]),
    }


@app.put("/api/users/me/interests")
async def set_my_interests(payload: OnboardingUpdate, user: dict = Depends(_get_current_user)):
    """Grava categorias e (opcionalmente) cidades do utilizador autenticado.

    É o endpoint usado pelo Onboarding Wizard. Um PUT com `categories` vazio
    é rejeitado: "sem interesses" traz o fallback de todas as categorias no
    backend, pelo que gravar vazio seria uma escolha que se perde.
    """
    if not payload.categories:
        raise HTTPException(status_code=400, detail="Escolha pelo menos uma categoria")
    ok = await db_service.set_user_interests(user["id"], payload.categories)
    if not ok:
        raise HTTPException(status_code=500, detail="Erro ao salvar interesses")
    if payload.cities is not None:
        await db_service.set_user_cities_filter(user["id"], payload.cities)
    return {
        "categories": await db_service.get_user_interests(user["id"]),
        "cities": await db_service.get_user_cities_filter(user["id"]),
    }


@app.get("/api/users/me/onboarding")
async def get_my_onboarding(user: dict = Depends(_get_current_user)):
    """Estado do onboarding: concluído quando há ≥1 categoria escolhida."""
    categories = await db_service.get_user_interests(user["id"])
    return {
        "completed": len(categories) > 0,
        "categories": categories,
        "cities": await db_service.get_user_cities_filter(user["id"]),
    }


@app.post("/api/users/me/onboarding")
async def complete_my_onboarding(payload: OnboardingUpdate, user: dict = Depends(_get_current_user)):
    """Conclui o onboarding numa única chamada (categorias + cidades)."""
    if not payload.categories:
        raise HTTPException(status_code=400, detail="Escolha pelo menos uma categoria")
    ok = await db_service.set_user_interests(user["id"], payload.categories)
    if not ok:
        raise HTTPException(status_code=500, detail="Erro ao salvar interesses")
    await db_service.set_user_cities_filter(user["id"], payload.cities)
    return {
        "completed": True,
        "categories": await db_service.get_user_interests(user["id"]),
        "cities": await db_service.get_user_cities_filter(user["id"]),
    }


@app.get("/api/users/{user_id}/score")
async def user_score(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    score = await db_service.get_user_score(user_id)
    if not score:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return score


@app.get("/api/users/{user_id}/interests")
async def get_interests(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    return {"categories": await db_service.get_user_interests(user_id)}


@app.put("/api/users/{user_id}/interests")
async def set_interests(
    user_id: int, payload: InterestsUpdate,
    user: dict = Depends(_get_current_user),
):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    ok = await db_service.set_user_interests(user_id, payload.categories)
    if not ok:
        raise HTTPException(status_code=500, detail="Erro ao salvar interesses")
    return {"categories": await db_service.get_user_interests(user_id)}


@app.get("/api/users/{user_id}/interests/push")
async def get_interests_push(user_id: int, user: dict = Depends(_get_current_user)):
    """Estado do sino de push por oficio (B2)."""
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    return {"settings": await db_service.get_user_interest_settings(user_id)}


@app.patch("/api/users/{user_id}/interests/{category}/push")
async def set_interest_push(
    user_id: int, category: str, payload: InterestPushUpdate,
    user: dict = Depends(_get_current_user),
):
    """Liga/desliga o push de uma categoria; o in-app continua sempre."""
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    ok = await db_service.set_user_interest_push(user_id, category, payload.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="Interesse não encontrado")
    return {"settings": await db_service.get_user_interest_settings(user_id)}


@app.get("/api/users/{user_id}/cities-filter")
async def get_cities_filter(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    cities = await db_service.get_user_cities_filter(user_id)
    return {"cities": cities}


@app.put("/api/users/{user_id}/cities-filter")
async def set_cities_filter(
    user_id: int, cities: list[str] | None = None,
    user: dict = Depends(_get_current_user),
):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    ok = await db_service.set_user_cities_filter(user_id, cities)
    if not ok:
        raise HTTPException(status_code=500, detail="Erro ao salvar cidades")
    return {"cities": await db_service.get_user_cities_filter(user_id)}


@app.put("/api/users/{user_id}/base-location")
async def set_base_location(
    user_id: int, payload: BaseLocationUpdate,
    user: dict = Depends(_get_current_user),
):
    """Guarda a base para mostrar a distância nos alertas.

    A distância é apenas informativa/ordenação: NÃO cria raio de exclusão.
    Fonte `city` usa o centroide da cidade (distância omitida no push).
    """
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    source = (payload.source or "gps").strip().lower()
    if source not in ("gps", "manual", "city"):
        raise HTTPException(status_code=422, detail="source inválido")
    if not (-90 <= payload.lat <= 90 and -180 <= payload.lng <= 180):
        raise HTTPException(status_code=422, detail="Coordenadas inválidas")
    ok = await db_service.set_user_base_location(
        user_id, payload.lat, payload.lng, source, payload.label
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    full = await db_service.get_user_by_id(user_id)
    return _user_response(full) if full else {"status": "ok"}


@app.delete("/api/users/{user_id}/base-location")
async def delete_base_location(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    await db_service.clear_user_base_location(user_id)
    full = await db_service.get_user_by_id(user_id)
    return _user_response(full) if full else {"status": "ok"}


@app.patch("/api/users/{user_id}/push-preferences")
async def set_push_preferences(
    user_id: int, payload: PushPreferencesUpdate,
    user: dict = Depends(_get_current_user),
):
    """Preferências de comunicação: morada, digest e ciclo de vida (B2)."""
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    if payload.show_address_in_push is not None:
        await db_service.set_show_address_in_push(
            user_id, payload.show_address_in_push
        )
    if payload.digest_enabled is not None:
        await db_service.set_user_digest_enabled(user_id, payload.digest_enabled)
    if payload.lifecycle_push_enabled is not None:
        await db_service.set_user_lifecycle_push_enabled(
            user_id, payload.lifecycle_push_enabled
        )
    if payload.chime_enabled is not None:
        await db_service.set_user_chime_enabled(user_id, payload.chime_enabled)
    full = await db_service.get_user_by_id(user_id)
    return _user_response(full) if full else {"status": "ok"}


# ------------------------------------------------------------------
# Notificações por usuário
# ------------------------------------------------------------------
@app.get("/api/users/{user_id}/notifications", response_model=list[NotificationResponse])
async def user_notifications(
    user_id: int,
    filter: str = "recent",
    limit: int = 50,
    unread: int = None,
    user: dict = Depends(_get_current_user),
):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    if unread == 1:
        filter = "unread"
    user_row = await db_service.get_user_by_id(user_id) or {}
    locale = user_row.get("locale")
    rows = await db_service.get_notifications_for_user(
        user_id, filter=filter, limit=limit
    )
    out = []
    for r in rows:
        item = _localize_notification(r, locale)
        out.append(NotificationResponse(
            id=item["id"],
            type=item["type"],
            title=item["title"],
            message=item["message"],
            lead_id=item.get("lead_id"),
            created_at=item["created_at"],
            read=bool(item.get("read")),
        ))
    return out


@app.get("/api/users/{user_id}/notifications/unread-count")
async def user_unread_count(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    return {"unread": await db_service.count_unread_notifications_for_user(user_id)}


@app.post("/api/users/{user_id}/notifications/{notification_id}/read")
async def user_mark_read(
    user_id: int, notification_id: int,
    user: dict = Depends(_get_current_user),
):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    ok = await db_service.mark_notification_read_for_user(notification_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notificação não encontrada")
    return {"status": "ok"}


@app.post("/api/users/{user_id}/notifications/read-all")
async def user_mark_all_read(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    marked = await db_service.mark_all_notifications_read_for_user(user_id)
    return {"status": "ok", "marked": marked}


# ------------------------------------------------------------------
# Status / Hold (reserva exclusiva) / ações de pipeline por usuário
# ------------------------------------------------------------------
@app.get("/api/leads/{lead_id}/status", response_model=LeadStatusResponse)
async def lead_status(lead_id: int, user: dict = Depends(_get_current_user)):
    lead = await db_service.get_lead_with_status(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    return LeadStatusResponse(
        id=lead["id"],
        external_id=lead["external_id"],
        address=lead.get("address"),
        city=lead.get("city"),
        issue_category=lead.get("issue_category"),
        lead_status=lead.get("lead_status"),
        reserved_by=lead.get("reserved_by"),
        reserved_until=_to_iso_utc(lead.get("reserved_until")),
        stage_expires_at=_to_iso_utc(lead.get("stage_expires_at") or lead.get("reserved_until")),
        contact_count=lead.get("contact_count") or 0,
        converted_by=lead.get("converted_by"),
        converted_at=lead.get("converted_at"),
        created_at=lead.get("created_at"),
    )


@app.post("/api/leads/{lead_id}/reserve", response_model=LeadHoldResponse)
@limiter.limit("20/minute")
async def reserve_lead(
    request: Request, lead_id: int, payload: ReserverLeadRequest,
    user: dict = Depends(_get_current_user),
):
    user_id = user["id"]

    # 1. GATE DE ASSINATURA (A5): 402 + REDIRECT_TO_CHECKOUT.
    await _require_active_access(user)

    # 1.1 Sinaliza contato nos reveals em aberto (watchdog para de notificar)
    await db_service.flag_reveal_contact(user_id, lead_id)

    minutes = payload.minutes or 60
    quota_exhausted = False

    # 2. COM CONSENTIMENTO => REVEAL (reserva 60min + conta 1/10 com idempotência)
    #
    # ORDEM CRÍTICA: o crédito NUNCA é debitado antes de os dados essenciais
    # (owner_name + owner_phone) estarem confirmados. O fluxo é:
    #   2.1 pré-validação sem débito  -> 2.2 enriquecimento  -> 2.3 regra A
    #   -> 2.4 reveal_lead (único ponto que debita)
    # Se os dados essenciais faltarem, o lead é ENTREGUE na mesma mas sem débito
    # e sem consumir cota. Nunca devolvemos 422 por isso.
    if payload.consent:
        key = payload.idempotency or f"{user_id}:{lead_id}"

        # 2.1 PRÉ-VALIDAÇÃO SEM EFEITO COLATERAL (não debita, não reserva)
        pre = await db_service.precheck_reveal(user_id, lead_id)
        pre_status = pre.get("status")
        pre_lead = pre.get("lead") or {}

        if pre_status == "not_found":
            raise HTTPException(status_code=404, detail="Lead não encontrado")

        if pre_status == "already_reserved":
            # Return lead data even when already reserved, so frontend can update UI
            return JSONResponse(
                status_code=409,
                content={
                    "error": "already_reserved",
                    "detail": "Lead já reservado por você",
                    "lead": {
                        "id": pre_lead.get("id"),
                        "owner_name": pre_lead.get("owner_name"),
                        "owner_phone": pre_lead.get("owner_phone"),
                        "owner_email": pre_lead.get("owner_email"),
                        "mailing_address": pre_lead.get("mailing_address"),
                        "my_status": "reserved",
                        "status": "reserved",
                        "visibility_status": "reserved_by_me",
                        "reserved_by_me": { "expires_at": pre_lead.get("reserved_until") },
                    }
                }
            )

        if pre_status == "limit_reached":
            raise HTTPException(
                status_code=429,
                detail="Limite de 10 leads/dia atingido. Volte amanhã e abra seus 10+ potenciais clientes."
            )

        # P0-C1B: pre-verificacao de cota ANTES da Searchbug. Se a cota
        # acabou, o lead e' entregue na MESMA sem telefone e sem custo (a
        # reserva gratis nao pode ser fechada), mas nenhuma chamada paga e'
        # feita. Leads gratuitos (sem nome) nao passam por aqui.
        if will_charge_if_phone_found(pre_lead):
            _daily = await db_service.get_daily_leads_used(user_id)
            if int(_daily.get("remaining", 1)) <= 0:
                quota_exhausted = True
                logger.info(
                    "[RESERVE] cota esgotada para user %s — lookup pago saltado, "
                    "lead entregue sem telefone", user_id,
                )

        # 2.1 ENRIQUECIMENTO / ENTREGA
        # Regra A: o lead e SEMPRE entregue. Nao existe mais bloqueio por dados
        # (o antigo 422 escondia a oportunidade e negava a "reserva gratis"
        # prometida na landing page). O que decide o preco e apenas
        # `charges_credit()` mais abaixo: so sucesso total (nome + telefone) e
        # cobrado; qualquer outro perfil e entregue com 0 creditos.
        #
        # Nota: o re-clique no mesmo lead com reveal ativo hoje nao consome um
        # segundo credito, e esse comportamento continua a ser tratado dentro de
        # `reveal_lead(charge_credit=...)`.
        lead = dict(pre_lead)

        # 2.2 ENRIQUECIMENTO ON-DEMAND — ANTES de qualquer débito
        owner_name = lead.get("owner_name")
        owner_phone = lead.get("owner_phone")
        mailing_address = lead.get("mailing_address")

        needs_enrichment = not owner_name or not owner_phone or not mailing_address
        logger.info(f"[RESERVE] Enrichment check: needs_enrichment={needs_enrichment} owner_name={bool(owner_name)} owner_phone={bool(owner_phone)} mailing_address={bool(mailing_address)}")

        if needs_enrichment:
            try:
                # Enriquecimento de nome + mailing address (Socrata/CKAN)
                logger.info(f"[RESERVE] Calling owner_enrichment.enrich for lead_id={lead_id}")
                enrich_result = await owner_enrichment.enrich(
                    lead.get("address", ""),
                    lead.get("city", ""),
                    bbl=lead.get("bbl") if hasattr(lead, "get") else None,
                )
                logger.info(f"[RESERVE] owner_enrichment result: {enrich_result}")
                if not enrich_result:
                    logger.warning(f"[RESERVE] owner_enrichment returned None/empty for lead_id={lead_id}")
                if enrich_result:
                    if not owner_name and enrich_result.get("owner_name"):
                        owner_name = enrich_result["owner_name"]
                        await db_service.update_owner(lead_id, owner_name)
                    if not mailing_address and enrich_result.get("mailing_address"):
                        mailing_address = enrich_result["mailing_address"]
                        await db_service.update_mailing_address(lead_id, mailing_address)

                # Busca de telefone (Searchbug em prod, mock em dev)
                if not owner_phone:
                    # Re-checa a cota DEPOIS do enriquecimento gratuito: um
                    # lead sem nome pode ganhar nome (e passar a cobravel) aqui.
                    if will_charge_if_phone_found(lead) and not quota_exhausted:
                        _daily = await db_service.get_daily_leads_used(user_id)
                        if int(_daily.get("remaining", 1)) <= 0:
                            quota_exhausted = True
                    if quota_exhausted:
                        logger.info(
                            "[RESERVE] cota esgotada para user %s — lookup pago "
                            "saltado, lead entregue sem telefone", user_id,
                        )
                    else:
                        # P0-C1B: orcamento de tentativas POR UTILIZADOR
                        # (30/dia, 3/min). Nao existe cap global. Cobre qualquer
                        # chamada paga, inclusive L3 sem nome (que nao consome
                        # cota porque a entrega fica incompleta).
                        if will_call_provider(
                            lead, bool(getattr(settings, "PHONE_L3_UNNAMED_ENABLED", False))
                        ):
                            _attempt = await db_service.reserve_phone_attempt(user_id)
                            if not _attempt.get("ok"):
                                raise HTTPException(
                                    status_code=429,
                                    detail=(
                                        "Limite de tentativas de telefone atingido "
                                        f"({_attempt.get('reason')}). Tente novamente mais tarde."
                                    ),
                                )
                        logger.info(f"[RESERVE] Calling searchbug_service.lookup_phone for lead_id={lead_id}")
                        phone_result = await searchbug_service.lookup_phone(
                            lead.get("address", ""),
                            lead.get("city", ""),
                            lead.get("state", ""),
                            owner_name=owner_name,
                            zip_code=lead.get("zip_code") or lead.get("zip"),
                            owner_class=get_owner_class(owner_name),
                            lead_id=lead_id,
                        )
                        logger.info(
                            f"[RESERVE] searchbug result: success={phone_result.success} "
                            f"phone={phone_result.phone} verified={phone_result.verified} "
                            f"match={phone_result.name_match} error={phone_result.error}"
                        )
                        if phone_result.success and phone_result.phone:
                            owner_phone = phone_result.phone
                            await db_service.update_owner_phone(
                                lead_id, owner_phone, verified=phone_result.verified
                            )
                        else:
                            # Distinguir quem consultou o provider (custo real) de quem o
                            # guard impediu (custo zero). Antes dizia "Searchbug phone
                            # lookup sem resultado" nos dois casos, o que levava um
                            # operador a concluir que tinha havido chamada paga.
                            _err = str(phone_result.error or "")
                            if _err.startswith("guard_skipped:"):
                                logger.info(
                                    f"[PHONE][guard_skipped] lead {lead_id}: {_err} — "
                                    f"Searchbug NAO foi consultado, custo zero"
                                )
                            elif phone_result.provider == "cache":
                                logger.info(
                                    f"[PHONE][cache_hit] lead {lead_id}: {_err} — "
                                    f"servido do cache, sem nova chamada"
                                )
                            else:
                                logger.warning(
                                    f"[PHONE][provider_no_results] lead {lead_id}: {_err} — "
                                    f"Searchbug foi consultado e nao devolveu telefone"
                                )
            except HTTPException:
                raise
            except Exception as e:
                logger.warning(f"Enriquecimento on-demand falhou para lead {lead_id}: {e}")

            # Recarrega lead com os dados enriquecidos já persistidos
            enriched_lead = await db_service.get_lead_by_id(lead_id)
            if enriched_lead:
                lead = dict(enriched_lead)

        # 2.3 REGRA A: ENTREGA E COBRANCA DESACOPLADAS.
        #
        # O lead e SEMPRE entregue. O que muda com a qualidade dos dados e so se
        # ha cobranca e consumo de cota:
        #   1) Lead padrao      -> owner_name + owner_phone               -> debita credito
        #   2) Lead corporativo -> owner_name + mailing_address, sem phone -> de graca
        #   3) Lead incompleto  -> sem phone e sem morada                  -> de graca,
        #                           entregue com aviso de "dados protegidos"
        #
        # Nao devolvemos 422 por dados incompletos: isso escondia o lead do
        # utilizador e negava a "reserva gratis" prometida na landing page. A
        # qualidade dos dados nunca bloqueia a entrega -- decide o preco e o aviso.
        missing_critical = missing_critical_fields(lead)
        charge_credit = charges_credit(lead)
        is_corporate = is_corporate_lead(lead)
        incomplete_delivery = bool(missing_critical)

        if incomplete_delivery:
            logger.info(
                f"[RESERVE] Lead {lead_id} ENTREGUE DE GRACA - "
                f"missing={missing_critical} corporate={is_corporate}"
            )

        # 2.4 UNICO PONTO QUE DEBITA CREDITO -- so quando charge_credit=True.
        # Com charge_credit=False a reserva e criada e o lead e devolvido, mas
        # sem tocar em `user_daily_stats` (nem cota, nem credito).
        logger.info(
            f"[RESERVE] Calling reveal_lead user_id={user_id} lead_id={lead_id} "
            f"key={key} minutes={minutes} corporate={is_corporate}"
        )
        try:
            result = await db_service.reveal_lead(
                user_id, lead_id, key, minutes=minutes, charge_credit=charge_credit
            )
            logger.info(f"[RESERVE] reveal_lead result: {result}")
        except Exception as e:
            logger.exception(f"[RESERVE] EXCEPTION in reveal_lead user_id={user_id} lead_id={lead_id}: {e}")
            raise HTTPException(status_code=500, detail="Erro interno. Detalhe registado nos logs do servidor.")

        if not result:
            raise HTTPException(status_code=404, detail="Lead não encontrado")
        if result.get("error") == "not_found":
            raise HTTPException(status_code=404, detail="Lead não encontrado")
        if result.get("error") == "already_reserved":
            # Corrida: outro usuário reservou entre o precheck e o reveal.
            lost = result.get("lead") or {}
            return JSONResponse(
                status_code=409,
                content={
                    "error": "already_reserved",
                    "detail": "Lead já reservado por você",
                    "lead": {
                        "id": lost.get("id"),
                        "owner_name": lost.get("owner_name"),
                        "owner_phone": lost.get("owner_phone"),
                        "owner_email": lost.get("owner_email"),
                        "mailing_address": lost.get("mailing_address"),
                        "my_status": "reserved",
                        "status": "reserved",
                        "visibility_status": "reserved_by_me",
                        "reserved_by_me": { "expires_at": lost.get("reserved_until") },
                    }
                }
            )
        if result.get("error") == "limit_reached":
            raise HTTPException(
                status_code=429,
                detail="Limite de 10 leads/dia atingido. Volte amanhã e abra seus 10+ potenciais clientes."
            )

        revealed_lead = result.get("lead") or {}
        if revealed_lead:
            lead = dict(revealed_lead)

        # Registra interação (o crédito, quando devido, já foi debitado em reveal_lead)
        await db_service.record_event(lead_id, "revealed")

        return JSONResponse(
        status_code=200,
        content={
            "reserved": True,
            "revealed": True,
            "status": lead.get("lead_status", "reserved"),
            "expires_at": _to_iso_utc(lead.get("reserved_until")),
            "my_status": "reserved",
            "stage": lead.get("lead_status", "reserved"),
            "stage_expires_at": _to_iso_utc(lead.get("stage_expires_at") or lead.get("reserved_until")),
            "server_now": utcnow().isoformat() + "Z",
            "message": (
                "Dados revelados — reserva de 1 hora ativa"
                if charge_credit
                else "Dados revelados sem custo — reserva de 1 hora ativa"
            ),
            "counted_again": result.get("counted_again", True),
            "used": result.get("used"),
            "limit": result.get("limit"),
            "remaining": result.get("remaining"),
            "reset_at": result.get("reset_at"),
            "corporate": is_corporate,
            "charged": charge_credit,
            "incomplete_delivery": incomplete_delivery,
            "missing": missing_critical,
            "owner": {
                "name": lead.get("owner_name"),
                "phone": lead.get("owner_phone"),
                "email": lead.get("owner_email"),
                "mailing_address": lead.get("mailing_address"),
                "address": lead.get("address"),
                "city": lead.get("city"),
            },
        },
        )

    # 3. SEM CONSENTIMENTO: reserva simples, SEM dados do proprietario e SEM
    # chamada paga. O fluxo antigo chamava a Searchbug e consumia cota antes de
    # saber se havia telefone; a chamada paga foi removida. A reserva simples
    # continua a consumir 1 unidade de cota (anti-abuso de holds), de forma
    # atomica.
    if not await db_service.increment_daily_leads(user_id):
        raise HTTPException(
            status_code=429,
            detail="Limite de 10 leads/dia atingido. Volte amanhã e abra seus 10+ potenciais clientes.",
        )
    result = await db_service.reserve_lead_only(lead_id, user["id"], minutes=minutes)
    if not result:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    if result.get("error") == "already_reserved":
        raise HTTPException(status_code=409, detail="Lead já reservado por outro usuário")
    if result.get("error") == "suspended":
        raise HTTPException(
            status_code=403,
            detail=f"Conta suspensa por penalidades até {result.get('penalty_until', '')}",
        )
    if result.get("error") == "reduced_delay":
        raise HTTPException(
            status_code=429,
            detail=result.get("message", "Prioridade reduzida: aguarde 5min entre reservas"),
        )

    # Registra interação
    await db_service.record_event(lead_id, "reserve")

    return LeadHoldResponse(
        reserved=True,
        status=result.get("lead_status", "reserved"),
        expires_at=result.get("reserved_until"),
        message="Lead reservado com exclusividade por 1 hora",
    )


@app.post("/api/leads/{lead_id}/release", response_model=LeadHoldResponse)
async def release_lead(
    lead_id: int, payload: ReleaseLeadRequest,
    user: dict = Depends(_get_current_user),
):
    result = await db_service.release_lead(
        lead_id, user["id"], reason=payload.reason, note=payload.note
    )
    if not result:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    if result.get("error") == "not_owner":
        raise HTTPException(status_code=403, detail="Este lead está reservado por outro usuário")
    penalty = result.get("_penalty") or {}
    message = "Lead liberado com motivo registrado"
    if penalty.get("penalty_level", 0) >= 3:
        message = "Suspensão: prioridade de reservas bloqueada por 30 dias"
    elif penalty.get("penalty_level", 0) == 2:
        message = "Alerta: prioridade reduzida — 5min entre reservas"
    elif penalty.get("penalty_level", 0) == 1:
        message = "Alerta: releases suspeitos contados para suspensão"
    return LeadHoldResponse(
        reserved=False,
        status=result.get("lead_status", "available"),
        expires_at=None,
        message=message,
    )


@app.post("/api/leads/{lead_id}/contact")
async def contact_lead(
    lead_id: int, payload: ContactLeadRequest,
    user: dict = Depends(_get_current_user),
):
    # A5: contacto é uma ação de valor; conta expirada não avança o ciclo.
    await _require_active_access(user)
    lead = await db_service.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    if payload.channel in ("sms", "whatsapp", "phone") and not (lead.get("owner_phone") or "").strip():
        raise HTTPException(status_code=400, detail="Canal exige telefone cadastrado")
    if payload.channel == "email" and not (lead.get("owner_email") or "").strip():
        raise HTTPException(status_code=400, detail="Canal exige e-mail cadastrado")
    if payload.channel in ("visit", "mail"):
        from backend.utils.address import is_intersection
        if is_intersection(lead.get("address")):
            raise HTTPException(status_code=400, detail="Visita ou carta exige endereço predial e não esquina")
    result = await db_service.record_contact(lead_id, user["id"], payload.channel)
    if not result:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    if result.get("error") == "already_reserved":
        raise HTTPException(status_code=409, detail="Lead reservado por outro usuário")
    # Sinalizou contacto => o watchdog de reveals deixa de notificar o empreiteiro
    try:
        await db_service.flag_reveal_contact(user["id"], lead_id)
    except Exception:
        pass
    return {"status": "ok", "channel": payload.channel, "contact_count": result.get("contact_count", 0)}


@app.post("/api/leads/{lead_id}/reveal-phone")
@limiter.limit("20/minute")
async def reveal_phone_endpoint(
    request: Request,
    lead_id: int,
    user: dict = Depends(_get_current_user),
):
    """Busca o telefone de um lead que ja tem proprietario identificado (Phase 4).

    Caminho "on-demand" do dashboard (frontend `revealPhone`): o botao so
    aparece quando existe `owner_name` e falta `owner_phone`. Antes este
    endpoint simplesmente NAO EXISTIA — `fetch` devolvia 404 e o botao caia no
    toast de erro generico.

    Reutiliza o mesmo caminho de dados do fluxo /reserve
    (owner_enrichment.enrich -> searchbug_service.lookup_phone ->
    update_owner_phone), com a mesma protecao de cota diaria: sem isso o
    botao permitiria procuras pagas ilimitadas sem reserva nem debito de
    creditos.

    Contrato devolvido (frontend/lib/api-client.ts `PhoneRevealResult`):
    `success=false` sai com HTTP 200 + `error` — e o que o handler da UI
    espera (`result.success`/`result.error`), nao uma excecao.
    """
    user_id = user["id"]
    try:
        # A5: 402 com action de renovação (igual a reservar/revelar).
        await _require_active_access(user)

        pre = await db_service.precheck_reveal(user_id, lead_id)
        pre_status = pre.get("status")
        pre_lead = pre.get("lead") or {}
        if pre_status == "not_found":
            raise HTTPException(status_code=404, detail="Lead não encontrado")
        if pre_status == "already_reserved":
            return {"success": False, "error": "already_reserved"}

        # Ja tem telefone: nada a procurar (evita chamada paga repetida).
        if pre_lead.get("owner_phone"):
            return {"success": True, "phone": pre_lead.get("owner_phone")}
        if not pre_lead.get("owner_name"):
            return {"success": False, "error": "owner_name_missing"}

        # P0-C1B: reserva atomica da cota ANTES da chamada paga. Se a busca
        # falhar, o `finally` devolve a unidade — "falha e' gratis".
        reserved = await db_service.reserve_daily_quota(user_id)
        if not reserved:
            return {"success": False, "error": "daily_limit_reached"}

        attempt = await db_service.reserve_phone_attempt(user_id)
        if not attempt.get("ok"):
            await db_service.refund_daily_quota(user_id)
            return {
                "success": False,
                "error": f"attempt_limit_{attempt.get('reason', 'unknown')}",
            }

        phone = None
        provider = None
        owner_name = pre_lead.get("owner_name")
        keep = False
        try:
            enrich_result = await owner_enrichment.enrich(
                pre_lead.get("address", ""),
                pre_lead.get("city", ""),
                bbl=pre_lead.get("bbl") if hasattr(pre_lead, "get") else None,
            )
            if enrich_result:
                if not owner_name and enrich_result.get("owner_name"):
                    owner_name = enrich_result["owner_name"]
                    await db_service.update_owner(lead_id, owner_name)
                if owner_name:
                    phone_result = await searchbug_service.lookup_phone(
                        pre_lead.get("address", ""),
                        pre_lead.get("city", ""),
                        pre_lead.get("state", ""),
                        owner_name=owner_name,
                        zip_code=pre_lead.get("zip_code") or pre_lead.get("zip"),
                        owner_class=get_owner_class(owner_name),
                        lead_id=lead_id,
                    )
                    if phone_result.success and phone_result.phone:
                        phone = phone_result.phone
                        provider = getattr(phone_result, "provider", None)
                        await db_service.update_owner_phone(
                            lead_id, phone, verified=phone_result.verified
                        )
                    else:
                        # guarda_skipped:* = custo zero (o guard de custo
                        # recusou); nao e o mesmo que provider sem resultados.
                        logger.info(
                            f"[PHONE][reveal-phone] lead {lead_id}: "
                            f"{phone_result.error or 'provider sem resultado'}"
                        )
        except Exception as e:
            logger.warning(f"reveal-phone: enriquecimento falhou lead {lead_id}: {e}")
        finally:
            if not phone:
                refreshed = await db_service.get_lead_by_id(lead_id)
                if refreshed:
                    phone = dict(refreshed).get("owner_phone") or None
            if phone:
                keep = True
            if not keep:
                await db_service.refund_daily_quota(user_id)

        if not phone:
            return {"success": False, "error": "phone_not_found"}

        await db_service.record_event(lead_id, "revealed")
        return {"success": True, "phone": phone, "provider": provider or "searchbug"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"reveal-phone failed for lead_id={lead_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")


@app.post("/api/leads/{lead_id}/report-invalid")
async def report_invalid_number(lead_id: int, user: dict = Depends(_get_current_user)):
    """Reporta número inválido/vazio para estorno de cota diária (Regra B).

    Regras:
    - Janela de 5 minutos após reveal (Regra B)
    - Lead não pode estar em negociação/convertido (Regra C)
    - Máximo 2 estornos por usuário/dia (Regra D)
    - Lead não pode ter refund_blocked
    """
    user_id = user["id"]

    # Valida permissões usando validação unificada
    safety = await db_service.validate_refund_safety(
        user_id,
        lead_id,
        check_active_reveal=True,
        check_time_window=True,      # Regra B: janela de 5 min
        check_lead_status=True,      # Regra C
        check_refund_blocked=True,
        check_daily_limit=True,      # Regra D
    )
    if not safety["allowed"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error": safety["reason"],
                "params": safety["params"],
            },
        )

    # Processa estorno (re-valida internamente)
    refund_result = await db_service.process_refund(
        user_id,
        lead_id,
        reason="invalid_number",
        check_active_reveal=True,
        check_time_window=True,
        check_lead_status=True,
        check_refund_blocked=True,
        check_daily_limit=True,
    )
    if not refund_result["success"]:
        raise HTTPException(
            status_code=400,
            detail={"error": refund_result["reason"], "params": refund_result.get("params", {})},
        )

    return {
        "status": "ok",
        "message": "Cota diária devolvida com sucesso",
        "refunds_remaining_today": refund_result["remaining"],
        "refund_count_today": refund_result["refund_count_today"],
    }


@app.post("/api/cron/freshness")
async def cron_freshness(x_cron_secret: str | None = Header(None)):
    """P1: dispara a re-verificacao HPD/DOB (o loop diario e' o caminho normal)."""
    _check_cron_secret(x_cron_secret)
    return await freshness.run_freshness()


# Cron: expira holds vencidos + watchdog de reveals (chamado por GitHub Actions a cada hora)
@app.get("/api/cron/expire-holds")
async def cron_expire_holds(x_cron_secret: str | None = Header(None)):
    _check_cron_secret(x_cron_secret)
    try:
        expired = await db_service.expire_holds()
        reveals = await db_service.check_reveal_watchdogs()
        lifecycle = await lifecycle_push.dispatch_lifecycle_pushes()
        return {
            "status": "ok",
            "expired_holds": expired,
            "reveals_processed": reveals,
            "lifecycle_pushed": lifecycle,
            "at": utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Erro no cron expire-holds: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao expirar holds")


# Consulta métricas/penalidades do contractor
@app.get("/api/contractor/metrics")
async def contractor_metrics(user: dict = Depends(_get_current_user)):
    metrics = await db_service.get_contractor_metrics(user["id"])
    if not metrics:
        return {"contractor_id": user["id"], "releases_this_month": 0, "suspicious_releases": 0, "penalty_level": 0, "penalty_until": None}
    return metrics


@app.post("/api/leads/{lead_id}/negotiate")
async def negotiate_lead(lead_id: int, user: dict = Depends(_get_current_user)):
    # A5: negociação é ação de valor; conta expirada bloqueia (402).
    await _require_active_access(user)
    result = await db_service.mark_negotiation(lead_id, user["id"])
    if not result:
        raise HTTPException(status_code=409, detail="Não foi possível marcar negociação")
    # Regra C: bloqueia estorno quando lead entra em negociação
    await db_service.block_lead_refund(lead_id, reason="negotiation_started")
    return {"status": "ok", "lead_status": result.get("lead_status")}


@app.post("/api/leads/{lead_id}/convert")
async def convert_lead(lead_id: int, user: dict = Depends(_get_current_user)):
    # A5: conversão é ação de valor; conta expirada bloqueia (402).
    await _require_active_access(user)
    result = await db_service.convert_lead(lead_id, user["id"])
    if not result:
        raise HTTPException(status_code=409, detail="Não foi possível confirmar conversão")
    # Regra C: bloqueia estorno quando lead é convertido
    await db_service.block_lead_refund(lead_id, reason="converted")
    return {"status": "ok", "lead_status": result.get("lead_status")}


@app.post("/api/leads/{lead_id}/reject")
async def reject_lead(
    lead_id: int, payload: RejectLeadRequest,
    user: dict = Depends(_get_current_user),
):
    result = await db_service.reject_lead(lead_id, user["id"], reason=payload.reason)
    if not result:
        raise HTTPException(status_code=409, detail="Não foi possível rejeitar o lead")
    return {"status": "ok", "lead_status": result.get("lead_status")}


async def _require_lead_possession(user: dict, lead_id: int) -> None:
    """Autorização por POSSE para os endpoints de histórico de um lead.

    Antes bastava ter qualquer sessão válida: um assinante que soubesse
    (ou adivinhasse) um `lead_id` lia o histórico e as ocorrências de
    qualquer imóvel da plataforma, incluindo moradas de clientes de outros
    contratores. Agora exige que o utilizador tenha reservas/reveals/conversão
    desse lead — ou seja, que tenha pago para o ver.

    Resposta 404 (não 403) quando não tem posse: confirmar "existe mas não é
    seu" já seria um oráculo de existência/enumeração de IDs.
    """
    probe = await db_service.get_user_by_id(user["id"])
    if probe and probe.get("is_admin"):
        return
    if await db_service.user_has_lead_history_access(user["id"], lead_id):
        return
    raise HTTPException(status_code=404, detail="Lead não encontrado")


@app.get("/api/leads/{lead_id}/history", response_model=list[HistoryEvent])
async def lead_history(lead_id: int, user: dict = Depends(_get_current_user)):
    await _require_lead_possession(user, lead_id)
    rows = await db_service.get_lead_history(lead_id)
    return [
        HistoryEvent(
            id=r["id"],
            lead_id=r["lead_id"],
            event_type=r["event_type"],
            detail=scrub(r.get("detail")),
            created_at=r["created_at"],
            user_id=r.get("user_id"),
        )
        for r in rows
    ]


@app.get("/api/leads/{lead_id}/occurrences")
async def lead_occurrences(lead_id: int, user: dict = Depends(_get_current_user)):
    """Timeline de ocorrências do imóvel (histórico de chamados no 311).
    Capturado pelo scraper (lead_case_history).

    Mesmo gate de posse de `/history`: sem ele, qualquer assinante lia a
    timeline de qualquer imóvel enumerando IDs.
    """
    await _require_lead_possession(user, lead_id)
    rows = await db_service.get_lead_case_history(lead_id)
    return [sanitize_lead(r) for r in rows]


@app.get("/api/me/taken-leads", response_model=LeadsListResponse)
async def my_taken_leads(limit: int = 100, user: dict = Depends(_get_current_user)):
    """Leads que o usuário logado já reservou/pegou."""
    rows = await db_service.list_leads_with_status(limit=limit)
    mine = [
        r for r in rows
        if r.get("reserved_by") == user["id"]
        or r.get("converted_by") == user["id"]
        or r.get("lead_status") in ("contacted", "in_negotiation", "converted")
    ]
    await _mark_revealed(mine, user)
    return LeadsListResponse(
        total=len(mine), page=1, per_page=limit, leads=[_to_lead_response(m) for m in mine]
    )


@app.get("/api/me/history")
async def my_leads_history(
    status: str | None = None,
    category: str | None = None,
    period: str | None = None,
    search: str | None = None,
    needs_action: bool = False,
    limit: int = 100,
    user: dict = Depends(_get_current_user),
):
    """Histórico completo 'Meus Leads' do usuário (reservas, negociações, conversões,
    liberações e holds expirados), agregado a partir de lead_holds."""
    try:
        rows, kpis = await db_service.get_user_leads_history(
            user["id"],
            status=status,
            category=category,
            period=period,
            search=search,
            needs_action=needs_action,
            limit=limit,
        )
        leads = []
        await _mark_revealed(rows, user)
        for r in rows:
            r["is_mine"] = True
            base = _to_lead_response(r).model_dump()
            base["my_status"] = r.get("my_status")
            base["hold_status"] = r.get("hold_status")
            base["held_at"] = r.get("held_at")
            base["hold_expires_at"] = r.get("hold_expires_at")
            base["hold_released_at"] = r.get("hold_released_at")
            base["release_reason"] = r.get("release_reason")
            base["contact_count"] = r.get("contact_count")
            base["converted_at"] = r.get("converted_at")
            base["reserved_until"] = r.get("reserved_until")
            base["favorited"] = bool(r.get("favorited"))
            leads.append(base)
        return {"kpis": kpis, "leads": leads}
    except Exception as e:
        logger.error(f"Erro ao buscar histórico de leads: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar histórico")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
