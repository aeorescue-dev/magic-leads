"""P1: frescura diaria das violacoes HPD/DOB + consolidacao da reincidencia.

Reverifica por `external_id` os leads legais abertos/desconhecidos e atualiza
`case_status`/`signal_status`. Fechados saem do feed; `unknown` que a fonte
confirma como Open passam a `open`. No fim recalcula `lead_history` (365 dias)
para todos os imoveis com historico.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from ..scrapers.socrata_311 import socrata_scraper
from ..utils.logger import logger
from .db import db_service
from .lead_rules import normalize_case_status

BATCH_SIZE = 200

_HPD = {
    "source": "hpd_violation",
    "domain": "data.cityofnewyork.us",
    "dataset": "wvxf-dwi5",
    "id_field": "violationid",
    "select": "violationid, violationstatus, currentstatus, novissueddate",
}
_DOB = {
    "source": "dob_violation",
    "domain": "data.cityofnewyork.us",
    "dataset": "3h2n-5cm9",
    "id_field": "violation_number",
    "select": "violation_number, disposition_date, disposition_comments",
}


def _chunks(items: list, size: int) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _quote_ids(ids: list[str]) -> str:
    return ", ".join("'" + str(i).replace("'", "''") + "'" for i in ids)


async def _fetch_rows(cfg: dict, ids: list[str]) -> list:
    rows: list = []
    for chunk in _chunks(ids, BATCH_SIZE):
        where = f"{cfg['id_field']} in ({_quote_ids(chunk)})"
        part = await socrata_scraper._fetch_soql(
            domain=cfg["domain"],
            dataset=cfg["dataset"],
            select=cfg["select"],
            where=where,
            order=None,
            limit=len(chunk),
        )
        rows.extend(part or [])
    return rows


async def _refresh_hpd() -> dict:
    leads = await db_service.list_leads_for_freshness(["hpd_violation"])
    if not leads:
        return {"checked": 0, "closed": 0, "updated": 0, "errors": []}
    by_id = {
        str(lead["external_id"]).strip(): lead
        for lead in leads if lead.get("external_id")
    }
    try:
        rows = await _fetch_rows(_HPD, list(by_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FRESHNESS] HPD fetch falhou: %s", exc)
        return {"checked": 0, "closed": 0, "updated": 0, "errors": [f"hpd: {exc}"]}

    checked = closed = updated = 0
    for row in rows:
        ext = str(row.get("violationid") or "").strip()
        lead = by_id.get(ext)
        if not lead:
            continue
        raw = row.get("violationstatus") or row.get("currentstatus") or ""
        status = normalize_case_status(raw)
        if status == "unknown":
            continue
        checked += 1
        if status == "closed":
            closed += 1
        ok = await db_service.update_lead_freshness(
            lead["id"],
            str(raw) or None,
            status,
            closed_dt=None,
            resolution=str(row.get("currentstatus") or "") or None,
        )
        if ok:
            updated += 1
    return {"checked": checked, "closed": closed, "updated": updated, "errors": []}


async def _refresh_dob() -> dict:
    leads = await db_service.list_leads_for_freshness(["dob_violation"])
    if not leads:
        return {"checked": 0, "closed": 0, "updated": 0, "errors": []}
    by_id = {
        str(lead["external_id"]).strip(): lead
        for lead in leads if lead.get("external_id")
    }
    try:
        rows = await _fetch_rows(_DOB, list(by_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FRESHNESS] DOB fetch falhou: %s", exc)
        return {"checked": 0, "closed": 0, "updated": 0, "errors": [f"dob: {exc}"]}

    checked = closed = updated = 0
    for row in rows:
        ext = str(row.get("violation_number") or "").strip()
        lead = by_id.get(ext)
        if not lead:
            continue
        disposed = str(row.get("disposition_date") or "").strip()
        status = "closed" if disposed else "open"
        checked += 1
        if status == "closed":
            closed += 1
        ok = await db_service.update_lead_freshness(
            lead["id"],
            "Closed" if disposed else "Open",
            status,
            closed_dt=disposed or None,
            resolution=str(row.get("disposition_comments") or "") or None,
        )
        if ok:
            updated += 1
    return {"checked": checked, "closed": closed, "updated": updated, "errors": []}


async def run_freshness() -> dict:
    """Executa HPD + DOB e consolida `lead_history`. Nunca levanta."""
    started = datetime.now(timezone.utc).isoformat()
    hpd = await _refresh_hpd()
    dob = await _refresh_dob()

    history_ids = await db_service.list_lead_ids_with_history()
    refreshed = 0
    try:
        refreshed = await db_service.refresh_lead_history(history_ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FRESHNESS] refresh do historico falhou: %s", exc)

    errors = list(hpd["errors"]) + list(dob["errors"])
    result = {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "hpd_checked": hpd["checked"],
        "hpd_closed": hpd["closed"],
        "dob_checked": dob["checked"],
        "dob_closed": dob["closed"],
        "history_refreshed": refreshed,
        "status": "partial" if errors else "ok",
        "errors": " | ".join(errors) if errors else None,
    }
    try:
        await db_service.record_freshness_run(result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FRESHNESS] registo do run falhou: %s", exc)
    logger.info(
        "[FRESHNESS] HPD %s/%s fechados · DOB %s/%s fechados · historico %s",
        hpd["closed"], hpd["checked"], dob["closed"], dob["checked"], refreshed,
    )
    return result
