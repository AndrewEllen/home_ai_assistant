# modules/smart_devices/interpret_smart_command.py
import json, re, threading, difflib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from .control_smart_devices import (
    light_on, light_off, light_toggle, light_color, _find_file, light_brightness
)

# ------- load devices + snapshot -------
DEVICES_JSON_PATH: Path | None = _find_file("devices.json")
SNAPSHOT_JSON_PATH: Path | None = _find_file("snapshot.json")
if not DEVICES_JSON_PATH:
    raise FileNotFoundError("devices.json not found. Set SMART_DEVICES_DIR or place it in project root.")

with DEVICES_JSON_PATH.open("r", encoding="utf-8") as f:
    _DEVICES: List[Dict[str, Any]] = json.load(f)

_SNAPSHOT: Dict[str, Dict[str, Any]] = {}
if SNAPSHOT_JSON_PATH and SNAPSHOT_JSON_PATH.exists():
    snap = json.load(SNAPSHOT_JSON_PATH.open("r", encoding="utf-8"))
    for d in snap.get("devices", []):
        did = d.get("id")
        if did:
            _SNAPSHOT[did] = {"ip": d.get("ip"), "ver": d.get("ver") or d.get("version") or "3.3"}

# canonical maps
_DEVICE_BY_NAME: Dict[str, Dict[str, Any]] = {}
_DEVICE_NAMES: List[str] = []
for d in _DEVICES:
    name = (d.get("name") or "").strip()
    if not name:
        continue
    # enrich with snapshot ip/version if missing
    did = d.get("id")
    snap = _SNAPSHOT.get(did or "")
    if not d.get("ip") and snap:
        d["ip"] = snap.get("ip")
    if not d.get("version") and snap:
        d["version"] = snap.get("ver")
    _DEVICE_BY_NAME[name.lower()] = d
    _DEVICE_NAMES.append(name)

_DEVICE_TOKENS = {name: set(re.sub(r"[^a-z0-9 ]+", "", name.lower()).split()) for name in _DEVICE_NAMES}

# ------- vocab -------
_ON_WORDS = {"on", "enable", "start", "power on"}
_OFF_WORDS = {"off", "disable", "stop", "power off", "shutdown"}
_TOGGLE_WORDS = {"toggle", "switch"}
_BRIGHTNESS = {"brightness"}
_GENERIC_LIGHT_TOKENS = {"light", "lights", "lamp", "lamps", "bulb", "bulbs"}
_STATUS = {"status", "state", "is it", "what is", "what's"}
_ALL_WORDS = {"all", "everything"}
_ROOM_HINTS = {"room", "bedroom", "kitchen", "office", "hall", "hallway", "living", "lounge", "bathroom"}
_COLOR_WORDS = {
    # Base
    "red","green","blue","yellow","purple","pink","orange","cyan","magenta","turquoise",
    
    # Extended basics
    "lime","teal","violet","indigo","maroon","navy","olive","aqua","coral","crimson",
    "lavender","mint","peach","plum","rose","salmon","scarlet","tan","beige","burgundy",
    "emerald","gold","silver","bronze","charcoal","chocolate","brown","black","white","gray","grey",

    # Pastels
    "baby blue","baby pink","powder blue","mint green","pastel yellow","pastel pink",
    "pastel purple","pastel orange","pastel green","pastel blue","pastel red",

    # Bright tones
    "neon green","neon blue","neon pink","neon yellow","neon orange","neon purple",
    
    # Warm tones
    "amber","apricot","copper","mustard","ochre","russet","rust","saffron","sepia",
    
    # Cool tones
    "aquamarine","azure","cobalt","cerulean","seafoam","sky blue","steel blue",
    
    # Earth tones
    "khaki","sand","mahogany","mocha","coffee","walnut","forest green","hunter green",
    
    # Miscellaneous popular names
    "fuchsia","chartreuse","periwinkle","blush","ivory","cream","off white",
    "pearl","smoke","slate","gunmetal","midnight blue","midnight","obsidian"
    
    #white colour
    "white","warm","cool","cold","neutral",
    "daylight","day light","day","candlelight","candle light","candle",
    "ivory","ivory white","warm white","cool white","soft white",
    "amber","gold","sunset","sunrise","halogen","natural","pure white",
    "bright white","arctic white"
}
_WHITE_COLOR_WORDS = (
    "white","warm","cool","cold","neutral",
    "daylight","day light","day","candlelight","candle light","candle",
    "ivory","ivory white","warm white","cool white","soft white",
    "amber","gold","sunset","sunrise","halogen","natural","pure white",
    "bright white","arctic white"
)
_GENERIC_TOKENS = {"light", "lights", "lamp"}
_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")

