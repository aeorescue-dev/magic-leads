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
import re
import sqlite3
from datetime import datetime, timezone
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
                    signal_type, severity, compliance_deadline, job_value)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                     updated_at=CURRENT_TIMESTAMP""",
                (
                    property_key, source_kind, source_record_id, source_type,
                    address, city, state, zip_code, bbl, bin_value, category,
                    signal_type, severity, compliance_deadline, job_value,
                ),
            )
            conn.commit()
            row = conn.execute(
                """SELECT * FROM opportunity_workflow
                   WHERE source_kind = ? AND source_record_id = ?""",
                (source_kind, source_record_id),
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def get(self, opportunity_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM opportunity_workflow WHERE id = ?", (opportunity_id,)
            ).fetchone()
            return dict(row) if row else None
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
            if row["reserved_by"] not in (None, user_id):
                conn.rollback()
                return {"error": "not_owner"}
            if row["status"] in ("contacted", "in_negotiation", "converted"):
                conn.commit()
                return {"opportunity": dict(row), "renewed": False}
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
            if row["reserved_by"] not in (None, user_id):
                conn.rollback()
                return {"error": "not_owner"}
            if row["status"] in ("in_negotiation", "converted"):
                conn.commit()
                return {"opportunity": dict(row), "renewed": False}
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
