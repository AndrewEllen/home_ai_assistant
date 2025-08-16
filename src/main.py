import time
from modules.facial_recognition.greetings import process_recognitions, start_face_recognition
from modules.smart_devices import *
from modules.voice_recognition import start_voice_commands
import sounddevice as sd
from sounddevice import PortAudioError
from modules.smart_devices.interpret_smart_command import execute_command
import re
from modules.smart_devices.interpret_smart_command import execute_command

#Hardcoded for now, hopefully in future can be taken from microphone location
ROOM_COMMAND_GIVEN = "office"

WAKE_PHRASE = "hey sharon"
_last_command_time = 0
_WAKE_WINDOW = 3  # seconds

def on_voice_command(text: str):
    global _last_command_time
    cleaned = re.sub(r"[^\w\s]", "", text).lower()
    now = time.time()

    # inside wake window → run directly
    #if now - _last_command_time <= _WAKE_WINDOW:
    #    cmd = cleaned.strip()
    #    if cmd:
    #        print("\nVOICE:", text)
    #        result = execute_command(cmd)
    #        if result:
    #            print(result)
    #            #speak_async(result)
    #    _last_command_time = now
    #    return
    
    # otherwise require wake phrase
    idx = cleaned.find(WAKE_PHRASE)
    if idx != -1:
        cmd = cleaned[idx + len(WAKE_PHRASE):].strip()
        if cmd:
            print("\nVOICE:", text)
            result = execute_command(text=cmd, room=ROOM_COMMAND_GIVEN)
            if result:
                print(result)
                speak_async(result)
            _last_command_time = now


def main():
    recognized_faces = []

    mic_index = 1
    try:
        info = sd.query_devices(mic_index)
        sr = int(info["default_samplerate"]) or 16000
    except (PortAudioError, ValueError, KeyError):
        mic_index = None
        sr = 16000  # safe for VAD

    # Explicitly input-only device to avoid WDM sync issues on Windows
    device = (mic_index, None) if isinstance(mic_index, int) else None

    voice_thread = start_voice_commands(
        handler=on_voice_command,
        device=device,
        sample_rate=sr,
        model_name="large-v3"  # change to medium.en if you want faster but slightly less accurate
    )

    face_thread = start_face_recognition(recognized_faces)
    start_console_command_listener(room=ROOM_COMMAND_GIVEN)

    print("AI Assistant started. Waiting for recognitions...")

    try:
        while True:
            process_recognitions(recognized_faces)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        print("Stopped")
        voice_thread.stop()
        voice_thread.join()
        face_thread.stop()
        face_thread.join()


def main_small():
    
    start_console_command_listener(room=ROOM_COMMAND_GIVEN)

    while True:
        time.sleep(0.1)



if __name__ == "__main__":
    main_small()
