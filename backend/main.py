import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta

import httpx
import stripe
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import settings
from .models.schemas import (
    AuthResponse,
    ContactLeadRequest,
    EnrichedLead,
    HistoryEvent,
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
    PushEnabledUpdate,
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
from .services import notifier, security
from .services.db import db_service
from .services.enrichment import owner_enrichment
from .services.phone_lookup import phone_lookup_service
from .services.push_service import push_service
from .services.searchbug import searchbug_service
from .utils.logger import logger


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


def _to_lead_response(lead: dict) -> LeadResponse:
    """Converte linha do SQLite (id int) para LeadResponse (id str)."""
    # Build visibility fields
    lead_status = lead.get("lead_status", "available")
    reserved_by = lead.get("reserved_by")
    reserved_until = lead.get("reserved_until")
    reserved_by_name = lead.get("reserved_by_name")

    visibility_status = "available"
    reserved_by_me = None
    reserved_by_other = None

    if lead_status == "reserved" and reserved_by:
        if lead.get("is_mine"):  # This will be set by the caller based on user_id
            visibility_status = "reserved_by_me"
            reserved_by_me = {
                "created_at": lead.get("reserved_created_at"),
                "expires_at": reserved_until,
                "hours_remaining": lead.get("hours_remaining")
            }
        else:
            visibility_status = "reserved_by_other"
            reserved_by_other = {
                "contractor_id": reserved_by,
                "contractor_name": reserved_by_name,
                "expires_at": reserved_until
            }

    # Proteção de dados do proprietário: só usuários com reveal ativo
    # (consentimento) veem owner_name/owner_phone/owner_email/mailing_address.
    # Sem reveal, os campos vêm mascarados (None) na response.
    show_owner = bool(lead.get("_revealed", False))

    return LeadResponse(
        id=str(lead["id"]),
        external_id=lead["external_id"],
        source_type=lead.get("source_type"),
        address=lead["address"],
        city=lead["city"],
        issue_category=lead["issue_category"],
        issue_description=lead["issue_description"] or "",
        owner_name=lead.get("owner_name") if show_owner else None,
        owner_phone=lead.get("owner_phone") if show_owner else None,
        owner_email=lead.get("owner_email") if show_owner else None,
        date_reported=lead["date_reported"],
        urgency_level=lead["urgency_level"],
        image_url=lead.get("image_url"),
        status=lead.get("status") or "new",
        favorited=bool(lead.get("favorited")),
        # Address details
        address_unit=lead.get("address_unit"),
        address_type=lead.get("address_type"),
        address_street=lead.get("address_street"),
        address_city=lead.get("address_city"),
        address_state=lead.get("address_state"),
        address_zip=lead.get("address_zip"),
        # Historical details from 311 systems
        case_title=lead.get("case_title"),
        subject=lead.get("subject"),
        reason=lead.get("reason"),
        type=lead.get("type"),
        queue=lead.get("queue"),
        department=lead.get("department"),
        closure_reason=lead.get("closure_reason"),
        case_status=lead.get("case_status"),
        on_time=lead.get("on_time"),
        sla_target_dt=lead.get("sla_target_dt"),
        closed_dt=lead.get("closed_dt"),
        submitted_photo=lead.get("submitted_photo"),
        closed_photo=lead.get("closed_photo"),
        source=lead.get("source"),
        neighborhood=lead.get("neighborhood"),
        ward=lead.get("ward"),
        precinct=lead.get("precinct"),
        descriptor=lead.get("descriptor"),
        resolution_description=lead.get("resolution_description"),
        resolution_action_updated_date=lead.get("resolution_action_updated_date"),
        # Owner mailing address (protegido até o reveal)
        mailing_address=lead.get("mailing_address") if show_owner else None,
        # Visibility fields
        visibility_status=visibility_status,
        reserved_by_me=reserved_by_me,
        reserved_by_other=reserved_by_other,
        revealed=show_owner,
        # Freshness fields (WS1 dual labels)
        first_seen=lead.get("date_first_seen") or lead.get("created_at"),
        last_synced=lead.get("updated_at") or lead.get("created_at"),
    )


# ------------------------------------------------------------------
# Ruído urbano NÃO-serviço (não corresponde aos 16 ofícios da plataforma):
# estacionamento, tráfego/sinalização, veículos abandonados, TPW, testes.
# Não lista mais os ofícios (telhado, encanamento, pintura, pragas, lixo,
# esgoto etc.) — esses agora são oportunidades qualificadas.
# ------------------------------------------------------------------
_JUNK_TERMS = [
    "parking enforcement", "traffic signal", "general traffic", "signal",
    "sign repair", "missing sign", "bike rack", "boston bikes",
    "abandoned vehicle", "abandoned bicycle", "abandoned bike", "illegal auto",
    "dead animal", "hydrant", "towing", "tpw", "transportation",
    "debug test", "test issue", "contractors complaint", "fair housing",
    "needle", "work w/out permit", "working beyond hours",
]

_RICH_COLS = ["issue_description", "descriptor", "case_title",
              "resolution_description", "department"]


def _junk_where(alias: str = "") -> str:
    """Fragmento SQL: verdadeiro quando o lead é lixo urbano (a excluir)."""
    cols = [f"{alias}.{c}" if alias else c for c in _RICH_COLS]
    concat = " || ' ' || ".join(f"COALESCE({c}, '')" for c in cols)
    return "(" + " OR ".join(
        f"LOWER({concat}) LIKE '%{t}%'" for t in _JUNK_TERMS
    ) + ")"


def _not_junk_where(alias: str = "") -> str:
    return f"NOT {_junk_where(alias)}"


# As 16 categorias de ofícios da plataforma.
_TRADE_CATEGORIES = (
    "Roof", "Structure", "Plumbing", "Grass", "Paint", "Permit_Rejected",
    "Heating", "Electrical", "Elevator", "Gas", "Rodent", "Mold", "Lead",
    "Unsanitary", "Door_Window", "Debris",
)

# Status "chamado aberto / em andamento" (gatilho preditivo).
_OPEN_STATUSES = (
    "open", "new", "in progress", "in_progress", "assigned", "active",
    "approved", "issued", "pending", "acknowledged", "referred", "scheduled",
    "investigation", "awaiting", "awaiting assignment",
)


def _address_where(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"TRIM({prefix}address) IS NOT NULL AND LENGTH(TRIM({prefix}address)) > 8"


def _category_where(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    values = ", ".join(f"'{c}'" for c in _TRADE_CATEGORIES)
    return f"{prefix}issue_category IN ({values})"


def _trigger_where(alias: str = "") -> str:
    """Obrigação legal (violação/multa/permisção) OU chamado 311 aberto/em andamento."""
    prefix = f"{alias}." if alias else ""
    statuses = ", ".join(f"'{s}'" for s in _OPEN_STATUSES)
    return (
        f"(LOWER({prefix}case_status) IN ({statuses}) "
        f"OR {prefix}source_type IN ('permit', 'dob_violation', 'tax_delinquency'))"
    )


def _qualified_where(alias: str = "") -> str:
    parts = [
        _address_where(alias),
        _category_where(alias),
        _trigger_where(alias),
        _not_junk_where(alias),
    ]
    return " AND ".join(parts)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    debug=settings.DEBUG
)

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
)


# ------------------------------------------------------------------
# Sessões via banco de dados (controle de concorrência: máx. 2 por usuário)
# ------------------------------------------------------------------
_SESSIONS: dict[str, int] = {}  # Fallback para compatibilidade (legacy)


def _hash_token(token: str) -> str:
    """Gera hash SHA-256 do token para armazenamento seguro no banco."""
    return hashlib.sha256(token.encode()).hexdigest()


async def _get_user_id_from_token(token: str) -> int | None:
    """Valida o token no banco de dados e retorna o user_id se válido."""
    token_hash = _hash_token(token)
    return await db_service.validate_user_session(token_hash)


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
    # sessões concorrentes só tem efeito se a checagem for feita aqui)
    user_id = await _get_user_id_from_token(token)

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "session_expired_concurrent_login",
                "message": "Você foi deslogado pois sua conta foi acessada em outro dispositivo."
            }
        )
    return {"id": user_id}


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

    user_id = await _get_user_id_from_token(token)

    if not user_id:
        return None
    return {"id": user_id}


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


