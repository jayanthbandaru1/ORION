"""
Tests for the computer-control MCP server. pyautogui itself is mocked —
these check the logic that's actually ours: argument validation
(button/key parsing), the single-vs-combo key dispatch, and the
cursor-status read path. Real pyautogui behavior (does moveTo actually
move the mouse) isn't something a unit test should exercise — that was
verified empirically once against this actual machine before writing
this server (see CLAUDE.md's Vision/Computer control section).
"""

from unittest.mock import MagicMock

import pytest

from conftest import load_server_module

computer_server = load_server_module("computer_server_module", "mcp_servers/computer/server.py")


@pytest.fixture(autouse=True)
def fake_pyautogui(monkeypatch):
    fake = MagicMock()
    fake.position.return_value = MagicMock(x=100, y=200)
    fake.size.return_value = MagicMock(width=1920, height=1080)
    fake.FAILSAFE = True
    monkeypatch.setattr(computer_server, "pyautogui", fake)
    return fake


class TestMoveMouse:
    def test_calls_move_to_with_given_coordinates(self, fake_pyautogui):
        result = computer_server.computer_move_mouse(x=500, y=300)
        fake_pyautogui.moveTo.assert_called_once_with(500, 300)
        assert "500, 300" in result


class TestClick:
    def test_default_left_click_at_given_coordinates(self, fake_pyautogui):
        result = computer_server.computer_click(x=10, y=20)
        fake_pyautogui.click.assert_called_once_with(x=10, y=20, clicks=1, button="left")
        assert "left" in result and "(10, 20)" in result

    def test_click_at_current_position_when_coords_omitted(self, fake_pyautogui):
        result = computer_server.computer_click()
        fake_pyautogui.click.assert_called_once_with(x=None, y=None, clicks=1, button="left")
        assert "current cursor position" in result

    def test_right_click_and_multi_click(self, fake_pyautogui):
        computer_server.computer_click(x=1, y=2, button="right", clicks=2)
        fake_pyautogui.click.assert_called_once_with(x=1, y=2, clicks=2, button="right")

    def test_invalid_button_is_rejected_before_calling_pyautogui(self, fake_pyautogui):
        with pytest.raises(ValueError, match="button must be one of"):
            computer_server.computer_click(button="double-secret-probation")
        fake_pyautogui.click.assert_not_called()


class TestTypeText:
    def test_calls_typewrite_with_the_given_text(self, fake_pyautogui):
        result = computer_server.computer_type_text("hello world")
        fake_pyautogui.typewrite.assert_called_once_with("hello world", interval=0.02)
        assert "11" in result  # len("hello world")


class TestPressKey:
    def test_single_key_calls_press_not_hotkey(self, fake_pyautogui):
        computer_server.computer_press_key("enter")
        fake_pyautogui.press.assert_called_once_with("enter")
        fake_pyautogui.hotkey.assert_not_called()

    def test_combo_key_calls_hotkey_with_each_part(self, fake_pyautogui):
        computer_server.computer_press_key("ctrl+shift+esc")
        fake_pyautogui.hotkey.assert_called_once_with("ctrl", "shift", "esc")
        fake_pyautogui.press.assert_not_called()

    def test_empty_key_is_rejected(self, fake_pyautogui):
        with pytest.raises(ValueError, match="empty"):
            computer_server.computer_press_key("   ")


class TestCursorStatus:
    def test_returns_real_position_and_screen_size(self, fake_pyautogui):
        status = computer_server.computer_cursor_status()
        assert status == {
            "x": 100,
            "y": 200,
            "screen_width": 1920,
            "screen_height": 1080,
            "failsafe_armed": True,
        }
