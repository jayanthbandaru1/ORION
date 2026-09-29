"""
Tests for the weather MCP server. httpx.Client is mocked — these check
the logic that's actually ours: field extraction/renaming, the WMO
weather-code-to-text mapping, and the days clamp. Open-Meteo's real
response shape was verified empirically against the live API before
writing this server (see CLAUDE.md).
"""

import pytest

from conftest import load_server_module

weather_server = load_server_module("weather_server_module", "mcp_servers/weather/server.py")


class FakeResponse:
    def __init__(self, json_data):
        self._json = json_data

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeHttpxClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        self.calls.append((url, params))
        return self.response


CURRENT_PAYLOAD = {
    "current": {
        "temperature_2m": 28.0,
        "apparent_temperature": 32.0,
        "relative_humidity_2m": 78,
        "precipitation": 0.0,
        "wind_speed_10m": 13.0,
        "weather_code": 3,
    }
}

FORECAST_PAYLOAD = {
    "daily": {
        "time": ["2026-08-22", "2026-08-23"],
        "temperature_2m_max": [31.0, 29.7],
        "temperature_2m_min": [26.7, 25.8],
        "precipitation_probability_max": [75, 98],
        "weather_code": [80, 61],
    }
}


class TestWeatherGetCurrent:
    def test_extracts_and_renames_fields(self, monkeypatch):
        fake = FakeHttpxClient(FakeResponse(CURRENT_PAYLOAD))
        monkeypatch.setattr(weather_server.httpx, "Client", lambda **kw: fake)

        result = weather_server.weather_get_current(lat=14.676, lon=121.0437)

        assert result == {
            "temperature_c": 28.0,
            "feels_like_c": 32.0,
            "humidity_percent": 78,
            "precipitation_mm": 0.0,
            "wind_speed_kmh": 13.0,
            "conditions": "Overcast",
        }

    def test_passes_lat_lon_through_to_the_api(self, monkeypatch):
        fake = FakeHttpxClient(FakeResponse(CURRENT_PAYLOAD))
        monkeypatch.setattr(weather_server.httpx, "Client", lambda **kw: fake)

        weather_server.weather_get_current(lat=1.5, lon=2.5)

        _, params = fake.calls[0]
        assert params["latitude"] == 1.5
        assert params["longitude"] == 2.5


class TestWeatherGetForecast:
    def test_returns_one_entry_per_day(self, monkeypatch):
        fake = FakeHttpxClient(FakeResponse(FORECAST_PAYLOAD))
        monkeypatch.setattr(weather_server.httpx, "Client", lambda **kw: fake)

        result = weather_server.weather_get_forecast(lat=0, lon=0, days=2)

        assert len(result) == 2
        assert result[0]["date"] == "2026-08-22"
        assert result[0]["conditions"] == "Slight rain showers"
        assert result[1]["conditions"] == "Slight rain"

    def test_days_is_clamped_to_valid_range(self, monkeypatch):
        fake = FakeHttpxClient(FakeResponse(FORECAST_PAYLOAD))
        monkeypatch.setattr(weather_server.httpx, "Client", lambda **kw: fake)

        weather_server.weather_get_forecast(lat=0, lon=0, days=999)

        _, params = fake.calls[0]
        assert params["forecast_days"] == 16

        weather_server.weather_get_forecast(lat=0, lon=0, days=0)
        _, params2 = fake.calls[1]
        assert params2["forecast_days"] == 1


class TestWmoCodeMapping:
    def test_known_code_maps_to_readable_text(self):
        assert weather_server._describe(0) == "Clear sky"
        assert weather_server._describe(95) == "Thunderstorm"

    def test_unknown_code_is_reported_honestly_not_silently_dropped(self):
        assert "Unknown conditions" in weather_server._describe(12345)
