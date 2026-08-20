"""
ORION's speech-to-text: faster-whisper.

The only job here is turning recorded audio into text. That text then
goes through the exact same Orchestrator.chat() path a typed message
does — voice never bypasses the tool-calling loop or permission tiers
typed input goes through (see api.py's /chat/voice).
"""

import io

from faster_whisper import WhisperModel

# "base" balances accuracy against staying light enough to run
# alongside the LLM on an 8GB card without real VRAM contention —
# int8 on CPU so it doesn't compete for GPU memory at all.
MODEL_SIZE = "base"

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def preload() -> None:
    """Load the model at startup rather than on the first real request,
    so the first voice interaction isn't the slowest one."""
    _get_model()


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe recorded audio (any container faster-whisper's av-based
    decoder handles, e.g. the webm/opus a browser's MediaRecorder produces)
    into plain text."""
    model = _get_model()
    segments, _info = model.transcribe(io.BytesIO(audio_bytes))
    return " ".join(segment.text.strip() for segment in segments).strip()
