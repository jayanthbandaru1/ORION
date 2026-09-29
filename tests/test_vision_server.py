"""
Tests for the vision MCP server. ollama.chat and pyautogui.screenshot are
mocked — these check the logic that's actually ours: which model gets
called, how a missing-model error is humanized, and that
computer_screenshot only calls the vision model when a question was
actually asked.
"""

from unittest.mock import MagicMock

import ollama
import pytest

from conftest import load_server_module

vision_server = load_server_module("vision_server_module", "mcp_servers/vision/server.py")


class TestVisionDescribeImage:
    def test_calls_the_configured_vision_model_with_the_image(self, monkeypatch):
        captured = {}

        def fake_chat(model, messages):
            captured["model"] = model
            captured["messages"] = messages
            return {"message": {"content": "A cyan ring on a dark background."}}

        monkeypatch.setattr(vision_server.ollama, "chat", fake_chat)

        result = vision_server.vision_describe_image("base64data", "What shape is this?")

        assert result == "A cyan ring on a dark background."
        assert captured["model"] == vision_server.VISION_MODEL
        assert captured["messages"][0]["images"] == ["base64data"]
        assert captured["messages"][0]["content"] == "What shape is this?"

    def test_default_question_is_a_general_description(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            vision_server.ollama, "chat",
            lambda model, messages: captured.update(messages=messages) or {"message": {"content": "ok"}},
        )
        vision_server.vision_describe_image("base64data")
        assert "describe" in captured["messages"][0]["content"].lower()

    def test_missing_model_error_is_humanized(self, monkeypatch):
        def fake_chat(model, messages):
            raise ollama.ResponseError("model 'moondream' not found")

        monkeypatch.setattr(vision_server.ollama, "chat", fake_chat)

        with pytest.raises(ValueError, match="ollama pull"):
            vision_server.vision_describe_image("base64data")

    def test_empty_model_response_returns_an_honest_message_not_blank(self, monkeypatch):
        # Regression test: empirically reproducible on the real moondream
        # model — some short/terse questions produce a genuinely empty
        # response. Silently returning "" would look like a bug rather
        # than a known model limitation.
        monkeypatch.setattr(
            vision_server.ollama, "chat",
            lambda model, messages: {"message": {"content": ""}},
        )
        result = vision_server.vision_describe_image("base64data", "What color and shape do you see?")
        assert result != ""
        assert "didn't produce a response" in result


class TestComputerScreenshot:
    def test_without_question_returns_size_summary_and_does_not_call_vision_model(self, monkeypatch):
        fake_image = MagicMock()
        fake_image.size = (1920, 1080)

        def fake_save(buf, format):
            buf.write(b"fake-png-bytes")

        fake_image.save.side_effect = fake_save

        fake_pyautogui = MagicMock()
        fake_pyautogui.screenshot.return_value = fake_image
        monkeypatch.setitem(__import__("sys").modules, "pyautogui", fake_pyautogui)

        chat_called = []
        monkeypatch.setattr(vision_server.ollama, "chat", lambda **kw: chat_called.append(kw) or {"message": {"content": "x"}})

        result = vision_server.computer_screenshot()

        assert "1920x1080" in result
        assert chat_called == []

    def test_with_question_describes_the_captured_screenshot(self, monkeypatch):
        fake_image = MagicMock()
        fake_image.size = (1920, 1080)
        fake_image.save.side_effect = lambda buf, format: buf.write(b"fake-png-bytes")

        fake_pyautogui = MagicMock()
        fake_pyautogui.screenshot.return_value = fake_image
        monkeypatch.setitem(__import__("sys").modules, "pyautogui", fake_pyautogui)

        captured = {}

        def fake_chat(model, messages):
            captured["images"] = messages[0]["images"]
            return {"message": {"content": "A code editor with a red squiggly underline."}}

        monkeypatch.setattr(vision_server.ollama, "chat", fake_chat)

        result = vision_server.computer_screenshot(question="What's wrong here?")

        assert result == "A code editor with a red squiggly underline."
        assert len(captured["images"]) == 1  # the screenshot was actually base64-encoded and passed through


class TestActiveVisionTracking:
    def teardown_method(self):
        # These two tools mutate module-level state in core.vision_tracking —
        # reset it so one test's start() doesn't leak into the next test.
        vision_server.vision_tracking.stop()

    def test_start_tracking_enables_state_and_reports_the_interval(self):
        result = vision_server.vision_start_tracking(interval_seconds=10)
        assert "10" in result
        assert vision_server.vision_tracking.enabled is True
        assert vision_server.vision_tracking.interval_seconds == 10

    def test_start_tracking_enforces_a_minimum_interval(self):
        vision_server.vision_start_tracking(interval_seconds=1)
        assert vision_server.vision_tracking.interval_seconds >= 2

    def test_stop_tracking_disables_state(self):
        vision_server.vision_start_tracking()
        vision_server.vision_stop_tracking()
        assert vision_server.vision_tracking.enabled is False
