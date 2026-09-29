"""
ORION's API. POST /chat (text) and POST /chat/voice (voice), plus the
static web chat UI.

Run with:
    uvicorn api:app --reload --reload-dir core --reload-dir mcp_servers --reload-dir config --reload-dir interfaces

The explicit --reload-dir allowlist matters: the coding tools write
into ./workspace and the SQLite store writes into ./data as part of
normal operation — without it, --reload's file watcher (which
defaults to the whole project directory) treats every tool call as a
source change and restarts the whole server, and every MCP subprocess,
mid-request. (--reload-exclude glob patterns are the "textbook" fix,
but got mangled by Git Bash's path conversion during development —
--reload-dir sidesteps that with no glob characters involved. Editing
api.py itself while the server is running needs a manual restart,
since the project root isn't in this list.)
"""

import asyncio
import base64
import getpass
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import proactive, realtime, system_monitor, vision_tracking
from core.memory import store
from core.orchestrator import OllamaUnavailableError, Orchestrator, _extract_text
from interfaces.voice import stt, tts

load_dotenv()

orchestrator = Orchestrator()

WEB_DIR = Path(__file__).parent / "interfaces" / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await orchestrator.start()
    stt.preload()
    tts.preload()
    print("[orion] voice models loaded (faster-whisper, Kokoro)")
    history_task = asyncio.create_task(system_monitor.history_loop())
    proactive_task = asyncio.create_task(proactive.proactive_loop(orchestrator))
    yield
    history_task.cancel()
    proactive_task.cancel()
    await orchestrator.stop()


