"""
ORION's API. One endpoint: POST /chat, plus the static web chat UI.

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

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.orchestrator import Orchestrator

orchestrator = Orchestrator()

WEB_DIR = Path(__file__).parent / "interfaces" / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await orchestrator.start()
    yield
    await orchestrator.stop()


app = FastAPI(title="ORION", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None


class ToolCallInfo(BaseModel):
    name: str
    tier: str


class ChatResponse(BaseModel):
    reply: str
    conversation_id: int
    tool_calls: list[ToolCallInfo] | None = None


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    conversation_id, reply, tool_calls = await orchestrator.chat(req.message, req.conversation_id)
    return ChatResponse(reply=reply, conversation_id=conversation_id, tool_calls=tool_calls or None)


@app.get("/health")
async def health():
    return {"status": "ok", "tools_loaded": len(orchestrator.tools_schema)}


# Mounted last so it doesn't shadow the API routes above — StaticFiles
# only catches paths the routes declared above didn't already claim.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
