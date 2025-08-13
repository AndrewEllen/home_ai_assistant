import time
from modules.facial_recognition.greetings import process_recognitions, start_face_recognition

def main():
    recognized_faces = []

    # Start facial recognition in background
    face_thread = start_face_recognition(recognized_faces)

    print("AI Assistant started. Waiting for recognitions...")

    try:
        while True:
            # Main AI loop — more tasks can go here
            process_recognitions(recognized_faces)
            # Other AI assistant logic...
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        face_thread.stop()
        face_thread.join()


if __name__ == "__main__":
    main()
