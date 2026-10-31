"""Control Tower: saude do motor, backup off-site e digest diario.

Porque existe
-------------
Tudo o que correu mal neste projeto foi descoberto por inspeccao manual:
bs4 ausente semanas a fio, BD de dev != producao, fila de deploy travada,
tokens revogados, `send_enabled=1` sem ninguem saber. Nao havia camada de
saude: a telemetria media *accoes*, nao *saude* nem *risco*.

Aqui ficam tres coisas:
  1. `run_health_checks()`  -> 8 verificacoes, persistidas em `health_checks`
  2. `backup_database()`    -> snapshot consistente -> VPS (outro fornecedor)
     `verify_latest_backup` -> teste de restauro (integridade + contagens)
  3. `build_digest()`/`send_digest()` -> 10 numeros + semaforos, 1x/dia

Nada aqui envia e-mail a prospects: o digest vai para o endereco interno.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from ..utils.logger import logger
from .db import DB_PATH, get_connection

VPS_URL = (os.getenv("VPS_WORKER_URL") or "").strip().rstrip("/")
VPS_SECRET = (os.getenv("VPS_WORKER_SECRET") or "").strip()
DIGEST_TO = (os.getenv("CONTROL_TOWER_EMAIL") or "").strip()

# Limiares (minutos/horas) das verificacoes.
WORKER_OK_MIN = 5
WORKER_WARN_MIN = 15
QUEUE_OK_H = 24
QUEUE_WARN_H = 48
BACKUP_OK_H = 30
BACKUP_WARN_H = 48
STUCK_SENDING_MIN = 30
DISK_OK_PCT = 20.0
DISK_WARN_PCT = 10.0

KV_LAST_TICK = "last_worker_tick"
KV_LAST_BACKUP = "last_backup_at"
KV_LAST_BACKUP_BYTES = "last_backup_bytes"
KV_LAST_VERIFY = "last_backup_verify_at"
KV_LAST_DIGEST = "last_digest_date"
KV_LAST_RED_ALERT = "last_red_alert_at"
RED_ALERT_COOLDOWN_MIN = 60


# ------------------------------------------------------------------ helpers

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def kv_get(key: str) -> Optional[str]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM system_kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def kv_set(key: str, value: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO system_kv (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key, value, _iso(_now())),
        )
        conn.commit()
    finally:
        conn.close()


def _record(checks: list[dict]) -> None:
    conn = get_connection()
    try:
        now = _iso(_now())
        for c in checks:
            conn.execute(
                "INSERT INTO health_checks (checked_at, check_name, status, detail) "
                "VALUES (?, ?, ?, ?)",
                (now, c["name"], c["status"], c.get("detail")),
            )
        conn.commit()
    finally:
        conn.close()


# -------------------------------------------------------------- healthchecks

def _check_db() -> dict:
    try:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO system_kv (key, value, updated_at) VALUES ('_probe', '1', ?) "
                "ON CONFLICT(key) DO UPDATE SET value='1'",
                (_iso(_now()),),
            )
            conn.execute("DELETE FROM system_kv WHERE key='_probe'")
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return {"name": "db", "status": "fail", "detail": f"nao gravavel: {exc}"}

    try:
        usage = shutil.disk_usage(os.path.dirname(DB_PATH) or ".")
        free_pct = usage.free / usage.total * 100
    except Exception:  # noqa: BLE001
        return {"name": "disk", "status": "warn", "detail": "disco nao medivel"}

    if free_pct < DISK_WARN_PCT:
        return {"name": "disk", "status": "fail", "detail": f"{free_pct:.1f}% livre"}
    if free_pct < DISK_OK_PCT:
        return {"name": "disk", "status": "warn", "detail": f"{free_pct:.1f}% livre"}
    return {"name": "disk", "status": "ok", "detail": f"{free_pct:.0f}% livre"}


def _check_worker() -> dict:
    last = _parse(kv_get(KV_LAST_TICK))
    if not last:
        return {"name": "worker", "status": "warn", "detail": "sem heartbeat"}
    age_min = (_now() - last).total_seconds() / 60
    if age_min > WORKER_WARN_MIN:
        return {"name": "worker", "status": "fail", "detail": f"{age_min:.0f} min sem tick"}
    if age_min > WORKER_OK_MIN:
        return {"name": "worker", "status": "warn", "detail": f"{age_min:.0f} min sem tick"}
    return {"name": "worker", "status": "ok", "detail": f"tick ha {age_min:.0f} min"}


def _ingestion_thresholds() -> tuple[float, float]:
    """Limiares (warn, fail) derivados da cadência do scraper.

    Default: intervalo 6 h -> warn 10.5 h, fail 15 h (uma e duas varreduras
    perdidas, com margem para runs longos). Override por env se necessário.
    """
    try:
        interval = float(os.getenv("SCRAPER_INTERVAL_HOURS") or 6)
    except (TypeError, ValueError):
        interval = 6.0
    interval = max(1.0, interval)

    def _env(name: str, default: float) -> float:
        try:
            value = float(os.getenv(name) or default)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    warn_h = _env("INGESTION_WARN_HOURS", max(8.0, interval * 1.75))
    fail_h = _env("INGESTION_FAIL_HOURS", max(12.0, interval * 2.5))
    if fail_h <= warn_h:
        fail_h = warn_h + 1
    return warn_h, fail_h


def _check_ingestion_freshness() -> dict:
    """O scraper parou de capturar? Esta era a falha silenciosa sem alerta.

    Considera o último run CONCLUÍDO (`success`/`partial`). Um run `error` mais
    recente do que o último sucesso é falha imediata. Um run `running` antigo
    (>2 h) indica processo preso. Runs com 0 inseridos não mudam o estado, mas
    ficam visíveis no detalhe.
    """
    now = _now()
    warn_h, fail_h = _ingestion_thresholds()
    conn = get_connection()
    try:
        last_ok = conn.execute(
            "SELECT * FROM scraper_runs WHERE status IN ('success', 'partial') "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        latest = conn.execute(
            "SELECT * FROM scraper_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        captured_24h = conn.execute(
            "SELECT COUNT(1) FROM leads "
            "WHERE created_at >= datetime('now', '-24 hours')"
        ).fetchone()[0]
    finally:
        conn.close()

    suffix = f" · {captured_24h} lead(s) em 24h"
    if captured_24h == 0:
        suffix += " (sem captura)"

    # Run em execução há demasiado tempo: o processo pode ter morrido.
    if latest and str(latest["status"]) == "running":
        started = _parse(latest["finished_at"] or latest["started_at"])
        if started:
            running_h = (now - started).total_seconds() / 3600
            if running_h > 2.0:
                return {
                    "name": "ingestion",
                    "status": "warn",
                    "detail": f"run em execução há {running_h:.1f}h (preso?){suffix}",
                }

    if not last_ok:
        if latest and str(latest["status"]) == "error":
            return {
                "name": "ingestion",
                "status": "fail",
                "detail": f"nenhum run concluído; último falhou: {str(latest['error'] or 'erro')[:80]}{suffix}",
            }
        return {
            "name": "ingestion",
            "status": "warn",
            "detail": f"sem run concluído registado{suffix}",
        }

    # Erro mais recente do que o último sucesso = ingestão parada por falha.
    if latest and str(latest["status"]) == "error" and latest["id"] > last_ok["id"]:
        return {
            "name": "ingestion",
            "status": "fail",
            "detail": f"último run falhou: {str(latest['error'] or 'erro')[:80]}{suffix}",
        }

    finished = _parse(last_ok["finished_at"] or last_ok["started_at"])
    if not finished:
        return {
            "name": "ingestion",
            "status": "warn",
            "detail": f"último run sem data de conclusão{suffix}",
        }

    age_h = (now - finished).total_seconds() / 3600
    base = (
        f"último run {last_ok['status']} há {age_h:.1f}h · "
        f"{int(last_ok['inserted'] or 0)} inseridos"
    )
    if age_h > fail_h:
        status = "fail"
    elif age_h > warn_h:
        status = "warn"
    else:
        status = "ok"
    return {"name": "ingestion", "status": status, "detail": f"{base}{suffix}"}


def _check_searchbug_cost() -> dict:
    """Anomalias de custo/qualidade da Searchbug (sem cap global).

    Nao bloqueia chamadas: apenas classifica para o alerta RED.
      * custo da ultima hora > max($1, 3x media horaria das 24h) -> warn
      * transport_error > 50% (>=5 chamadas/15min) -> fail
      * ghost charges > 30% das pagas em 24h (>=10) -> warn
      * name_mismatch > 50% dos resultados resolvidos (>=10) -> warn
    """
    try:
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT
                     COALESCE(SUM(CASE WHEN called_at >= datetime('now','-1 hour')
                                       THEN cost_usd ELSE 0 END), 0) AS cost_1h,
                     COALESCE(SUM(cost_usd), 0) AS cost_24h,
                     SUM(CASE WHEN called_at >= datetime('now','-15 minutes')
                              THEN 1 ELSE 0 END) AS calls_15m,
                     SUM(CASE WHEN called_at >= datetime('now','-15 minutes')
                              AND outcome = 'transport_error' THEN 1 ELSE 0 END) AS transport_15m,
                     SUM(CASE WHEN billed = 1 THEN 1 ELSE 0 END) AS billed_24h,
                     SUM(CASE WHEN billed = 1 AND outcome != 'success'
                              THEN 1 ELSE 0 END) AS ghost_24h,
                     SUM(CASE WHEN outcome IN ('success', 'name_mismatch')
                              THEN 1 ELSE 0 END) AS resolved_24h,
                     SUM(CASE WHEN outcome = 'name_mismatch' THEN 1 ELSE 0 END) AS mismatch_24h
                   FROM searchbug_calls
                   WHERE called_at >= datetime('now', '-24 hours')"""
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        return {"name": "searchbug_cost", "status": "warn", "detail": f"indisponivel: {exc}"}

    cost_1h = float(row["cost_1h"] or 0)
    cost_24h = float(row["cost_24h"] or 0)
    avg_hourly = cost_24h / 24.0
    if cost_1h > max(1.0, avg_hourly * 3):
        return {
            "name": "searchbug_cost", "status": "warn",
            "detail": f"${cost_1h:.2f}/h vs media ${avg_hourly:.2f}/h",
        }

    calls_15m = int(row["calls_15m"] or 0)
    transport_15m = int(row["transport_15m"] or 0)
    if calls_15m >= 5 and transport_15m / calls_15m > 0.5:
        return {
            "name": "searchbug_cost", "status": "fail",
            "detail": f"{transport_15m}/{calls_15m} transport_error em 15min",
        }

    billed = int(row["billed_24h"] or 0)
    ghost = int(row["ghost_24h"] or 0)
    if billed >= 10 and ghost / billed > 0.3:
        return {
            "name": "searchbug_cost", "status": "warn",
            "detail": f"{ghost}/{billed} pagas sem telefone em 24h",
        }

    resolved = int(row["resolved_24h"] or 0)
    mismatch = int(row["mismatch_24h"] or 0)
    if resolved >= 10 and mismatch / resolved > 0.5:
        return {
            "name": "searchbug_cost", "status": "warn",
            "detail": f"{mismatch}/{resolved} name_mismatch em 24h",
        }

    return {
        "name": "searchbug_cost", "status": "ok",
        "detail": f"${cost_24h:.2f}/24h · {billed} pagas",
    }


