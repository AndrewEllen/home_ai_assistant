# main.py
import asyncio, threading, os
from pystray import Icon, MenuItem, Menu
from PIL import Image
import detect_command as client  # has async main()

def _on_quit(icon, item):
    icon.stop()
    os._exit(0)  # simple, reliable exit

def run_tray():
    # use .ico if you want consistency, but .png works for tray
    img = Image.open("assets/icon.png")
    menu = Menu(MenuItem("Quit", _on_quit))
    Icon("jarvis", img, "Jarvis Assistant", menu).run()

if __name__ == "__main__":
    threading.Thread(target=run_tray, daemon=True).start()
    asyncio.run(client.main())
