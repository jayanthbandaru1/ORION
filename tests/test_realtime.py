"""
Tests for core/realtime.py — the WebSocket device registry behind the
NETWORK tab. The manager logic is tested directly against a fake
WebSocket (no real socket needed); a couple of integration tests exercise
the actual /ws, /network/devices, /network/info routes in api.py through
FastAPI's TestClient (used without the `with` context manager so the
app's lifespan — which spawns all 7 MCP server subprocesses and preloads
voice models — never runs; these routes don't touch any of that).
"""

import asyncio

import pytest

from conftest import PROJECT_ROOT  # noqa: F401 — ensures sys.path is set up

from core import realtime


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent = []
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        if self.closed:
            raise RuntimeError("socket closed")
        self.sent.append(data)


@pytest.fixture(autouse=True)
def fresh_manager():
    realtime.manager.devices.clear()
    yield
    realtime.manager.devices.clear()


class TestConnectionManager:
    def test_connect_generates_id_when_none_given(self):
        async def body():
            ws = FakeWebSocket()
            device = await realtime.manager.connect(ws, None, "web")
            assert ws.accepted is True
            assert device.device_id
            assert device.label == "web"
            assert device.device_id in realtime.manager.devices

        asyncio.run(body())

    def test_connect_reuses_given_device_id(self):
        async def body():
            ws = FakeWebSocket()
            device = await realtime.manager.connect(ws, "my-fixed-id", "phone")
            assert device.device_id == "my-fixed-id"

        asyncio.run(body())

    def test_disconnect_removes_device(self):
        realtime.manager.devices["x"] = object()
        realtime.manager.disconnect("x")
        assert "x" not in realtime.manager.devices

    def test_disconnect_unknown_id_is_a_noop(self):
        realtime.manager.disconnect("does-not-exist")  # must not raise

    def test_update_stats_sets_stats_and_last_seen(self):
        async def body():
            ws = FakeWebSocket()
            device = await realtime.manager.connect(ws, "d1", "web")
            before = device.last_seen
            await asyncio.sleep(0.01)
            realtime.manager.update_stats("d1", {"battery_percent": 42})
            assert device.stats == {"battery_percent": 42}
            assert device.last_seen > before

        asyncio.run(body())

    def test_update_stats_unknown_device_is_a_noop(self):
        realtime.manager.update_stats("ghost", {"a": 1})  # must not raise

    def test_list_devices_reflects_connected_state(self):
        async def body():
            ws1, ws2 = FakeWebSocket(), FakeWebSocket()
            await realtime.manager.connect(ws1, "a", "web")
            await realtime.manager.connect(ws2, "b", "phone")
            listed = realtime.manager.list_devices()
            assert {d["device_id"] for d in listed} == {"a", "b"}
            assert {d["label"] for d in listed} == {"web", "phone"}

        asyncio.run(body())

    def test_broadcast_reaches_every_connected_device(self):
        async def body():
            ws1, ws2 = FakeWebSocket(), FakeWebSocket()
            await realtime.manager.connect(ws1, "a", "web")
            await realtime.manager.connect(ws2, "b", "phone")
            await realtime.manager.broadcast({"type": "notification", "text": "hi"})
            assert ws1.sent == [{"type": "notification", "text": "hi"}]
            assert ws2.sent == [{"type": "notification", "text": "hi"}]

        asyncio.run(body())

    def test_broadcast_prunes_dead_sockets_without_raising(self):
        async def body():
            ws_alive, ws_dead = FakeWebSocket(), FakeWebSocket()
            await realtime.manager.connect(ws_alive, "alive", "web")
            await realtime.manager.connect(ws_dead, "dead", "web")
            ws_dead.closed = True

            await realtime.manager.broadcast({"type": "notification"})  # must not raise

            assert ws_alive.sent == [{"type": "notification"}]
            assert "dead" not in realtime.manager.devices
            assert "alive" in realtime.manager.devices

        asyncio.run(body())


class TestGetLanUrl:
    def test_returns_a_url_with_the_given_port(self):
        url = realtime.get_lan_url(8000)
        assert url.startswith("http://")
        assert url.endswith(":8000")


class TestApiIntegration:
    """api.py's TestClient is used *without* `with` so the app's lifespan
    (7 MCP subprocesses + voice model preload) never runs — /network/*
    and /ws don't depend on any of that, only on core.realtime."""

    def test_network_devices_endpoint_reflects_registry(self):
        from fastapi.testclient import TestClient

        import api

        api.realtime.manager.devices.clear()
        client = TestClient(api.app)
        response = client.get("/network/devices")
        assert response.status_code == 200
        assert response.json() == {"devices": []}

    def test_network_info_endpoint_returns_a_url(self):
        from fastapi.testclient import TestClient

        import api

        client = TestClient(api.app)
        response = client.get("/network/info")
        assert response.status_code == 200
        assert response.json()["lan_url"].startswith("http://")

    def test_websocket_hello_and_registry_roundtrip(self):
        from fastapi.testclient import TestClient

        import api

        api.realtime.manager.devices.clear()
        client = TestClient(api.app)
        with client.websocket_connect("/ws?device_id=test-dev&label=web") as ws:
            hello = ws.receive_json()
            assert hello == {"type": "hello", "device_id": "test-dev"}
            assert "test-dev" in api.realtime.manager.devices

            ws.send_json({"type": "stats", "stats": {"battery_percent": 55}})
            # give the server coroutine a moment to process the frame
            import time

            time.sleep(0.1)
            assert api.realtime.manager.devices["test-dev"].stats == {"battery_percent": 55}

        # Disconnect happens once the `with` block closes the socket.
        import time

        time.sleep(0.1)
        assert "test-dev" not in api.realtime.manager.devices
