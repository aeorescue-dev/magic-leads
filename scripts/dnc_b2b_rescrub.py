"""Re-scrub interno do DNC sob a política B2B (NY). Sem ferramentas pagas.

Uso:
  python scripts/dnc_b2b_rescrub.py
  # ou via railway ssh
"""
from __future__ import annotations

import json
from datetime import timedelta

from backend.services import b2b_voice as v


def main() -> None:
    v.init()
    now = v._utc_now()
    expires = now + timedelta(days=31)
    conn = v.get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO dnc_checks
              (phone, listed, source, provider, checked_at, expires_at, raw_status)
            SELECT phone, 0, 'b2b_exempt', 'internal_b2b_policy', ?, ?, 'b2b_exempt'
            FROM prospect_companies
            WHERE entity_type='business'
              AND state='NY'
              AND status NOT IN ('do_not_call','invalid','meeting')
              AND LENGTH(phone)=12 AND phone LIKE '+1%'
            ON CONFLICT(phone) DO UPDATE SET
              listed=0,
              source='b2b_exempt',
              provider='internal_b2b_policy',
              checked_at=excluded.checked_at,
              expires_at=excluded.expires_at,
              raw_status='b2b_exempt'
            """,
            (now.isoformat(), expires.isoformat()),
        )
        conn.commit()
        covered = conn.execute(
            "SELECT COUNT(*) c FROM dnc_checks "
            "WHERE source='b2b_exempt' AND listed=0 AND expires_at>?",
            (now.isoformat(),),
        ).fetchone()["c"]
        print(
            "DNC_B2B_RESCRUB",
            json.dumps(
                {
                    "rowcount": cur.rowcount,
                    "covered": covered,
                    "expires_at": expires.isoformat(),
                },
                ensure_ascii=True,
            ),
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
