"""
Tests for /weather/current and /weather/forecast in api.py — mirrors the
vision/computer/location API test approach (TestClient without `with`,
so api.py's lifespan never runs).
"""

from conftest import PROJECT_ROOT  # noqa: F401 — ensures sys.path is set up


class FakeContentBlock:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, text):
        self.content = [FakeContentBlock(text)]


class FakeWeatherClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return FakeResult(self.payload)


def _client():
    from fastapi.testclient import TestClient

    import api

    return api, TestClient(api.app)


class TestWeatherCurrent:
    def test_returns_the_tool_result(self):
        api, client = _client()
        payload = '{"temperature_c": 28.0, "feels_like_c": 32.0, "humidity_percent": 78, "precipitation_mm": 0.0, "wind_speed_kmh": 13.0, "conditions": "Overcast"}'
        api.orchestrator.tool_to_client["weather_get_current"] = FakeWeatherClient(payload)

        response = client.get("/weather/current", params={"lat": 14.676, "lon": 121.0437})

        assert response.status_code == 200
        assert response.json()["conditions"] == "Overcast"

    def test_missing_tool_returns_503(self):
        api, client = _client()
        api.orchestrator.tool_to_client.pop("weather_get_current", None)

        response = client.get("/weather/current", params={"lat": 0, "lon": 0})

        assert response.status_code == 503


class TestWeatherForecast:
    def test_returns_a_forecast_list(self):
        api, client = _client()
        payload = '[{"date": "2026-08-22", "temp_max_c": 31.0, "temp_min_c": 26.7, "precipitation_probability_percent": 75, "conditions": "Slight rain showers"}]'
        fake = FakeWeatherClient(payload)
        api.orchestrator.tool_to_client["weather_get_forecast"] = fake

        response = client.get("/weather/forecast", params={"lat": 14.676, "lon": 121.0437, "days": 3})

        assert response.status_code == 200
        assert len(response.json()["forecast"]) == 1
        assert fake.calls[0][1]["days"] == 3

    def test_missing_tool_returns_503(self):
        api, client = _client()
        api.orchestrator.tool_to_client.pop("weather_get_forecast", None)

        response = client.get("/weather/forecast", params={"lat": 0, "lon": 0})

        assert response.status_code == 503
