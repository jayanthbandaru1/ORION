"""
Unit tests for core/orchestrator.py — previously only exercised via the
one (non-mocked, somewhat flaky by nature) end-to-end smoke test. These
cover the pure logic (`_classify_emotion`) and the v1.2 Stage 9
`tool_use` broadcast added to `_execute_batch` (a real signal over the
Stage 1 WebSocket for the orb's TOOL_USE visual state), with everything
external (MCP client, realtime broadcast, the store) faked or real-but-
local (SQLite).
"""

import asyncio

from conftest import PROJECT_ROOT  # noqa: F401 — ensures sys.path is set up
from ollama import Message

from core import orchestrator as orch
from core.memory import store


class TestClassifyEmotion:
    def test_pending_confirmation_is_serious(self):
        assert orch._classify_emotion([], pending_actions=[{"tier": "SENSITIVE"}]) == "serious"

    def test_a_denied_call_is_concerned(self):
        assert orch._classify_emotion([{"name": "x", "tier": "READ", "denied": True}]) == "concerned"

    def test_an_errored_call_is_concerned(self):
        assert orch._classify_emotion([{"name": "x", "tier": "READ", "error": True}]) == "concerned"

    def test_a_completed_consequential_action_is_confident(self):
        assert orch._classify_emotion([{"name": "x", "tier": "SENSITIVE"}]) == "confident"

    def test_plain_read_only_calls_are_neutral(self):
        assert orch._classify_emotion([{"name": "x", "tier": "READ"}]) == "neutral"

    def test_no_calls_at_all_is_neutral(self):
        assert orch._classify_emotion([]) == "neutral"

    def test_denied_takes_priority_over_a_plain_error(self):
        # a real turn could have both a denial and an unrelated error — denial
        # (the user actively said no) is the more important signal to surface
        calls = [{"name": "a", "tier": "READ", "denied": True}, {"name": "b", "tier": "READ", "error": True}]
        assert orch._classify_emotion(calls) == "concerned"


class FakeContentBlock:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, text):
        self.content = [FakeContentBlock(text)]


class FakeToolClient:
    def __init__(self, result_text):
        self.result_text = result_text

    async def call_tool(self, name, args):
        return FakeResult(self.result_text)


class TestExecuteBatchToolUseBroadcast:
    def test_broadcasts_tool_use_before_calling_the_tool(self, monkeypatch):
        store.init_db()
        conversation_id = store.create_conversation()

        broadcasts = []

        async def fake_broadcast(message):
            broadcasts.append(message)

        monkeypatch.setattr(orch.realtime.manager, "broadcast", fake_broadcast)

        o = orch.Orchestrator()
        o.tool_to_client["task_list"] = FakeToolClient("[]")

        calls = [{"function": {"name": "task_list", "arguments": {}}}]
        tool_calls_made = []
        messages = []

        asyncio.run(o._execute_batch(conversation_id, messages, calls, tool_calls_made))

        assert broadcasts == [{"type": "tool_use", "tool": "task_list", "tier": "READ"}]
        assert tool_calls_made == [{"name": "task_list", "tier": "READ"}]

    def test_a_broadcast_failure_does_not_block_the_tool_call(self, monkeypatch):
        """A slow/dead connected client shouldn't be able to break a real
        tool call — the broadcast is wrapped in try/except for exactly this."""
        store.init_db()
        conversation_id = store.create_conversation()

        async def broken_broadcast(message):
            raise RuntimeError("some client disconnected mid-send")

        monkeypatch.setattr(orch.realtime.manager, "broadcast", broken_broadcast)

        o = orch.Orchestrator()
        o.tool_to_client["task_list"] = FakeToolClient('[{"id": 1}]')

        calls = [{"function": {"name": "task_list", "arguments": {}}}]
        tool_calls_made = []
        messages = []

        asyncio.run(o._execute_batch(conversation_id, messages, calls, tool_calls_made))

        # the tool call itself still completed successfully despite the broadcast blowing up
        assert tool_calls_made == [{"name": "task_list", "tier": "READ"}]
        assert messages[0]["content"] == '[{"id": 1}]'


class TestVoiceFirstSystemPrompt:
    """v1.2 Stage 10: a voice-originated turn gets an extra system-prompt
    addendum (brief, no markdown, no reflexive follow-up question) since
    the reply is actually spoken aloud, not just displayed."""

    def test_is_voice_true_adds_the_voice_addendum(self, monkeypatch):
        store.init_db()
        captured = {}

        async def fake_ollama_chat(self, messages):
            captured["messages"] = messages
            return {"message": Message(role="assistant", content="Done.")}

        monkeypatch.setattr(orch.Orchestrator, "_ollama_chat", fake_ollama_chat)

        o = orch.Orchestrator()
        asyncio.run(o.chat("remind me to call mom", is_voice=True))

        system_content = captured["messages"][0]["content"]
        assert "spoken aloud" in system_content
        assert "no markdown at all" in system_content

    def test_is_voice_false_omits_the_voice_addendum(self, monkeypatch):
        store.init_db()
        captured = {}

        async def fake_ollama_chat(self, messages):
            captured["messages"] = messages
            return {"message": Message(role="assistant", content="Done.")}

        monkeypatch.setattr(orch.Orchestrator, "_ollama_chat", fake_ollama_chat)

        o = orch.Orchestrator()
        asyncio.run(o.chat("remind me to call mom"))

        system_content = captured["messages"][0]["content"]
        assert "spoken aloud" not in system_content
