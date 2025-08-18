import os
import time
import wave
import threading
from pathlib import Path

try:
    import simpleaudio as audio
except Exception:
    audio = None  # playback disabled if not available

from piper import PiperVoice

MODEL_BASENAME = "en_GB-alba-medium.onnx"

def _resolve_model_path() -> str:
    # 1) Env var wins
    env = os.getenv("PIPER_MODEL_PATH")
    if env and Path(env).expanduser().exists():
        return str(Path(env).expanduser())

    here = Path(__file__).resolve()

    # Find project root that has a "src" dir
    root = None
    for p in here.parents:
        if (p / "src").is_dir():
            root = p
            break

    candidates = [
        # from this module: src/client/modules/voice_synth/ → src/client/assets/
        here.parents[2] / "assets" / MODEL_BASENAME,            # src/client/assets
        # explicit root-based fallbacks
        root / "src" / "client" / "assets" / MODEL_BASENAME if root else None,
        root / "src" / "assets" / MODEL_BASENAME if root else None,
        # cwd-based fallback
        Path.cwd() / "src" / "client" / "assets" / MODEL_BASENAME,
    ]

    for c in filter(None, candidates):
        if c.exists():
            return str(c)

    tried = " | ".join(str(c) for c in candidates if c is not None)
    raise FileNotFoundError(
        f"Piper model not found as {MODEL_BASENAME}. "
        f"Set PIPER_MODEL_PATH or place it under src/client/assets/. Tried: {tried}"
    )


MODEL_PATH = _resolve_model_path()
_voice = PiperVoice.load(MODEL_PATH)

_audio_dir = (Path(__file__).resolve().parent / "temp_audio")
_audio_dir.mkdir(parents=True, exist_ok=True)

def speak(message: str) -> str:
    """Synthesize and (if available) play speech. Returns WAV path."""
    filename = _audio_dir / f"tts_{int(time.time()*1000)}.wav"
    # synthesize
    with wave.open(str(filename), "wb") as f:
        _voice.synthesize_wav(message, f)
    # play if simpleaudio present
    if audio is not None:
        try:
            wave_obj = audio.WaveObject.from_wave_file(str(filename))
            play_obj = wave_obj.play()
            play_obj.wait_done()
        except Exception:
            pass
    return str(filename)

def speak_async(message: str) -> None:
    threading.Thread(target=speak, args=(message,), daemon=True).start()
