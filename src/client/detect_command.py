# Wake word on Windows → chime → record until silence → send PCM to Mac
import time, json, queue, sys, os, re, asyncio
import sounddevice as sd
from vosk import Model, KaldiRecognizer
import websockets, webrtcvad
import numpy as np
from pathlib import Path
from modules.voice_synth.voice_synth import speak_async
from modules.application_control.open_games import launch_game_by_name
from modules.application_control.game_clip import make_clip


# ---- optional chime (pip install simpleaudio) ----
try:
    import simpleaudio as sa  # type: ignore
except Exception:
    sa = None

def make_chime(sr=24000):
    def tone(freq, dur, amp=0.12):
        n = int(sr * dur)
        t = np.arange(n, dtype=np.float32) / sr
        w = 0.5 - 0.5 * np.cos(2*np.pi*np.arange(n)/max(n-1,1))
        s = np.sin(2*np.pi*freq*t) * w * amp
        return (s * 32767).astype(np.int16)
    t1 = tone(600, 0.09)
    gap = np.zeros(int(sr*0.04), dtype=np.int16)
    t2 = tone(800, 0.12)
    data = np.concatenate([t1, gap, t2])
    return data.tobytes(), sr

_CHIME, _CHIME_SR = make_chime()
def play_chime():
    if sa is None:
        return
    try:
        sa.play_buffer(_CHIME, 1, 2, _CHIME_SR)  # non-blocking
    except Exception:
        pass

# ---- config ----
MODEL_DIR = str(Path(__file__).resolve().parent / "assets" / "vosk-model-small-en-us-0.15")
SR = 16000
BLOCK = 1600
WAKE = "jarvis"
DEBOUNCE_S = 1.5
WS_URI = "ws://192.168.1.97:8765"  # Mac IP:port
SECRET = "change_me"
ROOM = "office"  # set per-PC location

def norm(s: str) -> str:
    return re.sub(r"[^a-z ]", " ", s.lower()).strip()

# ---- launch helper ----

def _handle_clip():
    make_clip()
    speak_async("Clipped.")

def _handle_launch_game(query: str):
    # Call the launcher and speak ONLY the result from that function.
    print("Printing Query")
    print(query)
    spoken = launch_game_by_name(query)
    print(spoken)
    if not spoken:
        spoken = f"Couldn't find '{query}'"
    print(f"[client] launch_game -> {spoken}")
    speak_async(spoken)

# ---- handle payloads from server (supports structured + legacy) ----
def _maybe_handle_legacy_route(msg: str) -> bool:
    """
    Legacy text protocol: "route_client: launch_app|<query>" or "route_client: launch_game|<query>"
    Returns True if handled.
    """
    if not isinstance(msg, str):
        return False
    if not msg.lower().startswith("route_client:"):
        return False
    rest = msg.split(":", 1)[1].strip()  # "launch_app|Rocket League"
    if not rest:
        return False
    if "|" in rest:
        act, query = rest.split("|", 1)
    else:
        act, query = rest, ""
    act = act.strip().lower()
    query = query.strip()
    if act in ("launch_app", "launch_game"):
        _handle_launch_game(query or "")
        return True
    if act == "clip":
        _handle_clip()
        return True
    return False

def handle_routed_action_or_msg(payload: dict) -> None:
    """
    Priority:
      1) Structured route: {"route":"client","action":"launch_game","query":...}
      2) Legacy msg: "route_client: launch_app|<query>"
      3) Otherwise, speak payload.msg unless skip_tts
    """
    # 1) Structured route
    if str(payload.get("route") or "").lower() == "client":
        action = str(payload.get("action") or "").lower()
        if action in ("launch_game", "launch_app"):
            _handle_launch_game(payload.get("query", "") or "")
            return
        if action == "clip":
            _handle_clip()
            return

    # 2) Legacy route encoded in msg
    msg = payload.get("msg")
    if isinstance(msg, str) and _maybe_handle_legacy_route(msg):
        return

    # 3) Normal say-path
    if not payload.get("skip_tts"):
        if isinstance(msg, str) and msg.strip():
            print(f"[client] say -> {msg}")
            speak_async(msg)

async def send_pcm(pcm_bytes: bytes, sr: int = SR):
    if not pcm_bytes:
        return

    hdr = {
        "type": "utterance",
        "sr": sr,
        "secret": SECRET,
        "host": os.environ.get("COMPUTERNAME","windows"),
        "room": ROOM,
    }

    async with websockets.connect(WS_URI, max_size=None, ping_interval=30, ping_timeout=15) as ws:
        await ws.send(json.dumps(hdr))
        await ws.send(pcm_bytes)
        await ws.send("__end__")
        raw = await ws.recv()

    # Parse response
    try:
        payload = json.loads(raw)
    except Exception:
        print("Mac reply (non-JSON):", raw)
        speak_async(str(raw))
        return

    handle_routed_action_or_msg(payload)

def record_until_silence(stream_q: queue.Queue, vad: webrtcvad.Vad,
                         pre_ms=500, max_ms=8000, tail_ms=800, min_voiced_ms=200) -> bytes:
    pcm = bytearray()
    # preroll
    for _ in range(pre_ms // 100):
        pcm.extend(stream_q.get())

    silent_ms = 0
    total_ms = 0
    voiced_ms = 0
    step = int(0.02 * SR)  # 20 ms

    while total_ms < max_ms:
        b = stream_q.get()
        pcm.extend(b)
        total_ms += 100

        arr = np.frombuffer(b, dtype=np.int16)
        voiced = False
        for i in range(0, len(arr), step):
            chunk = arr[i:i+step]
            if len(chunk) != step:
                break
            if vad.is_speech(chunk.tobytes(), sample_rate=SR):
                voiced = True
                voiced_ms += 20
                break

        if voiced:
            silent_ms = 0
        else:
            silent_ms += 100
            if silent_ms >= tail_ms:
                break

    if voiced_ms < min_voiced_ms:
        return b""
    return bytes(pcm)

def drain_queue(q: queue.Queue):
    try:
        while True:
            q.get_nowait()
    except Exception:
        pass

def main():
    if not os.path.isdir(MODEL_DIR):
        print("Model not found:", MODEL_DIR)
        sys.exit(1)

    model = Model(MODEL_DIR)
    rec = KaldiRecognizer(model, SR)
    rec.SetWords(True)

    q = queue.Queue(maxsize=50)
    vad = webrtcvad.Vad(2)  # 0=loose..3=strict

    def cb(indata, frames, t, status):
        if status:
            return
        b = bytes(indata)
        try:
            q.put_nowait(b)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            q.put_nowait(b)

    last_fire = 0.0
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=BLOCK, callback=cb):
        print(f"Listening for wake word: {WAKE}  (room={ROOM})")
        while True:
            b = q.get()
            if rec.AcceptWaveform(b):
                txt = norm(json.loads(rec.Result()).get("text", ""))
                if WAKE in txt and time.time() - last_fire > DEBOUNCE_S:
                    last_fire = time.time()
                    play_chime()
                    utter = record_until_silence(q, vad)
                    asyncio.run(send_pcm(utter))
                    drain_queue(q)
                    time.sleep(0.25)
                    last_fire = time.time()
            else:
                ptxt = norm(json.loads(rec.PartialResult()).get("partial", ""))
                if WAKE in ptxt and time.time() - last_fire > DEBOUNCE_S:
                    last_fire = time.time()
                    play_chime()
                    utter = record_until_silence(q, vad)
                    asyncio.run(send_pcm(utter))
                    drain_queue(q)
                    time.sleep(0.25)
                    last_fire = time.time()

if __name__ == "__main__":
    main()
