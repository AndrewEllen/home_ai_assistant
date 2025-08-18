# win_client.py
# Wake word on Windows → chime → record until silence → send PCM to Mac
import time, json, queue, sys, os, re, asyncio
import sounddevice as sd
from vosk import Model, KaldiRecognizer
import websockets, webrtcvad
import numpy as np

# ---- optional chime (install: pip install simpleaudio) ----
try:
    import simpleaudio as sa
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
MODEL_DIR = r"C:\Projects\home_ai_assistant\src\assets\vosk-model-small-en-us-0.15"
SR = 16000
BLOCK = 1600  # 100 ms
WAKE = "test"
DEBOUNCE_S = 1.5
WS_URI = "ws://192.168.1.97:8765"  # Mac IP
SECRET = "change_me"

def norm(s): return re.sub(r"[^a-z ]", " ", s.lower()).strip()

async def send_pcm(pcm_bytes: bytes, sr: int = SR):
    hdr = {"type":"utterance","sr":sr,"secret":SECRET,"host":os.environ.get("COMPUTERNAME","windows")}
    async with websockets.connect(WS_URI, max_size=None) as ws:
        await ws.send(json.dumps(hdr))
        await ws.send(pcm_bytes)     # binary frame
        await ws.send("__end__")     # terminator
        resp = await ws.recv()
        print("Mac transcript:", resp)

def record_until_silence(stream_q: queue.Queue, vad: webrtcvad.Vad, pre_ms=500, max_ms=8000, tail_ms=800):
    # include short preroll so words aren’t clipped
    pcm = bytearray()
    for _ in range(pre_ms // 100):
        pcm.extend(stream_q.get())

    silent_ms = 0
    total_ms = 0
    step = int(0.02 * SR)  # 20 ms for VAD

    while total_ms < max_ms:
        b = stream_q.get()
        pcm.extend(b)
        total_ms += 100

        arr = np.frombuffer(b, dtype=np.int16)
        voiced = False
        for i in range(0, len(arr), step):
            chunk = arr[i:i+step]
            if len(chunk) != step: break
            if vad.is_speech(chunk.tobytes(), sample_rate=SR):
                voiced = True
                break

        if voiced:
            silent_ms = 0
        else:
            silent_ms += 100
            if silent_ms >= tail_ms:
                break

    return bytes(pcm)

def main():
    if not os.path.isdir(MODEL_DIR):
        print("Model not found"); sys.exit(1)

    model = Model(MODEL_DIR)
    rec = KaldiRecognizer(model, SR)
    rec.SetWords(True)

    q = queue.Queue(maxsize=50)
    vad = webrtcvad.Vad(2)  # 0=loose..3=strict

    def cb(indata, frames, t, status):
        if status: return
        b = bytes(indata)
        try: q.put_nowait(b)
        except queue.Full:
            try: q.get_nowait()
            except queue.Empty: pass
            q.put_nowait(b)

    last_fire = 0.0
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=BLOCK, callback=cb):
        print("Listening for wake word:", WAKE)
        while True:
            b = q.get()
            if rec.AcceptWaveform(b):
                txt = norm(json.loads(rec.Result()).get("text",""))
                if WAKE in txt and time.time() - last_fire > DEBOUNCE_S:
                    last_fire = time.time()
                    play_chime()  # wake heard → ready to speak
                    utter = record_until_silence(q, vad)
                    asyncio.run(send_pcm(utter))
            else:
                ptxt = norm(json.loads(rec.PartialResult()).get("partial",""))
                if WAKE in ptxt and time.time() - last_fire > DEBOUNCE_S:
                    last_fire = time.time()
                    play_chime()  # wake heard → ready to speak
                    utter = record_until_silence(q, vad)
                    asyncio.run(send_pcm(utter))

if __name__ == "__main__":
    main()
