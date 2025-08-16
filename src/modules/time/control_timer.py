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

class TimerManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._t: Optional[threading.Thread] = None
        self._end_ms: Optional[int] = None
        self._stop = threading.Event()
        self._beep_stop = threading.Event()

    def _now_ms(self) -> int:
        return int(time.monotonic() * 1000)

    def _ring_loop(self):
      # ring up to 5s or until stopped
      t_end = self._now_ms() + 5000
      while not self._beep_stop.is_set() and self._now_ms() < t_end:
          _ring_once()
          time.sleep(0.3)

    def is_ringing(self) -> bool:
        # True while the ring loop is allowed to run
        return not self._beep_stop.is_set()


    def _runner(self, duration_ms: int):
      deadline = self._now_ms() + duration_ms
      with self._lock:
          self._end_ms = deadline
      while not self._stop.is_set():
          if deadline - self._now_ms() <= 0:
              break
          time.sleep(0.2)

      if not self._stop.is_set():
          self._beep_stop.clear()       # enable ringing
          self._ring_loop()

      # cleanup
      with self._lock:
          self._t = None
          self._end_ms = None
          self._stop.clear()
          self._beep_stop.set()         # disable ringing


    def set_timer_ms(self, duration_ms: int) -> str:
        if duration_ms <= 0:
            return "Timer duration must be positive."
        self.stop_timer()  # replace existing
        self._stop.clear()
        self._beep_stop.set()
        th = threading.Thread(target=self._runner, args=(duration_ms,), daemon=True)
        self._t = th
        th.start()
        return f"Timer set for {_fmt_ms(duration_ms)}."

    def time_left(self) -> str:
        with self._lock:
            if self._end_ms is None:
                return "No active timer."
            left = self._end_ms - self._now_ms()
        if left <= 0:
            return "Timer has finished."
        return f"{_fmt_ms(left)} remaining."

    def stop_timer(self) -> str:
        with self._lock:
            if self._t is None and not self.is_ringing():
                return "No active timer."
            self._stop.set()
            self._beep_stop.set()  # stop any ringing
        return "Timer stopped."


# ---- simple NLP helpers ----
_DURATION_RE = re.compile(
    r"(?:(\d+)\s*h(?:ours?)?)?\s*(?:(\d+)\s*m(?:in(?:utes?)?)?)?\s*(?:(\d+)\s*s(?:ec(?:onds?)?)?)?",
    re.I,
)
_IN_RE = re.compile(r"\b(?:in|for)\b", re.I)

def parse_duration_ms(text: str) -> Optional[int]:
    t = text.lower()

    # quick unit typo normalisation
    t = re.sub(r"\bsec?n?d?s?\b", "seconds", t)   # sec, secs, secnds, second(s)
    t = re.sub(r"\bmins?\b", "minutes", t)        # min, mins
    t = re.sub(r"\bhrs?\b", "hours", t)           # hr, hrs

    # number words → int
    ONES = {
        "zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,
        "ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,"fifteen":15,
        "sixteen":16,"seventeen":17,"eighteen":18,"nineteen":19,
        "a":1,"an":1
    }
    TENS = {"twenty":20,"thirty":30,"forty":40,"fifty":50,"sixty":60,"seventy":70,"eighty":80,"ninety":90}

    def _words_to_int(s: str) -> Optional[int]:
        s = s.replace("-", " ")
        parts = [p for p in s.split() if p]
        if not parts: return None
        total = 0
        i = 0
        while i < len(parts):
            w = parts[i]
            if w in ONES:
                total += ONES[w]; i += 1; continue
            if w in TENS:
                val = TENS[w]; i += 1
                if i < len(parts) and parts[i] in ONES and ONES[parts[i]] < 10:
                    val += ONES[parts[i]]; i += 1
                total += val; continue
            if w == "hundred":
                total = max(1,total) * 100; i += 1; continue
            return None
        return total

    # match (number | number-words) + unit, in any order, multiple segments
    pattern = re.compile(
        r"(?P<num>\d+|(?:a|an|zero|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
        r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[-\s](?:one|two|three|four|five|six|seven|eight|nine))?(?:\s+hundred)?)"
        r"\s*(?P<unit>hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b",
        re.I,
    )

    h = m = s = 0
    for mobj in pattern.finditer(t):
        raw_num = mobj.group("num").lower()
        unit = mobj.group("unit").lower()

        if raw_num.isdigit():
            num = int(raw_num)
        else:
            num = _words_to_int(raw_num)
            if num is None:
                continue

        if unit.startswith(("h","hr")):
            h += num
        elif unit.startswith(("m","min")):
            m += num
        else:
            s += num

    total_ms = (h*3600 + m*60 + s) * 1000
    return total_ms if total_ms > 0 else None



# Singleton
TIMER = TimerManager()

def handle_timer_intent(msg: str) -> Optional[str]:
    t = msg.lower().strip()

    if "set" in t and "timer" in t and _IN_RE.search(t):
        dur = parse_duration_ms(t)
        return TIMER.set_timer_ms(dur) if dur else "I couldn't parse the timer duration."

    if "how long" in t and "timer" in t:
        return TIMER.time_left()

    # stop if explicitly mentions timer OR if currently ringing
    if ("stop" in t or "cancel" in t) and ("timer" in t or TIMER.is_ringing()):
        return TIMER.stop_timer()

    return None

