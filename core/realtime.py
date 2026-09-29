"""
ORION's realtime layer — a WebSocket-based device registry and broadcast
channel. This is what makes "always-on server" and "phone as another
client" real rather than aspirational: any client (a browser tab, a
phone that installed the PWA) that connects to /ws shares the same live
event stream, and the registry here is the actual source of truth for
"which devices are connected right now" in the NETWORK tab — never a
fabricated count.

Each device reports its *own* stats (battery, connection type,
geolocation) rather than the server assuming one machine's hardware
numbers apply to whoever's looking — see core/system_monitor.py for
this machine's own numbers, which are a separate, clearly-labeled thing.
"""

import time
import uuid
from typing import Any

from fastapi import WebSocket


class Device:
    def __init__(self, device_id: str, websocket: WebSocket, label: str):
        self.device_id = device_id
        self.websocket = websocket
        self.label = label
        self.connected_at = time.time()
        self.last_seen = time.time()
        self.stats: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "label": self.label,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
            "connected_seconds": round(time.time() - self.connected_at),
            "stats": self.stats,
        }


class ConnectionManager:
    def __init__(self):
        self.devices: dict[str, Device] = {}

    async def connect(self, websocket: WebSocket, device_id: str | None, label: str) -> Device:
        await websocket.accept()
        device_id = device_id or str(uuid.uuid4())
        device = Device(device_id, websocket, label)
        self.devices[device_id] = device
        return device

    def disconnect(self, device_id: str) -> None:
        self.devices.pop(device_id, None)

    def update_stats(self, device_id: str, stats: dict[str, Any]) -> None:
        device = self.devices.get(device_id)
        if device is None:
            return
        device.stats = stats
        device.last_seen = time.time()

    def list_devices(self) -> list[dict[str, Any]]:
        return [d.to_dict() for d in self.devices.values()]

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Push a JSON event (e.g. a Stage 2 proactive notification) to
        every connected device. Dead sockets are pruned rather than
        raising — a disconnected phone shouldn't break notifications for
        everyone else."""
        dead = []
        for device_id, device in self.devices.items():
            try:
                await device.websocket.send_json(message)
            except Exception:
                dead.append(device_id)
        for device_id in dead:
            self.disconnect(device_id)


manager = ConnectionManager()


def get_lan_url(port: int) -> str:
    """Best-effort LAN URL for this machine so a phone on the same
    Wi-Fi/network can actually reach it — localhost obviously won't
    work from a second device. Uses the no-send UDP-connect trick to
    find the outbound-facing interface IP without any real network
    traffic or new dependency; falls back to localhost if that fails
    (e.g. no network interface at all)."""
    import socket

    ip = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
    except OSError:
        pass
    return f"http://{ip}:{port}"
