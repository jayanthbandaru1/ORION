"""
ORION's orchestrator.

The loop: user message -> Ollama decides to call a tool -> we run it
via MCP -> result goes back to Ollama -> Ollama gives a final answer.
Phase 1 adds persistent history (core/memory/store.py), a
permission-tier lookup (core/permissions.py), the ORION system prompt,
and multiple MCP servers (config/mcp_servers.yaml) on top of that
same loop. Phase 4 adds a real pause: hitting a SENSITIVE/DESTRUCTIVE
tool call no longer executes it immediately — chat() returns a
pending_confirmation instead, and confirm() resumes the exact same
in-flight loop once the human approves or denies it.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
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
MAX_TOOL_ROUNDS = 5

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
The only reason a SENSITIVE or DESTRUCTIVE action pauses is a real
confirmation prompt the system itself inserts — not something you
need to ask permission for in words first; ordinary READ/SAFE lookups
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


class OllamaUnavailableError(Exception):
    """Ollama isn't reachable (not started, wrong port, etc.) — distinct from
    a normal tool/API error so the caller can show a clear, specific message
    instead of a raw connection traceback."""


class Orchestrator:
    def __init__(self):
        self.clients: list[Client] = []
        self.tool_to_client: dict[str, Client] = {}
        self.ollama = AsyncClient()
        self.tools_schema: list[dict] = []
        # confirmation_id -> paused state, purely in-memory: a pending
        # confirmation that outlives a server restart was never really
        # confirmed, so losing it on restart is correct, not a bug.
        self.pending: dict[str, dict[str, Any]] = {}

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

    async def _ollama_chat(self, messages: list[dict]) -> dict:
        try:
            response = await self.ollama.chat(model=MODEL, messages=messages, tools=self.tools_schema, options=OLLAMA_OPTIONS)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise OllamaUnavailableError(
                "Can't reach Ollama — is it running? (SETUP.md step 1: `ollama --version`, "
                "then the model should respond to `ollama run qwen3:8b \"hi\"`)"
            ) from exc
        return response

    def _persist_assistant(self, conversation_id: int, assistant_message: dict) -> None:
        serialized = _serialize_message(assistant_message)
        store.add_message(conversation_id, "assistant", serialized.get("content"), serialized.get("tool_calls"))

    async def _execute_batch(
        self, conversation_id: int, messages: list[dict], calls: list[dict], tool_calls_made: list[dict]
    ) -> None:
        for call in calls:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            tier = permissions.classify_tool_call(name, args)
            print(f"[orion] tool call: {name}({args}) [tier: {tier}]")
            tool_calls_made.append({"name": name, "tier": tier})

            client = self.tool_to_client.get(name)
            if client is None:
                result_text = f"Error: no tool named '{name}' is registered — the model may have hallucinated a tool name."
            else:
                try:
                    result = await client.call_tool(name, args)
                    result_text = _extract_text(result)
                except Exception as exc:  # noqa: BLE001 — surface the error to the model, not a crash
                    result_text = f"Error running {name}: {exc}"

            messages.append({"role": "tool", "content": result_text})
            store.add_message(conversation_id, "tool", result_text)

    async def _process(
        self,
        conversation_id: int,
        messages: list[dict],
        assistant_message: dict,
        tool_calls_made: list[dict],
        rounds: int,
    ) -> dict[str, Any]:
        while assistant_message.get("tool_calls") and rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            calls = assistant_message["tool_calls"]

            classified = [
                (call, permissions.classify_tool_call(call["function"]["name"], call["function"]["arguments"]))
                for call in calls
            ]
            needs_confirmation = [(call, tier) for call, tier in classified if tier in permissions.NEEDS_CONFIRMATION]

            if needs_confirmation:
                # Pause the *whole* batch, not just the sensitive calls in
                # it — simpler than partially executing some calls and
                # stalling others, and the safe ones just run a moment
                # later once approved instead of immediately.
                confirmation_id = str(uuid.uuid4())
                self.pending[confirmation_id] = {
                    "conversation_id": conversation_id,
                    "messages": messages,
                    "assistant_message": assistant_message,
                    "tool_calls_made": tool_calls_made,
                    "rounds": rounds,
                }
                return {
                    "status": "pending_confirmation",
                    "conversation_id": conversation_id,
                    "confirmation_id": confirmation_id,
                    "pending_actions": [
                        {
                            "name": call["function"]["name"],
                            "arguments": call["function"]["arguments"],
                            "tier": tier,
                            "description": permissions.describe_action(call["function"]["name"], call["function"]["arguments"]),
                        }
                        for call, tier in needs_confirmation
                    ],
                }

            await self._execute_batch(conversation_id, messages, calls, tool_calls_made)

            response = await self._ollama_chat(messages)
            assistant_message = response["message"]
            messages.append(assistant_message)
            self._persist_assistant(conversation_id, assistant_message)

        return {
            "status": "complete",
            "conversation_id": conversation_id,
            "reply": assistant_message["content"],
            "tool_calls": tool_calls_made,
        }

    async def chat(self, user_message: str, conversation_id: int | None = None) -> dict[str, Any]:
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

        response = await self._ollama_chat(messages)
        assistant_message = response["message"]
        messages.append(assistant_message)
        self._persist_assistant(conversation_id, assistant_message)

        return await self._process(conversation_id, messages, assistant_message, [], rounds=0)

    async def confirm(self, confirmation_id: str, approved: bool) -> dict[str, Any]:
        pending = self.pending.pop(confirmation_id, None)
        if pending is None:
            raise KeyError(f"No pending confirmation with id '{confirmation_id}' — it may have already been resolved.")

        conversation_id = pending["conversation_id"]
        messages = pending["messages"]
        assistant_message = pending["assistant_message"]
        tool_calls_made = pending["tool_calls_made"]
        rounds = pending["rounds"]
        calls = assistant_message["tool_calls"]

        if approved:
            await self._execute_batch(conversation_id, messages, calls, tool_calls_made)
        else:
            for call in calls:
                name = call["function"]["name"]
                args = call["function"]["arguments"]
                tier = permissions.classify_tool_call(name, args)
                print(f"[orion] tool call denied by user: {name}({args}) [tier: {tier}]")
                tool_calls_made.append({"name": name, "tier": tier, "denied": True})
                result_text = f"The user denied this action ({name}). Do not attempt it again unless explicitly asked to."
                messages.append({"role": "tool", "content": result_text})
                store.add_message(conversation_id, "tool", result_text)

        response = await self._ollama_chat(messages)
        assistant_message = response["message"]
        messages.append(assistant_message)
        self._persist_assistant(conversation_id, assistant_message)

        return await self._process(conversation_id, messages, assistant_message, tool_calls_made, rounds)
