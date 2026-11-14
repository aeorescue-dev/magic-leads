"""Workflow aditivo para oportunidades de pré-inspeção (staging).

Este modulo NAO e' chamado pelo pipeline de producao. Ele existe para validar
o desenho aprovado:

* uma oportunidade por imovel (`property_key`) num ciclo ativo;
* o mesmo ciclo 1h -> 48h -> 48h do feed atual;
* outcomes (`won`/`lost`/`no_decision`) numa tabela separada;
* nenhuma escrita em `leads` nem alteracao das colunas existentes.

O endpoint publico e a UI continuam a usar o modal atual; a integracao faz-se
por um adaptador na fase seguinte.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..utils.time import utcnow
from .db import db_service, get_connection

ACTIVE_STATUSES = ("reserved", "contacted", "in_negotiation")
TERMINAL_STATUSES = ("converted", "expired")
VALID_OUTCOMES = ("won", "lost", "no_decision")


def _now_iso() -> str:
    return utcnow().replace(microsecond=0).isoformat()


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def make_property_key(
    *,
    bbl: Optional[str] = None,
    bin_value: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    zip_code: Optional[str] = None,
) -> str:
    """Chave estavel do imovel: BBL > BIN > hash normalizado do endereco."""
    bbl_digits = re.sub(r"\D", "", str(bbl or ""))
    if len(bbl_digits) >= 9:
        return f"bbl:{bbl_digits[-10:]}"
    bin_digits = re.sub(r"\D", "", str(bin_value or ""))
    if len(bin_digits) >= 6:
        return f"bin:{bin_digits}"
    raw = "|".join(
        " ".join(str(part or "").upper().split())
        for part in (address, city, zip_code)
    )
    return "addr:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


class OpportunityWorkflowService:
    """Ciclo 1h/48h/48h e outcomes, sem tocar em `leads`."""

    @staticmethod
    def _public(row: dict) -> dict:
        out = dict(row)
        for raw_key, key in (
            ("tags_json", "tags"),
            ("timeline_json", "timeline"),
            ("history_json", "history"),
            ("property_json", "property"),
        ):
            raw = out.pop(raw_key, None)
            if raw:
                try:
                    out[key] = json.loads(raw)
                except (TypeError, ValueError):
                    out[key] = [] if key in ("tags", "timeline", "history") else {}
            else:
                out[key] = [] if key in ("tags", "timeline", "history") else {}
        # O payload bruto da fonte fica só na BD: devolvê-lo ao cliente violaria
        # a regra de não expor termos/datasets da origem (invariante 27).
        out.pop("source_payload", None)
        return out

    @staticmethod
    def _json(value) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def create_opportunity(
        self,
        *,
        source_kind: str,
        source_record_id: str,
        address: str,
        city: str,
        state: str,
        zip_code: Optional[str] = None,
        bbl: Optional[str] = None,
        bin_value: Optional[str] = None,
        source_type: Optional[str] = None,
        category: Optional[str] = None,
        signal_type: Optional[str] = None,
        severity: Optional[str] = None,
        compliance_deadline: Optional[str] = None,
        job_value: Optional[float] = None,
        fine_balance: Optional[float] = None,
        fine_imposed: Optional[float] = None,
        fine_paid: Optional[float] = None,
        hearing_date: Optional[str] = None,
        hearing_status: Optional[str] = None,
        value_source: Optional[str] = None,
        description: Optional[str] = None,
        owner_name: Optional[str] = None,
        owner_type: Optional[str] = None,
        inspection_status: Optional[str] = None,
        received_at: Optional[str] = None,
        tags: Optional[list] = None,
        timeline: Optional[list] = None,
        history: Optional[list] = None,
        property: Optional[dict] = None,
        source_payload: Optional[dict] = None,
    ) -> dict:
        """Cria/atualiza o evento de origem; nao reserva nada."""
        if source_kind not in ("preventive", "reactive", "permit"):
            raise ValueError("invalid_source_kind")
        property_key = make_property_key(
            bbl=bbl, bin_value=bin_value, address=address, city=city, zip_code=zip_code
        )
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO opportunity_workflow
                   (property_key, source_kind, source_record_id, source_type,
                    address, city, state, zip_code, bbl, bin, category,
                    signal_type, severity, compliance_deadline, job_value,
                    value_source, fine_balance, fine_imposed, fine_paid,
                    hearing_date, hearing_status,
                    description, owner_name, owner_type, inspection_status,
                    received_at, tags_json, timeline_json, history_json,
                    property_json, source_payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_kind, source_record_id) DO UPDATE SET
                     property_key=excluded.property_key,
                     source_type=excluded.source_type,
                     address=excluded.address,
                     city=excluded.city,
                     state=excluded.state,
                     zip_code=excluded.zip_code,
                     bbl=excluded.bbl,
                     bin=excluded.bin,
                     category=excluded.category,
                     signal_type=excluded.signal_type,
                     severity=excluded.severity,
                     compliance_deadline=excluded.compliance_deadline,
                     job_value=excluded.job_value,
                     value_source=excluded.value_source,
                     fine_balance=excluded.fine_balance,
                     fine_imposed=excluded.fine_imposed,
                     fine_paid=excluded.fine_paid,
                     hearing_date=excluded.hearing_date,
                     hearing_status=excluded.hearing_status,
                     description=excluded.description,
                     owner_name=excluded.owner_name,
                     owner_type=excluded.owner_type,
                     inspection_status=excluded.inspection_status,
                     received_at=excluded.received_at,
                     tags_json=excluded.tags_json,
                     timeline_json=excluded.timeline_json,
                     history_json=excluded.history_json,
                     property_json=excluded.property_json,
                     source_payload=excluded.source_payload,
                     updated_at=CURRENT_TIMESTAMP""",
                (
                    property_key, source_kind, source_record_id, source_type,
                    address, city, state, zip_code, bbl, bin_value, category,
                    signal_type, severity, compliance_deadline, job_value,
                    value_source, fine_balance, fine_imposed, fine_paid,
                    hearing_date, hearing_status,
                    description, owner_name, owner_type, inspection_status,
                    received_at, self._json(tags), self._json(timeline),
                    self._json(history), self._json(property),
                    self._json(source_payload),
                ),
            )
            conn.commit()
            row = conn.execute(
                """SELECT * FROM opportunity_workflow
                   WHERE source_kind = ? AND source_record_id = ?""",
                (source_kind, source_record_id),
            ).fetchone()
            return self._public(dict(row))
        finally:
            conn.close()

    # Colunas que a camada de enriquecimento pode atualizar. `status`,
    # `reserved_by` e companhia ficam de fora: o ciclo de vida é dono delas.
    _ENRICHABLE = {
        "compliance_deadline": ("compliance_deadline", None),
        "job_value": ("job_value", None),
        "value_source": ("value_source", None),
        "fine_balance": ("fine_balance", None),
        "fine_imposed": ("fine_imposed", None),
        "fine_paid": ("fine_paid", None),
        "hearing_date": ("hearing_date", None),
        "hearing_status": ("hearing_status", None),
        "description": ("description", None),
        "category": ("category", None),
        "owner_name": ("owner_name", None),
        "owner_type": ("owner_type", None),
        "inspection_status": ("inspection_status", None),
        "tags": ("tags_json", "json"),
        "timeline": ("timeline_json", "json"),
        "history": ("history_json", "json"),
        "property": ("property_json", "json"),
    }

    def update_enrichment(self, opportunity_id: int, **fields) -> Optional[dict]:
        """Atualiza só campos de enriquecimento; nunca toca no ciclo de vida."""
        sets = []
        params: list = []
        for key, value in fields.items():
            spec = self._ENRICHABLE.get(key)
            if not spec:
                continue
            column, kind = spec
            sets.append(f"{column} = ?")
            params.append(self._json(value) if kind == "json" else value)
        if not sets:
            return self.get(opportunity_id)
        params.append(opportunity_id)
        conn = get_connection()
        try:
            conn.execute(
                f"""UPDATE opportunity_workflow
                    SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?""",
                tuple(params),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM opportunity_workflow WHERE id = ?", (opportunity_id,)
            ).fetchone()
            return self._public(dict(row)) if row else None
        finally:
            conn.close()

    def record_view(self, opportunity_id: int, user_id: int) -> Optional[str]:
        """Marca/atualiza a visualização de uma oportunidade por um utilizador."""
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO opportunity_views
                   (user_id, opportunity_id, first_viewed_at, last_viewed_at, view_count)
                   VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
                   ON CONFLICT(user_id, opportunity_id) DO UPDATE SET
                     last_viewed_at = CURRENT_TIMESTAMP,
                     view_count = opportunity_views.view_count + 1""",
                (user_id, opportunity_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT last_viewed_at FROM opportunity_views "
                "WHERE user_id = ? AND opportunity_id = ?",
                (user_id, opportunity_id),
            ).fetchone()
            return row["last_viewed_at"] if row else None
        finally:
            conn.close()

    def get(
        self, opportunity_id: int, viewer_id: Optional[int] = None
    ) -> Optional[dict]:
        conn = get_connection()
        try:
            if viewer_id:
                row = conn.execute(
                    """SELECT o.*, v.last_viewed_at AS viewed_at
                       FROM opportunity_workflow o
                       LEFT JOIN opportunity_views v
                         ON v.opportunity_id = o.id AND v.user_id = ?
                       WHERE o.id = ?""",
                    (viewer_id, opportunity_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT *, NULL AS viewed_at FROM opportunity_workflow WHERE id = ?",
                    (opportunity_id,),
                ).fetchone()
            return self._public(dict(row)) if row else None
        finally:
            conn.close()

    def list(
        self,
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        city: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        days: Optional[int] = None,
        deadline_within: Optional[int] = None,
        with_fines: bool = False,
        search: Optional[str] = None,
        viewer_id: Optional[int] = None,
    ) -> dict:
        """Lista oportunidades com janela/paginação e filtros no servidor."""
        limit = max(1, min(int(limit or 50), 300))
        offset = max(0, int(offset or 0))
        clauses = []
        params: list = []
        if kind:
            clauses.append("source_kind = ?")
            params.append(kind)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if city:
            clauses.append("UPPER(TRIM(city)) = UPPER(TRIM(?))")
            params.append(city)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if days:
            clauses.append(
                "date(COALESCE(received_at, created_at)) >= date('now', ?)"
            )
            params.append(f"-{int(days)} days")
        if deadline_within is not None:
            clauses.append("compliance_deadline IS NOT NULL")
            clauses.append(
                "date(compliance_deadline) <= date('now', ?)"
            )
            params.append(f"+{int(deadline_within)} days")
        if with_fines:
            clauses.append(
                "(COALESCE(fine_balance, 0) > 0 OR "
                "(COALESCE(fine_imposed, 0) - COALESCE(fine_paid, 0)) > 0)"
            )
        term = str(search or "").strip().lower()
        if term:
            like = f"%{term}%"
            clauses.append(
                "(LOWER(address) LIKE ? OR LOWER(city) LIKE ? OR "
                "LOWER(COALESCE(zip_code, '')) LIKE ? OR "
                "LOWER(COALESCE(category, '')) LIKE ? OR "
                "LOWER(COALESCE(description, '')) LIKE ? OR "
                "LOWER(COALESCE(owner_name, '')) LIKE ?)"
            )
            params.extend([like] * 6)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = get_connection()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM opportunity_workflow {where}",
                tuple(params),
            ).fetchone()["c"]
            rows = conn.execute(
                f"""SELECT o.*, v.last_viewed_at AS viewed_at
                    FROM opportunity_workflow o
                    LEFT JOIN opportunity_views v
                      ON v.opportunity_id = o.id AND v.user_id = ?
                    {where}
                    ORDER BY
                      CASE o.status
                        WHEN 'reserved' THEN 0
                        WHEN 'contacted' THEN 1
                        WHEN 'in_negotiation' THEN 2
                        WHEN 'available' THEN 3
                        ELSE 4
                      END,
                      CASE WHEN v.last_viewed_at IS NULL THEN 0 ELSE 1 END,
                      o.created_at DESC
                    LIMIT ? OFFSET ?""",
                (int(viewer_id or -1), *params, limit, offset),
            ).fetchall()
            count_clauses = []
            count_params: list = []
            if days:
                count_clauses.append(
                    "date(COALESCE(received_at, created_at)) >= date('now', ?)"
                )
                count_params.append(f"-{int(days)} days")
            count_where = (
                f"WHERE {' AND '.join(count_clauses)}" if count_clauses else ""
            )
            counts_rows = conn.execute(
                "SELECT source_kind, status, COUNT(*) AS c "
                f"FROM opportunity_workflow {count_where} "
                "GROUP BY source_kind, status",
                tuple(count_params),
            ).fetchall()
            counts = {"all": 0, "preventive": 0, "reactive": 0, "permit": 0}
            for row in counts_rows:
                counts["all"] += row["c"]
                if row["source_kind"] in counts:
                    counts[row["source_kind"]] += row["c"]
            return {
                "opportunities": [self._public(dict(r)) for r in rows],
                "counts": counts,
                "total": int(total or 0),
                "offset": offset,
                "limit": limit,
                "has_more": offset + len(rows) < int(total or 0),
                "insights": self.insights(kind=kind or "all", window_days=days),
            }
        finally:
            conn.close()

    # Severidade -> quatro buckets do painel (Crítica/Alta/Média/Rotina).
    _SEVERITY_BUCKETS = {
        "critical": "critical",
        "immediate": "critical",
        "emergency": "critical",
        "class_1": "critical",
        "class_c": "critical",
        "high": "high",
        "class_2": "high",
        "class_b": "high",
        "medium": "medium",
        "class_a": "medium",
    }

    def insights(
        self,
        kind: Optional[str] = "preventive",
        days: int = 10,
        window_days: Optional[int] = None,
    ) -> dict:
        """Agregados do painel lateral e dos KPI, sem expor dados sensíveis."""
        days = max(1, min(int(days or 10), 30))
        today = datetime.now(timezone.utc).date()
        clause_parts = []
        params: list = []
        if kind and kind != "all":
            clause_parts.append("source_kind = ?")
            params.append(kind)
        if window_days:
            clause_parts.append(
                "date(COALESCE(received_at, created_at)) >= date('now', ?)"
            )
            params.append(f"-{int(window_days)} days")
        clause = f"WHERE {' AND '.join(clause_parts)}" if clause_parts else ""
        conn = get_connection()
        try:
            rows = conn.execute(
                f"""SELECT id, address, city, state, zip_code, severity,
                           compliance_deadline, job_value, fine_balance,
                           fine_imposed, fine_paid, status, received_at, created_at
                    FROM opportunity_workflow {clause}""",
                tuple(params),
            ).fetchall()
        finally:
            conn.close()

        buckets = {"critical": 0, "high": 0, "medium": 0, "routine": 0}
        zips: dict = {}
        deadlines: list = []
        awaiting = 0
        fines_at_risk = 0.0
        fines_count = 0
        deadline_counts = {
            (today + timedelta(days=offset)).isoformat(): 0 for offset in range(days)
        }
        deadline_values = {key: 0.0 for key in deadline_counts}
        deadline_fines = {key: 0.0 for key in deadline_counts}
        series_counts = {
            (today - timedelta(days=offset)).isoformat(): 0
            for offset in range(days - 1, -1, -1)
        }

        for row in rows:
            severity = str(row["severity"] or "").strip().lower()
            buckets[self._SEVERITY_BUCKETS.get(severity, "routine")] += 1
            if row["status"] == "available":
                awaiting += 1
            zip_code = str(row["zip_code"] or "").strip()[:5]
            if len(zip_code) == 5:
                zips[zip_code] = zips.get(zip_code, 0) + 1

            # Multa real: saldo em aberto; se a fonte só publica o valor
            # imposto, usa imposed - paid. Nunca deriva da obra.
            balance = float(row["fine_balance"] or 0)
            if balance <= 0:
                imposed = float(row["fine_imposed"] or 0)
                paid = float(row["fine_paid"] or 0)
                balance = max(0.0, imposed - paid)
            if balance > 0:
                fines_at_risk += balance
                fines_count += 1

            value = float(row["job_value"] or 0)
            deadline = str(row["compliance_deadline"] or "").strip()
            if deadline:
                try:
                    target = datetime.fromisoformat(
                        deadline.replace("Z", "+00:00")
                    ).date()
                except ValueError:
                    target = None
                if target is not None:
                    days_left = (target - today).days
                    deadlines.append(
                        {
                            "id": row["id"],
                            "address": row["address"],
                            "city": row["city"],
                            "state": row["state"],
                            "severity": severity,
                            "deadline": target.isoformat(),
                            "days_left": days_left,
                            "job_value": round(value),
                            "fine_balance": round(balance),
                        }
                    )
                    key = target.isoformat()
                    if key in deadline_counts:
                        deadline_counts[key] += 1
                        deadline_values[key] += value
                        deadline_fines[key] += balance

            received = str(row["received_at"] or row["created_at"] or "")
            if received:
                try:
                    day = datetime.fromisoformat(
                        received.replace("Z", "+00:00")
                    ).date().isoformat()
                except ValueError:
                    day = received[:10]
                if day in series_counts:
                    series_counts[day] += 1

        deadlines.sort(key=lambda item: (item["days_left"], item["deadline"]))
        value_at_risk = sum(item["job_value"] for item in deadlines if item["days_left"] <= 7)

        return {
            "kind": kind or "all",
            "totals": {
                "count": len(rows),
                "awaiting_inspection": awaiting,
                "deadlines_7d": sum(1 for item in deadlines if item["days_left"] <= 7),
                "deadlines_3d": sum(1 for item in deadlines if item["days_left"] <= 3),
                "value_at_risk": value_at_risk,
                "fines_at_risk": round(fines_at_risk),
                "fines_count": fines_count,
            },
            "by_severity": buckets,
            "by_zip": [
                {"zip": zip_code, "count": count}
                for zip_code, count in sorted(
                    zips.items(), key=lambda item: (-item[1], item[0])
                )[:5]
            ],
            "deadlines": [
                {**item, "days_left": max(0, item["days_left"])}
                for item in deadlines[:5]
            ],
            "series": [
                {"date": day, "count": count} for day, count in series_counts.items()
            ],
            "deadline_series": [
                {
                    "date": day,
                    "count": deadline_counts[day],
                    "value": round(deadline_values[day]),
                    "fines": round(deadline_fines[day]),
                }
                for day in deadline_counts
            ],
        }

    def prune_old(self, retention_days: int = 90, dry_run: bool = False) -> int:
        """Purga oportunidades antigas, preservando ciclos ativos.

        A fila mostra 7 dias; a BD guarda até `retention_days` para auditoria.
        Linhas reservadas/contactadas/em negociação nunca são apagadas.
        """
        days = max(1, int(retention_days or 90))
        active = "'reserved','contacted','in_negotiation'"
        where = (
            f"status NOT IN ({active}) AND "
            "date(created_at) < date('now', ?)"
        )
        conn = get_connection()
        try:
            if dry_run:
                row = conn.execute(
                    f"SELECT COUNT(*) AS c FROM opportunity_workflow WHERE {where}",
                    (f"-{days} days",),
                ).fetchone()
                return int(row["c"] or 0)
            cursor = conn.execute(
                f"DELETE FROM opportunity_workflow WHERE {where}",
                (f"-{days} days",),
            )
            conn.execute(
                "DELETE FROM opportunity_views WHERE opportunity_id NOT IN "
                "(SELECT id FROM opportunity_workflow)"
            )
            conn.commit()
            return int(cursor.rowcount or 0)
        finally:
            conn.close()

    def _release_property_lock(self, conn: sqlite3.Connection, opportunity_id: int) -> None:
        conn.execute(
            "DELETE FROM property_locks WHERE owner_kind='opportunity' AND owner_id=?",
            (opportunity_id,),
        )

    def _lock_conflict(
        self,
        conn: sqlite3.Connection,
        opportunity: dict,
        user_id: int,
    ) -> Optional[str]:
        """Devolve 'property_locked' se outro ciclo ativo detem o imovel."""
        key = opportunity["property_key"]
        lock = conn.execute(
            "SELECT * FROM property_locks WHERE property_key = ?", (key,)
        ).fetchone()
        if lock:
            expires = _parse_dt(lock["expires_at"])
            if expires and expires < utcnow():
                conn.execute("DELETE FROM property_locks WHERE property_key = ?", (key,))
            else:
                same = (
                    lock["owner_kind"] == "opportunity"
                    and int(lock["owner_id"]) == int(opportunity["id"])
                )
                if not same or lock["reserved_by"] not in (None, user_id):
                    return "property_locked"

        # Trava cruzada: um lead reativo ativo no mesmo BBL.
        bbl = re.sub(r"\D", "", str(opportunity.get("bbl") or ""))
        if bbl:
            row = conn.execute(
                """SELECT id, reserved_by FROM leads
                   WHERE bbl = ? AND lead_status IN ('reserved','contacted','in_negotiation')
                   LIMIT 1""",
                (bbl,),
            ).fetchone()
            if row and row["reserved_by"] not in (None, user_id):
                return "property_locked"
        return None

    def reserve(self, opportunity_id: int, user_id: int, minutes: int = 60) -> dict:
        """Reserva 1h e consome 1 unidade da cota diaria.

        A cota e' reservada antes da transacao para nao abrir uma segunda
        conexao dentro do `BEGIN IMMEDIATE`; se a reserva falhar, e' estornada.
        """
        opportunity = self.get(opportunity_id)
        if not opportunity:
            return {"error": "not_found"}

        if opportunity["status"] in ("reserved", "contacted", "in_negotiation"):
            if opportunity["reserved_by"] == user_id:
                return {
                    "opportunity": opportunity,
                    "idempotent": True,
                    "counted_again": False,
                }
            return {"error": "already_reserved", "opportunity": opportunity}
        if opportunity["status"] == "converted":
            return {"error": "already_converted", "opportunity": opportunity}

        quota = db_service._service.reserve_daily_quota(user_id)
        if not quota:
            return {"error": "daily_limit_reached"}

        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conflict = self._lock_conflict(conn, opportunity, user_id)
            if conflict:
                conn.rollback()
                db_service._service.refund_daily_quota(user_id)
                return {"error": conflict}

            conn.execute(
                """UPDATE opportunity_workflow
                   SET status='reserved', reserved_by=?,
                       reserved_until=datetime('now', ?),
                       stage_expires_at=datetime('now', ?),
                       updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (user_id, f"+{int(minutes)} minutes", f"+{int(minutes)} minutes", opportunity_id),
            )
            conn.execute(
                """INSERT INTO property_locks
                   (property_key, owner_kind, owner_id, reserved_by, expires_at, updated_at)
                   VALUES (?, 'opportunity', ?, ?, datetime('now', ?), CURRENT_TIMESTAMP)
                   ON CONFLICT(property_key) DO UPDATE SET
                     owner_kind='opportunity',
                     owner_id=excluded.owner_id,
                     reserved_by=excluded.reserved_by,
                     expires_at=excluded.expires_at,
                     updated_at=CURRENT_TIMESTAMP""",
                (
                    opportunity["property_key"], opportunity_id, user_id,
                    f"+{int(minutes)} minutes",
                ),
            )
            conn.commit()
            updated = self.get(opportunity_id) or opportunity
            return {
                "opportunity": updated,
                "idempotent": False,
                "counted_again": True,
                "quota": db_service._service.get_daily_leads_used(user_id),
            }
        except Exception:
            conn.rollback()
            db_service._service.refund_daily_quota(user_id)
            raise
        finally:
            conn.close()

    def mark_contacted(self, opportunity_id: int, user_id: int) -> dict:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM opportunity_workflow WHERE id=?", (opportunity_id,)
            ).fetchone()
            if not row:
                conn.rollback()
                return {"error": "not_found"}
            if row["status"] == "converted":
                conn.rollback()
                return {"error": "already_converted"}
            if row["status"] == "available":
                conn.rollback()
                return {"error": "not_reserved"}
            if row["reserved_by"] not in (None, user_id):
                conn.rollback()
                return {"error": "not_owner"}
            if row["status"] in ("contacted", "in_negotiation"):
                conn.commit()
                return {"opportunity": self._public(dict(row)), "renewed": False}
            conn.execute(
                """UPDATE opportunity_workflow
                   SET status='contacted', reserved_by=?,
                       contacted_at=COALESCE(contacted_at, CURRENT_TIMESTAMP),
                       stage_expires_at=datetime('now', '+48 hours'),
                       updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (user_id, opportunity_id),
            )
            conn.execute(
                """UPDATE property_locks
                   SET reserved_by=?, expires_at=datetime('now', '+48 hours'),
                       updated_at=CURRENT_TIMESTAMP
                   WHERE owner_kind='opportunity' AND owner_id=?""",
                (user_id, opportunity_id),
            )
            conn.commit()
            return {"opportunity": self.get(opportunity_id), "renewed": True}
        finally:
            conn.close()

    def mark_negotiation(self, opportunity_id: int, user_id: int) -> dict:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM opportunity_workflow WHERE id=?", (opportunity_id,)
            ).fetchone()
            if not row:
                conn.rollback()
                return {"error": "not_found"}
            if row["status"] == "converted":
                conn.rollback()
                return {"error": "already_converted"}
            if row["status"] == "available":
                conn.rollback()
                return {"error": "not_reserved"}
            if row["reserved_by"] not in (None, user_id):
                conn.rollback()
                return {"error": "not_owner"}
            if row["status"] == "in_negotiation":
                conn.commit()
                return {"opportunity": self._public(dict(row)), "renewed": False}
            conn.execute(
                """UPDATE opportunity_workflow
                   SET status='in_negotiation', reserved_by=?,
                       negotiated_at=COALESCE(negotiated_at, CURRENT_TIMESTAMP),
                       stage_expires_at=datetime('now', '+48 hours'),
                       updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (user_id, opportunity_id),
            )
            conn.execute(
                """UPDATE property_locks
                   SET reserved_by=?, expires_at=datetime('now', '+48 hours'),
                       updated_at=CURRENT_TIMESTAMP
                   WHERE owner_kind='opportunity' AND owner_id=?""",
                (user_id, opportunity_id),
            )
            conn.commit()
            return {"opportunity": self.get(opportunity_id), "renewed": True}
        finally:
            conn.close()

    def convert(self, opportunity_id: int, user_id: int) -> dict:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM opportunity_workflow WHERE id=?", (opportunity_id,)
            ).fetchone()
            if not row:
                conn.rollback()
                return {"error": "not_found"}
            if row["status"] == "converted":
                conn.rollback()
                return {"error": "already_converted"}
            if row["status"] == "available":
                conn.rollback()
                return {"error": "not_reserved"}
            if row["reserved_by"] not in (None, user_id):
                conn.rollback()
                return {"error": "not_owner"}
            conn.execute(
                """UPDATE opportunity_workflow
                   SET status='converted', converted_at=CURRENT_TIMESTAMP,
                       stage_expires_at=NULL, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (opportunity_id,),
            )
            self._release_property_lock(conn, opportunity_id)
            conn.commit()
            return {"opportunity": self.get(opportunity_id)}
        finally:
            conn.close()

    def record_outcome(
        self,
        *,
        opportunity_id: Optional[int],
        lead_id: Optional[int],
        outcome: str,
        contract_value: Optional[float] = None,
        lost_reason: Optional[str] = None,
        recorded_by: Optional[int] = None,
        currency: str = "USD",
    ) -> dict:
        if outcome not in VALID_OUTCOMES:
            raise ValueError("invalid_outcome")
        if contract_value is not None and contract_value < 0:
            raise ValueError("invalid_contract_value")
        if opportunity_id is None and lead_id is None:
            raise ValueError("subject_required")

        now = _now_iso()
        won_at = now if outcome == "won" else None
        lost_at = now if outcome == "lost" else None
        conn = get_connection()
        try:
            if opportunity_id is not None:
                conn.execute(
                    """INSERT INTO opportunity_outcomes
                       (opportunity_id, lead_id, outcome, won_at, lost_at,
                        contract_value, currency, lost_reason, recorded_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(opportunity_id) DO UPDATE SET
                         outcome=excluded.outcome,
                         won_at=excluded.won_at,
                         lost_at=excluded.lost_at,
                         contract_value=excluded.contract_value,
                         currency=excluded.currency,
                         lost_reason=excluded.lost_reason,
                         recorded_by=excluded.recorded_by,
                         recorded_at=CURRENT_TIMESTAMP""",
                    (
                        opportunity_id, lead_id, outcome, won_at, lost_at,
                        contract_value, currency, lost_reason, recorded_by,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO opportunity_outcomes
                       (opportunity_id, lead_id, outcome, won_at, lost_at,
                        contract_value, currency, lost_reason, recorded_by)
                       VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        lead_id, outcome, won_at, lost_at,
                        contract_value, currency, lost_reason, recorded_by,
                    ),
                )
            conn.commit()
            row = conn.execute(
                """SELECT * FROM opportunity_outcomes
                   WHERE (opportunity_id = ?) OR (? IS NULL AND lead_id = ?)
                   ORDER BY id DESC LIMIT 1""",
                (opportunity_id, opportunity_id, lead_id),
            ).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()


opportunity_workflow = OpportunityWorkflowService()
