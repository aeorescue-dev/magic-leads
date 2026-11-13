"""Adaptador de ingestão da camada preventiva.

Lê os leads já capturados (chamados abertos e obrigações legais) e cria/atualiza
linhas em `opportunity_workflow` com `source_kind='preventive'`. É o elo que
faltava entre a ingestão reativa e o feed de pré-inspeção.

Regras:
- Nunca escreve em `leads` (camada aditiva).
- Deduplica por `property_key` (BBL/BIN/morada): um imóvel só entra uma vez.
- O payload bruto fica em `source_payload` (interno; a API já não o expõe).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .db import get_connection
from .opportunity_workflow import make_property_key, opportunity_workflow

# Urgência do lead -> severidade da pré-inspeção.
_SEVERITY = {"high": "immediate", "medium": "medium", "low": "routine"}
_DEFAULT_SIGNAL_TYPES = ("open_request", "legal_obligation")


class PreventiveIngestionService:
    """Mapeia leads reativos para oportunidades preventivas."""

    @staticmethod
    def _existing_property_keys() -> set:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT property_key FROM opportunity_workflow "
                "WHERE source_kind = 'preventive'"
            ).fetchall()
            return {row["property_key"] for row in rows if row["property_key"]}
        finally:
            conn.close()

    @staticmethod
    def _timeline(received_at: Optional[str]) -> list:
        day = str(received_at or "")[:10] or None
        return [
            {"key": "complaint", "state": "done", "date": day},
            {"key": "inspection", "state": "current"},
            {"key": "violation", "state": "future"},
        ]

    @staticmethod
    def _owner_type(lead: dict, owner_name: str) -> str:
        if str(lead.get("owner_class") or "").lower() == "institutional":
            return "institutional"
        if lead.get("institutional"):
            return "institutional"
        if owner_name:
            return "company"
        return "unknown"

    def map_lead(self, lead: dict, now: Optional[datetime] = None) -> dict:
        """Converte uma linha de `leads` no payload de `create_opportunity`."""
        current = now or datetime.now(timezone.utc)
        received_at = str(lead.get("date_reported") or "") or None
        owner_name = str(lead.get("owner_name") or "").strip()
        deadline = str(lead.get("sla_target_dt") or "")[:10] or None

        tags = ["inspection_possible"]
        if owner_name:
            tags.append("owner_identified")
        if deadline:
            try:
                target = datetime.fromisoformat(deadline).date()
                if (target - current.date()).days <= 7:
                    tags.append("deadline_soon")
            except ValueError:
                pass

        return {
            "source_kind": "preventive",
            "source_record_id": f"lead-{lead['id']}",
            "source_type": "pre_inspection",
            "address": lead.get("address") or "",
            "city": lead.get("city") or "",
            "state": lead.get("state") or "",
            "zip_code": lead.get("zip_code"),
            "bbl": lead.get("bbl"),
            "bin_value": lead.get("bin"),
            "category": lead.get("issue_category") or "Unclassified",
            "signal_type": lead.get("signal_type") or "open_request",
            "severity": _SEVERITY.get(str(lead.get("urgency_level") or "").lower(), "high"),
            "compliance_deadline": deadline,
            "job_value": None,
            "description": lead.get("issue_description"),
            "owner_name": owner_name or None,
            "owner_type": self._owner_type(lead, owner_name),
            "inspection_status": "possible",
            "received_at": received_at,
            "tags": tags,
            "timeline": self._timeline(received_at),
            # Interno (a API pública remove este campo).
            "source_payload": {
                "lead_id": lead.get("id"),
                "signal_type": lead.get("signal_type"),
                "source_type": lead.get("source_type"),
            },
        }

    @staticmethod
    def _load_lead(lead: dict) -> dict:
        """Relê a linha completa (alguns chamadores devolvem só um resumo)."""
        lead_id = lead.get("id")
        if not lead_id:
            return lead
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
            return dict(row) if row else lead
        finally:
            conn.close()

    def ingest_lead(self, lead: dict) -> dict:
        lead = self._load_lead(lead)
        payload = self.map_lead(lead)
        key = make_property_key(
            bbl=payload.get("bbl"),
            bin_value=payload.get("bin_value"),
            address=payload.get("address"),
            city=payload.get("city"),
            zip_code=payload.get("zip_code"),
        )
        if key in self._existing_property_keys():
            return {"status": "skipped_duplicate", "property_key": key}
        row = opportunity_workflow.create_opportunity(**payload)
        return {"status": "ingested", "id": row["id"], "property_key": key}

    def ingest_from_leads(
        self,
        limit: int = 200,
        include_legal_obligation: bool = True,
    ) -> dict:
        """Percorre os leads elegíveis e alimenta a camada preventiva."""
        signal_types = list(_DEFAULT_SIGNAL_TYPES if include_legal_obligation else ("open_request",))
        placeholders = ",".join("?" * len(signal_types))
        conn = get_connection()
        try:
            rows = conn.execute(
                f"""SELECT * FROM leads
                    WHERE signal_type IN ({placeholders})
                    ORDER BY date_reported DESC
                    LIMIT ?""",
                (*signal_types, max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()

        existing = self._existing_property_keys()
        stats = {
            "scanned": len(rows),
            "ingested": 0,
            "skipped_duplicate": 0,
            "ids": [],
        }
        for row in rows:
            lead = dict(row)
            key = make_property_key(
                bbl=lead.get("bbl"),
                bin_value=lead.get("bin"),
                address=lead.get("address"),
                city=lead.get("city"),
                zip_code=lead.get("zip_code"),
            )
            if key in existing:
                stats["skipped_duplicate"] += 1
                continue
            result = self.ingest_lead(lead)
            if result["status"] == "ingested":
                stats["ingested"] += 1
                stats["ids"].append(result["id"])
                existing.add(key)
            else:
                stats["skipped_duplicate"] += 1
        return stats


preventive_ingestion = PreventiveIngestionService()
