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


def synthesize(text: str) -> bytes:
    """Turn reply text into WAV audio bytes."""
    kokoro = _get_kokoro()
    samples, sample_rate = kokoro.create(text, voice=VOICE, speed=1.0, lang="en-us")
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV")
    return buf.getvalue()