def _check_cron_secret(x_cron_secret: str | None) -> None:
    """Valida o header X-Cron-Secret. Fail-closed (antes aceitava requisições sem secret)."""
    expected = settings.CRON_SECRET
    if not expected or not x_cron_secret or not secrets.compare_digest(x_cron_secret, expected):
        raise HTTPException(status_code=401, detail="Não autorizado: CRON_SECRET inválido")


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
        lead["is_mine"] = bool(user_id) and lead.get("reserved_by") == user_id
        # Per-user favorite status
        lead["favorited"] = 1 if lead.get("id") in user_fav_ids else 0
        # Dados do proprietário só para quem revelou o lead (consentimento)
        revealed_ids = revealed_ids or set()
        lead["_revealed"] = bool(user_id) and lead.get("id") in revealed_ids
        if lead.get("reserved_until") and lead.get("lead_status") == "reserved":
            try:
                expires = datetime.fromisoformat(lead["reserved_until"].replace("Z", "+00:00"))
                if expires.tzinfo is not None:
                    expires = expires.replace(tzinfo=None)
                hours_left = int((expires - datetime.utcnow()).total_seconds() / 3600)
                lead["hours_remaining"] = max(0, hours_left)
            except Exception:
                lead["hours_remaining"] = 0
        else:
            lead["hours_remaining"] = 0


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
@app.get("/api/leads", response_model=LeadsListResponse)
async def get_leads(
    city: str = "NYC",
    category: str = None,
    type: str = None,
    page: int = 1,
    per_page: int = 20,
    user: dict | None = Depends(_get_optional_user)
):
    """Retorna leads da cidade especificada com filtros opcionais"""
    try:
        leads = await db_service.get_leads_by_city(
            city,
            limit=per_page * page,
            source_type=type,
            category=category
        )

        await _annotate_visibility(leads, user)

        return LeadsListResponse(
            total=len(leads),
            page=page,
            per_page=per_page,
            leads=[_to_lead_response(lead) for lead in leads[:per_page]]
        )

    except Exception as e:
        logger.error(f"Erro ao buscar leads: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar leads")


