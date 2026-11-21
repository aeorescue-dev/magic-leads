"""Pre-renderiza o greeting aprovado para MP3 estatico (voice_audio_cache).

Uso (no contentor de producao):

    python -m backend.scripts.prerender_voice_script --trade plumbing --city Dallas
    python -m backend.scripts.prerender_voice_script --text-file new_script.txt

O MP3 fica `pinned=1`: o cleanup por TTL nunca o remove. As chamadas seguintes
usam `gather_using_audio` com esse URL (sem sintese por chamada).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.services import voice_audio_cache, voice_scripts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade", default="general_contractor")
    parser.add_argument("--city", default="")
    parser.add_argument("--state", default="")
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument(
        "--company",
        default="there",
        help="Nome usado em {{company}} (shared mode usa 'there').",
    )
    parser.add_argument(
        "--text-file",
        default="",
        help="Sintetiza exatamente este texto em vez de renderizar o roteiro.",
    )
    parser.add_argument(
        "--unpin",
        action="store_true",
        help="Remove o pin de um hash (usa --hash).",
    )
    parser.add_argument("--hash", default="")
    args = parser.parse_args()

    if args.unpin:
        if not args.hash:
            print(json.dumps({"ok": False, "error": "missing --hash"}))
            return 2
        print(json.dumps(voice_audio_cache.pin(args.hash, False)))
        return 0

    if not voice_audio_cache.enabled():
        print(json.dumps({"ok": False, "error": "VOICE_TTS_CACHE_ENABLED=0"}))
        return 2

    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8").strip()
        source = "text_file"
    else:
        try:
            rendered = voice_scripts.render(
                args.trade,
                args.company,
                args.city,
                args.count,
                args.state,
                "",
            )
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 2
        text = str(rendered.get("greeting") or "").strip()
        source = "script"

    if not text:
        print(json.dumps({"ok": False, "error": "empty_text"}))
        return 2

    result = voice_audio_cache.get_or_create(text, pin=True)
    result["source"] = source
    result["trade"] = args.trade
    result["city"] = args.city or None
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
