import asyncio, websockets, json, time, os
import numpy as np
from faster_whisper import WhisperModel
from modules.smart_devices.interpret_smart_command import execute_command
#                                                                  ^^^^^^^^^^^^^^

SECRET = "change_me"
SAMPLE_RATE = 16000
model = WhisperModel("medium.en", device="cpu", compute_type="int8", num_workers=os.cpu_count())

def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]"," ".join(str(x) for x in a), flush=True)

# ---- route client-side launches (raw utterance) ----
def _route_from_result(result: str, heard: str, room: str | None):
    if not isinstance(result, str):
        return None
    if not result.lower().startswith("route_client:"):
        return None
    rest = result.split(":", 1)[1].strip()           # e.g. "launch_app|Rocket League" or "clip"
    parts = rest.split("|", 1)
    act = parts[0].strip().lower()
    query = parts[1].strip() if len(parts) > 1 else ""
    return {
        "route": "client",
        "action": act,    # "launch_app" or "clip"
        "query": query,   # may be ""
        "heard": heard,
        "room": room,
        "skip_tts": False
    }

def _stt_blocking(pcm_bytes: bytes) -> str:
    if not pcm_bytes or len(pcm_bytes) < 3200:  # <100ms @16k
        return ""
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=True, temperature=0.0)
    return " ".join(s.text.strip() for s in segments).strip()

def _exec_blocking(text: str, room: str | None) -> str:
    return execute_command(text=text, room=room)

async def handler(ws):
    peer = getattr(ws, "remote_address", None)
    log("client connected:", peer)
    buf = bytearray()
    room = None
    try:
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                buf.extend(msg)
                continue

            if msg == "__end__":
                pcm = bytes(buf); buf = bytearray()
                log("end; bytes:", len(pcm), "room:", room)
                if not pcm:
                    await ws.send(json.dumps({"msg": "", "heard": "", "skip_tts": True}))
                    log("sent: empty (no pcm)"); continue

                try:
                    text = await asyncio.to_thread(_stt_blocking, pcm)
                except Exception as e:
                    err = f"stt_error: {e}"
                    await ws.send(json.dumps({"msg": err, "heard": "", "skip_tts": False}))
                    log(err); continue

                log("heard:", repr(text), "room:", room)
                if not text:
                    await ws.send(json.dumps({"msg": "", "heard": "", "skip_tts": True}))
                    log("sent: empty transcript (skip_tts)"); continue

                # ----------------------------------------------------

                # Single call decides everything (including routing)
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(_exec_blocking, text, room),
                        timeout=20
                    )
                except asyncio.TimeoutError:
                    result = "exec_error: timeout"
                except Exception as e:
                    result = f"exec_error: {e}"

                if not result:
                    await ws.send(json.dumps({"msg":"", "heard": text, "room": room, "skip_tts": True}))
                    log("sent: empty result"); continue

                routed = _route_from_result(result, text, room)
                if routed:
                    await ws.send(json.dumps(routed))
                    log("sent (to client):", routed)
                else:
                    payload = {"msg": result, "heard": text, "room": room, "skip_tts": False}
                    await ws.send(json.dumps(payload))
                    log("sent:", payload)
                continue


            # header
            try:
                hdr = json.loads(msg)
            except Exception:
                log("bad header"); await ws.close(code=4000, reason="bad header"); break
            if hdr.get("secret") != SECRET:
                log("auth fail"); await ws.close(code=4001, reason="auth"); break
            if hdr.get("type") != "utterance" or int(hdr.get("sr", SAMPLE_RATE)) != SAMPLE_RATE:
                log("bad type/sr"); await ws.close(code=4002, reason="bad sample rate or type"); break
            room = str(hdr.get("room") or "").strip() or None
            log("header ok; room:", room)
    except websockets.ConnectionClosed as e:
        log("closed:", peer, e.code, e.reason)
    except Exception as e:
        log("handler err:", repr(e))
    finally:
        log("disconnected:", peer)

async def main():
    log("server on 0.0.0.0:8765")
    async with websockets.serve(
        handler, "0.0.0.0", 8765, max_size=None, ping_interval=30, ping_timeout=15
    ):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