def _queue_capacity(config: dict, now) -> dict:
    """Capacidade agregada das caixas ligadas para hoje (UTC).

    Sincrono e sem side-effects: a Control Tower corre no thread de health.
    Reaproveita as MESMAS funções puras do motor para o número não divergir.
    """
    from .outbound_engine import effective_mailbox_cap, warmup_days

    day = now.strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        mailboxes = conn.execute(
            "SELECT * FROM sending_mailboxes WHERE enabled=1 ORDER BY id"
        ).fetchall()
        rows = []
        for mb in mailboxes:
            mb = dict(mb)
            sent = conn.execute(
                "SELECT COUNT(1) FROM outbound_messages "
                "WHERE mailbox_id=? AND status='sent' AND sent_at >= ?",
                (mb["id"], f"{day} 00:00:00"),
            ).fetchone()[0]
            cap = effective_mailbox_cap(mb, config, now)
            rows.append(
                {
                    "email": mb.get("email"),
                    "cap": cap,
                    "sent": int(sent),
                    "remaining": max(0, cap - int(sent)),
                    "warmup_days": warmup_days(mb.get("warmup_started_at"), now),
                }
            )
        return {
            "mailboxes": rows,
            "cap_total": sum(r["cap"] for r in rows),
            "sent_total": sum(r["sent"] for r in rows),
            "remaining": sum(r["remaining"] for r in rows),
        }
    finally:
        conn.close()


