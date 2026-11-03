"""Gera o MP3 deterministico do fallback (tecla 2) com a voz Callie.

Uso (com as env vars do servico Railway):
    railway run --service magic-leads ".venv/Scripts/python.exe scripts/generate_fallback_tts.py"

O ficheiro gerado e servido em /api/voice/fallback.mp3. Regenerar sempre que o
texto do fallback mudar.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx

TEXT = (
    "No problem at all! Just visit MagicLeads.app to check out the best active "
    "opportunities available for you right now. There's no competition, and "
    "best of all, you get access up to 7 days before any other contractor even "
    "knows about them. The first to call gets the job!"
)
VOICE = "Telnyx.Ultra.00a77add-48d5-4ef6-8157-71e5437b282d"


def main() -> None:
    key = os.getenv("TELNYX_API_KEY", "")
    if not key:
        raise SystemExit("TELNYX_API_KEY missing")
    response = httpx.post(
        "https://api.telnyx.com/v2/text-to-speech/speech",
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        json={"text": TEXT, "voice": VOICE, "output_type": "binary_output"},
        timeout=90,
    )
    print("HTTP", response.status_code, "TYPE", response.headers.get("content-type"))
    if response.status_code >= 300:
        print(response.text[:1000])
        raise SystemExit(1)
    out = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "static"
        / "voice_fallback.mp3"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(response.content)
    print("WROTE", out, "BYTES", len(response.content))


if __name__ == "__main__":
    main()
