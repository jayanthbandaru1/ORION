"""
ORION's weather MCP server, via Open-Meteo — free, keyless, global
(unlike the US-only National Weather Service API), verified live against
the real API before being wired in here.

Like location (mcp_servers/location/), "current location" is never
guessed server-side — every tool takes lat/lon explicitly, sourced from
whichever client's own browser Geolocation API the user granted.
"""

import sys
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo's weather_code follows the standard WMO weather interpretation
# codes (a public meteorological standard, not something Open-Meteo invented) —
# https://open-meteo.com/en/docs lists this exact mapping.
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def _describe(code: int) -> str:
    return WMO_CODES.get(code, f"Unknown conditions (code {code})")


mcp = FastMCP(
    name="orion-weather",
    instructions=(
        "Current conditions and forecast for a given lat/lon — always take location "
        "explicitly from the user's own device, never guess it."
    ),
)


@mcp.tool()
def weather_get_current(lat: float, lon: float) -> dict[str, Any]:
    """Current weather conditions at (lat, lon). READ."""
    with httpx.Client(timeout=10) as client:
        response = client.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,wind_speed_10m,weather_code",
                "timezone": "auto",
            },
        )
        response.raise_for_status()
    current = response.json()["current"]
    return {
        "temperature_c": current["temperature_2m"],
        "feels_like_c": current["apparent_temperature"],
        "humidity_percent": current["relative_humidity_2m"],
        "precipitation_mm": current["precipitation"],
        "wind_speed_kmh": current["wind_speed_10m"],
        "conditions": _describe(current["weather_code"]),
    }


@mcp.tool()
def weather_get_forecast(lat: float, lon: float, days: int = 5) -> list[dict[str, Any]]:
    """Daily forecast for the next `days` days (max 16) at (lat, lon). READ."""
    days = max(1, min(days, 16))
    with httpx.Client(timeout=10) as client:
        response = client.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "forecast_days": days,
                "timezone": "auto",
            },
        )
        response.raise_for_status()
    daily = response.json()["daily"]
    return [
        {
            "date": daily["time"][i],
            "temp_max_c": daily["temperature_2m_max"][i],
            "temp_min_c": daily["temperature_2m_min"][i],
            "precipitation_probability_percent": daily["precipitation_probability_max"][i],
            "conditions": _describe(daily["weather_code"][i]),
        }
        for i in range(len(daily["time"]))
    ]


if __name__ == "__main__":
    mcp.run()
