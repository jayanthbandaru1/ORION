"""
Tests for the location/maps MCP server. httpx.Client is mocked — these
check the logic that's actually ours: viewbox computation for "nearby"
search, geocode-then-route composition, mode validation, and error
handling when Nominatim finds nothing or OSRM can't route. Nominatim's
and OSRM's real response shapes were verified empirically against the
live public endpoints before writing this server (see CLAUDE.md).
"""

import pytest

from conftest import load_server_module

location_server = load_server_module("location_server_module", "mcp_servers/location/server.py")


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class FakeHttpxClient:
    """Mimics httpx.Client used as `with httpx.Client(...) as client:` —
    routes GETs to canned responses keyed by which API was hit."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        self.calls.append((url, params))
        if "nominatim" in url:
            return self.responses.get("nominatim", FakeResponse([]))
        if "router.project-osrm.org" in url:
            return self.responses.get("osrm", FakeResponse({"code": "NoRoute"}))
        raise AssertionError(f"unexpected URL: {url}")


def _patch_client(monkeypatch, **responses):
    fake = FakeHttpxClient(responses)
    monkeypatch.setattr(location_server, "_client", lambda: fake)
    return fake


NOMINATIM_RESULT = [{"lat": "48.8582599", "lon": "2.2945006", "display_name": "Eiffel Tower, Paris"}]
OSRM_ROUTE = {
    "code": "Ok",
    "routes": [
        {
            "distance": 4315.5,
            "duration": 635.5,
            "geometry": {"coordinates": [[2.29, 48.85], [2.33, 48.86]]},
        }
    ],
}


class TestGeocode:
    def test_returns_lat_lon_and_display_name(self, monkeypatch):
        _patch_client(monkeypatch, nominatim=FakeResponse(NOMINATIM_RESULT))
        result = location_server._geocode("Eiffel Tower")
        assert result == {"lat": 48.8582599, "lon": 2.2945006, "display_name": "Eiffel Tower, Paris"}

    def test_no_results_raises_a_clear_error(self, monkeypatch):
        _patch_client(monkeypatch, nominatim=FakeResponse([]))
        with pytest.raises(ValueError, match="Could not find"):
            location_server._geocode("asdkjfhqwoeiruqwoeiru")


class TestFindNearby:
    def test_computes_a_viewbox_around_the_given_point_and_returns_places(self, monkeypatch):
        cafe_results = [
            {"lat": "48.86", "lon": "2.30", "display_name": "Cafe One"},
            {"lat": "48.87", "lon": "2.31", "display_name": "Cafe Two"},
        ]
        fake = _patch_client(monkeypatch, nominatim=FakeResponse(cafe_results))

        result = location_server.location_find_nearby("cafe", lat=48.8583, lon=2.2945, radius_km=3.0)

        assert len(result) == 2
        assert result[0]["name"] == "Cafe One"
        url, params = fake.calls[0]
        assert params["bounded"] == 1
        assert "viewbox" in params

    def test_empty_results_returns_empty_list_not_an_error(self, monkeypatch):
        _patch_client(monkeypatch, nominatim=FakeResponse([]))
        assert location_server.location_find_nearby("nonexistent thing", lat=0, lon=0) == []


class TestGetDirections:
    def test_geocodes_destination_and_returns_route_summary(self, monkeypatch):
        _patch_client(monkeypatch, nominatim=FakeResponse(NOMINATIM_RESULT), osrm=FakeResponse(OSRM_ROUTE))

        result = location_server.location_get_directions(origin_lat=48.85, origin_lon=2.29, destination="Eiffel Tower")

        assert result["destination"] == "Eiffel Tower, Paris"
        assert result["distance_km"] == 4.32
        assert result["duration_minutes"] == 10.6
        assert result["mode"] == "driving"
        assert result["route_geometry"] == [[2.29, 48.85], [2.33, 48.86]]

    def test_invalid_mode_is_rejected_before_calling_osrm(self, monkeypatch):
        fake = _patch_client(monkeypatch, nominatim=FakeResponse(NOMINATIM_RESULT))
        with pytest.raises(ValueError, match="mode must be one of"):
            location_server.location_get_directions(origin_lat=0, origin_lon=0, destination="X", mode="teleport")

    def test_unroutable_destination_raises_a_clear_error(self, monkeypatch):
        _patch_client(
            monkeypatch,
            nominatim=FakeResponse(NOMINATIM_RESULT),
            osrm=FakeResponse({"code": "NoRoute", "message": "no route found"}),
        )
        with pytest.raises(ValueError, match="couldn't find a route"):
            location_server.location_get_directions(origin_lat=0, origin_lon=0, destination="Eiffel Tower")


class TestEstimateTravelTime:
    def test_returns_duration_without_full_geometry(self, monkeypatch):
        _patch_client(monkeypatch, nominatim=FakeResponse(NOMINATIM_RESULT), osrm=FakeResponse(OSRM_ROUTE))

        result = location_server.location_estimate_travel_time(origin_lat=48.85, origin_lon=2.29, destination="Eiffel Tower")

        assert "route_geometry" not in result
        assert result["duration_minutes"] == 10.6
        assert result["distance_km"] == 4.32


class TestTrafficHonesty:
    def test_directions_always_report_traffic_as_unavailable_not_faked(self, monkeypatch):
        _patch_client(monkeypatch, nominatim=FakeResponse(NOMINATIM_RESULT), osrm=FakeResponse(OSRM_ROUTE))
        result = location_server.location_get_directions(origin_lat=48.85, origin_lon=2.29, destination="Eiffel Tower")
        assert result["traffic"] == "unavailable"


class TestAlternativeRoutes:
    TWO_ROUTE_RESPONSE = {
        "code": "Ok",
        "routes": [
            {"distance": 4315.5, "duration": 635.5, "geometry": {"coordinates": [[2.29, 48.85], [2.33, 48.86]]}, "legs": []},
            {"distance": 4600.0, "duration": 700.0, "geometry": {"coordinates": [[2.29, 48.85], [2.30, 48.87], [2.33, 48.86]]}, "legs": []},
        ],
    }

    def test_alternatives_false_returns_no_alternate_routes(self, monkeypatch):
        _patch_client(monkeypatch, nominatim=FakeResponse(NOMINATIM_RESULT), osrm=FakeResponse(self.TWO_ROUTE_RESPONSE))
        result = location_server.location_get_directions(origin_lat=48.85, origin_lon=2.29, destination="Eiffel Tower")
        assert result["alternative_routes"] == []

    def test_alternatives_true_returns_the_other_routes(self, monkeypatch):
        fake = _patch_client(monkeypatch, nominatim=FakeResponse(NOMINATIM_RESULT), osrm=FakeResponse(self.TWO_ROUTE_RESPONSE))
        result = location_server.location_get_directions(
            origin_lat=48.85, origin_lon=2.29, destination="Eiffel Tower", alternatives=True
        )
        assert len(result["alternative_routes"]) == 1
        assert result["alternative_routes"][0]["distance_km"] == 4.6
        # the primary route stays the first/best one regardless of the flag
        assert result["distance_km"] == 4.32
        # alternates don't need their own turn-by-turn breakdown
        assert "steps" not in result["alternative_routes"][0]

        url, params = fake.calls[-1]
        assert params["alternatives"] == "true"


class TestTurnByTurnSteps:
    def test_primary_route_includes_readable_step_instructions(self, monkeypatch):
        route_with_steps = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 4315.5,
                    "duration": 635.5,
                    "geometry": {"coordinates": [[2.29, 48.85], [2.33, 48.86]]},
                    "legs": [
                        {
                            "steps": [
                                {"maneuver": {"type": "depart"}, "name": "Rue de Rivoli", "distance": 120},
                                {"maneuver": {"type": "turn", "modifier": "left"}, "name": "Quai Branly", "distance": 300},
                                {"maneuver": {"type": "arrive"}, "name": "", "distance": 0},
                            ]
                        }
                    ],
                }
            ],
        }
        _patch_client(monkeypatch, nominatim=FakeResponse(NOMINATIM_RESULT), osrm=FakeResponse(route_with_steps))

        result = location_server.location_get_directions(origin_lat=48.85, origin_lon=2.29, destination="Eiffel Tower")

        assert result["steps"] == [
            "Head out on Rue de Rivoli (120 m)",
            "Turn left onto Quai Branly (300 m)",
            "Arrive at your destination",
        ]


class TestStepInstruction:
    def test_unrecognized_maneuver_type_falls_back_gracefully(self):
        step = {"maneuver": {"type": "something-new-osrm-added"}, "name": "Main St", "distance": 50}
        text = location_server._step_instruction(step)
        assert "Main St" in text
        assert "50" in text
