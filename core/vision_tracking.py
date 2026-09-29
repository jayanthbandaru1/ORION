"""
ORION's active vision tracking state — v1.2 Stage 14.

The camera itself only ever lives in a browser tab (core/realtime.py's
per-device model applies here too: the server has no camera of its own).
So unlike core/proactive.py's background asyncio loop, there is no
server-side polling loop here — the browser captures frames on its own
interval, cheaply diffs each one against the last frame it *sent*
(not the last one analyzed) to skip static scenes, and POSTs only the
frames worth analyzing to /vision/track. This module is just the shared
on/off state and the resulting event log, mirroring core/proactive.py's
enabled/_recent/_record/get_recent shape so both features look and
behave the same way to anything watching them.

Starting tracking is SENSITIVE (see config/permissions.yaml) — a real,
ongoing privacy-relevant behavior change, not a one-shot capture like
vision_describe_image. Stopping it is always SAFE.
"""

import time
from typing import Any

enabled = False
interval_seconds = 5

_RECENT_MAXLEN = 50
_recent: list[dict[str, Any]] = []


def _record(event: dict[str, Any]) -> None:
    _recent.append(event)
    if len(_recent) > _RECENT_MAXLEN:
        del _recent[: len(_recent) - _RECENT_MAXLEN]


def get_recent() -> list[dict[str, Any]]:
    return list(reversed(_recent))


def start(seconds: int = 5) -> dict[str, Any]:
    global enabled, interval_seconds
    enabled = True
    interval_seconds = max(2, int(seconds))  # a floor so this can't be turned into a de facto video stream
    return state()


def stop() -> dict[str, Any]:
    global enabled
    enabled = False
    return state()


def state() -> dict[str, Any]:
    return {"enabled": enabled, "interval_seconds": interval_seconds}


def record_event(description: str) -> dict[str, Any]:
    event = {
        "type": "vision_tracking_event",
        "description": description,
        "created_at": time.time(),
    }
    _record(event)
    return event
