"""Relatório diário por DID (foco no 518 vs 929).

Uso:
  type scripts\\did_518_report.py | railway ssh --service magic-leads \
    --environment production -p 7b6bbb01-0fd5-462c-b723-3b3597b60d79 python
"""
from __future__ import annotations

import json

from backend.services import b2b_voice as v

FOCUS = "+15189429910"  # 518 Albany


def main() -> None:
    v.init()
    conn = v.get_conn()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                  COALESCE(NULLIF(from_number, ''), '-') AS did,
                  COUNT(*) AS dialed,
                  SUM(answered_at IS NOT NULL) AS answered,
                  SUM(CASE WHEN amd_result LIKE 'human%' THEN 1 ELSE 0 END) AS human,
                  SUM(CASE WHEN amd_result = 'machine' THEN 1 ELSE 0 END) AS machine,
                  SUM(CASE WHEN answered_at IS NULL THEN 1 ELSE 0 END) AS unanswered,
                  ROUND(AVG(CASE WHEN amd_result LIKE 'human%'
                                 THEN duration_seconds END), 1) AS aht_human,
                  SUM(CASE WHEN intent = 'opt_out' OR status = 'opt_out'
                           THEN 1 ELSE 0 END) AS opt_out,
                  SUM(CASE WHEN showcase_clicked_at IS NOT NULL
                           THEN 1 ELSE 0 END) AS clicks,
                  SUM(COALESCE(revenue_cents, 0)) AS revenue_cents,
                  ROUND(100.0 * SUM(answered_at IS NOT NULL) / COUNT(*), 1)
                    AS answer_rate
                FROM voice_calls
                WHERE datetime(created_at) >= datetime('now', '-1 day')
                  AND COALESCE(provider, '') = 'telnyx'
                  AND COALESCE(campaign_id, '') <> 'test_call'
                GROUP BY 1
                ORDER BY dialed DESC
                """
            ).fetchall()
        ]
    finally:
        conn.close()

    print("DID_REPORT", json.dumps({"focus": FOCUS, "rows": rows}, ensure_ascii=True))
    for row in rows:
        tag = "FOCUS_518" if row["did"] == FOCUS else "OTHER"
        print(
            "DID",
            tag,
            row["did"],
            "dialed", row["dialed"],
            "answered", row["answered"],
            "human", row["human"],
            "machine", row["machine"],
            "unanswered", row["unanswered"],
            "answer_rate", row["answer_rate"],
            "aht_human", row["aht_human"],
            "opt_out", row["opt_out"],
            "clicks", row["clicks"],
            "revenue_cents", row["revenue_cents"],
        )


if __name__ == "__main__":
    main()
