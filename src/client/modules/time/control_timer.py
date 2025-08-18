# modules/time/timer_manager.py
import re, time, threading
from typing import Optional
import platform, sys
import platform, sys, time
try:
    import simpleaudio as sa  # pip install simpleaudio
except Exception:
    sa = None
import math

def _ring_once():
    """Beep-beep pattern: 1.0 kHz then 1.4 kHz with short gaps."""
    if sa:
      def _beep(freq_hz: float, dur_s: float = 0.12, sr: int = 44100, glide: float = 1.03):
          n = int(sr * dur_s)
          samples = bytearray()
          for i in range(n):
              t = i / sr
              # tiny upward glide
              f = freq_hz * (1.0 + (glide - 1.0) * i / (n - 1))
              # add a bit of 2nd harmonic for "alarm" bite
              s = math.sin(2*math.pi*f*t) + 0.35 * math.sin(2*math.pi*2*f*t)
              # fast attack + exponential decay envelope
              attack = min(t / 0.01, 1.0)                 # ~10 ms attack
              env = attack * math.exp(-5.0 * t / dur_s)   # percussive decay
              v = int(32767 * 0.22 * s * env)
              samples += v.to_bytes(2, "little", signed=True)
          sa.play_buffer(bytes(samples), 1, 2, sr).wait_done()

      def play_timer_alarm():
          base = 720  # try 580–700 to taste
          for _ in range(8):
              _beep(base, 0.12); time.sleep(0.08)
              _beep(base, 0.12); time.sleep(0.08)
              _beep(base, 0.12); time.sleep(0.35)

      play_timer_alarm()

    elif platform.system() == "Windows":
        print("Windows Alarm")
        import winsound
        winsound.Beep(1000, 120); time.sleep(0.08)
        winsound.Beep(1400, 120); time.sleep(0.35)

    else:
        # Fallback: terminal bell twice
        sys.stdout.write('\a'); sys.stdout.flush(); time.sleep(0.08)
        sys.stdout.write('\a'); sys.stdout.flush(); time.sleep(0.35)


def _fmt_ms(ms: int) -> str:
    s = max(0, ms // 1000)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if h: parts.append(f"{h} hour{'s' if h!=1 else ''}")
    if m: parts.append(f"{m} minute{'s' if m!=1 else ''}")
    if s or not parts: parts.append(f"{s} second{'s' if s!=1 else ''}")
    return " ".join(parts)