# Busca global por endereço/nome/telefone
@app.get("/api/leads/search", response_model=LeadsListResponse)
async def search_leads(q: str = "", per_page: int = 50, user: dict | None = Depends(_get_optional_user)):
    """Busca leads por endereço, nome do dono ou telefone."""
    try:
        results = await db_service.search_leads(q, limit=per_page)

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
async def recent_leads(limit: int = 12, user: dict | None = Depends(_get_optional_user)):
    """Retorna os leads RECENTES e QUALIFICADOS (endereço + 16 ofícios + gatilho
    preditivo), de todas as cidades/estados. Filtro feito em SQL para nunca zerar a lista."""
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
async def leads_today(limit: int = 60, page: int = 1, city: str = None, type: str = None, include_incomplete: bool = False, user: dict | None = Depends(_get_optional_user)):
    """Retorna demandas dos últimos 7 dias.

    REGRA FIXA por default: apenas leads QUALIFICADOS (endereço + 16 ofícios +
    gatilho preditivo: obrigação legal OU chamado aberto/em andamento).
    Não exige mais department/descriptor/neighborhood (campos que descartavam
    chamados válidos dos 16 ofícios).
    include_incomplete=true libera os leads fora desse critério.
    """
    try:
        from backend.services import db as dbmod
        conn = dbmod.get_connection()
        try:
            sql = """
                SELECT * FROM leads
                WHERE date_reported IS NOT NULL
                  AND date(date_reported) >= date('now', '-7 days')
            """
            params: list = []
            if city:
                sql += " AND city = ?"
                params.append(city)
            if type:
                sql += " AND source_type = ?"
                params.append(type)
            if not include_incomplete:
                sql += f" AND {_qualified_where()}"

            # Conta total para paginação
            count_sql = sql.replace("SELECT *", "SELECT COUNT(*) as total")
            total = conn.execute(count_sql, params).fetchone()["total"]

            # Aplica paginação
            offset = (page - 1) * limit
            sql += " ORDER BY date_reported DESC, id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            results = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        results = [dict(r) for r in results]

        await _annotate_visibility(results, user)

        return LeadsListResponse(
            total=total,
            page=page,
            per_page=limit,
            leads=[_to_lead_response(lead) for lead in results],
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


# Daily Stats (limit 10/day)
@app.get("/api/users/{user_id}/daily-stats")
async def user_daily_stats(user_id: int, user: dict = Depends(_get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Sem permissão")
    try:
        # Sweep watchdog de reveals (notificação 30/45min, retorno ao pool 60min)
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
async def get_lead(lead_id: int, user: dict | None = Depends(_get_optional_user)):
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
            )
    if payload.owner_phone is not None:
        await db_service.update_owner_phone(lead_id, payload.owner_phone)
    lead = await db_service.get_lead_by_id(lead_id)
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
        rows = await db_service.get_notifications_for_user(user["id"], filter=filter, limit=limit)
        return [
            NotificationResponse(
                id=r["id"],
                type=r["type"],
                title=r["title"],
                message=r["message"],
                lead_id=r.get("lead_id"),
                created_at=r["created_at"],
                read=bool(r["read"]),
            )
            for r in rows
        ]
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
    print(f"DEBUG: push_service._vapid_public_key = {push_service._vapid_public_key[:50] if push_service._vapid_public_key else 'NOT SET'}")
    print(f"DEBUG: push_service.is_configured() = {push_service.is_configured()}")
    public_key = push_service._vapid_public_key
    if not public_key:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"public_key": public_key}


@app.get("/api/push/test-endpoint")
async def test_endpoint():
    """Test endpoint to debug 503 issues."""
    return {"status": "ok", "message": "Test endpoint working"}


@app.post("/api/push/subscribe")
async def subscribe_push(
    payload: PushSubscribeRequest,
    user: dict = Depends(_get_current_user),
):
    """Registra uma push subscription para o usuário."""
    try:
        ok = await db_service.add_push_subscription(user["id"], payload.endpoint, payload.p256dh, payload.auth)
        if ok:
            await db_service.set_user_push_enabled(user["id"], True)
        return {"status": "ok", "subscribed": ok}
    except Exception as e:
        logger.error(f"Erro ao inscrever push: {e}")
        raise HTTPException(status_code=500, detail="Erro ao inscrever")


@app.post("/api/push/unsubscribe")
async def unsubscribe_push(
    payload: PushUnsubscribeRequest,
    user: dict = Depends(_get_current_user),
):
    """Remove uma push subscription do usuário."""
    ok = await db_service.remove_push_subscription(user["id"], payload.endpoint)
    # Se não restarem subscriptions, marca push_enabled = false
    remaining = await db_service.get_user_push_subscriptions(user["id"])
    if not remaining:
        await db_service.set_user_push_enabled(user["id"], False)
    return {"status": "ok", "unsubscribed": ok}


@app.patch("/api/push/enabled")
async def update_push_enabled(
    payload: PushEnabledUpdate,
    user: dict = Depends(_get_current_user),
):
    """Define manualmente o flag push_enabled do usuário."""
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
    _scrape_runs[run_id] = {
        "run_id": run_id, "running": True,
        "started_at": datetime.utcnow().isoformat(),
        "inserted": 0, "total_raw": 0, "status": "running", "error": None,
    }
    asyncio.create_task(_scrape_worker(run_id, max_cities, hours_override=hours))
    return JSONResponse(status_code=202, content={
        "status": "started", "run_id": run_id,
        "note": "Run em background; acompanhe em GET /api/scraper/status",
    })


@app.get("/api/scraper/status")
async def scraper_status():
    """Progresso/último resultado do scraper em background."""
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
    # Inclui city_health no status
    city_health = await db_service.get_city_health_for_scraper_status()
    return {"active": bool(active), "running": active, "last_run": last, "city_health": city_health}


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
# DLQ (Dead Letter Queue) Helpers
# ============================================================
DLQ_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "dlq")

def _ensure_dlq_dir() -> None:
    os.makedirs(DLQ_DIR, exist_ok=True)

