"""
ORION's computer-control MCP server — real mouse/keyboard automation via
pyautogui. This is full remote control of the user's actual input
devices, a materially bigger security surface than anything else ORION
does — the user explicitly chose to have this built now, after being
told plainly what it means (v1.2 plan, Stage 4).

Every tool here is DESTRUCTIVE tier (config/permissions.yaml), which
means the existing real confirmation flow (core/orchestrator.py) pauses
before any of it actually runs — nothing new needed there, that's the
whole point of the permission-tier architecture. One nuance worth
knowing: if the model batches several of these calls into one turn,
approving shows every queued action individually but one "Approve"
click runs all of them in that batch, not one confirmation per call —
a pre-existing characteristic of the confirmation flow, not something
specific to this server.

pyautogui.FAILSAFE stays on (the library default): slamming the mouse
into a screen corner aborts whatever pyautogui is doing mid-action — a
real, independent kill switch that doesn't depend on ORION's own
confirmation flow at all.
"""

import pyautogui
from fastmcp import FastMCP

pyautogui.FAILSAFE = True

VALID_BUTTONS = {"left", "right", "middle"}

mcp = FastMCP(
    name="orion-computer",
    instructions=(
        "Real mouse/keyboard control of this PC — every call here is DESTRUCTIVE, "
        "confirmed with the user before it actually runs. Use computer_screenshot "
        "(mcp_servers/vision) first to see the screen before deciding where to click."
    ),
)


@mcp.tool()
def computer_move_mouse(x: int, y: int) -> str:
    """Move the mouse cursor to absolute screen coordinates (x, y). DESTRUCTIVE."""
    pyautogui.moveTo(x, y)
    return f"Moved mouse to ({x}, {y})"


@mcp.tool()
def computer_click(x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> str:
    """Click at (x, y), or at the current cursor position if x/y are omitted.
    button is 'left', 'right', or 'middle'. DESTRUCTIVE."""
    if button not in VALID_BUTTONS:
        raise ValueError(f"button must be one of {sorted(VALID_BUTTONS)}, got {button!r}")
    pyautogui.click(x=x, y=y, clicks=clicks, button=button)
    where = f"({x}, {y})" if x is not None and y is not None else "the current cursor position"
    return f"Clicked {button} button {clicks}x at {where}"


@mcp.tool()
def computer_type_text(text: str) -> str:
    """Type text at the current keyboard focus, as if typed by hand. DESTRUCTIVE."""
    pyautogui.typewrite(text, interval=0.02)
    return f"Typed {len(text)} character(s)"


@mcp.tool()
def computer_press_key(key: str) -> str:
    """Press a single key or a combo joined with '+' (e.g. 'enter', 'esc', 'ctrl+c',
    'alt+tab'). DESTRUCTIVE."""
    keys = [k.strip() for k in key.lower().split("+") if k.strip()]
    if not keys:
        raise ValueError("key must not be empty")
    if len(keys) > 1:
        pyautogui.hotkey(*keys)
    else:
        pyautogui.press(keys[0])
    return f"Pressed {key}"


@mcp.tool()
def computer_cursor_status() -> dict:
    """Current real mouse position and screen resolution — READ, no side effects."""
    pos = pyautogui.position()
    size = pyautogui.size()
    return {
        "x": pos.x,
        "y": pos.y,
        "screen_width": size.width,
        "screen_height": size.height,
        "failsafe_armed": pyautogui.FAILSAFE,
    }


if __name__ == "__main__":
    mcp.run()
