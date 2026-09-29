"""
Tests for /computer/status in api.py — mirrors tests/test_vision_api.py's
approach (TestClient without `with`, so api.py's lifespan never runs;
this route only touches orchestrator.tool_to_client).
"""

from conftest import PROJECT_ROOT  # noqa: F401 — ensures sys.path is set up


class FakeContentBlock:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, text):
        self.content = [FakeContentBlock(text)]


class FakeComputerClient:
    async def call_tool(self, name, args):
        return FakeResult('{"x": 100, "y": 200, "screen_width": 1920, "screen_height": 1080, "failsafe_armed": true}')


def _client():
    from fastapi.testclient import TestClient

    import api

    return api, TestClient(api.app)


class TestComputerStatus:
    def test_returns_real_cursor_status_from_the_tool(self):
        api, client = _client()
        api.orchestrator.tool_to_client["computer_cursor_status"] = FakeComputerClient()

        response = client.get("/computer/status")

        assert response.status_code == 200
        assert response.json() == {
            "x": 100, "y": 200, "screen_width": 1920, "screen_height": 1080, "failsafe_armed": True,
        }

    def test_missing_tool_returns_503(self):
        api, client = _client()
        api.orchestrator.tool_to_client.pop("computer_cursor_status", None)

        response = client.get("/computer/status")

        assert response.status_code == 503
