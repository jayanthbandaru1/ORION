"""
Regression test for v1.2 Stage 6's low-friction permission change.

This is a deliberate, security-relevant loosening (routine calendar
create/update no longer pauses for confirmation) — worth locking in with
an explicit test rather than relying on nobody accidentally reverting or
over-loosening it later.
"""

from core import permissions


class TestLowFrictionCalendarActions:
    """Routine, reversible calendar actions execute without confirmation."""

    def test_google_calendar_create_and_update_are_reversible_not_sensitive(self):
        assert permissions.get_tier("calendar_create_event") == "REVERSIBLE"
        assert permissions.get_tier("calendar_update_event") == "REVERSIBLE"

    def test_icloud_calendar_create_and_update_are_reversible_not_sensitive(self):
        assert permissions.get_tier("icloud_calendar_create_event") == "REVERSIBLE"
        assert permissions.get_tier("icloud_calendar_update_event") == "REVERSIBLE"

    def test_these_do_not_require_confirmation(self):
        for tool in ["calendar_create_event", "calendar_update_event", "icloud_calendar_create_event", "icloud_calendar_update_event"]:
            assert permissions.get_tier(tool) not in permissions.NEEDS_CONFIRMATION, tool


class TestHighFrictionActionsUnchanged:
    """Destructive/irreversible actions — and email sending specifically —
    still require confirmation; the loosening above must not have spread."""

    def test_calendar_delete_is_still_destructive(self):
        assert permissions.get_tier("calendar_delete_event") == "DESTRUCTIVE"
        assert permissions.get_tier("icloud_calendar_delete_event") == "DESTRUCTIVE"

    def test_gmail_send_is_still_sensitive(self):
        assert permissions.get_tier("gmail_send_draft") == "SENSITIVE"

    def test_computer_control_actions_are_still_destructive(self):
        for tool in ["computer_move_mouse", "computer_click", "computer_type_text", "computer_press_key"]:
            assert permissions.get_tier(tool) == "DESTRUCTIVE"

    def test_all_of_these_require_confirmation(self):
        for tool in [
            "calendar_delete_event", "icloud_calendar_delete_event", "gmail_send_draft",
            "computer_move_mouse", "computer_click", "computer_type_text", "computer_press_key",
        ]:
            assert permissions.get_tier(tool) in permissions.NEEDS_CONFIRMATION, tool
