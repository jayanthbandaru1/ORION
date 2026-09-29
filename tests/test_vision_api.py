"""
Tests for the /vision/analyze endpoint in api.py — verifies it calls the
vision tool via tool_to_client (not the full LLM tool-selection loop,
since qwen3:8b can't see the image to decide to call it) and that the
exchange lands in the *same* conversation history as ordinary chat.

Uses TestClient without `with` so api.py's lifespan (7 MCP subprocesses +
voice preload) never runs — this endpoint only touches
orchestrator.tool_to_client and core.memory.store, both fakeable/real
without any of that.
"""

from conftest import PROJECT_ROOT  # noqa: F401 — ensures sys.path is set up

from core.memory import store


class FakeContentBlock:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, text):
        self.content = [FakeContentBlock(text)]


class FakeVisionClient:
    def __init__(self, description):
        self.description = description
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return FakeResult(self.description)


def _client():
    from fastapi.testclient import TestClient

    import api

    store.init_db()
    return api, TestClient(api.app)


class TestVisionAnalyze:
    def test_calls_vision_tool_and_returns_its_description(self):
        api, client = _client()
        api.orchestrator.tool_to_client["vision_describe_image"] = FakeVisionClient(
            "A cyan ring on a dark background."
        )

        response = client.post("/vision/analyze", json={"image_base64": "abc123", "question": "What shape?"})

        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "A cyan ring on a dark background."
        assert data["status"] == "complete"
        assert isinstance(data["conversation_id"], int)

    def test_passes_the_image_and_question_through_unmodified(self):
        api, client = _client()
        fake_client = FakeVisionClient("ok")
        api.orchestrator.tool_to_client["vision_describe_image"] = fake_client

        client.post("/vision/analyze", json={"image_base64": "the-image-data", "question": "Custom question?"})

        assert fake_client.calls == [("vision_describe_image", {"image_base64": "the-image-data", "question": "Custom question?"})]

    def test_default_question_when_none_given(self):
        api, client = _client()
        fake_client = FakeVisionClient("ok")
        api.orchestrator.tool_to_client["vision_describe_image"] = fake_client

        client.post("/vision/analyze", json={"image_base64": "img"})

        assert "describe" in fake_client.calls[0][1]["question"].lower()

    def test_exchange_is_persisted_into_the_same_conversation_history(self):
        api, client = _client()
        api.orchestrator.tool_to_client["vision_describe_image"] = FakeVisionClient("It's a cat.")

        response = client.post("/vision/analyze", json={"image_base64": "abc", "question": "What is this?"})
        conversation_id = response.json()["conversation_id"]

        messages = store.get_messages(conversation_id)
        assert any(m["role"] == "user" and "[Image attached]" in (m["content"] or "") for m in messages)
        assert any(m["role"] == "assistant" and m["content"] == "It's a cat." for m in messages)

    def test_reuses_an_existing_conversation_id(self):
        api, client = _client()
        api.orchestrator.tool_to_client["vision_describe_image"] = FakeVisionClient("desc")
        existing_id = store.create_conversation()

        response = client.post("/vision/analyze", json={"conversation_id": existing_id, "image_base64": "abc"})

        assert response.json()["conversation_id"] == existing_id

    def test_missing_vision_tool_returns_503(self):
        api, client = _client()
        api.orchestrator.tool_to_client.pop("vision_describe_image", None)

        response = client.post("/vision/analyze", json={"image_base64": "abc"})

        assert response.status_code == 503

    def test_tool_failure_returns_502_not_a_crash(self):
        api, client = _client()

        class FailingClient:
            async def call_tool(self, name, args):
                raise RuntimeError("model not found")

        api.orchestrator.tool_to_client["vision_describe_image"] = FailingClient()

        response = client.post("/vision/analyze", json={"image_base64": "abc"})

        assert response.status_code == 502