def _check_queue() -> list[dict]:
    from .outbound_engine import is_quiet_hours, next_utc_midnight, quiet_hours_end_iso

    out = []
    now = _now()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT MIN(queued_at) AS oldest, COUNT(1) AS n FROM outbound_messages "
            "WHERE status='queued'"
        ).fetchone()
        oldest_msg = conn.execute(
            "SELECT city FROM outbound_messages WHERE status='queued' "
            "ORDER BY queued_at, id LIMIT 1"
        ).fetchone()
        config = {
            r["key"]: r["value"]
            for r in conn.execute("SELECT key, value FROM outbound_config WHERE city=''")
        }
        oldest = _parse(row["oldest"]) if row else None
        if row and row["n"]:
            age_h = (now - oldest).total_seconds() / 3600 if oldest else 0
            oldest_city = (oldest_msg["city"] or "") if oldest_msg else ""
            capacity = _queue_capacity(config, now)
            quiet_now = is_quiet_hours(
                now, config.get("quiet_hours_start"), config.get("quiet_hours_end")
            )

            # Uma fila velha nem sempre é um defeito: se o motor está
            # deliberadamente parado (quiet hours/cap de warm-up/motor off),
            # o alerta explica o motivo em vez de acusar "falha".
            blocked_reason = None
            blocked_detail = ""
            retry_at = None
            if config.get("send_enabled") != "1":
                blocked_reason = "motor desligado"
                blocked_detail = "send_enabled=0 (envio manualmente desligado)"
            elif quiet_now:
                blocked_reason = "quiet hours"
                retry_at = quiet_hours_end_iso(now, config)
                blocked_detail = (
                    f"quiet hours até {retry_at[11:16]} UTC" if retry_at else "quiet hours"
                )
            elif capacity["remaining"] <= 0:
                blocked_reason = "limite de caixa"
                retry_at = next_utc_midnight(now)
                ramp_day = capacity["mailboxes"][0]["warmup_days"] if capacity["mailboxes"] else 0
                blocked_detail = (
                    f"{capacity['sent_total']}/{capacity['cap_total']} envios hoje; "
                    f"warm-up dia {ramp_day} — retoma à meia-noite UTC"
                )
            else:
                # Capacidade existe mas a fila não anda: pode ser config por
                # cidade ou um lote preso. Isto sim é uma falha operacional.
                if oldest_city:
                    city_cfg = conn.execute(
                        "SELECT key, value FROM outbound_config WHERE UPPER(city)=?",
                        (oldest_city.strip().upper(),),
                    ).fetchall()
                    city_map = {r["key"]: r["value"] for r in city_cfg}
                    if city_map.get("send_enabled") == "0":
                        blocked_reason = "cidade com envio desligado"
                        blocked_detail = (
                            f"{oldest_city}: send_enabled=0 na configuração por cidade"
                        )

            base = f"{row['n']} na fila; mais antiga {age_h:.0f}h"
            if blocked_reason:
                detail = f"{base} · parada por {blocked_reason}: {blocked_detail}"
                status = "warn"
            elif age_h > QUEUE_WARN_H:
                detail = (
                    f"{base} · há capacidade ({capacity['remaining']} envio(s) hoje) "
                    "mas a fila não avança — verificar config/caixas"
                )
                status = "fail"
            elif age_h > QUEUE_OK_H:
                detail = f"{base} · restam {capacity['remaining']} envio(s) hoje"
                status = "warn"
            else:
                detail = (
                    f"{base} · {capacity['sent_total']}/{capacity['cap_total']} hoje"
                )
                status = "ok"
            out.append({"name": "queue_age", "status": status, "detail": detail})
        else:
            out.append({"name": "queue_age", "status": "ok", "detail": "fila vazia"})

        cutoff = _iso(_now() - timedelta(minutes=STUCK_SENDING_MIN))
        stuck = conn.execute(
            "SELECT COUNT(1) FROM outbound_messages WHERE status='sending' "
            "AND COALESCE(claimed_at, queued_at) < ?",
            (cutoff,),
        ).fetchone()[0]
        out.append({
            "name": "stuck_sending",
            "status": "ok" if not stuck else "warn",
            "detail": f"{stuck} presas ha >{STUCK_SENDING_MIN}min",
        })
    finally:
        conn.close()
    return out


