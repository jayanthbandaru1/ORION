"""
Tests for /voice/synthesize in api.py — v1.2 Stage 10's voice-first
behavior (speaking proactive notifications aloud). tts.synthesize is
mocked; the real synthesis path is already covered by /chat/voice's
existing usage of the same function.
"""

from conftest import PROJECT_ROOT  # noqa: F401 — ensures sys.path is set up


def _client():
    from fastapi.testclient import TestClient

    import api

    return api, TestClient(api.app)


class TestVoiceSynthesize:
    def test_returns_base64_audio_from_the_given_text(self, monkeypatch):
        api, client = _client()
        captured = {}

        def fake_synthesize(text, emotion="neutral"):
            captured["text"] = text
            captured["emotion"] = emotion
            return b"fake-wav-bytes"

        monkeypatch.setattr(api.tts, "synthesize", fake_synthesize)

        response = client.post("/voice/synthesize", json={"text": "Your meeting starts in 20 minutes.", "emotion": "serious"})

        assert response.status_code == 200
        import base64
        assert base64.b64decode(response.json()["audio_base64"]) == b"fake-wav-bytes"
        assert captured["text"] == "Your meeting starts in 20 minutes."
        assert captured["emotion"] == "serious"

    def test_defaults_to_neutral_emotion(self, monkeypatch):
        api, client = _client()
        captured = {}

        def fake_synthesize(text, emotion="neutral"):
            captured["emotion"] = emotion
            return b"x"

        monkeypatch.setattr(api.tts, "synthesize", fake_synthesize)

        client.post("/voice/synthesize", json={"text": "hi"})

        assert captured["emotion"] == "neutral"
