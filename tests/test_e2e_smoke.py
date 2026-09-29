"""
One end-to-end smoke test per PHASE4.md: exercise the full
orchestrator loop — user message -> Ollama decides to call a tool ->
MCP executes it -> Ollama answers — against the real, local
mcp_servers/files/server.py (v1.2 Stage 11's personal-file search
server). Nothing here is mocked: this is the one piece that doesn't
need it, and it's the cheapest way to prove the whole pipeline (Ollama
connectivity, MCP subprocess communication, tool-call parsing,
permission classification, the conversation store) actually works
together, not just each piece in isolation.

This used to target the original Phase 0 sandbox filesystem server
(mcp_servers/filesystem_server.py, tool `list_files`, scoped to
./sandbox). That server still exists and still works, but it's no
longer what a real "what files do you have" request resolves to: with
mcp_servers/files/server.py now also connected, the model reliably
reaches for its `list_directory` tool instead (it's the more
directly-named match, and it's what real filesystem-style requests are
routed to in practice) — and a prompt that said "/sandbox" made that
tool reject the path outright, since `list_directory` only ever
resolves paths against config/authorized_paths.yaml, never a relative
sandbox path. Rather than fight the model back onto the old tool (or
loosen the authorization check to accept a path it was never meant to
accept), this test now exercises the tool the model actually calls.

Deliberately asks for the *default* authorized directory (no path
named in the prompt at all) rather than a specific one of
config/authorized_paths.yaml's real entries (~/OneDrive/Desktop,
~/Documents, ...): `list_directory(path=None)` defaults to
AUTHORIZED_PATHS[0] server-side, so this needs no machine-specific
path — not the user's real Windows username, not an assumption about
which of those directories exists on whatever machine runs this suite.
Assertions are structural (right tool, no error, real non-empty reply)
rather than matching a specific filename: unlike the old sandbox's
checked-in welcome.txt, an authorized personal directory's real
contents aren't something a test should assume, depend on, or print.

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
            return await orchestrator.chat(
                "Use the list_directory tool with no path argument to show me what's in "
                "my default authorized files directory. Just list the filenames, nothing else."
            )
        finally:
            await orchestrator.stop()

    result = asyncio.run(run())

    assert result["status"] == "complete"
    assert result["tool_calls"], "expected at least one tool call (list_directory)"
    assert any(call["name"] == "list_directory" for call in result["tool_calls"])
    assert not any(call.get("error") for call in result["tool_calls"]), (
        f"a filesystem tool call errored: {result['tool_calls']}"
    )
    assert result["reply"].strip(), "expected a real, non-empty reply"
