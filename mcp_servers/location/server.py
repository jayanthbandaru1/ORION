"""
ORION's location/maps MCP server.

Uses the free, keyless OpenStreetMap stack (Nominatim for geocoding/
place search, the public OSRM demo server for routing) rather than
Google Maps/Apple MapKit — both of those need real credentials this
repo doesn't have (a billing-enabled Google Cloud project, or a paid
Apple Developer Program membership + server-signed MapKit JS token).
Swappable later if the user gets one of those and wants richer data;
nothing else in ORION is coupled to this specific provider.

"Current location" is deliberately never guessed server-side (a
desktop has no GPS, and IP-geolocation is coarse and a real privacy
tradeoff) — every tool here takes lat/lon explicitly, sourced from
whichever client's own browser Geolocation API the user granted
permission to (most meaningful on a phone).

Both Nominatim's usage policy (identify your app via User-Agent, don't
hammer it) and OSRM's public-demo-server policy (light use only, not a
production dependency) are respected here — this is a personal,
single-user assistant, not a service making bulk requests.
"""

import sys
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

USER_AGENT = "ORION-Personal-AI-Assistant/1.0 (local, single-user; see github.com for source)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
OSRM_URL = "https://router.project-osrm.org"
VALID_MODES = {"driving", "walking", "cycling"}

mcp = FastMCP(
    name="orion-location",
    instructions=(
        "Find nearby places and get directions/travel-time estimates. Every tool takes the "
        "user's current lat/lon explicitly — this server never guesses location itself. "
        "'destination' is a free-text place name/address, geocoded internally."
    ),
)


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10)


def _geocode(place: str) -> dict[str, Any]:
    with _client() as client:
        response = client.get(f"{NOMINATIM_URL}/search", params={"q": place, "format": "json", "limit": 1})
        response.raise_for_status()
        results = response.json()
    if not results:
        raise ValueError(f"Could not find a location matching '{place}'.")
    return {"lat": float(results[0]["lat"]), "lon": float(results[0]["lon"]), "display_name": results[0]["display_name"]}


def _step_instruction(step: dict[str, Any]) -> str:
    """Turns one OSRM route step into a plain-language instruction. OSRM's
    maneuver.type/modifier vocabulary is documented in its API spec —
    this covers the common cases and falls back to something reasonable
    (never invented) for anything it doesn't specifically recognize."""
    maneuver = step.get("maneuver", {})
    m_type = maneuver.get("type", "")
    modifier = (maneuver.get("modifier") or "").replace("_", " ")
    name = step.get("name") or ""
    distance_m = step.get("distance", 0)

    if m_type == "depart":
        text = f"Head out on {name}" if name else "Head out"
    elif m_type == "arrive":
        return "Arrive at your destination"
    elif m_type in ("turn", "end of road", "fork", "merge", "ramp", "on ramp", "off ramp"):
        direction = modifier or "onto"
        text = f"Turn {direction}" + (f" onto {name}" if name else "")
    elif m_type == "roundabout" or m_type == "rotary":
        text = "Enter the roundabout" + (f" and take the exit onto {name}" if name else "")
    elif m_type == "new name":
        text = f"Continue onto {name}" if name else "Continue straight"
    else:
        text = f"Continue on {name}" if name else "Continue"

    if distance_m:
        text += f" ({round(distance_m)} m)"
    return text


def _format_route(route: dict[str, Any], mode: str, include_steps: bool) -> dict[str, Any]:
    formatted = {
        "distance_km": round(route["distance"] / 1000, 2),
        "duration_minutes": round(route["duration"] / 60, 1),
        "mode": mode,
        "route_geometry": route["geometry"]["coordinates"],  # [[lon, lat], ...] for map rendering
    }
    if include_steps:
        steps = [step for leg in route.get("legs", []) for step in leg.get("steps", [])]
        formatted["steps"] = [_step_instruction(step) for step in steps]
    return formatted


def _get_routes(
    mode: str, origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float, alternatives: bool
) -> list[dict[str, Any]]:
    """Hits OSRM once and returns the raw route list — 1 route normally,
    up to a few when alternatives is requested (verified empirically:
    the public OSRM server genuinely supports this, no traffic data
    though — that's not something the free routing engine models at all,
    so it's never included or faked here)."""
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}")
    url = f"{OSRM_URL}/route/v1/{mode}/{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
    with _client() as client:
        response = client.get(
            url,
            params={
                "overview": "full",
                "geometries": "geojson",
                "steps": "true",
                "alternatives": "true" if alternatives else "false",
            },
        )
        response.raise_for_status()
        data = response.json()
    if data.get("code") != "Ok":
        raise ValueError(f"OSRM couldn't find a route: {data.get('message', data.get('code'))}")
    return data["routes"]


@mcp.tool()
def location_find_nearby(query: str, lat: float, lon: float, radius_km: float = 3.0) -> list[dict]:
    """Find places matching `query` (e.g. 'coffee shop', 'gas station') near (lat, lon),
    within roughly radius_km. READ."""
    # ~1 degree latitude is ~111km; longitude degrees shrink with latitude, but a
    # simple latitude-based approximation is good enough for a "nearby" radius,
    # not turn-by-turn precision.
    delta = radius_km / 111.0
    with _client() as client:
        response = client.get(
            f"{NOMINATIM_URL}/search",
            params={
                "q": query,
                "format": "json",
                "limit": 8,
                "viewbox": f"{lon - delta},{lat + delta},{lon + delta},{lat - delta}",
                "bounded": 1,
            },
        )
        response.raise_for_status()
        results = response.json()
    return [
        {"name": r["display_name"], "lat": float(r["lat"]), "lon": float(r["lon"])}
        for r in results
    ]


@mcp.tool()
def location_get_directions(
    origin_lat: float,
    origin_lon: float,
    destination: str,
    mode: str = "driving",
    alternatives: bool = False,
) -> dict:
    """Get a route from (origin_lat, origin_lon) to `destination` (a place name or
    address, geocoded internally), with turn-by-turn steps. mode is 'driving',
    'walking', or 'cycling'. Set alternatives=True to also get other route options
    for comparison (distance/duration each, matching the primary route's shape) —
    live traffic is never included since the free OSRM routing engine doesn't
    model it at all; asking for alternatives doesn't change that. READ."""
    dest = _geocode(destination)
    routes = _get_routes(mode, origin_lat, origin_lon, dest["lat"], dest["lon"], alternatives)
    primary = _format_route(routes[0], mode, include_steps=True)
    return {
        "destination": dest["display_name"],
        "destination_lat": dest["lat"],
        "destination_lon": dest["lon"],
        "traffic": "unavailable",  # said plainly rather than omitted silently or faked
        **primary,
        # Trust the caller's own request, not just however many routes OSRM
        # happened to hand back — don't surface "alternatives" nobody asked for.
        "alternative_routes": [_format_route(r, mode, include_steps=False) for r in routes[1:]] if alternatives else [],
    }


@mcp.tool()
def location_estimate_travel_time(origin_lat: float, origin_lon: float, destination: str, mode: str = "driving") -> dict:
    """Just the travel-time estimate to `destination` (place name/address), without the
    full route geometry — for a plain 'how long would it take' question. READ."""
    dest = _geocode(destination)
    routes = _get_routes(mode, origin_lat, origin_lon, dest["lat"], dest["lon"], alternatives=False)
    route = routes[0]
    return {
        "destination": dest["display_name"],
        "distance_km": round(route["distance"] / 1000, 2),
        "duration_minutes": round(route["duration"] / 60, 1),
        "mode": mode,
    }


if __name__ == "__main__":
    mcp.run()
