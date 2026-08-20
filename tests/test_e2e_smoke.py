"""
One end-to-end smoke test per PHASE4.md: exercise the full
orchestrator loop — user message -> Ollama decides to call a tool ->
MCP executes it -> Ollama answers — against the real, local,
already-sandboxed Phase 0 filesystem tools. Nothing here is mocked:
this is the one piece that doesn't need it, and it's the cheapest way
to prove the whole pipeline (Ollama connectivity, MCP subprocess
communication, tool-call parsing, permission classification, the
conversation store) actually works together, not just each piece in
isolation.

Needs Ollama running locally with qwen3:8b pulled, and every MCP
server's own prerequisites (Google OAuth token, Tavily key) since
Orchestrator.start() connects all of them — this is the real app
starting up, not a stub. Plain asyncio.run() rather than
pytest-asyncio/pytest.mark.asyncio, to avoid a dependency an
asyncio.run() one-liner doesn't need.
"""

import asyncio

from core.orchestrator import Orchestrator


def test_filesystem_tool_call_end_to_end():
    async def run():
        orchestrator = Orchestrator()
        await orchestrator.start()
        try:
            return await orchestrator.chat("What files are in your sandbox directory? Just list the filenames, nothing else.")
        finally:
            await orchestrator.stop()

    result = asyncio.run(run())

    assert result["status"] == "complete"
    assert result["tool_calls"], "expected at least one tool call (list_files)"
    assert any(call["name"] == "list_files" for call in result["tool_calls"])
    assert "welcome.txt" in result["reply"]
