"""
ORION's API. One endpoint: POST /chat, plus the static web chat UI.

Run with:
    uvicorn api:app --reload
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
