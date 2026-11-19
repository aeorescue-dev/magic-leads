#!/usr/bin/env python3
"""Envia o pedido objetivo à Telnyx sobre o brand 10DLC — fail-closed.

Uso:
  python scripts/send_10dlc_email.py                 # dry-run (imprime o payload)
  python scripts/send_10dlc_email.py --send          # envia via Resend
  python scripts/send_10dlc_email.py --send --attachment CP575G.pdf

Credenciais (nunca hardcoded):
  RESEND_API_KEY ou EMAIL_API_KEY
  EMAIL_FROM (ex.: "Magic Leads Team <support@magicleads.app>")

O e-mail vai para 10dlcquestions@telnyx.com, com Reply-To e Cc para
aeorescue@gmail.com (canal de acompanhamento do owner).
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TO = ["10dlcquestions@telnyx.com"]
CC = ["aeorescue@gmail.com"]
REPLY_TO = "aeorescue@gmail.com"
SUBJECT = (
    "Re: Manual brand verification request - Brand ID "
    "4b2001a1-d187-485a-2062-cb5501a9fe37 / TCR BCW3GRB"
)
IN_REPLY_TO = "<010001a1d1b7ca61-491a3f20-060c-4d95-aad6-805e44255d8b-000000@email.amazonses.com>"

BODY = """Hello Telnyx 10DLC Support,

Thank you for confirming that the appeal was denied and for contacting TCR
for the reason. Please share the exact TCR denial reason/code for brand
BCW3GRB as soon as you receive it.

We believe the brand record needs a data correction before any new appeal:

- Brand ID: 4b2001a1-d187-485a-2062-cb5501a9fe37
- TCR Brand ID: BCW3GRB
- Current entityType: PRIVATE_PROFIT
- Requested entityType: SOLE_PROPRIETOR
- Legal name: FABIO HENRIQUE SOARES DE OLIVEIRA
- Trade name / display name: MAGIC LEADS TECHNOLOGIES
- EIN: 43-2940311 (Name Control SOAR, as shown on the attached CP575G)
- Business contact: fabio@magicleads.app (please resend the verification link)

The CP575G shows the EIN under the individual's name with the trade name
MAGIC LEADS TECHNOLOGIES. That is why we believe SOLE_PROPRIETOR is the
correct classification, not PRIVATE_PROFIT.

Please confirm:

1. Can the existing brand be corrected in place to entityType=SOLE_PROPRIETOR
   using the CP575G data above?
2. If it cannot be corrected, can we delete or replace this brand without
   paying the brand/vetting fees twice and without leaving a conflicting
   record in the TCR?
3. If a new SOLE_PROPRIETOR brand with SMS OTP is required, will the existing
   number +19739137808 and messaging profile
   4001a1d1-8bd1-4cdc-a13b-e05580d2b932 be reusable?

We will not create a duplicate brand, campaign or number assignment until you
confirm the correct path. The CP575G is attached again for reference.

Thank you,
Magic Leads Team
"""


def resend_key() -> str:
    key = os.environ.get("RESEND_API_KEY") or os.environ.get("EMAIL_API_KEY") or ""
    if not key:
        sys.exit("ERRO: define RESEND_API_KEY (ou EMAIL_API_KEY) antes de enviar.")
    return key


def from_address() -> str:
    value = os.environ.get("EMAIL_FROM") or "Magic Leads Team <support@magicleads.app>"
    return value


def build_payload(attachment: Path | None) -> dict:
    payload: dict = {
        "from": from_address(),
        "to": TO,
        "cc": CC,
        "reply_to": REPLY_TO,
        "subject": SUBJECT,
        "text": BODY,
        "headers": {"In-Reply-To": IN_REPLY_TO, "References": IN_REPLY_TO},
    }
    if attachment:
        if not attachment.exists():
            sys.exit(f"ERRO: anexo não encontrado: {attachment}")
        mime = mimetypes.guess_type(attachment.name)[0] or "application/octet-stream"
        payload["attachments"] = [
            {
                "filename": attachment.name,
                "content": base64.b64encode(attachment.read_bytes()).decode("ascii"),
                "content_type": mime,
            }
        ]
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="Envia de facto (sem isto é dry-run)")
    parser.add_argument("--attachment", type=Path, default=None, help="CP575G.pdf")
    args = parser.parse_args()

    payload = build_payload(args.attachment)
    if not args.send:
        printable = {key: value for key, value in payload.items() if key != "text"}
        if "attachments" in printable:
            printable["attachments"] = [item["filename"] for item in printable["attachments"]]
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        print("\n--- BODY ---\n")
        print(payload["text"])
        print("\n[dry-run] nada foi enviado. Usa --send para entregar.")
        return

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {resend_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        sys.exit(f"ERRO HTTP {exc.code}: {detail}")
    print(f"[ok] enviado — id={body.get('id', '?')}")


if __name__ == "__main__":
    main()
