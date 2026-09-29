"""
ORION's permission-tier lookup.

Look up each tool's tier and log it before the call runs. Phase 4 adds
real interactive confirmation for SENSITIVE/DESTRUCTIVE tools on top of
this same lookup (see NEEDS_CONFIRMATION and describe_action below) —
through Phase 2/3 those tiers were logged but not yet blocked.
"""

from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config" / "permissions.yaml"

# Unknown tools default to the most cautious tier until someone
# classifies them in config/permissions.yaml.
DEFAULT_TIER = "DESTRUCTIVE"

# Only these two tiers pause for approval — READ/SAFE/REVERSIBLE keep
# executing with zero friction, per PHASE4.md's explicit "don't
# over-correct into confirming everything."
NEEDS_CONFIRMATION = {"SENSITIVE", "DESTRUCTIVE"}


def _load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_CONFIG = _load_config()


def get_tier(tool_name: str) -> str:
    tier = _CONFIG.get(tool_name, DEFAULT_TIER)
    # run_command_allowlist is config, not a tool — never mistake it for one.
    return tier if isinstance(tier, str) else DEFAULT_TIER


def classify_tool_call(tool_name: str, args: dict) -> str:
    """Like get_tier, but with a per-argument override for run_command: SAFE
    when its first word is on the allowlist, SENSITIVE otherwise. Everything
    else is a plain per-tool-name lookup — see PHASE2.md for why run_command
    alone needs this nuance."""
    if tool_name == "run_command":
        command = str(args.get("command", "")).strip()
        first_word = command.split()[0] if command else ""
        allowlist = _CONFIG.get("run_command_allowlist") or []
        if first_word in allowlist:
            return "SAFE"
    return get_tier(tool_name)


# Per-tool plain-language descriptions of the consequence, built only from
# the arguments already present on the call (no extra lookups — e.g. no
# fetching the calendar event's title before asking, which would add a
# round trip and a new failure mode to something that's supposed to be a
# safety pause). Falls back to a generic rendering for anything not listed.
_DESCRIPTIONS = {
    "calendar_create_event": lambda a: (
        f"Create calendar event '{a.get('summary', '?')}' from {a.get('start', '?')} to {a.get('end', '?')}"
        + (f" on calendar {a['calendar_id']}" if a.get("calendar_id") and a["calendar_id"] != "primary" else "")
    ),
    "calendar_update_event": lambda a: f"Update calendar event {a.get('event_id', '?')}",
    "calendar_delete_event": lambda a: f"Permanently delete calendar event {a.get('event_id', '?')}",
    "icloud_calendar_create_event": lambda a: (
        f"Create iCloud calendar event '{a.get('summary', '?')}' from {a.get('start', '?')} to {a.get('end', '?')}"
        + (f" on calendar {a['calendar_name']}" if a.get("calendar_name") else "")
    ),
    "icloud_calendar_update_event": lambda a: f"Update iCloud calendar event {a.get('uid', '?')}",
    "icloud_calendar_delete_event": lambda a: f"Permanently delete iCloud calendar event {a.get('uid', '?')}",
    "gmail_send_draft": lambda a: f"Send email draft {a.get('draft_id', '?')} — this delivers real mail, not reversible",
    "write_file": lambda a: f"Write to '{a.get('path', '?')}' in the coding workspace (overwrites if it exists)",
    "edit_file": lambda a: f"Edit '{a.get('path', '?')}' in the coding workspace",
    "run_command": lambda a: f"Run command: {a.get('command', '?')}",
    "computer_screenshot": lambda a: "Capture whatever is currently on screen" + (f" and describe it: {a['question']}" if a.get("question") else ""),
    "computer_move_mouse": lambda a: f"Move the mouse to ({a.get('x', '?')}, {a.get('y', '?')})",
    "computer_click": lambda a: (
        f"{a.get('button', 'left')}-click"
        + (f" {a['clicks']}x" if a.get("clicks", 1) != 1 else "")
        + (f" at ({a['x']}, {a['y']})" if a.get("x") is not None and a.get("y") is not None else " at the current cursor position")
    ),
    "computer_type_text": lambda a: f"Type this text on the real keyboard: \"{a.get('text', '?')}\"",
    "computer_press_key": lambda a: f"Press the key(s): {a.get('key', '?')}",
    "open_file": lambda a: f"Open '{a.get('path', '?')}' in its default application",
    "vision_start_tracking": lambda a: f"Start continuously watching the webcam (checking roughly every {a.get('interval_seconds', 5)}s) and describing what changes",
}


def describe_action(tool_name: str, args: dict) -> str:
    """Plain-language consequence for the confirmation prompt — PHASE4.md:
    'This will permanently delete the calendar event...' rather than the
    raw tool_name(args) call."""
    builder = _DESCRIPTIONS.get(tool_name)
    if builder:
        try:
            return builder(args)
        except Exception:  # noqa: BLE001 — malformed args shouldn't break the prompt, just fall through
            pass
    args_str = ", ".join(f"{k}={v}" for k, v in args.items())
    return f"{tool_name}({args_str})"
