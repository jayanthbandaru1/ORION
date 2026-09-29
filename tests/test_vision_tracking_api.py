"""
Tests for the active-vision-tracking endpoints in api.py:
/vision/tracking_state, /vision/tracking/toggle, /vision/track,
/vision/tracking_log. Mirrors test_vision_api.py's TestClient pattern
(no `with`, so api.py's lifespan/MCP subprocesses never spin up).
"""

import pytest

from conftest import PROJECT_ROOT  # noqa: F401 — ensures sys.path is set up

from core import vision_tracking


class FakeContentBlock:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, text):
        self.content = [FakeContentBlock(text)]


class FakeVisionClient:
    def __init__(self, description):
        self.description = description
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return FakeResult(self.description)


def _client():
    from fastapi.testclient import TestClient

    import api

    return api, TestClient(api.app)


@pytest.fixture(autouse=True)
def _reset_tracking_state():
    vision_tracking.stop()
    vision_tracking._recent.clear()
    yield
    vision_tracking.stop()
    vision_tracking._recent.clear()


class TestTrackingToggle:
    def test_enabling_sets_state_and_returns_it(self):
        api, client = _client()
        response = client.post("/vision/tracking/toggle", json={"enabled": True, "interval_seconds": 8})
        assert response.status_code == 200
        assert response.json() == {"enabled": True, "interval_seconds": 8}
        assert vision_tracking.enabled is True

    def test_disabling_clears_state(self):
        api, client = _client()
        client.post("/vision/tracking/toggle", json={"enabled": True})
        response = client.post("/vision/tracking/toggle", json={"enabled": False})
        assert response.json()["enabled"] is False
        assert vision_tracking.enabled is False

    def test_state_endpoint_reflects_current_toggle(self):
        api, client = _client()
        client.post("/vision/tracking/toggle", json={"enabled": True, "interval_seconds": 7})
        response = client.get("/vision/tracking_state")
        assert response.json() == {"enabled": True, "interval_seconds": 7}


class TestTrackFrame:
    def test_rejects_a_frame_when_tracking_is_not_enabled(self):
        api, client = _client()
        api.orchestrator.tool_to_client["vision_describe_image"] = FakeVisionClient("a person walked in")

        response = client.post("/vision/track", json={"image_base64": "abc"})

        assert response.status_code == 409

    def test_accepts_and_analyzes_a_frame_while_tracking_is_enabled(self):
        api, client = _client()
        client.post("/vision/tracking/toggle", json={"enabled": True})
        fake_client = FakeVisionClient("A person walked into frame.")
        api.orchestrator.tool_to_client["vision_describe_image"] = fake_client

        response = client.post("/vision/track", json={"image_base64": "framedata"})

        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "A person walked into frame."
        assert "created_at" in data
        assert fake_client.calls[0] == (
            "vision_describe_image",
            {
                "image_base64": "framedata",
                "question": "Describe what you see, focusing on people, movement, or anything that changed.",
            },
        )

    def test_analyzed_frame_lands_in_the_tracking_log_not_chat_history(self):
        api, client = _client()
        client.post("/vision/tracking/toggle", json={"enabled": True})
        api.orchestrator.tool_to_client["vision_describe_image"] = FakeVisionClient("Nothing unusual.")

        client.post("/vision/track", json={"image_base64": "framedata"})
        log = client.get("/vision/tracking_log").json()["events"]

        assert len(log) == 1
        assert log[0]["description"] == "Nothing unusual."

    def test_missing_vision_tool_returns_503(self):
        api, client = _client()
        client.post("/vision/tracking/toggle", json={"enabled": True})
        api.orchestrator.tool_to_client.pop("vision_describe_image", None)

        response = client.post("/vision/track", json={"image_base64": "abc"})

        assert response.status_code == 503

    def test_tool_failure_returns_502_not_a_crash(self):
        api, client = _client()
        client.post("/vision/tracking/toggle", json={"enabled": True})

        class FailingClient:
            async def call_tool(self, name, args):
                raise RuntimeError("model not found")

        api.orchestrator.tool_to_client["vision_describe_image"] = FailingClient()

        response = client.post("/vision/track", json={"image_base64": "abc"})

        assert response.status_code == 502


class TestTrackingLog:
    def test_empty_log_by_default(self):
        api, client = _client()
        assert client.get("/vision/tracking_log").json() == {"events": []}

    def test_newest_event_first(self):
        api, client = _client()
        client.post("/vision/tracking/toggle", json={"enabled": True})
        api.orchestrator.tool_to_client["vision_describe_image"] = FakeVisionClient("first")
        client.post("/vision/track", json={"image_base64": "a"})
        api.orchestrator.tool_to_client["vision_describe_image"] = FakeVisionClient("second")
        client.post("/vision/track", json={"image_base64": "b"})

        events = client.get("/vision/tracking_log").json()["events"]
        assert events[0]["description"] == "second"
        assert events[1]["description"] == "first"
