import time
import wave
import simpleaudio as audio
from piper import PiperVoice
from .facial_recognition import FaceRecognitionThread

MY_NAME = "andrew"

voice = PiperVoice.load("C:/Projects/home_ai_assistant/src/assets/en_GB-alba-medium.onnx")

# cooldowns in seconds
COOLDOWN = {
    "andrew_alone": 60,
    "andrew_with_few": 60,
    "andrew_with_many": 60,
    "known_only_few": 60,
    "known_only_many": 60,
    "generic": 30,
}

GLOBAL_COOLDOWN = 60  # minimum gap between any "Welcome" message

last_fired = {}        # msg_type -> last_time
last_any_greeting = 0  # last time *any* greeting was spoken


def format_names(names):
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def build_message(current_names):
    known = sorted(n for n in current_names if n != "unknown")
    unknown_count = sum(1 for n in current_names if n == "unknown")
    total = len(current_names)
    has_andrew = MY_NAME in known
    others = [n for n in known if n != MY_NAME]

    if has_andrew:
        if total == 1:
            return "andrew_alone", f"Welcome home, {MY_NAME}."
        elif total > 3:
            return "andrew_with_many", f"Welcome home, {MY_NAME} — and guests."
        else:
            parts = []
            if others:
                parts.append(f"welcome {format_names(others)}")
            if unknown_count:
                parts.append(f"and {unknown_count} guest" + ("s" if unknown_count > 1 else ""))
            tail = " and ".join(parts) if parts else "welcome"
            return "andrew_with_few", f"Welcome home, {MY_NAME} — {tail}."

    if known:
        if len(known) > 3:
            return "known_only_many", "Welcome, everyone."
        else:
            return "known_only_few", f"Welcome, {format_names(known)}."

    return "generic", "Welcome."


def process_recognitions(recognized_faces):
    """Called every loop iteration. Prints greeting if cooldowns allow."""
    global last_fired, last_any_greeting
    if not recognized_faces:
        return

    names_now = {name for name, _ in recognized_faces}
    msg_type, msg = build_message(names_now)

    now = time.time()
    type_cd = COOLDOWN.get(msg_type, 60)

    if (now - last_any_greeting >= GLOBAL_COOLDOWN
            and now - last_fired.get(msg_type, 0) >= type_cd):
        print(msg)
        last_fired[msg_type] = now
        last_any_greeting = now
        with wave.open("temp_audio/tts.wav", "wb") as wav_file:
            voice.synthesize_wav(msg, wav_file)
        wave_obj = audio.WaveObject.from_wave_file("temp_audio/tts.wav")
        play_obj = wave_obj.play()
        play_obj.wait_done()


def start_face_recognition(recognized_faces):
    """Starts background face recognition thread."""
    face_thread = FaceRecognitionThread(recognized_faces)
    face_thread.start()
    return face_thread
