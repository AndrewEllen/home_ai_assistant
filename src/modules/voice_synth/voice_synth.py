import os
import time
import wave
import threading
from pathlib import Path
import simpleaudio as audio
from piper import PiperVoice

MODEL_PATH = os.getenv(
    "PIPER_MODEL_PATH",
    "C:/Projects/home_ai_assistant/src/assets/en_GB-alba-medium.onnx",
)

_voice = PiperVoice.load(MODEL_PATH)
_audio_dir = Path("temp_audio")
_audio_dir.mkdir(parents=True, exist_ok=True)


def speak(message: str) -> str:
    filename = _audio_dir / f"tts_{int(time.time() * 1000)}.wav"
    with wave.open(str(filename), "wb") as f:
        _voice.synthesize_wav(message, f)
    wave_obj = audio.WaveObject.from_wave_file(str(filename))
    play_obj = wave_obj.play()
    play_obj.wait_done()
    return str(filename)


def speak_async(message: str) -> None:
    threading.Thread(target=speak, args=(message,), daemon=True).start()