def _check_backup() -> list[dict]:
    last = _parse(kv_get(KV_LAST_BACKUP))
    verified = _parse(kv_get(KV_LAST_VERIFY))
    out = []
    if not last:
        out.append({"name": "backup", "status": "fail", "detail": "nunca correu"})
    else:
        age_h = (_now() - last).total_seconds() / 3600
        status = "ok" if age_h <= BACKUP_OK_H else ("warn" if age_h <= BACKUP_WARN_H else "fail")
        size = kv_get(KV_LAST_BACKUP_BYTES) or "?"
        out.append({"name": "backup", "status": status,
                    "detail": f"ha {age_h:.1f}h ({size} bytes)"})
    if not verified:
        out.append({"name": "backup_verify", "status": "warn", "detail": "nunca verificado"})
    else:
        age_h = (_now() - verified).total_seconds() / 3600
        out.append({"name": "backup_verify",
                    "status": "ok" if age_h <= BACKUP_WARN_H else "warn",
                    "detail": f"restauro validado ha {age_h:.1f}h"})
    return out


async def _check_vps() -> dict:
    if not VPS_URL:
        return {"name": "vps_worker", "status": "fail", "detail": "VPS_WORKER_URL ausente"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{VPS_URL}/health")
        if r.status_code == 200:
            return {"name": "vps_worker", "status": "ok", "detail": "TLS + health OK"}
        return {"name": "vps_worker", "status": "fail", "detail": f"HTTP {r.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {"name": "vps_worker", "status": "fail", "detail": f"inacessivel: {exc}"}


async def _check_tokens() -> dict:
    """Valida o refresh OAuth das caixas ativas (o que falhou anonimamente antes)."""
    import httpx as _httpx

    client_id = (os.getenv("GMAIL_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GMAIL_CLIENT_SECRET") or "").strip()
    conn = get_connection()
    try:
        mailboxes = conn.execute(
            "SELECT id, email, auth_ref FROM sending_mailboxes WHERE enabled=1"
        ).fetchall()
    finally:
        conn.close()

    if not mailboxes:
        return {"name": "gmail_tokens", "status": "warn", "detail": "sem caixas ativas"}

    failures = []
    for mb in mailboxes:
        raw = mb["auth_ref"]
        rt = cid = csec = None
        if raw:
            try:
                d = json.loads(raw)
                cid, csec, rt = d.get("client_id"), d.get("client_secret"), d.get("refresh_token")
            except Exception:  # noqa: BLE001
                pass
        cid = cid or client_id
        csec = csec or client_secret
        if not rt:
            local = str(mb["email"]).split("@")[0].upper()
            rt = (os.getenv(f"GMAIL_REFRESH_TOKEN_{local}") or "").strip()
        if not (cid and csec and rt):
            failures.append(f"{mb['email']}: sem credenciais")
            continue
        try:
            async with _httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={"client_id": cid, "client_secret": csec,
                          "refresh_token": rt, "grant_type": "refresh_token"},
                )
            if r.status_code != 200:
                failures.append(f"{mb['email']}: HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{mb['email']}: {type(exc).__name__}")

    if failures:
        return {"name": "gmail_tokens", "status": "fail", "detail": "; ".join(failures)[:180]}
    return {"name": "gmail_tokens", "status": "ok", "detail": f"{len(mailboxes)} caixa(s) OK"}


async def send_alert(checks: list[dict]) -> dict:
    """Envia um alerta imediato quando o estado fica VERMELHO (1x/hora)."""
    if not DIGEST_TO:
        return {"status": "skipped", "reason": "CONTROL_TOWER_EMAIL ausente"}
    mailbox = _load_mailbox()
    if not mailbox:
        return {"status": "skipped", "reason": "sem caixa ativa"}

    from .gmail import gmail_sender

    failing = [c for c in checks if c["status"] == "fail"]
    lines = [
        "ALERTA — Magic Leads Control Tower",
        "",
        f"{len(failing)} verificacao(oes) em FALHA:",
    ]
    for c in failing:
        lines.append(f"  - {c['name']}: {c['detail']}")
    lines += ["", "--- estado completo ---", build_digest()]
    result = await gmail_sender.send(
        mailbox, DIGEST_TO, "[ALERTA] Magic Leads — motor em VERMELHO", "\n".join(lines)
    )
    if getattr(result, "success", False):
        kv_set(KV_LAST_RED_ALERT, _iso(_now()))
        return {"status": "ok", "to": DIGEST_TO, "failing": len(failing)}
    return {"status": "error", "reason": getattr(result, "error", "unknown")}


async def maybe_send_red_alert(checks: list[dict]) -> Optional[dict]:
    """Dispara no maximo 1x/hora, so' quando ha pelo menos um `fail`."""
    if not any(c["status"] == "fail" for c in checks):
        return None
    last = _parse(kv_get(KV_LAST_RED_ALERT))
    if last and (_now() - last) < timedelta(minutes=RED_ALERT_COOLDOWN_MIN):
        return None
    return await send_alert(checks)


def _check_push_health() -> dict:
    """Saude das entregas de push nas ultimas 24h.

    `accepted` nao prova entrega; o que importa aqui e' a ausencia de entregas
    com subscricoes ativas, VAPID em falta e uma explosao de subscriptions
    mortas (404/410/401/403) que indica aparelhos a receber para o vazio.
    """
    try:
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT
                     COUNT(*) AS deliveries,
                     SUM(CASE WHEN outcome = 'accepted' THEN 1 ELSE 0 END) AS accepted,
                     SUM(CASE WHEN outcome = 'expired' THEN 1 ELSE 0 END) AS expired,
                     SUM(CASE WHEN outcome = 'rejected_dead' THEN 1 ELSE 0 END) AS dead,
                     SUM(CASE WHEN outcome = 'not_configured' THEN 1 ELSE 0 END) AS not_configured
                   FROM push_deliveries
                   WHERE sent_at >= datetime('now', '-24 hours')"""
            ).fetchone()
            subs = conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        return {"name": "push_health", "status": "warn", "detail": f"indisponivel: {exc}"}

    deliveries = int(row["deliveries"] or 0)
    accepted = int(row["accepted"] or 0)
    expired = int(row["expired"] or 0)
    dead = int(row["dead"] or 0)
    not_configured = int(row["not_configured"] or 0)

    if not_configured:
        return {
            "name": "push_health", "status": "fail",
            "detail": f"{not_configured} entrega(s) com VAPID em falta",
        }
    if subs > 0 and deliveries == 0:
        return {
            "name": "push_health", "status": "warn",
            "detail": f"{subs} subscription(s) sem entregas em 24h",
        }
    bad = expired + dead
    if deliveries >= 10 and bad / deliveries > 0.2:
        return {
            "name": "push_health", "status": "warn",
            "detail": f"{bad}/{deliveries} subscriptions mortas em 24h",
        }
    return {
        "name": "push_health", "status": "ok",
        "detail": f"{accepted}/{deliveries} aceites · {subs} subscription(s)",
    }


async def run_health_checks() -> list[dict]:
    checks: list[dict] = [_check_db(), _check_worker()]
    checks.append(_check_ingestion_freshness())
    checks.extend(_check_queue())
    checks.extend(_check_backup())
    checks.append(await _check_vps())
    checks.append(await _check_tokens())
    checks.append(_check_searchbug_cost())
    checks.append(_check_push_health())
    _record(checks)
    worst = max(
        (c["status"] for c in checks),
        key=lambda s: {"ok": 0, "warn": 1, "fail": 2}.get(s, 0),
    )
    if worst != "ok":
        logger.warning(
            "[CONTROL-TOWER] %s",
            [(c["name"], c["status"], c["detail"]) for c in checks if c["status"] != "ok"],
        )
    if worst == "fail":
        try:
            await maybe_send_red_alert(checks)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CONTROL-TOWER] alerta falhou: %s", exc)
    return checks


def latest_health() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT check_name, status, detail, checked_at FROM health_checks "
            "WHERE checked_at = (SELECT MAX(checked_at) FROM health_checks) "
            "ORDER BY check_name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ------------------------------------------------------------------- backup

def _snapshot_bytes() -> bytes:
    """Snapshot consistente via API de backup do SQLite (seguro com WAL)."""
    tmpdir = tempfile.mkdtemp(prefix="ct-backup-")
    dest = os.path.join(tmpdir, "leads.db")
    try:
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(dest, "rb") as fh:
            raw = fh.read()
        return gzip.compress(raw, compresslevel=6)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def backup_database() -> dict:
    if not VPS_URL or not VPS_SECRET:
        return {"status": "skipped", "reason": "VPS nao configurada"}
    day = _now().strftime("%Y-%m-%d")
    name = f"leads-{day}.db.gz"
    try:
        payload = _snapshot_bytes()
    except Exception as exc:  # noqa: BLE001
        logger.error("[CONTROL-TOWER] snapshot falhou: %s", exc)
        return {"status": "error", "reason": str(exc)}

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{VPS_URL}/backup",
                params={"name": name},
                headers={"Authorization": f"Bearer {VPS_SECRET}",
                         "Content-Type": "application/gzip"},
                content=payload,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("[CONTROL-TOWER] upload do backup falhou: %s", exc)
        return {"status": "error", "reason": str(exc)}

    if r.status_code != 200:
        return {"status": "error", "reason": f"HTTP {r.status_code}: {r.text[:120]}"}

    kv_set(KV_LAST_BACKUP, _iso(_now()))
    kv_set(KV_LAST_BACKUP_BYTES, str(len(payload)))
    logger.info("[CONTROL-TOWER] backup %s enviado (%s bytes)", name, len(payload))
    return {"status": "ok", "name": name, "bytes": len(payload), "remote": r.json()}


async def verify_latest_backup() -> dict:
    """Teste de restauro: descarrega, integridade do SQLite + contagens."""
    if not VPS_URL or not VPS_SECRET:
        return {"status": "skipped"}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(
                f"{VPS_URL}/backup/latest",
                headers={"Authorization": f"Bearer {VPS_SECRET}"},
            )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": str(exc)}
    if r.status_code != 200:
        return {"status": "error", "reason": f"HTTP {r.status_code}"}

    tmpdir = tempfile.mkdtemp(prefix="ct-verify-")
    path = os.path.join(tmpdir, "restore.db")
    try:
        with open(path, "wb") as fh:
            fh.write(gzip.decompress(r.content))
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            leads = conn.execute("SELECT COUNT(1) FROM leads").fetchone()[0]
            contacts = conn.execute("SELECT COUNT(1) FROM outbound_contacts").fetchone()[0]
            messages = conn.execute("SELECT COUNT(1) FROM outbound_messages").fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": f"restauro falhou: {exc}"}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if integrity != "ok":
        return {"status": "error", "reason": f"integrity_check={integrity}"}

    kv_set(KV_LAST_VERIFY, _iso(_now()))
    logger.info("[CONTROL-TOWER] restauro validado: %s leads / %s contactos", leads, contacts)
    return {"status": "ok", "leads": leads, "contacts": contacts, "messages": messages}


# -------------------------------------------------------------------- runs

async def maybe_backup() -> Optional[dict]:
    last = _parse(kv_get(KV_LAST_BACKUP))
    if last and (_now() - last) < timedelta(hours=20):
        return None
    result = await backup_database()
    if result.get("status") == "ok":
        await verify_latest_backup()
    return result


# ------------------------------------------------------------------- digest

def _load_mailbox() -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM sending_mailboxes WHERE enabled=1 ORDER BY id LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def build_digest() -> str:
    now = _now()
    day = now.strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        queued = conn.execute(
            "SELECT COUNT(1) FROM outbound_messages WHERE status='queued'"
        ).fetchone()[0]
        oldest = conn.execute(
            "SELECT MIN(queued_at) FROM outbound_messages WHERE status='queued'"
        ).fetchone()[0]
        sent_24h = conn.execute(
            "SELECT COUNT(1) FROM outbound_messages WHERE status='sent' "
            "AND sent_at >= ?",
            ((now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchone()[0]
        replied_24h = conn.execute(
            "SELECT COUNT(1) FROM outbound_contacts WHERE replied_at >= ?",
            ((now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchone()[0]
        contacts = conn.execute("SELECT COUNT(1) FROM outbound_contacts").fetchone()[0]
        quarantined = conn.execute(
            "SELECT COUNT(1) FROM leads WHERE niche_status IN ('ambiguous','unknown') "
            "AND source_type='import_b2b'"
        ).fetchone()[0]
        config = {
            r["key"]: r["value"]
            for r in conn.execute(
                "SELECT key, value FROM outbound_config WHERE city=''"
            )
        }
        today_sent = 0
        for r in conn.execute(
            "SELECT sent FROM outbound_daily_counters WHERE day=?", (day,)
        ):
            today_sent += int(r["sent"] or 0)
    finally:
        conn.close()

    checks = latest_health()
    flags = [c for c in checks if c["status"] != "ok"]
    worst = "VERDE"
    if any(c["status"] == "fail" for c in checks):
        worst = "VERMELHO"
    elif flags:
        worst = "AMARELO"

    lines = [
        f"CONTROL TOWER — {day}",
        f"estado geral: {worst}",
        "",
        f"MOTOR      fila {queued}"
        + (f" (mais antiga desde {oldest} UTC)" if oldest else "")
        + f" · enviados 24h {sent_24h} · hoje {today_sent}"
        + f" · send_enabled={config.get('send_enabled')}",
    ]
    cap = _queue_capacity(config, now)
    for mb in cap["mailboxes"]:
        lines.append(
            f"CAIXA      {mb['email']}: cap {mb['cap']}/dia · "
            f"hoje {mb['sent']}/{mb['cap']} · warm-up dia {mb['warmup_days']}"
        )
    if cap["mailboxes"]:
        lines.append(
            f"CAPACIDADE restam {cap['remaining']} envio(s) hoje "
            f"(total {cap['cap_total']})"
        )
    ingestion = next(
        (c for c in checks if c.get("check_name") == "ingestion"), None
    ) or _check_ingestion_freshness()
    lines.append(f"INGESTAO   {ingestion['detail']}")
    lines += [
        f"FUNIL      contactos {contacts} · respostas 24h {replied_24h}",
        f"DADOS      quarentena de nicho {quarantined}",
        f"BACKUP     {kv_get(KV_LAST_BACKUP) or 'nunca'}"
        f" · verificado {kv_get(KV_LAST_VERIFY) or 'nunca'}",
    ]
    if flags:
        lines.append("")
        lines.append("ALERTAS:")
        for c in flags:
            lines.append(f"  [{c['status']}] {c['check_name']}: {c['detail']}")
    else:
        lines.append("ALERTAS    nenhum")

    lines += ["", "https://www.magicleads.app/"]
    return "\n".join(lines)


async def send_digest() -> dict:
    if not DIGEST_TO:
        return {"status": "skipped", "reason": "CONTROL_TOWER_EMAIL ausente"}
    mailbox = _load_mailbox()
    if not mailbox:
        return {"status": "skipped", "reason": "sem caixa ativa"}

    from .gmail import gmail_sender

    body = build_digest()
    result = await gmail_sender.send(
        mailbox, DIGEST_TO, "Magic Leads — Control Tower (diario)", body
    )
    if getattr(result, "success", False):
        kv_set(KV_LAST_DIGEST, _now().strftime("%Y-%m-%d"))
        return {"status": "ok", "to": DIGEST_TO}
    return {"status": "error", "reason": getattr(result, "error", "unknown")}


async def maybe_send_digest() -> Optional[dict]:
    today = _now().strftime("%Y-%m-%d")
    if kv_get(KV_LAST_DIGEST) == today:
        return None
    if _now().hour < 8:  # antes das 08:00 UTC nao envia
        return None
    return await send_digest()
