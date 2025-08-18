import keyboard
import time

def make_clip():
    # Trigger your custom clip hotkey
    keyboard.press_and_release("ctrl+shift+s")

# Example standalone test
if __name__ == "__main__":
    print("Clipping in 3s...")
    time.sleep(3)
    make_clip()
    print("Clip command sent.")
