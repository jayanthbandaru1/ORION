"""
ORION's vision MCP server.

qwen3:8b (the primary model) is text-only — it cannot see an image at
all. Rather than replacing it (a real quality/VRAM tradeoff on
text/tool-calling that wasn't worth it), a separate small vision-capable
model (moondream, ~1.2GB resident, verified empirically against this
exact 8GB card before being wired in here) handles image-description
calls only. Ollama loads/unloads models on demand by keep_alive, so
having two models registered doesn't mean both sit in VRAM at once.

This keeps CLAUDE.md's "one central intelligence" principle intact:
vision is just another tool the main agent calls, exactly like
web_search or calendar_get_events — qwen3:8b decides *when* to look,
the vision model only ever answers "what's in this image."

computer_screenshot lives here (not in mcp_servers/computer/, which is
mouse/keyboard control) because a screenshot is a vision *input* —
conceptually the same shape as vision_describe_image, just sourced from
the screen instead of an upload.
"""

import base64
import io
import sys
from pathlib import Path

import ollama
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import vision_tracking  # noqa: E402 — needs the sys.path insert above

VISION_MODEL = "moondream"

mcp = FastMCP(
    name="orion-vision",
    instructions=(
        "Describe or answer questions about an image (screenshot, photo, upload) using a "
        "separate small vision model — qwen3:8b itself cannot see images. Use "
        "computer_screenshot first if the user means 'my screen' rather than a specific image."
    ),
)


@mcp.tool()
def vision_describe_image(image_base64: str, question: str = "Describe what's in this image.") -> str:
    """Answer a question about an image (base64-encoded PNG/JPEG, no data: prefix).
    READ — this only reads and describes an image already provided; nothing is
    written or sent anywhere outside this machine."""
    try:
        response = ollama.chat(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": question, "images": [image_base64]}],
        )
    except ollama.ResponseError as exc:
        raise ValueError(
            f"Vision model '{VISION_MODEL}' isn't available — run `ollama pull {VISION_MODEL}` first. ({exc})"
        ) from exc

    content = response["message"]["content"].strip()
    if not content:
        # Empirically reproducible on this small model: some short/terse
        # phrasings ("What color and shape do you see?") reliably produce
        # an immediate empty response, while descriptive phrasings
        # ("Describe what's in this image.") don't. Rather than silently
        # returning nothing, say so plainly and suggest what works.
        return (
            f"The vision model ({VISION_MODEL}) didn't produce a response to that "
            "question — it can be unreliable with short, terse phrasing. Try "
            "something more descriptive, e.g. \"Describe what's in this image\" "
            "or \"What is in this image?\"."
        )
    return content


@mcp.tool()
def computer_screenshot(question: str | None = None) -> str:
    """Capture the current screen and, if `question` is given, also describe it via the
    vision model in the same call. SENSITIVE — this captures whatever is actually on
    screen right now, which may include content the user didn't expect to share; confirm
    before calling this for real."""
    import pyautogui

    image = pyautogui.screenshot()
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    image_b64 = base64.b64encode(buf.getvalue()).decode()

    if question:
        return vision_describe_image(image_b64, question)
    return f"Screenshot captured ({image.size[0]}x{image.size[1]}). Pass a question to have it described."


@mcp.tool()
def vision_start_tracking(interval_seconds: int = 5) -> str:
    """Start active vision tracking — the browser periodically captures a webcam frame
    (only when it looks meaningfully different from the last one sent, so a static
    scene doesn't spam analysis calls) and this describes what's changed. SENSITIVE —
    unlike a single vision_describe_image call, this is an ongoing camera-watching
    behavior, not a one-shot capture; confirm before starting it for real. Actually
    turning the camera on still requires the VISION tab to be open in a browser with
    that permission granted — this only arms the feature server-side."""
    result = vision_tracking.start(interval_seconds)
    return f"Active vision tracking armed (checking roughly every {result['interval_seconds']}s once a camera is open)."


@mcp.tool()
def vision_stop_tracking() -> str:
    """Stop active vision tracking. SAFE — always reversible, no real consequence."""
    vision_tracking.stop()
    return "Active vision tracking stopped."


if __name__ == "__main__":
    mcp.run()