# ------- helpers -------
def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9 #%]", "", s.lower()).strip()

def _contains_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None

def _has_color(text: str) -> Optional[str]:
    h = _HEX_RE.search(text)
    if h:
        return h.group(0)
    for c in sorted(_COLOR_WORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(c)}\b", text):
            return c
    return None

def _extract_brightness_strict(text: str) -> Optional[int]:
    if not any(_contains_word(text, w) for w in _BRIGHTNESS):
        return None
    m = re.search(r"(?:brightness|bright)\s*(?:to|at|=)?\s*(\d{1,3})\s*%?", text) \
        or re.search(r"(\d{1,3})\s*%?\s*(?:brightness|bright)", text)
    if not m:
        return None
    v = int(m.group(1))
    return max(0, min(100, v))

def _extract_brightness_loose(text: str, targets: List[str]) -> Optional[int]:
    if not _looks_like_light(text, targets):
        return None
    m = re.search(r"\b(?:to|at)\s*(\d{1,3})\s*%?\b", text) or re.search(r"\b(\d{1,3})\s*%\b", text)
    if not m and targets:
        m = re.search(r"\b(\d{1,3})\b", text)
    if not m:
        return None
    v = int(m.group(1))
    return max(0, min(100, v))

def _looks_like_light(text: str, targets: List[str]) -> bool:
    if any(_contains_word(text, w) for w in _GENERIC_LIGHT_TOKENS):
        return True
    for t in targets:
        if any(w in t.lower() for w in _GENERIC_LIGHT_TOKENS):
            return True
    return False

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
    stripped = re.sub(r"\b(on|off|toggle)\b", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    targets = _best_device_freeform(stripped)
    if not targets and len(_DEVICE_NAMES) == 1:
        return _DEVICE_NAMES[:]
    return targets

def _filter_online(targets: List[str]) -> List[str]:
    out = []
    for name in targets:
        meta = _DEVICE_BY_NAME.get(name.lower())
        if not meta:
            continue
        ip = meta.get("ip")
        if ip:
            out.append(name)
        else:
            # allow if only one known device of that name; control module can still resolve via snapshot at runtime
            out.append(name)
    return out

# ------- parser -------
def parse_command(text: str) -> Tuple[str, Optional[str], List[str]]:
    t = _normalize(text)
    targets_guess = _extract_targets(t)

    if any(_contains_word(t, w) for w in _STATUS):
        return "status", None, _extract_targets(t)

    if re.search(r"\b(turn|switch)\s+on\b", t):
        return "on", None, _extract_targets(t)
    if re.search(r"\b(turn|switch)\s+off\b", t):
        return "off", None, _extract_targets(t)
    
    b = _extract_brightness_strict(t)
    if b is None:
        # if we don’t have confident targets yet, try a freeform guess for gating
        tg = targets_guess or _best_device_freeform(t)
        b = _extract_brightness_loose(t, tg)
    if b is not None:
        return "brightness", str(b), targets_guess

    color = _has_color(t)
    if color:
        return "color", color, _extract_targets(t)

    if any(_contains_word(t, w) for w in _TOGGLE_WORDS):
        return "toggle", None, _extract_targets(t)
    if any(_contains_word(t, w) for w in _OFF_WORDS) and not any(_contains_word(t, w) for w in _ON_WORDS):
        return "off", None, _extract_targets(t)
    if any(_contains_word(t, w) for w in _ON_WORDS) and not any(_contains_word(t, w) for w in _OFF_WORDS):
        return "on", None, _extract_targets(t)

    # presets to map into color handler
    for preset in _WHITE_COLOR_WORDS:
        if _contains_word(t, preset):
            return "color", preset, _extract_targets(t)

    return "toggle", None, _extract_targets(t)

# ------- executor -------
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
        return _exec_each(targets, lambda d: (light_on(d) or "on"))
    if action == "off":
        return _exec_each(targets, lambda d: (light_off(d) or "off"))
    if action == "toggle":
        return _exec_each(targets, lambda d: (light_toggle(d) or "toggled"))
    if action == "color":
        col = str(value) if value else "white"
        return _exec_each(targets, lambda d: (light_color(d, col) or f"color {col}"))
    if action == "brightness":
        pct = int(value) if value is not None else 100
        return _exec_each(targets, lambda d: (light_brightness(d, pct) or f"brightness {pct}%"))
    if action == "status":
        resp = []
        for name in targets:
            meta = _DEVICE_BY_NAME.get(name.lower())
            if meta:
                resp.append(f"{meta.get('name', name)}: ip={meta.get('ip') or 'unknown'}")
            else:
                resp.append(f"{name}: unknown")
        return "\n".join(resp)

    return "Unknown action."

# ------- console -------
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