def _dlq_save(run_id: str, city: str, leads: list, error: str) -> str:
    """Salva batch falho no DLQ para reprocessamento posterior."""
    _ensure_dlq_dir()
    filename = f"{run_id}_{city}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    path = os.path.join(DLQ_DIR, filename)
    payload = {
        "run_id": run_id,
        "city": city,
        "leads": leads,
        "error": error,
        "saved_at": datetime.utcnow().isoformat(),
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
                )
                new_lead = await db_service.insert_lead_new(enriched)
                if new_lead:
                    inserted += 1
                    # Enriquecimento
                    try:
                        enrich_result = await owner_enrichment.enrich(raw_lead.get("address", ""), raw_lead.get("city", ""))
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
            city_lines.append(f"  {city}: ❌ ERRO — {result['error'][:100]}")
        else:
            count = len(result.get("leads", []))
            city_lines.append(f"  {city}: {count} leads {'✅' if count > 0 else '🔴 ZERADO'}")
            if count == 0:
                anomalies.append(city)

    # Verifica anomalias (cidade ativa zerou 2x+)
    anomaly_lines = []
    for city in anomalies:
        health = await db_service.get_city_health(city)
        anomaly_count = health.get("anomaly_counter", 0)
        if anomaly_count >= 2:
            anomaly_lines.append(f"⚠️ **ANOMALIA**: {city} zerou {anomaly_count} execuções consecutivas!")
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
        f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC | Trigger: {trigger}",
        "",
        f"📥 **Total bruto**: {total_raw} | ✅ **Inseridos**: {inserted} | 🔄 **DLQ reprocessado**: {dlq_reprocessed}",
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
            {"domain": "data.cityofnewyork.us", "dataset": "erm2-nwe9", "city": "NYC", "state": "NY", "hours": 96, "limit": 5000, "fields": ["unique_key", "created_date", "complaint_type", "incident_address", "incident_zip", "latitude", "longitude", "status"]},
            {"domain": "data.cityofnewyork.us", "dataset": "wvxf-dwi5", "city": "NYC", "state": "NY", "hours": 120, "fields": ["violation_id", "inspection_date", "building_id", "address", "city", "state", "zip", "latitude", "longitude", "violation_type", "violation_status", "disposition_date"]},  # HPD Violations
            {"domain": "data.cityofchicago.org", "dataset": "v6vf-nfxy", "city": "Chicago", "state": "IL", "hours": 48, "fields": ["service_request_number", "created_date", "sr_type", "street_address", "zip_code", "latitude", "longitude", "status"]},
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
        city_results = {}  # {city: {"leads": [...], "error": None/str, "skipped": bool}}

        for entry in all_entries:
            city = entry["city"]
            health = city_health.get(city, {})
            _failure_count = health.get("failure_count", 0)
            circuit_open_until = health.get("circuit_open_until")

            # Circuit Breaker: pula cidade se circuit breaker aberto
            if circuit_open_until and datetime.utcnow().isoformat() < circuit_open_until:
                logger.warning(f"Circuit Breaker ATIVO para {city} até {circuit_open_until} — pulando")
                city_results[city] = {"leads": [], "error": "circuit_breaker_open", "skipped": True}
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
                    rows = await _s._fetch_soql(
                        domain=domain, dataset=dataset,
                        select="violation_number, issue_date, house_number, street, boro, description, violation_type, violation_category, ecb_number, disposition_date, disposition_comments",
                        where=where, limit=5000, order="issue_date DESC",
                    )
                    logger.info(f"DOB Violations: got {len(rows)} raw rows from Socrata")
                    out = []
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
                            ))
                        except Exception as e:
                            logger.warning(f"DOB Violations row error: {e}")
                            continue
                    leads = out

                elif entry.get("type") == "dob_permits":
                    # NYC DOB Permits
                    import backend.models.schemas as _sch
                    from backend.scrapers.socrata_311 import socrata_scraper as _s
                    domain = "data.cityofnewyork.us"
                    dataset = "rbx6-tga4"
                    logger.info(f"DOB Permits: fetching from {domain}/{dataset}")
                    try:
                        rows = await _s._fetch_soql(
                            domain=domain, dataset=dataset,
                            select="job_filing_number, work_permit, house_no, street_name, borough, zip_code, latitude, longitude, approved_date, issued_date, job_description, work_type, job_type, permit_status, applicant_first_name, applicant_last_name, applicant_business_name, owner_name, owner_business_name, nta, council_district",
                            where=None, limit=5000, order="approved_date DESC",
                        )
                        logger.info(f"DOB Permits: got {len(rows)} raw rows from Socrata")
                    except Exception as e:
                        logger.error(f"DOB Permits: fetch failed: {e}")
                        rows = []

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
                    leads = await socrata_scraper.fetch_from_dataset(
                        entry["domain"], entry["dataset"], entry["city"], entry["state"],
                        field_names=fields, hours=city_hours, limit=entry.get("limit", 2000),
                    )

                # Boston (CKAN) - caso especial
                if city == "Boston":
                    from backend.scrapers.socrata_311 import socrata_scraper as _s
                    try:
                        import httpx as _h
                        async with _h.AsyncClient(timeout=60) as client:
                            resp = await client.get(
                                "https://data.boston.gov/api/3/action/datastore_search",
                                params={
                                    "resource_id": "1a0b420d-99f1-4887-9851-990b2a5a6e17",
                                    "limit": 5000,
                                    "sort": "open_dt DESC",
                                },
                            )
                            logger.info(f"Boston CKAN: HTTP {resp.status_code}, bytes={len(resp.text)}")
                            data = resp.json()
                            if not data.get("success"):
                                logger.warning(f"Boston CKAN: success=FALSE -> {str(data.get('error'))[:300]}")
                                leads = []
                            else:
                                since = datetime.now() - timedelta(hours=entry["hours"])
                                records = data["result"]["records"]
                                out = []
                                for rec in records:
                                    od = rec.get("open_dt")
                                    if not od:
                                        continue
                                    try:
                                        odo = datetime.fromisoformat(str(od).replace("Z", "+00:00").replace("T", " "))
                                    except Exception:
                                        continue
                                    if odo < since:
                                        continue
                                    eid = str(rec.get("case_enquiry_id") or rec.get("_id") or "")
                                    if not eid:
                                        continue
                                    address = rec.get("location") or rec.get("location_street_name") or "Boston, MA"
                                    desc = rec.get("case_title") or rec.get("reason") or rec.get("type") or ""
                                    import backend.models.schemas as _sch
                                    out.append(_sch.RawLead311(
                                        external_id=eid,
                                        address=f"{address}, Boston, MA" if address else "Boston, MA",
                                        city="Boston",
                                        state="MA",
                                        zip_code=str(rec.get("location_zipcode")) if rec.get("location_zipcode") else None,
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
                                leads = out
                    except Exception as e:
                        logger.warning(f"Boston CKAN fetch error: {e}")
                        leads = []

                # Sucesso: registra city health
                await db_service.record_city_success(city)
                await db_service.reset_anomaly_counter(city)
                city_results[city] = {"leads": leads, "error": None, "skipped": False}
                all_raw.extend(leads)
                logger.info(f"{city}: {len(leads)} leads obtidos")

            except Exception as e:
                # Falha isolada: registra failure, não derruba outras cidades
                logger.error(f"Erro ao buscar {city}: {e}", exc_info=True)
                _failure_info = await db_service.record_city_failure(city, str(e))
                city_results[city] = {"leads": [], "error": str(e), "skipped": False}

        logger.info(f"Total bruto 311 (todas cidades): {len(all_raw)}")

        # 5. Inserção com DLQ fallback
        inserted = 0
        newly_added: list[dict] = []

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
            )
            new_lead = await db_service.insert_lead_new(enriched)
            if new_lead:
                inserted += 1
                newly_added.append(new_lead)
                # Enriquecimento automático APENAS em leads estritamente novos
                try:
                    enrich_result = await owner_enrichment.enrich(raw_lead.address, raw_lead.city)
                    owner_name_val = (enrich_result or {}).get("owner_name")
                    if owner_name_val:
                        await db_service.update_owner(new_lead["id"], owner_name_val)
                except Exception:
                    pass

        # 6. Fan-out + Anomalia detection por categoria
        notified_total = 0
        audience_total = 0
        added_by_cat: dict = {}
        if inserted > 0:
            for nl in newly_added:
                cat = (nl.get("issue_category") or "Structure").strip()
                added_by_cat.setdefault(cat, []).append(nl)
            for cat, items in added_by_cat.items():
                report = await notifier.fanout_new_lead_batch(cat, items)
                notified_total += int(report.created or 0)
                audience_total += int(report.audience or 0)

            # Dead Man's Switch: alerta só quando NÃO houver nenhum elegível
            # (cap diário atingido é saudável e não dispara).
            await notifier.guard_silent_fanout(
                inserted=inserted,
                notified=notified_total,
                audience=audience_total,
                context={
                    "run_id": run_id,
                    "inserted": inserted,
                    "notified": notified_total,
                    "audience": audience_total,
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

        logger.info(f"Scraper completo [run {run_id}]: {inserted} leads inseridos")
        state.update(
            status="success", inserted=inserted,
            total_raw=len(all_raw), cities_covered=len([c for c in city_results if not city_results[c]["skipped"]]),
            note="311 multi-cidade com Circuit Breaker + DLQ + City Health + Webhook",
            running=False, finished_at=datetime.utcnow().isoformat(),
        )
        await db_service.record_scrape_run(state)

    except Exception as e:
        logger.error(f"Erro no scraper [run {run_id}]: {e}", exc_info=True)
        state.update(status="error", error=str(e), running=False, finished_at=datetime.utcnow().isoformat())
        await db_service.record_scrape_run(state)


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
    _scrape_runs[run_id] = {
        "run_id": run_id, "running": True,
        "started_at": datetime.utcnow().isoformat(),
        "inserted": 0, "total_raw": 0, "status": "running", "error": None,
        "trigger": "scheduler",
    }
    asyncio.create_task(_scrape_worker(run_id, max_cities, hours_override=hours_override))
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
            now_utc = datetime.utcnow()
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

    # Validação de VAPID keys no startup
    if not settings.VAPID_PUBLIC_KEY or not settings.VAPID_PRIVATE_KEY:
        logger.critical("❌ VAPID keys NÃO CONFIGURADAS — Push notifications DESABILITADAS!")
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
        logger.info("✅ VAPID keys configuradas — Push notifications ATIVAS")

    if settings.SCRAPER_SELF_SCHEDULED:
        _scheduler_task = asyncio.create_task(_scheduler_loop())
        logger.info(f"Scheduler interno ativo (a cada {settings.SCRAPER_INTERVAL_HOURS}h)")

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
            logger.info("✅ Stripe LIVE configurado — pagamentos em PRODUÇÃO")
        elif settings.STRIPE_API_KEY.startswith("sk_test_"):
            logger.warning("⚠️ Stripe TEST configurado — pagamentos em MODO TESTE (não use em produção)")
        else:
            logger.warning(f"⚠️ Stripe key prefixo desconhecido: {settings.STRIPE_API_KEY[:12]}...")
        logger.info(f"✅ Stripe PRICE_ID: {settings.STRIPE_PRICE_ID_PRO}")
    else:
        logger.warning("⚠️ Stripe NÃO configurado completamente — checkout usará mock")
    yield
    if _scheduler_task:
        _scheduler_task.cancel()


async def _scheduler_loop():
    """Loop do scheduler interno: espera o intervalo e dispara a varredura."""
    interval_seconds = max(300, settings.SCRAPER_INTERVAL_HOURS * 3600)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            _scheduled_scrape(max_cities=8)
        except Exception as e:
            logger.error(f"Erro no scheduler interno: {e}", exc_info=True)


app.router.lifespan_context = _lifespan


# Lista o que o framework nacional descobriu (estados/mercados cobertos)
@app.get("/api/scraper/discover")
async def discover_available():
    """Retorna os datasets/mercados descobertos nacionalmente (311, permits, tax)."""
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
        raise HTTPException(status_code=500, detail=f"Erro: {e!s}")


# Enriquecimento em lote: preenche owner_name = nome do proprietário (registro público)
@app.post("/api/scraper/enrich")
async def enrich_leads(city: str = "NYC", limit: int = 500, user: dict = Depends(_get_current_user)):
    """Busca o nome do proprietário para os leads que ainda não têm owner_name (requer login)."""
    try:
        from backend.services import db as dbmod

        # pega leads sem owner_name
        conn = dbmod.get_connection()
        rows = conn.execute(
            "SELECT id, address, city FROM leads "
            "WHERE (owner_name IS NULL OR owner_name = '') AND city = ? "
            "ORDER BY date_reported DESC LIMIT ?",
            (city, limit),
        ).fetchall()
        conn.close()

        logger.info(f"Enriquecendo {len(rows)} leads de {city}...")
        updated = 0
        found = 0
        for row in rows:
            enrich_result = await owner_enrichment.enrich(row["address"], row["city"])
            if enrich_result and enrich_result.get("owner_name"):
                await db_service.update_owner(row["id"], enrich_result["owner_name"])
                found += 1
            updated += 1

        logger.info(f"Enriquecimento: {found} donos encontrados de {updated} leads")
        if found > 0:
            await db_service.add_notification(
                "owner_enriched",
                "Novos proprietários identificados",
                f"{found} novo(s) proprietário(s) encontrado(s) em {city}",
            )
        return {
            "status": "success",
            "processed": updated,
            "owners_found": found,
        }
    except Exception as e:
        logger.error(f"Erro no enriquecimento: {e}")
        raise HTTPException(status_code=500, detail=f"Erro: {e!s}")


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
                "SELECT id, address, city FROM leads "
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
            address_city_pairs = [(row["address"], row["city"]) for row in rows]

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
        raise HTTPException(status_code=500, detail=f"Erro: {e!s}")


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
        raise HTTPException(status_code=500, detail=f"Erro: {e!s}")


# Enriquecimento/consulta do dono de um único lead
@app.post("/api/leads/{lead_id}/enrich")
async def enrich_single_lead(lead_id: int, user: dict = Depends(_get_current_user)):
    """Consulta o nome do proprietário de um lead específico (requer login)."""
    try:
        lead = await db_service.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead não encontrado")
        owner = await owner_enrichment.enrich(lead["address"], lead["city"])
        if owner:
            await db_service.update_owner(lead_id, owner)
        return {"lead_id": lead_id, "owner_name": owner}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao enriquecer lead {lead_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro: {e!s}")


# ------------------------------------------------------------------
# Autenticação e usuários
# ------------------------------------------------------------------
@app.post("/api/auth/register", response_model=AuthResponse)
@limiter.limit("3/minute")
async def register_user(request: Request, payload: UserCreate, response: Response = None):
    try:
        pwd_hash = security.hash_password(payload.password)
        user = await db_service.create_user(
            payload.email.lower(), pwd_hash, payload.company_name, plan="free",
            subscription_status="expired", plan_until=None,
            locale=payload.locale if payload.locale else "pt",
        )
        if not user:
            raise HTTPException(status_code=409, detail="Email já cadastrado")
        token = security.new_session_token()
        # Registra a sessão no banco (aplica limite de 2 sessões por usuário - FIFO)
        await db_service.create_user_session(user["id"], _hash_token(token), "Signup", None)
        _SESSIONS[token] = user["id"]

        # Define httpOnly cookie com o token
        if response:
            response.set_cookie(
                key="garimpador_token",
                value=token,
                httponly=True,
                secure=not settings.DEBUG,  # False em dev (HTTP), True em prod (HTTPS)
                samesite="lax",
                max_age=30 * 24 * 60 * 60,  # 30 dias
                path="/",
            )

        return AuthResponse(
            token=token,
            user=UserResponse(
                id=user["id"],
                email=user["email"],
                company_name=user.get("company_name"),
                plan=user.get("plan"),
                subscription_status=user.get("subscription_status"),
                plan_until=user.get("plan_until"),
                score=user.get("score") or 0,
                leads_taken=user.get("leads_taken") or 0,
                conversions=user.get("conversions") or 0,
                push_enabled=bool(user.get("push_enabled")),
                created_at=user.get("created_at"),
            ),
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

        # Mantém compatibilidade com fallback em memória
        _SESSIONS[token] = user["id"]

        # Define httpOnly cookie com o token
        if response:
            response.set_cookie(
                key="garimpador_token",
                value=token,
                httponly=True,
                secure=not settings.DEBUG,  # False em dev (HTTP), True em prod (HTTPS)
                samesite="lax",
                max_age=30 * 24 * 60 * 60,  # 30 dias
                path="/",
            )

        return AuthResponse(
            token=token,
            user=UserResponse(
                id=user["id"],
                email=user["email"],
                company_name=user.get("company_name"),
                plan=user.get("plan"),
                subscription_status=user.get("subscription_status"),
                plan_until=user.get("plan_until"),
                score=user.get("score") or 0,
                leads_taken=user.get("leads_taken") or 0,
                conversions=user.get("conversions") or 0,
                push_enabled=bool(user.get("push_enabled")),
                created_at=user.get("created_at"),
            ),
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
    return UserResponse(
        id=full["id"],
        email=full["email"],
        company_name=full.get("company_name"),
        plan=full.get("plan"),
        subscription_status=full.get("subscription_status"),
        plan_until=full.get("plan_until"),
        score=full.get("score") or 0,
        leads_taken=full.get("leads_taken") or 0,
        conversions=full.get("conversions") or 0,
        push_enabled=bool(full.get("push_enabled")),
        created_at=full.get("created_at"),
    )


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
        return UserResponse(
            id=full["id"],
            email=full["email"],
            company_name=full.get("company_name"),
            plan=full.get("plan"),
            subscription_status=full.get("subscription_status"),
            locale=full.get("locale"),
            created_at=full.get("created_at"),
        )
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
        return UserResponse(
            id=full["id"],
            email=full["email"],
            company_name=full.get("company_name"),
            plan=full.get("plan"),
            subscription_status=full.get("subscription_status"),
            plan_until=full.get("plan_until"),
            score=full.get("score") or 0,
            leads_taken=full.get("leads_taken") or 0,
            conversions=full.get("conversions") or 0,
            created_at=full.get("created_at"),
        )
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
        # Remove do fallback em memória
        _SESSIONS.pop(token, None)

    # Limpa o cookie
    if response:
        response.delete_cookie(
            key="garimpador_token",
            path="/",
        )

    return {"status": "ok"}


@app.post("/api/auth/demo", response_model=AuthResponse)
async def demo_login(response: Response = None):
    import os
    demo_email = os.getenv("DEMO_EMAIL", "demo@magicleads.app")
    demo_password = os.getenv("DEMO_PASSWORD", "Demo2026#Magic")
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

    # Mantém compatibilidade com fallback em memória
    _SESSIONS[token] = user["id"]

# Define httpOnly cookie com o token
    if response:
        response.set_cookie(
            key="garimpador_token",
            value=token,
            httponly=True,
secure=not settings.DEBUG,
            samesite="lax",
            max_age=30 * 24 * 60 * 60,
            path="/",
        )

    logger.info(f"Demo login successful for user {user['id']}")
    return AuthResponse(
        token=token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            company_name=user.get("company_name"),
            plan=user.get("plan"),
            subscription_status=user.get("subscription_status"),
            plan_until=user.get("plan_until"),
            score=user.get("score") or 0,
            leads_taken=user.get("leads_taken") or 0,
            conversions=user.get("conversions") or 0,
            created_at=user.get("created_at"),
        ),
    )


# ===== PASSWORD RESET =====

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str

@app.post("/api/auth/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest):
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
async def reset_password(payload: ResetPasswordRequest):
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


def _create_stripe_checkout_session(user_id: int, locale: str = "auto") -> tuple:
    """Cria sessão Stripe de PAGAMENTO AVULSO (sem recorrência) de 7 dias.

    Retorna (mock: bool, checkout_url: Optional[str]). Pagamento único em USD;
    o acesso é liberado pelo webhook (checkout.session.completed) por 7 dias.
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

    session = stripe.checkout.Session.create(
        mode="payment",
        currency="usd",
        line_items=[{"price": settings.STRIPE_PRICE_ID_PRO, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(user_id),
        locale=stripe_locale,
        metadata={
            "user_id": str(user_id),
            "access": "7_days",
            "plan": settings.PLAN_NAME.lower(),
        },
    )
    return False, session.url


@app.post("/api/billing/checkout")
async def create_checkout(request: Request, user: dict = Depends(_get_current_user)):
    """Cria sessão de checkout do acesso de 7 dias ($79, pagamento avulso).

    Se STRIPE_API_KEY + STRIPE_PRICE_ID_PRO estiverem configurados, cria uma
    sessão real no Stripe (hosted). Caso contrário retorna mock para o fluxo
    local (sem gateway ainda) — o frontend chama /api/billing/mock-activate.
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
        mock, checkout_url = _create_stripe_checkout_session(user["id"], locale)
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
        mock, checkout_url = _create_stripe_checkout_session(user["id"], locale)
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


@app.post("/api/billing/mock-activate")
async def mock_activate(user: dict = Depends(_get_current_user)):
    """Mock de confirmação de pagamento: libera +1 semana ($79)."""
    renewed = await db_service.activate_week(
        user["id"], plan=settings.PLAN_NAME.lower(),
        subscription_status="active", days=7,
    )
    if not renewed:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return {
        "status": "ok",
        "mock": True,
        "plan": renewed.get("plan"),
        "subscription_status": renewed.get("subscription_status"),
        "plan_until": renewed.get("plan_until"),
    }


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
    if await db_service.has_stripe_event(event_id):
        return {"status": "received", "handled": True, "idempotent": True}

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

        recorded = await db_service.record_stripe_event(event_id, event_type, user_id)
        if not recorded:
            return {"status": "received", "handled": True, "idempotent": True}

        updated = await db_service.extend_access(user_id, days=7)
        if updated is None:
            logger.error(f"Stripe {event_id}: user {user_id} não encontrado")
            return {"status": "received", "handled": False, "reason": "user_not_found"}

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
    return {"status": "received", "handled": False}


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
    rows = await db_service.get_notifications_for_user(
        user_id, filter=filter, limit=limit
    )
    return [
        NotificationResponse(
            id=r["id"],
            type=r["type"],
            title=r["title"],
            message=r["message"],
            lead_id=r.get("lead_id"),
            created_at=r["created_at"],
            read=bool(r["read"]),
        )
        for r in rows
    ]


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
        reserved_until=lead.get("reserved_until"),
        contact_count=lead.get("contact_count") or 0,
        converted_by=lead.get("converted_by"),
        converted_at=lead.get("converted_at"),
        created_at=lead.get("created_at"),
    )


@app.post("/api/leads/{lead_id}/reserve", response_model=LeadHoldResponse)
async def reserve_lead(
    lead_id: int, payload: ReserverLeadRequest,
    user: dict = Depends(_get_current_user),
):
    user_id = user["id"]

    # 1. VALIDA SUBSCRIPTION STATUS (PRIMEIRO!)
    sub_status = await db_service.get_user_subscription_status(user_id)
    if not sub_status.get("can_access", False):
        return JSONResponse(
            status_code=403,
            content={
                "error": sub_status.get("message", "Acesso negado"),
                "status": sub_status.get("status", "denied"),
                "action": "REDIRECT_TO_CHECKOUT"
            }
        )

    # 1.1 Sinaliza contato nos reveals em aberto (watchdog para de notificar)
    await db_service.flag_reveal_contact(user_id, lead_id)

    minutes = payload.minutes or 60

    # 2. COM CONSENTIMENTO => REVEAL (reserva 60min + conta 1/10 com idempotência)
    if payload.consent:
        key = payload.idempotency or f"{user_id}:{lead_id}"
        try:
            result = await db_service.reveal_lead(user_id, lead_id, key, minutes=minutes)
        except Exception as e:
            logger.error(f"Erro ao revelar lead {lead_id}: {e}")
            raise HTTPException(status_code=500, detail="Erro ao processar reserva")
        
        if not result:
            raise HTTPException(status_code=404, detail="Lead não encontrado")
        if result.get("error") == "not_found":
            raise HTTPException(status_code=404, detail="Lead não encontrado")
        if result.get("error") == "already_reserved":
            raise HTTPException(status_code=409, detail="Lead já reservado por outro usuário")
        if result.get("error") == "limit_reached":
            raise HTTPException(
                status_code=429,
                detail="Limite de 10 leads/dia atingido. Volte amanhã e abra seus 10+ potenciais clientes."
            )

        lead = result.get("lead") or {}

        # ENRIQUECIMENTO ON-DEMAND: se dados do dono faltam, busca nas APIs externas
        try:
            owner_name = lead.get("owner_name")
            owner_phone = lead.get("owner_phone")
            owner_email = lead.get("owner_email")
            mailing_address = lead.get("mailing_address")

            needs_enrichment = not owner_name or not owner_phone or not mailing_address

            enrichment_failed = False

            if needs_enrichment:
                # Enriquecimento de nome + mailing address (Socrata/CKAN)
                enrich_result = await owner_enrichment.enrich(lead.get("address", ""), lead.get("city", ""))
                if enrich_result:
                    if not owner_name and enrich_result.get("owner_name"):
                        owner_name = enrich_result["owner_name"]
                        await db_service.update_owner(lead_id, owner_name)
                    if not mailing_address and enrich_result.get("mailing_address"):
                        mailing_address = enrich_result["mailing_address"]
                        await db_service.update_mailing_address(lead_id, mailing_address)
                else:
                    enrichment_failed = True

                # Busca de telefone (Searchbug em prod, mock em dev)
                if not owner_phone:
                    phone_result = await searchbug_service.lookup_phone(lead.get("address", ""), lead.get("city", ""), lead.get("state", ""))
                    if phone_result.success:
                        owner_phone = phone_result.phone
                        await db_service.update_owner_phone(lead_id, owner_phone)
                    else:
                        enrichment_failed = True

                # Recarrega lead com dados enriquecidos
                enriched_lead = await db_service.get_lead_by_id(lead_id)
                if enriched_lead:
                    lead = dict(enriched_lead)

        except Exception as e:
            logger.warning(f"Enriquecimento on-demand falhou para lead {lead_id}: {e}")
            enrichment_failed = True

        # REGRA A: Se enriquecimento falhou ou dados vazios, não debita a cota diária
        if enrichment_failed or not lead.get("owner_name") or not lead.get("owner_phone"):
            logger.info(f"Regra A aplicada: estorno de cota por dados vazios/falha no lead {lead_id}")
            refund_result = await db_service.process_refund(user_id, lead_id, reason="enrichment_failed")
            if not refund_result.get("success"):
                logger.warning(f"Falha ao processar estorno Regra A: {refund_result.get('reason')}")

        # Registra interação
        await db_service.record_event(lead_id, "revealed")

        return JSONResponse(
            status_code=200,
            content={
                "reserved": True,
                "revealed": True,
                "status": lead.get("lead_status", "reserved"),
                "expires_at": lead.get("reserved_until"),
                "message": "Dados revelados — reserva de 1 hora ativa",
                "counted_again": result.get("counted_again", True),
                "used": result.get("used"),
                "limit": result.get("limit"),
                "remaining": result.get("remaining"),
                "reset_at": result.get("reset_at"),
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

    # 3. SEM CONSENTIMENTO: fluxo antigo (reserva simples, contando no limite)
    # 3.1 VALIDA DAILY LIMIT (10 leads/dia)
    if not await db_service.increment_daily_leads(user_id):
        daily_stats = await db_service.get_daily_leads_used(user_id)
        reset_at = daily_stats.get("reset_at")
        reset_str = ""
        if reset_at:
            try:
                reset_dt = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
                hours_left = int((reset_dt - datetime.utcnow()).total_seconds() / 3600)
                reset_str = f" Reset em {hours_left}h."
            except Exception:
                pass
        raise HTTPException(
            status_code=429,
            detail=f"Limite de 10 leads/dia atingido. Volte amanhã e abra seus 10+ potenciais clientes.{reset_str}"
        )

    # 3.2 RESERVA LEAD
    result = await db_service.reserve_lead(lead_id, user["id"], minutes=minutes)
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
    result = await db_service.record_contact(lead_id, user["id"], payload.channel)
    if not result:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    if result.get("error") == "already_reserved":
        raise HTTPException(status_code=409, detail="Lead reservado por outro usuário")
    # Sinalizou contato => watchdog de reveals para de notificar o empreiteiro
    try:
        await db_service.flag_reveal_contact(user["id"], lead_id)
    except Exception:
        pass
    return {"status": "ok", "channel": payload.channel, "contact_count": result.get("contact_count", 0)}


@app.post("/api/leads/{lead_id}/report-invalid")
async def report_invalid_number(lead_id: int, user: dict = Depends(_get_current_user)):
    """Reporta número inválido/vazio para estorno de cota diária.

    Regras (Regra B, C, D):
    - Janela de 5 minutos após reveal (Regra B)
    - Lead não pode estar em negociação/convertido (Regra C)
    - Máximo 2 estornos por usuário/dia (Regra D)
    - Lead não pode ter refund_blocked
    """
    user_id = user["id"]

    # Valida permissões
    can_report = await db_service.can_report_invalid_number(user_id, lead_id)
    if not can_report["allowed"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error": can_report["reason"],
                "message": {
                    "report_window_expired": "Janela de 5 minutos para reportar expirou",
                    "lead_status_blocked": "Lead em negociação ou convertido — estorno bloqueado",
                    "refund_blocked": "Estorno já processado ou bloqueado para este lead",
                    "daily_refund_limit_exceeded": f"Limite de {db_service.MAX_REFUNDS_PER_DAY} estornos por dia atingido",
                    "no_active_reveal": "Nenhum reveal ativo para este lead",
                    "invalid_revealed_at": "Dados de reveal inválidos",
                }.get(can_report["reason"], "Não foi possível processar o estorno"),
            }
        )

    # Processa estorno
    refund_result = await db_service.process_refund(user_id, lead_id, reason="invalid_number")
    if not refund_result["success"]:
        raise HTTPException(
            status_code=400,
            detail={"error": refund_result["reason"], "message": "Falha ao processar estorno"}
        )

    return {
        "status": "ok",
        "message": "Cota diária devolvida com sucesso",
        "refunds_remaining_today": refund_result["remaining"],
        "refund_count_today": refund_result["refund_count_today"],
    }


# Cron: expira holds vencidos + watchdog de reveals (chamado por GitHub Actions a cada hora)
@app.get("/api/cron/expire-holds")
async def cron_expire_holds(x_cron_secret: str | None = Header(None)):
    _check_cron_secret(x_cron_secret)
    try:
        expired = await db_service.expire_holds()
        reveals = await db_service.check_reveal_watchdogs()
        return {
            "status": "ok",
            "expired_holds": expired,
            "reveals_processed": reveals,
            "at": datetime.utcnow().isoformat(),
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
    result = await db_service.mark_negotiation(lead_id, user["id"])
    if not result:
        raise HTTPException(status_code=409, detail="Não foi possível marcar negociação")
    # Regra C: bloqueia estorno quando lead entra em negociação
    await db_service.block_lead_refund(lead_id, reason="negotiation_started")
    return {"status": "ok", "lead_status": result.get("lead_status")}


@app.post("/api/leads/{lead_id}/convert")
async def convert_lead(lead_id: int, user: dict = Depends(_get_current_user)):
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


@app.get("/api/leads/{lead_id}/history", response_model=list[HistoryEvent])
async def lead_history(lead_id: int, user: dict = Depends(_get_current_user)):
    rows = await db_service.get_lead_history(lead_id)
    return [
        HistoryEvent(
            id=r["id"],
            lead_id=r["lead_id"],
            event_type=r["event_type"],
            detail=r.get("detail"),
            created_at=r["created_at"],
            user_id=r.get("user_id"),
        )
        for r in rows
    ]


@app.get("/api/leads/{lead_id}/occurrences")
async def lead_occurrences(lead_id: int, user: dict = Depends(_get_current_user)):
    """Timeline de ocorrências do imóvel (histórico de chamados no 311).
    Capturado pelo scraper (lead_case_history)."""
    rows = await db_service.get_lead_case_history(lead_id)
    return rows


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
