"""
ORION's text-to-speech: Kokoro, via the kokoro-onnx package.

Chosen for its tiny footprint (CLAUDE.md: "leaves VRAM for the LLM") —
runs on CPU through onnxruntime, so it uses zero VRAM, none of which
this 8GB card can spare while qwen3:8b is loaded. The native `kokoro`
package pulls in a numpy build that needs a C compiler this machine
doesn't have; kokoro-onnx ships prebuilt ONNX weights instead, no
compilation required. Model weights (~92MB int8 model + ~28MB voices)
live in ./models, gitignored — see SETUP.md for how to fetch them.
"""

import io
import re
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro

MODELS_DIR = Path(__file__).parent.parent.parent / "models"
MODEL_PATH = MODELS_DIR / "kokoro-v1.0.int8.onnx"
VOICES_PATH = MODELS_DIR / "voices-v1.0.bin"
VOICE = "af_heart"

_kokoro: Kokoro | None = None


def _get_kokoro() -> Kokoro:
    global _kokoro
    if _kokoro is None:
        if not MODEL_PATH.exists() or not VOICES_PATH.exists():
            raise RuntimeError(
                f"Kokoro model files not found in {MODELS_DIR} — "
                "download kokoro-v1.0.int8.onnx and voices-v1.0.bin from "
                "https://github.com/thewh1teagle/kokoro-onnx/releases (model-files-v1.0)."
            )
        _kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
    return _kokoro


def preload() -> None:
    """Load the model at startup rather than on the first real request,
    so the first voice interaction isn't the slowest one."""
    _get_kokoro()


_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols, pictographs, emoticons, transport, supplemental
    "\U00002600-\U000027BF"  # misc symbols, dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicators
    "\U0000FE0F"  # variation selector-16
    "]+"
)


def _strip_markdown(text: str) -> str:
    """Kokoro has no markdown awareness — it vocalizes '**' and '#' as literal
    characters, and would either mangle or silently choke on emoji. The text
    UI wants the raw markdown/emoji (it renders fine there); only the audio
    path needs this."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)  # code blocks
    text = re.sub(r"`([^`]+)`", r"\1", text)  # inline code
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)  # headers
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # bold
    text = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", text)  # italic
    text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [text](url)
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# The only real levers Kokoro exposes are speed and inter-sentence/clause
# pause length — no pitch, volume, or emphasis control exists in this
# engine. This is the whole personality layer's actual mechanism, not a
# simplification of a richer one: core/orchestrator.py's _classify_emotion
# derives one of these four from real signals in the turn (a denial, a
# tool error, a consequential action completing, or plain neutral), and
# this table is where that becomes an audible difference.
_EMOTION_PARAMS = {
    # (speed, sentence_pause, clause_pause)
    "neutral": (1.0, 0.25, 0.10),
    "confident": (1.05, 0.20, 0.08),  # a real action just completed — slightly brisker
    "concerned": (0.92, 0.35, 0.15),  # something failed or was denied — slower, more deliberate
    "serious": (0.90, 0.40, 0.18),  # a SENSITIVE/DESTRUCTIVE action awaits approval — most deliberate
}


def synthesize(text: str, emotion: str = "neutral") -> bytes:
    """Turn reply text into WAV audio bytes. emotion is one of
    core/orchestrator.py's _classify_emotion outputs; unrecognized values
    fall back to neutral rather than raising."""
    speed, sentence_pause, clause_pause = _EMOTION_PARAMS.get(emotion, _EMOTION_PARAMS["neutral"])
    kokoro = _get_kokoro()
    samples, sample_rate = kokoro.create(
        _strip_markdown(text),
        voice=VOICE,
        speed=speed,
        lang="en-us",
        sentence_pause=sentence_pause,
        clause_pause=clause_pause,
    )
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV")
    return buf.getvalue()
