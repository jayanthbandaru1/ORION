"""
Tests for /location/directions and /voice/transcribe in api.py — mirrors
the vision/computer API test approach (TestClient without `with`, so
api.py's lifespan never runs).
"""

from conftest import PROJECT_ROOT  # noqa: F401 — ensures sys.path is set up


class FakeContentBlock:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, text):
        self.content = [FakeContentBlock(text)]


class FakeLocationClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return FakeResult(self.payload)


class FailingLocationClient:
    async def call_tool(self, name, args):
        raise ValueError("Could not find a location matching 'asdkjfh'.")


def _client():
    from fastapi.testclient import TestClient

    import api

    return api, TestClient(api.app)


class TestLocationDirections:
    def test_returns_the_tool_result(self):
        api, client = _client()
        payload = '{"destination": "Eiffel Tower, Paris", "distance_km": 4.32, "duration_minutes": 10.6, "mode": "driving", "route_geometry": [[2.29, 48.85]]}'
        fake = FakeLocationClient(payload)
        api.orchestrator.tool_to_client["location_get_directions"] = fake

        response = client.post(
            "/location/directions",
            json={"origin_lat": 48.85, "origin_lon": 2.29, "destination": "Eiffel Tower"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["destination"] == "Eiffel Tower, Paris"
        assert fake.calls[0] == (
            "location_get_directions",
            {"origin_lat": 48.85, "origin_lon": 2.29, "destination": "Eiffel Tower", "mode": "driving", "alternatives": False},
        )

    def test_missing_tool_returns_503(self):
        api, client = _client()
        api.orchestrator.tool_to_client.pop("location_get_directions", None)

        response = client.post(
            "/location/directions",
            json={"origin_lat": 0, "origin_lon": 0, "destination": "X"},
        )

        assert response.status_code == 503

    def test_geocoding_failure_returns_502_not_a_crash(self):
        api, client = _client()
        api.orchestrator.tool_to_client["location_get_directions"] = FailingLocationClient()

        response = client.post(
            "/location/directions",
            json={"origin_lat": 0, "origin_lon": 0, "destination": "asdkjfh"},
        )

        assert response.status_code == 502

    def test_custom_mode_is_passed_through(self):
        api, client = _client()
        fake = FakeLocationClient('{"destination": "x", "distance_km": 1, "duration_minutes": 1, "mode": "walking", "route_geometry": []}')
        api.orchestrator.tool_to_client["location_get_directions"] = fake

        client.post(
            "/location/directions",
            json={"origin_lat": 0, "origin_lon": 0, "destination": "X", "mode": "walking"},
        )

        assert fake.calls[0][1]["mode"] == "walking"

    def test_alternatives_flag_is_passed_through(self):
        api, client = _client()
        fake = FakeLocationClient('{"destination": "x", "distance_km": 1, "duration_minutes": 1, "mode": "driving", "route_geometry": [], "alternative_routes": []}')
        api.orchestrator.tool_to_client["location_get_directions"] = fake

        client.post(
            "/location/directions",
            json={"origin_lat": 0, "origin_lon": 0, "destination": "X", "alternatives": True},
        )

        assert fake.calls[0][1]["alternatives"] is True


class TestVoiceTranscribe:
    def test_calls_stt_transcribe_and_returns_text(self, monkeypatch):
        api, client = _client()
        monkeypatch.setattr(api.stt, "transcribe", lambda audio_bytes: "take me to the airport")

        response = client.post("/voice/transcribe", files={"audio": ("clip.webm", b"fake-audio-bytes", "audio/webm")})

        assert response.status_code == 200
        assert response.json() == {"text": "take me to the airport"}
