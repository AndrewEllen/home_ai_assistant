# modules/smart_devices/interpreter.py
import json, re, threading, difflib
from pathlib import Path
from typing import Optional, Tuple, List
from .control_smart_devices import (
    light_set, light_toggle, light_brightness, light_brightness_step,
    light_temp_named, light_color, list_devices, _find_file
)

# ---- load devices ----
DEVICES_JSON_PATH: Path | None = _find_file("devices.json")
if not DEVICES_JSON_PATH:
    raise FileNotFoundError("devices.json not found. Set SMART_DEVICES_DIR or place it in project root.")
with DEVICES_JSON_PATH.open("r", encoding="utf-8") as f:
    _DEVICES = json.load(f)

_DEVICE_NAMES: List[str] = [d.get("name", "") for d in _DEVICES if d.get("name")]
_DEVICE_TOKENS = {name: set(re.sub(r"[^a-z0-9 ]+", "", name.lower()).split()) for name in _DEVICE_NAMES}

# ---- vocab ----
_ON_WORDS = {"on", "enable", "start", "power on"}
_OFF_WORDS = {"off", "disable", "stop", "power off", "shutdown"}
_TOGGLE_WORDS = {"toggle", "switch"}
_BRIGHTER = {"brighter", "increase", "up", "raise", "higher", "brighten"}
_DIMMER = {"dimmer", "decrease", "down", "lower", "dim"}
_STATUS = {"status", "state", "is it", "what is", "what's"}
_ALL_WORDS = {"all", "everything"}
_ROOM_HINTS = {"room", "bedroom", "kitchen", "office", "hall", "hallway", "living", "lounge", "bathroom"}
# only RGB-like colors here, NO "white" or temp words
_COLOR_WORDS = {"red","green","blue","yellow","purple","pink","orange","cyan","magenta","turquoise"}
_MAX_WORDS = {"max","full","100"}
_MIN_WORDS = {"min","minimum","0","zero"}

_GENERIC_TOKENS = {"light", "lights", "lamp"}
_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")

# ---- helpers ----
def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9 #%]", "", s.lower()).strip()

def _contains_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None

def _extract_int(text: str) -> Optional[int]:
    m = re.search(r"\b(\d{1,3})\b", text)
    return int(m.group(1)) if m else None

def _extract_brightness(text: str) -> Optional[int]:
    if any(_contains_word(text, w) for w in _MAX_WORDS):
        return 100
    if any(_contains_word(text, w) for w in _MIN_WORDS):
        return 0
    m = re.search(r"(\d{1,3})\s*%?", text)
    if not m:
        return None
    return max(0, min(100, int(m.group(1))))

def _has_color(text: str) -> Optional[str]:
    h = _HEX_RE.search(text)
    if h:
        return h.group(0)
    for c in sorted(_COLOR_WORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(c)}\b", text):
            return c
    return None

def _best_devices_from_tokens(qt: set[str]) -> List[str]:
    if qt & _ALL_WORDS:
        return list(_DEVICE_NAMES)

    room_tokens = qt & _ROOM_HINTS
    qsig = {t for t in qt if t not in _GENERIC_TOKENS}

    candidates = {
        name: toks for name, toks in _DEVICE_TOKENS.items()
        if not room_tokens or (toks & room_tokens)
    }

    def score(tokens: set[str]) -> float:
        sig = {t for t in tokens if t not in _GENERIC_TOKENS}
        inter = len(sig & qsig)
        if inter == 0:
            return 0.0
        return inter / max(1, len(sig))

    scored = sorted(((score(tokens), name) for name, tokens in candidates.items()), reverse=True)
    hits = [name for s, name in scored if s >= 0.67]
    if hits:
        return hits
    if room_tokens:
        hits = [name for s, name in scored if s >= 0.5]
        if hits:
            return hits
    return []

def _best_device_freeform(query: str) -> List[str]:
    qt = set(_normalize(query).split())
    if not qt or not _DEVICE_TOKENS:
        return []
    hits = _best_devices_from_tokens(qt)
    if hits:
        return hits

    qn = " ".join(qt)
    if len(qn) >= 5:
        for name in _DEVICE_NAMES:
            if _normalize(name) in qn or qn in _normalize(name):
                return [name]
    m = difflib.get_close_matches(" ".join(qt), _DEVICE_NAMES, n=1, cutoff=0.7)
    return m if m else []

