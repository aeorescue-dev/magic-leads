"""Deduplicação de alertas operacionais.

A tabela `system_alerts` é append-only: o mesmo problema (ex.: BOSTON stale)
gera uma linha nova a cada ciclo. Para o painel, o que interessa é o estado
atual por código, não o histórico bruto. Este módulo é puro (sem BD) para
poder ser usado pela API admin e pelo System Health sem efeitos laterais.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

_CRITICAL = {"critical", "error", "fail", "fatal"}
_WARNING = {"warning", "warn"}
_INFO = {"info", "informational", "notice", "debug"}


def severity_rank(level: Any) -> int:
    """0 = crítico, 1 = aviso, 2 = informativo."""
    value = str(level or "").strip().lower()
    if value in _CRITICAL:
        return 0
    if value in _WARNING:
        return 1
    if value in _INFO:
        return 2
    return 1


def _as_dict(row: Any) -> dict:
    if isinstance(row, dict):
        return dict(row)
    try:
        return {key: row[key] for key in row.keys()}
    except Exception:  # noqa: BLE001 - sqlite3.Row ou mapping simples
        return dict(row)


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return parsed


def dedupe_alerts(rows: Iterable[Any], limit: int = 100) -> list[dict]:
    """Agrupa alertas por `code`, mantendo o mais recente de cada grupo.

    Devolve o código, a mensagem mais recente, a severidade máxima observada,
    contagem de ocorrências, primeira/última ocorrência e o id mais recente.
    Ordena por severidade (crítico primeiro) e depois por recência.
    """
    groups: dict[str, dict] = {}
    for raw in rows or []:
        row = _as_dict(raw)
        code = str(row.get("code") or "").strip() or "UNKNOWN"
        created = _parse(row.get("created_at"))
        rank = severity_rank(row.get("level"))
        current = groups.get(code)
        if current is None:
            groups[code] = {
                **row,
                "code": code,
                "occurrences": 1,
                "first_seen": row.get("created_at"),
                "last_seen": row.get("created_at"),
                "latest_id": row.get("id"),
                "_rank": rank,
                "_created": created,
            }
            continue

        current["occurrences"] = int(current.get("occurrences") or 0) + 1
        # A mensagem exibida é a do id mais recente; a severidade é a máxima
        # observada no grupo. Nunca deixar um aviso recente "baixar" um
        # crítico antigo ainda aberto.
        row_id = int(row.get("id") or 0)
        latest_id = int(current.get("latest_id") or 0)
        if row_id >= latest_id:
            current["message"] = row.get("message")
            current["created_at"] = row.get("created_at")
            current["last_seen"] = row.get("created_at")
            current["latest_id"] = row.get("id")
            current["context"] = row.get("context")
            current["_created"] = created
        if rank < int(current["_rank"]):
            current["level"] = row.get("level")
            current["_rank"] = rank
        if created and (
            current.get("first_seen") is None
            or created < (_parse(current.get("first_seen")) or created)
        ):
            current["first_seen"] = row.get("created_at")

    ordered = sorted(
        groups.values(),
        key=lambda item: (
            1 if item.get("_rank") is None else int(item["_rank"]),
            -int(item.get("latest_id") or 0),
        ),
    )
    out: list[dict] = []
    for item in ordered[: max(1, int(limit))]:
        item.pop("_rank", None)
        item.pop("_created", None)
        out.append(item)
    return out