app = FastAPI(title="ORION", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None


class ConfirmRequest(BaseModel):
    confirmation_id: str
    approved: bool


class ToolCallInfo(BaseModel):
    name: str
    tier: str
    denied: bool | None = None


class PendingAction(BaseModel):
    name: str
    arguments: dict[str, Any]
    tier: str
    description: str


class ChatResponse(BaseModel):
    status: str  # "complete" | "pending_confirmation"
    conversation_id: int
    reply: str | None = None
    tool_calls: list[ToolCallInfo] | None = None
    confirmation_id: str | None = None
    pending_actions: list[PendingAction] | None = None
    # v1.1 personality layer — one of core/orchestrator.py's
    # _classify_emotion outputs, derived from what actually happened this
    # turn (not the LLM self-reporting a mood). Drives TTS speed/pacing in
    # /chat/voice and the core's color/intensity in the UI, from the same
    # signal, on every response including text-only ones.
    emotion: str | None = None


class VoiceChatResponse(ChatResponse):
    transcribed_text: str | None = None
    audio_base64: str | None = None


def _to_chat_response(result: dict[str, Any]) -> ChatResponse:
    return ChatResponse(
        status=result["status"],
        conversation_id=result["conversation_id"],
        reply=result.get("reply"),
        tool_calls=result.get("tool_calls") or None,
        confirmation_id=result.get("confirmation_id"),
        pending_actions=result.get("pending_actions"),
        emotion=result.get("emotion"),
    )


async def _run_orchestrator_chat(message: str, conversation_id: int | None, is_voice: bool = False) -> dict[str, Any]:
    try:
        return await orchestrator.chat(message, conversation_id, is_voice=is_voice)
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    result = await _run_orchestrator_chat(req.message, req.conversation_id)
    return _to_chat_response(result)


@app.post("/chat/confirm", response_model=ChatResponse)
async def chat_confirm(req: ConfirmRequest) -> ChatResponse:
    try:
        result = await orchestrator.confirm(req.confirmation_id, req.approved)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _to_chat_response(result)


@app.post("/chat/voice", response_model=VoiceChatResponse)
async def chat_voice(
    audio: UploadFile = File(...),
    conversation_id: int | None = Form(None),
) -> VoiceChatResponse:
    audio_bytes = await audio.read()
    text = stt.transcribe(audio_bytes)

    result = await _run_orchestrator_chat(text, conversation_id, is_voice=True)
    base = _to_chat_response(result)

    # No audio to synthesize yet if this turn paused for confirmation —
    # there's no reply text until the human approves or denies it.
    audio_b64 = (
        base64.b64encode(tts.synthesize(base.reply, emotion=base.emotion or "neutral")).decode()
        if base.reply
        else None
    )

    return VoiceChatResponse(**base.model_dump(), transcribed_text=text, audio_base64=audio_b64)


@app.get("/health")
async def health():
    return {"status": "ok", "tools_loaded": len(orchestrator.tools_schema)}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    """The realtime channel behind the NETWORK tab and (Stage 2)
    proactive notifications. Any client — the web UI, a phone that's
    installed the PWA — connects here and becomes a real entry in
    core.realtime.manager, sharing the same push channel as every other
    connected device."""
    device_id = websocket.query_params.get("device_id")
    label = websocket.query_params.get("label", "unknown")
    device = await realtime.manager.connect(websocket, device_id, label)
    try:
        await websocket.send_json({"type": "hello", "device_id": device.device_id})
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "stats":
                realtime.manager.update_stats(device.device_id, data.get("stats") or {})
    except WebSocketDisconnect:
        realtime.manager.disconnect(device.device_id)


@app.get("/network/devices")
async def network_devices():
    """Real, currently-connected devices — never a fabricated count."""
    return {"devices": realtime.manager.list_devices()}


@app.get("/network/info")
async def network_info():
    return {"lan_url": realtime.get_lan_url(port=int(os.environ.get("ORION_PORT", "8000")))}


class ProactiveToggleRequest(BaseModel):
    enabled: bool


@app.get("/proactive/notifications")
async def proactive_notifications():
    return {"enabled": proactive.enabled, "notifications": proactive.get_recent()}


@app.post("/proactive/toggle")
async def proactive_toggle(req: ProactiveToggleRequest):
    proactive.enabled = req.enabled
    return {"enabled": proactive.enabled}


@app.post("/proactive/check_now")
async def proactive_check_now():
    """Manual trigger — mainly for verifying the scheduler actually works
    without waiting up to POLL_SECONDS for the next real cycle."""
    notifications = await proactive.check_once(orchestrator)
    return {"notifications": notifications}


class VisionAnalyzeRequest(BaseModel):
    conversation_id: int | None = None
    image_base64: str
    question: str | None = None


@app.post("/vision/analyze", response_model=ChatResponse)
async def vision_analyze(req: VisionAnalyzeRequest) -> ChatResponse:
    """Calls vision_describe_image directly (bypassing the LLM's own tool
    selection) since qwen3:8b can't see the image itself to decide to call
    it — but the exchange still lands in the *same* conversation history
    as ordinary chat, not a separate vision-only log, via store.add_message."""
    conversation_id = req.conversation_id
    if conversation_id is None or not store.conversation_exists(conversation_id):
        conversation_id = store.create_conversation()

    client = orchestrator.tool_to_client.get("vision_describe_image")
    if client is None:
        raise HTTPException(status_code=503, detail="Vision tool not available — is mcp_servers/vision/server.py registered in config/mcp_servers.yaml?")

    question = req.question or "Describe what's in this image."
    try:
        result = await client.call_tool("vision_describe_image", {"image_base64": req.image_base64, "question": question})
        description = _extract_text(result)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Vision analysis failed: {exc}") from exc

    store.add_message(conversation_id, "user", f"[Image attached] {question}")
    store.add_message(conversation_id, "assistant", description)

    return ChatResponse(status="complete", conversation_id=conversation_id, reply=description, emotion="neutral")


class VisionTrackingToggleRequest(BaseModel):
    enabled: bool
    interval_seconds: int = 5


@app.get("/vision/tracking_state")
async def vision_tracking_state():
    return vision_tracking.state()


@app.post("/vision/tracking/toggle")
async def vision_tracking_toggle(req: VisionTrackingToggleRequest):
    """Manual on/off from the VISION tab's own toggle — separate from the
    vision_start_tracking/vision_stop_tracking MCP tools ORION itself can
    call conversationally, but both land on the same core.vision_tracking
    state and broadcast, so either path stays in sync everywhere."""
    result = vision_tracking.start(req.interval_seconds) if req.enabled else vision_tracking.stop()
    await realtime.manager.broadcast({"type": "vision_tracking_state", **result})
    return result


class VisionTrackRequest(BaseModel):
    image_base64: str


@app.post("/vision/track")
async def vision_track(req: VisionTrackRequest):
    """One frame from an active-tracking loop (see interfaces/web/index.html's
    client-side capture+diff logic). Deliberately does NOT touch
    store.add_message — a frame every few seconds would flood the Dialogue
    Log, so these live in their own short ring buffer (core.vision_tracking)
    instead, surfaced in the VISION tab's own feed and over the WebSocket."""
    if not vision_tracking.enabled:
        raise HTTPException(status_code=409, detail="Active vision tracking isn't currently enabled.")

    client = orchestrator.tool_to_client.get("vision_describe_image")
    if client is None:
        raise HTTPException(status_code=503, detail="Vision tool not available.")

    try:
        result = await client.call_tool(
            "vision_describe_image",
            {
                "image_base64": req.image_base64,
                "question": "Describe what you see, focusing on people, movement, or anything that changed.",
            },
        )
        description = _extract_text(result)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Vision tracking analysis failed: {exc}") from exc

    event = vision_tracking.record_event(description)
    await realtime.manager.broadcast(event)
    return event


@app.get("/vision/tracking_log")
async def vision_tracking_log():
    return {"events": vision_tracking.get_recent()}


@app.get("/computer/status")
async def computer_status():
    """Real, live cursor position/screen size for the COMPUTER tab — READ,
    no side effects. Actual mouse/keyboard control only happens through
    conversation with ORION (computer_move_mouse/click/type_text/press_key,
    all DESTRUCTIVE, all behind the real confirmation flow), not a manual
    control panel here."""
    client = orchestrator.tool_to_client.get("computer_cursor_status")
    if client is None:
        raise HTTPException(status_code=503, detail="Computer-control tool not available.")
    result = await client.call_tool("computer_cursor_status", {})
    return json.loads(_extract_text(result))


class SynthesizeRequest(BaseModel):
    text: str
    emotion: str = "neutral"


@app.post("/voice/synthesize")
async def voice_synthesize(req: SynthesizeRequest):
    """Text-to-speech only, no chat/LLM turn — v1.2 Stage 10's voice-first
    behavior uses this to speak Stage 2 proactive notifications aloud
    when the user is in a voice-active session (wake word armed), rather
    than only ever showing a silent browser toast."""
    audio_bytes = tts.synthesize(req.text, emotion=req.emotion)
    return {"audio_base64": base64.b64encode(audio_bytes).decode()}


@app.post("/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...)):
    """Transcription only, no chat/LLM turn — used by the LOCATION tab's
    destination mic input, which fills a text field the user can review/
    edit rather than immediately acting on a raw transcript."""
    audio_bytes = await audio.read()
    text = stt.transcribe(audio_bytes)
    return {"text": text}


class DirectionsRequest(BaseModel):
    origin_lat: float
    origin_lon: float
    destination: str
    mode: str = "driving"
    alternatives: bool = False


@app.post("/location/directions")
async def location_directions(req: DirectionsRequest):
    client = orchestrator.tool_to_client.get("location_get_directions")
    if client is None:
        raise HTTPException(status_code=503, detail="Location tool not available.")
    try:
        result = await client.call_tool(
            "location_get_directions",
            {
                "origin_lat": req.origin_lat,
                "origin_lon": req.origin_lon,
                "destination": req.destination,
                "mode": req.mode,
                "alternatives": req.alternatives,
            },
        )
        return json.loads(_extract_text(result))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/weather/current")
async def weather_current(lat: float, lon: float):
    client = orchestrator.tool_to_client.get("weather_get_current")
    if client is None:
        raise HTTPException(status_code=503, detail="Weather tool not available.")
    try:
        result = await client.call_tool("weather_get_current", {"lat": lat, "lon": lon})
        return json.loads(_extract_text(result))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/weather/forecast")
async def weather_forecast(lat: float, lon: float, days: int = 5):
    client = orchestrator.tool_to_client.get("weather_get_forecast")
    if client is None:
        raise HTTPException(status_code=503, detail="Weather tool not available.")
    try:
        result = await client.call_tool("weather_get_forecast", {"lat": lat, "lon": lon, "days": days})
        return {"forecast": json.loads(_extract_text(result))}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/system/stats")
async def system_stats():
    """Real hardware/system telemetry for the CONSOLE and INTERNALS tabs —
    see core/system_monitor.py for exactly what's real vs. reported as
    unavailable, and why."""
    stats = await system_monitor.get_stats(mcp_servers_connected=len(orchestrator.clients))
    stats["operator"] = getpass.getuser()
    return stats


@app.get("/config/voice")
async def voice_config():
    """Serves the Picovoice AccessKey to the wake-word JS. Kept out of the
    static HTML/JS source (env var, not hardcoded) even though Porcupine
    Web's own design has this key end up client-side either way — see
    SETUP.md. Empty string if unset; the JS treats that as "wake word not
    configured" and just doesn't start it, rather than erroring."""
    return {"picovoice_access_key": os.environ.get("PICOVOICE_ACCESS_KEY", "")}


# Mounted last so it doesn't shadow the API routes above — StaticFiles
# only catches paths the routes declared above didn't already claim.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