def _extract_targets(text: str) -> List[str]:
    stripped = re.sub(r"\b(turn|set|switch|the|my|in|to|at|please|a|an|by|of)\b", " ", text)
    stripped = re.sub(r"\b(on|off|toggle|brighter|dimmer|increase|decrease|up|down|lower|raise|brighten)\b", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    targets = _best_device_freeform(stripped)
    if not targets and len(_DEVICE_NAMES) == 1:
        return _DEVICE_NAMES[:]
    return targets

def _extract_delta(text: str) -> int:
    n = _extract_int(text)
    if n is None:
        return 10
    return max(1, min(100, n))

def _filter_online(targets: List[str]) -> List[str]:
    try:
        known = list_devices()
        return [d for d in targets if known.get(d.lower(), {}).get("ip")]
    except Exception:
        return targets

# ---- parser ----
def parse_command(text: str) -> Tuple[str, Optional[int | str], List[str]]:
    t = _normalize(text)

    if any(_contains_word(t, w) for w in _STATUS):
        return "status", None, _extract_targets(t)

    if re.search(r"\b(turn|switch)\s+on\b", t):
        return "on", None, _extract_targets(t)
    if re.search(r"\b(turn|switch)\s+off\b", t):
        return "off", None, _extract_targets(t)

    # white and temperature presets
    if _contains_word(t, "white"):
        return "temp_named", "neutral", _extract_targets(t)
    if _contains_word(t, "warm") or _contains_word(t, "cool") or _contains_word(t, "daylight") or _contains_word(t, "neutral"):
        preset = "warm" if _contains_word(t, "warm") else "cool" if _contains_word(t, "cool") else "daylight" if _contains_word(t, "daylight") else "neutral"
        return "temp_named", preset, _extract_targets(t)

    # RGB colors or hex
    color = _has_color(t)
    if color:
        return "color", color, _extract_targets(t)

    if any(_contains_word(t, w) for w in _TOGGLE_WORDS):
        return "toggle", None, _extract_targets(t)
    if any(_contains_word(t, w) for w in _OFF_WORDS) and not any(_contains_word(t, w) for w in _ON_WORDS):
        return "off", None, _extract_targets(t)
    if any(_contains_word(t, w) for w in _ON_WORDS) and not any(_contains_word(t, w) for w in _OFF_WORDS):
        return "on", None, _extract_targets(t)

    if "%" in t or re.search(r"\b\d{1,3}\b", t):
        lvl = _extract_brightness(t)
        if lvl is not None:
            return "brightness", lvl, _extract_targets(t)

    if any(_contains_word(t, w) for w in (_BRIGHTER | _DIMMER)):
        delta = _extract_delta(t)
        return ("brightness_up" if any(_contains_word(t, w) for w in _BRIGHTER) else "brightness_down"), delta, _extract_targets(t)

    return "toggle", None, _extract_targets(t)

# ---- executor ----
def _ensure_targets(targets: List[str]) -> List[str]:
    if targets:
        return targets
    return []

def _exec_each(targets: List[str], fn):
    outputs = []
    for dev in targets:
        try:
            msg = fn(dev)
        except Exception as e:
            msg = f"Error: {e}"
        outputs.append(f"{dev}: {msg}")
    return "\n".join(outputs) if outputs else "No matching device."

def execute_command(text: str) -> str:
    action, value, targets = parse_command(text)
    targets = _ensure_targets(targets)

    if not targets:
        targets = _best_device_freeform(text)
    if not targets:
        return "No matching device."

    targets = _filter_online(targets)
    if not targets:
        return "No matching device."

    if action == "on":
        return _exec_each(targets, lambda d: (light_set(d, True) or "on"))
    if action == "off":
        return _exec_each(targets, lambda d: (light_set(d, False) or "off"))
    if action == "toggle":
        return _exec_each(targets, lambda d: (light_toggle(d) or "toggled"))
    if action == "brightness":
        lvl = int(value) if isinstance(value, int) else 50
        return _exec_each(targets, lambda d: (light_brightness(d, lvl) or f"{lvl}%"))
    if action == "brightness_up":
        delta = int(value) if isinstance(value, int) else 10
        return _exec_each(targets, lambda d: (light_brightness_step(d, +delta) or f"+{delta}%"))
    if action == "brightness_down":
        delta = int(value) if isinstance(value, int) else 10
        return _exec_each(targets, lambda d: (light_brightness_step(d, -delta) or f"-{delta}%"))
    if action == "color":
        col = str(value)
        return _exec_each(targets, lambda d: (light_color(d, col) or f"color {col}"))
    if action == "temp_named":
        preset = str(value)
        return _exec_each(targets, lambda d: (light_temp_named(d, preset) or f"temp {preset}"))
    if action == "status":
        known = list_devices()
        resp = []
        for d in targets:
            if d.lower() in known:
                info = known[d.lower()]
                resp.append(f"{info['name']}: ip={info.get('ip') or 'unknown'}")
            else:
                resp.append(f"{d}: unknown")
        return "\n".join(resp)

    return "Unknown action."

# ---- console ----
def start_console_command_listener() -> threading.Thread:
    def _loop():
        while True:
            try:
                text = input("> ").strip()
                if text:
                    print(execute_command(text))
            except (EOFError, KeyboardInterrupt):
                break
    th = threading.Thread(target=_loop, daemon=True)
    th.start()
    return th
