"""
ORION's orchestrator.

The loop: user message -> Ollama decides to call a tool -> we run it
via MCP -> result goes back to Ollama -> Ollama gives a final answer.
Phase 1 adds persistent history (core/memory/store.py), a
permission-tier lookup (core/permissions.py), the ORION system prompt,
and multiple MCP servers (config/mcp_servers.yaml) on top of that
same loop.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastmcp import Client
from ollama import AsyncClient

from core import permissions
from core.memory import store

# If tool calls come back unreliable, try "qwen3.5:9b" instead and
# compare — see SETUP.md for why both are worth testing on your card.
MODEL = "qwen3:8b"

PROJECT_ROOT = Path(__file__).parent.parent
MCP_SERVERS_CONFIG = PROJECT_ROOT / "config" / "mcp_servers.yaml"

ORION_SYSTEM_PROMPT = """You are ORION (Omni-Responsive Intelligence &
Operations Nexus) — a highly capable personal AI operating system.

Voice: confident, analytical, calm, precise. Occasional dry humor is
fine, but don't force it — restraint is part of the character. You are
not obsequious: if a request is a bad idea, say so plainly before doing
it. Be proactive about surfacing things that matter, but don't pad
responses with unnecessary commentary.

Answer like someone talking, not like a support ticket: skip headers,
bullet lists, and bold text for ordinary conversational answers —
reach for that structure only when the content genuinely has multiple
parallel items (a list of files, a set of options) worth scanning.
Don't close every reply with a reflexive "would you like me to..." or
"let me know if..." — only offer a next step when there's a real one
worth naming. Vary your phrasing and structure between turns; nothing
should read like it was pulled from a template, especially the same
question asked twice.

You have real tools and real consequences — when you call a tool, you
are actually doing the thing, not describing it. This cuts the other
way too: never say you're about to check, look up, search, or
calculate something and then stop without calling the tool right then
in that same turn. "Let me look that up" followed by nothing is worse
than useless — if you need a tool to answer, call it immediately and
give the real answer in this response, not a promise to get to it.
The only reason to pause before acting is a genuine SENSITIVE or
DESTRUCTIVE action that needs confirmation first — ordinary lookups
never need permission to proceed."""

# Some sampling variance so factual/simple questions don't collapse into
# the same phrasing every time; still grounded, not scattershot.
OLLAMA_OPTIONS = {"temperature": 0.9}


def _mcp_tool_to_ollama_schema(tool) -> dict:
    """Convert an MCP tool definition into the JSON schema Ollama's /api/chat expects."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


def _extract_text(result) -> str:
    """FastMCP tool results come back as content blocks; flatten to plain text."""
    if hasattr(result, "content") and result.content:
        parts = [getattr(block, "text", str(block)) for block in result.content]
        return "\n".join(parts)
    return str(result)


def _serialize_message(message) -> dict[str, Any]:
    """Turn an Ollama Message (pydantic) into a plain, JSON-serializable dict."""
    return message.model_dump(exclude_none=True, mode="json")


class Orchestrator:
    def __init__(self):
        self.clients: list[Client] = []
        self.tool_to_client: dict[str, Client] = {}
        self.ollama = AsyncClient()
        self.tools_schema: list[dict] = []

    async def start(self):
        store.init_db()

        with MCP_SERVERS_CONFIG.open(encoding="utf-8") as f:
            server_specs = yaml.safe_load(f) or []

        for spec in server_specs:
            server_path = PROJECT_ROOT / spec["path"]
            client = Client(str(server_path))
            await client.__aenter__()
            self.clients.append(client)

            mcp_tools = await client.list_tools()
            for tool in mcp_tools:
                self.tools_schema.append(_mcp_tool_to_ollama_schema(tool))
                self.tool_to_client[tool.name] = client

        print(f"[orion] connected to {len(self.clients)} MCP server(s), {len(self.tools_schema)} tool(s) available")

    async def stop(self):
        for client in self.clients:
            await client.__aexit__(None, None, None)

    async def chat(
        self, user_message: str, conversation_id: int | None = None
    ) -> tuple[int, str, list[dict[str, str]]]:
        if conversation_id is None or not store.conversation_exists(conversation_id):
            conversation_id = store.create_conversation()

        store.add_message(conversation_id, "user", user_message)
        # TODO: smarter truncation — get_messages just keeps the last N turns
        history = store.get_messages(conversation_id)
        # The model has no other way to know "today" — without this, relative
        # dates ("tomorrow", "this weekend") in calendar/task tools get
        # hallucinated against whatever date happens to be in its training data.
        now = datetime.now().astimezone()
        system_prompt = f"{ORION_SYSTEM_PROMPT}\n\nCurrent date and time: {now.strftime('%A, %Y-%m-%d %H:%M %Z')}."
        messages = [{"role": "system", "content": system_prompt}, *history]

        tool_calls_made: list[dict[str, str]] = []

        response = await self.ollama.chat(model=MODEL, messages=messages, tools=self.tools_schema, options=OLLAMA_OPTIONS)
        assistant_message = response["message"]
        messages.append(assistant_message)
        serialized = _serialize_message(assistant_message)
        store.add_message(conversation_id, "assistant", serialized.get("content"), serialized.get("tool_calls"))

        # Loop in case the model wants to call a tool, see the result,
        # and then call another tool before it's ready to answer.
        max_tool_rounds = 5
        rounds = 0
        while assistant_message.get("tool_calls") and rounds < max_tool_rounds:
            rounds += 1
            for call in assistant_message["tool_calls"]:
                name = call["function"]["name"]
                args = call["function"]["arguments"]
                tier = permissions.classify_tool_call(name, args)
                print(f"[orion] tool call: {name}({args}) [tier: {tier}]")
                tool_calls_made.append({"name": name, "tier": tier})

                try:
                    client = self.tool_to_client[name]
                    result = await client.call_tool(name, args)
                    result_text = _extract_text(result)
                except Exception as exc:  # noqa: BLE001 — surface the error to the model, not a crash
                    result_text = f"Error running {name}: {exc}"

                messages.append({
                    "role": "tool",
                    "content": result_text,
                })
                store.add_message(conversation_id, "tool", result_text)

            response = await self.ollama.chat(model=MODEL, messages=messages, tools=self.tools_schema, options=OLLAMA_OPTIONS)
            assistant_message = response["message"]
            messages.append(assistant_message)
            serialized = _serialize_message(assistant_message)
            store.add_message(conversation_id, "assistant", serialized.get("content"), serialized.get("tool_calls"))

        return conversation_id, assistant_message["content"], tool_calls_made
