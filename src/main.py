import time
from facial_recognition import FaceRecognitionThread

def main():
    # Shared list between threads
    recognized_faces = []

    # Start face recognition in background
    face_thread = FaceRecognitionThread(recognized_faces)
    face_thread.start()

    print("AI Assistant started. Waiting for recognitions...")

    last_seen = {}

    try:
        while True:
            if recognized_faces:
                for name, sim in recognized_faces:
                    if name != "unknown":
                        # Prevent spamming the same greeting
                        now = time.time()
                        if name not in last_seen or now - last_seen[name] > 5:
                            print(f"Welcome Home, {name} (confidence {sim:.2f})")
                            last_seen[name] = now
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("Stopping...")
        face_thread.stop()
        face_thread.join()

if __name__ == "__main__":
    main()
