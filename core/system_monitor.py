"""
ORION's hardware/system telemetry — the real data behind the CONSOLE
tab's Core Telemetry card and the INTERNALS tab. Every number here
comes from psutil or `nvidia-smi` at request time; nothing is invented.

Sensors this hardware genuinely doesn't expose through any officially
supported API — CPU package temperature, fan RPM, PCIe link topology,
PSU/coolant telemetry — are reported as unavailable (see
SENSOR_LIMITATIONS) rather than faked. Getting real numbers for those
would need a dedicated sensor bridge (e.g. LibreHardwareMonitor)
running alongside ORION, which isn't wired up here.

GPU stats shell out to `nvidia-smi` rather than adding a pynvml
dependency — nvidia-smi ships with any NVIDIA driver install, so this
needs no extra package (CLAUDE.md: "avoid unnecessary dependencies").
"""

import asyncio
import shutil
import subprocess
import time
from collections import deque
from typing import Any

import httpx
import psutil

SENSOR_LIMITATIONS = (
    "Fan speed, PCIe link topology, and PSU/coolant telemetry aren't exposed "
    "by Windows or this hardware through any officially supported API without "
    "a dedicated sensor bridge (e.g. LibreHardwareMonitor) running alongside "
    "ORION. Not wired up — shown as unavailable rather than faked."
)

_START_TIME = time.monotonic()
_NVIDIA_SMI = shutil.which("nvidia-smi")

_HISTORY_MAXLEN = 60  # one sample per ~5s -> ~5 minutes of real history
_history: deque[dict[str, Any]] = deque(maxlen=_HISTORY_MAXLEN)

_last_disk_io = psutil.disk_io_counters()
_last_net_io = psutil.net_io_counters()
_last_sample_time = time.monotonic()

# Prime psutil's internal cpu_percent timers so the first real call
# reports a meaningful window instead of psutil's documented "0.0 or
# garbage on the very first call" behavior.
psutil.cpu_percent(interval=None)
psutil.cpu_percent(interval=None, percpu=True)


def _gpu_stats_sync() -> dict[str, Any] | None:
    if not _NVIDIA_SMI:
        return None
    try:
        result = subprocess.run(
            [
                _NVIDIA_SMI,
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        name, util, mem_used, mem_total, temp, power = (p.strip() for p in result.stdout.strip().split(","))
        return {
            "name": name,
            "utilization_percent": float(util),
            "vram_used_mb": float(mem_used),
            "vram_total_mb": float(mem_total),
            "temperature_c": float(temp),
            "power_draw_w": float(power),
        }
    except Exception:
        return None


async def _gpu_stats() -> dict[str, Any] | None:
    return await asyncio.to_thread(_gpu_stats_sync)


async def _ollama_latency_ms() -> float | None:
    try:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=1.5) as client:
            await client.get("http://localhost:11434/api/version")
        return round((time.monotonic() - start) * 1000, 1)
    except Exception:
        return None


async def sample_for_history() -> None:
    """Called on a background timer (see api.py's lifespan) so real load
    history exists even before any client opens the Internals tab."""
    cpu = psutil.cpu_percent(interval=None)
    gpu = await _gpu_stats()
    _history.append(
        {
            "t": time.time(),
            "cpu_percent": cpu,
            "gpu_percent": gpu["utilization_percent"] if gpu else None,
        }
    )


async def history_loop() -> None:
    while True:
        try:
            await sample_for_history()
        except Exception:
            pass
        await asyncio.sleep(5)


async def get_stats(mcp_servers_connected: int) -> dict[str, Any]:
    global _last_disk_io, _last_net_io, _last_sample_time

    now = time.monotonic()
    elapsed = max(now - _last_sample_time, 0.001)

    disk_io = psutil.disk_io_counters()
    net_io = psutil.net_io_counters()
    disk_read_mb_s = (disk_io.read_bytes - _last_disk_io.read_bytes) / 1e6 / elapsed
    disk_write_mb_s = (disk_io.write_bytes - _last_disk_io.write_bytes) / 1e6 / elapsed
    net_sent_kb_s = (net_io.bytes_sent - _last_net_io.bytes_sent) / 1e3 / elapsed
    net_recv_kb_s = (net_io.bytes_recv - _last_net_io.bytes_recv) / 1e3 / elapsed
    _last_disk_io, _last_net_io, _last_sample_time = disk_io, net_io, now

    vm = psutil.virtual_memory()
    disks = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue  # unmounted/inaccessible (e.g. an empty optical drive)
        disks.append(
            {
                "device": part.device,
                "total_gb": round(usage.total / 1e9, 1),
                "used_gb": round(usage.used / 1e9, 1),
                "percent": usage.percent,
            }
        )

    gpu, ollama_latency_ms = await asyncio.gather(_gpu_stats(), _ollama_latency_ms())

    return {
        "cpu": {
            "logical_cores": psutil.cpu_count(logical=True),
            "physical_cores": psutil.cpu_count(logical=False),
            "overall_percent": psutil.cpu_percent(interval=None),
            "per_core_percent": psutil.cpu_percent(interval=None, percpu=True),
        },
        "memory": {
            "total_gb": round(vm.total / 1e9, 1),
            "used_gb": round(vm.used / 1e9, 1),
            "available_gb": round(vm.available / 1e9, 1),
            "percent": vm.percent,
        },
        "disks": disks,
        "disk_io": {
            "read_mb_s": round(max(disk_read_mb_s, 0), 2),
            "write_mb_s": round(max(disk_write_mb_s, 0), 2),
        },
        "network": {
            "sent_kb_s": round(max(net_sent_kb_s, 0), 1),
            "recv_kb_s": round(max(net_recv_kb_s, 0), 1),
            "ollama_latency_ms": ollama_latency_ms,
        },
        "gpu": gpu,
        "uptime_seconds": round(time.monotonic() - _START_TIME),
        "subsystems": {"mcp_servers_connected": mcp_servers_connected},
        "history": list(_history),
        "sensor_limitations": SENSOR_LIMITATIONS,
    }
