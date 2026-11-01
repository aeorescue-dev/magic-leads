"""One-off: trocar e-mails genericos dos prontos por nominais (OSINT do dono).

Nao usa a Brave. So atua em entidades `ready` sem mensagem ativa e nunca
sobrescreve outro contacto. Seguro por design: qualquer duvida -> skip.
"""
from __future__ import annotations

import argparse
import time

from backend.services import owner_email
from backend.services.db import db_service

CITIES = ("NYC", "CHICAGO", "BOSTON", "DALLAS")


def run(limit: int = 200, budget_s: int = 1500) -> dict:
    svc = db_service._service
    counts: dict[str, int] = {}
    started = time.time()
    processed = 0
    for city in CITIES:
        if time.time() - started > budget_s:
            break
        entities = [
            e for e in svc.list_contractor_entities(city)
            if e.get("status") == "ready"
            and (e.get("email") or "")
            and (e.get("domain") or "")
            and (e.get("email_source") or "") != "owner_osint"
        ]
        for entity in entities:
            if processed >= limit or time.time() - started > budget_s:
                break
            processed += 1
            found = owner_email.find_owner_email(
                entity["domain"], entity.get("legal_name") or ""
            )
            if not found or found.lower() == (entity.get("email") or "").lower():
                counts["no_named"] = counts.get("no_named", 0) + 1
                continue
            result = svc.upgrade_contact_email(int(entity["id"]), found)
            counts[result["status"]] = counts.get(result["status"], 0) + 1
            if processed % 5 == 0:
                print("PROGRESS", processed, counts, round(time.time() - started, 1),
                      flush=True)
    print("DONE", processed, counts, round(time.time() - started, 1), flush=True)
    return {"processed": processed, "counts": counts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--budget", type=int, default=1500)
    args = parser.parse_args()
    run(limit=args.limit, budget_s=args.budget)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
