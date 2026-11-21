"""MP3 estatico: pin impede o cleanup por TTL."""
from __future__ import annotations

import sqlite3

from backend.config import settings
from backend.services import b2b_voice
from backend.services import voice_audio_cache as cache


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "VOICE_TTS_CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "VOICE_TTS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "VOICE_TTS_VOICE", "voice-test")
    monkeypatch.setattr(settings, "TELNYX_API_KEY", "key-test")
    monkeypatch.setattr(
        cache,
        "_synthesize",
        lambda text: {"ok": True, "audio": b"ID3" + b"0" * 64},
    )
    cache._INIT["path"] = None


def test_pinned_mp3_survives_cleanup(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    pinned = cache.get_or_create("pinned script", pin=True)
    loose = cache.get_or_create("old script", pin=False)
    assert pinned["ok"] and pinned["pinned"] is True
    assert loose["ok"] and loose["pinned"] is False

    conn = sqlite3.connect(b2b_voice.db_path())
    try:
        conn.execute(
            "UPDATE voice_tts_cache SET last_used_at='2000-01-01T00:00:00+00:00'"
        )
        conn.commit()
    finally:
        conn.close()

    result = cache.cleanup(days=1)
    assert result["removed"] == 1
    assert cache.path_for(pinned["hash"]).exists()
    assert not cache.path_for(loose["hash"]).exists()


def test_get_or_create_hit_can_be_pinned(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    first = cache.get_or_create("same text", pin=False)
    assert first["hit"] is False
    second = cache.get_or_create("same text", pin=True)
    assert second["hit"] is True
    assert second["pinned"] is True
    conn = sqlite3.connect(b2b_voice.db_path())
    try:
        row = conn.execute(
            "SELECT pinned FROM voice_tts_cache WHERE hash=?", (first["hash"],)
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 1
