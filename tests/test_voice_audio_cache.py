"""Cache de TTS (pré-renderização) para o modo static."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.config import settings
from backend.services import b2b_voice as voice
from backend.services import voice_audio_cache as cache


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("VOICE_NOW_ISO", "2026-11-02T16:00:00+00:00")
    voice.init()
    cache.init()
    conn = voice.get_conn()
    try:
        conn.execute("DELETE FROM voice_tts_cache")
        conn.commit()
    finally:
        conn.close()
    yield


def _enable(monkeypatch, tmp_path: Path, voice_id: str = "voice.test") -> None:
    monkeypatch.setattr(settings, "VOICE_TTS_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "VOICE_TTS_CACHE_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(
        settings, "VOICE_TTS_CACHE_BASE_URL", "https://example.test", raising=False
    )
    monkeypatch.setattr(settings, "VOICE_TTS_VOICE", voice_id, raising=False)
    cache.init()


def test_key_is_stable_and_voice_scoped(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_TTS_VOICE", "voice.a", raising=False)
    key_a = cache.key("hello")
    assert key_a == cache.key("hello")
    assert cache.key("hello") != cache.key("hello!")
    monkeypatch.setattr(settings, "VOICE_TTS_VOICE", "voice.b", raising=False)
    assert cache.key("hello") != key_a


def test_disabled_returns_error(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_TTS_CACHE_ENABLED", False, raising=False)
    result = cache.get_or_create("hello")
    assert result["ok"] is False
    assert result["reason"] == "disabled"


def test_synthesize_once_then_hit(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    calls: list[str] = []

    def fake_synth(text: str) -> dict:
        calls.append(text)
        return {
            "ok": True,
            "audio": b"ID3" + b"\x00" * 300,
            "content_type": "audio/mpeg",
        }

    monkeypatch.setattr(cache, "_synthesize", fake_synth)
    first = cache.get_or_create("Hello world.")
    assert first["ok"] is True
    assert first["hit"] is False
    assert first["url"].startswith("https://example.test/api/voice/tts/")
    assert Path(first["path"]).exists()

    second = cache.get_or_create("Hello world.")
    assert second["ok"] is True
    assert second["hit"] is True
    assert second["hash"] == first["hash"]
    assert calls == ["Hello world."]


def test_empty_text_and_synthesis_failure(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    assert cache.get_or_create("")["reason"] == "empty_text"
    monkeypatch.setattr(
        cache, "_synthesize", lambda text: {"ok": False, "reason": "http_500"}
    )
    result = cache.get_or_create("will fail")
    assert result["ok"] is False
    assert result["reason"] == "http_500"


def test_prewarm_counts(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cache,
        "_synthesize",
        lambda text: {"ok": True, "audio": b"ID3" + b"\x00" * 200},
    )
    first = cache.prewarm(["a", "b"])
    assert first == {"ok": True, "created": 2, "hits": 0, "errors": []}
    second = cache.prewarm(["a", "b"])
    assert second["created"] == 0
    assert second["hits"] == 2


def test_stats_and_clear(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cache,
        "_synthesize",
        lambda text: {"ok": True, "audio": b"ID3" + b"\x00" * 200},
    )
    cache.get_or_create("alpha")
    cache.get_or_create("alpha")
    stats = cache.stats()
    assert stats["n"] == 1
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    cleared = cache.clear()
    assert cleared["ok"] is True
    assert cache.stats()["n"] == 0
    assert list(Path(tmp_path).glob("*.mp3")) == []
