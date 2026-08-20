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

import base64
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.orchestrator import OllamaUnavailableError, Orchestrator
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
    yield
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
    )


async def _run_orchestrator_chat(message: str, conversation_id: int | None) -> dict[str, Any]:
    try:
        return await orchestrator.chat(message, conversation_id)
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

    result = await _run_orchestrator_chat(text, conversation_id)
    base = _to_chat_response(result)

    # No audio to synthesize yet if this turn paused for confirmation —
    # there's no reply text until the human approves or denies it.
    audio_b64 = base64.b64encode(tts.synthesize(base.reply)).decode() if base.reply else None

    return VoiceChatResponse(**base.model_dump(), transcribed_text=text, audio_base64=audio_b64)


@app.get("/health")
async def health():
    return {"status": "ok", "tools_loaded": len(orchestrator.tools_schema)}


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
