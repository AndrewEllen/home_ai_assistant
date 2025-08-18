# modules/smart_devices/interpret_smart_command.py

DEBUG_SMART = True
def _dbg(*a):
    if DEBUG_SMART: print("[smart]", *a, flush=True)

import json, re, threading, difflib, unicodedata

from modules.weather.weather_api import get_weather
from modules.maths.calculator import try_calculate
from modules.time.date_and_time import build_time_message
from modules.time.control_timer import handle_timer_intent, TIMER
from modules.google_search.search_for_answers import answer_with_search


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
_LAUNCH_WORDS = {"launch", "open up", "start up", "boot up"}
_CLIP_PHRASES = {"clip that", "clip it", "make a clip", "save that clip"}
_WEATHER_WORDS = {"weather", "forecast", "temperature", "rain", "snow", "wind"}
_MATH_WORDS = {
    # basic operations
    "plus", "add", "addition", "minus", "subtract", "subtraction",
    "times", "multiply", "multiplied", "multiplication",
    "divide", "divided", "division", "over", "into",
    "mod", "modulus", "remainder",
    "power", "to the power", "raised", "squared", "cubed",
    # roots
    "square root", "cube root", "root",
    # percentages
    "percent of", "percentage of"
}
_MATH_SYM_RE = re.compile(r"\d+\s*(?:[\+\-\*/^]|percent)", re.I)
_TIME_DATE_WORDS = {"time", "date", "day", "month", "year", "today", "now"}
_SEARCH_START = {"who", "search", "what", "when", "where", "why", "how"}
_PLACE_RE = re.compile(r"\b(?:in|at|for)\s+([a-z0-9 ,.'-]{2,})$", re.I)
_ON_WORDS = {"on", "enable", "start", "power on"}
_OFF_WORDS = {"off", "disable", "power off", "shutdown"}
_TOGGLE_WORDS = {"toggle", "switch"}
_BRIGHTNESS = {"brightness", "dim", "brighten"}
_DIM_WORDS = {"dim"}
_BRIGHTEN_WORDS = {"brighten"}
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

def _all_room_devices(room: Optional[str]) -> List[str]:
    if not room:
        return []
    r = room.lower().strip()
    return [n for n in _DEVICE_NAMES if r in n.lower()]


_CLAUSE_SPLIT_RE = re.compile(r"\b(?:and then|then|and)\b|[,;]", re.I)

def _strip_edge_punct(s: str) -> str:
    i, j = 0, len(s)
    def is_punct(ch): return unicodedata.category(ch).startswith("P")
    while i < j and (s[i].isspace() or is_punct(s[i])): i += 1
    while j > i and (s[j-1].isspace() or is_punct(s[j-1])): j -= 1
    return s[i:j]

def extract_game_query(text: str) -> str:
    low = text.lower()
    # find first launch phrase anywhere; keep hyphens in the remainder
    m = re.search(r"\b(?:open up|start up|boot up|launch)\b", low)
    if not m:
        return _strip_edge_punct(text)
    return _strip_edge_punct(text[m.end():])

def _is_clip_intent(text: str) -> bool:
    t = " ".join(text.lower().split())
    return any(p in t for p in _CLIP_PHRASES)

# ------- executor helpers -------
def _do_and_label(fn, label: str) -> str:
    try:
        fn()
        return label
    except Exception as e:
        return f"Error: {e}"


def _split_clauses(text: str) -> List[str]:
    return [c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]

def _run_action(action: str, value: Optional[str], targets: List[str]) -> str:

    if action == "clip":
        # server tells client to press the clip hotkey
        return "route_client: clip"
    if action == "launch_app":
        # server should route to client; return a sentinel for logging only
        q = (value or "").strip()
        return f"route_client: launch_app|{q}" if q else "route_client: launch_app"

    if action == "weather":
        place = value if isinstance(value, str) and value.strip() else None
        return get_weather(place)
    
    if action == "math":
        try:
            res = try_calculate(value or "")
            return "The answer is " + str(res) if res is not None else "No calculation found."
        except Exception as e:
            return f"Math error: {e}"
        
    if action == "time":
        try:
            res = build_time_message(value or "")
            return str(res) if res is not None else "No calculation found."
        except Exception as e:
            return f"Couldn't get the time: {e}"
        
    if action == "timer":
        return value
    
    if action == "search":
        try:
            # bundle = web_search(value)  # fetch web results
            # return humanize_search(value, bundle, is_topic=False)
            res = answer_with_search(value)
            return res["answer"]
        except Exception as e:
            return f"Search error: {e}"

    targets = _ensure_targets(targets)
    if not targets:
        return "No matching device."
    targets = _filter_online(targets)
    if not targets:
        return "No matching device."

    if action == "on":
        return _exec_each(targets, lambda d: _do_and_label(lambda: light_on(d), "turned on"))

    if action == "off":
        return _exec_each(targets, lambda d: _do_and_label(lambda: light_off(d), "turned off"))

    if action == "toggle":
        return _exec_each(targets, lambda d: _do_and_label(lambda: light_toggle(d), "toggled"))

    if action == "color":
        col = str(value) if value else "white"
        return _exec_each(targets, lambda d: _do_and_label(lambda: light_color(d, col), f"set to {col}"))

    if action == "brightness":
        pct = int(value) if value is not None else 100
        return _exec_each(targets, lambda d: _do_and_label(lambda: light_brightness(d, pct), f"brightness set to {pct}%"))

    if action == "status":
        resp = []
        for name in targets:
            meta = _DEVICE_BY_NAME.get(name.lower())
            if meta:
                resp.append(f"{meta.get('name', name)}: ip={meta.get('ip') or 'unknown'}")
            else:
                resp.append(f"{name}: unknown")
        return "\n".join(resp)
    return "Sorry, I didn't understand that command."

# ------- parser -------
def parse_command(text: str) -> Tuple[str, Optional[str], List[str]]:
    if _is_clip_intent(text):
        return "clip", None, []
    if re.search(r"\b(?:open up|start up|boot up|launch)\b", text.lower()):
        return "launch_app", extract_game_query(text), []
    t = _normalize(text)
    targets_guess = _extract_targets(t)

    # app launch queries
    if any(p in t for p in _LAUNCH_WORDS):
        return "launch_app", text, []

    # weather queries
    if any(_contains_word(t, w) for w in _WEATHER_WORDS):
        m = _PLACE_RE.search(text.strip())
        place = m.group(1).strip() if m else None
        return "weather", place, []  # targets unused
    
    # maths
    if any(_contains_word(t, w) for w in _MATH_WORDS) or _MATH_SYM_RE.search(text):
        return "math", text, []
    
    # time
    if any(_contains_word(t, w) for w in _TIME_DATE_WORDS):
        return "time", text, []
    
    resp = handle_timer_intent(text)
    if resp is not None:
        return "timer", resp, []
    
    if any(text.lower().startswith(q) for q in _SEARCH_START):
        return "search", text, []
    
    if any(_contains_word(t, w) for w in _DIM_WORDS) and _looks_like_light(t, targets_guess):
        return "brightness", "30", targets_guess
    if any(_contains_word(t, w) for w in _BRIGHTEN_WORDS) and _looks_like_light(t, targets_guess):
        return "brightness", "100", targets_guess

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

    return "unknown", None, []

# ------- executor -------
def _ensure_targets(targets: List[str]) -> List[str]:
    if targets:
        return targets
    return []

def _exec_each(targets: List[str], fn):
    outputs = []
    for dev in targets:
        _dbg("ENTER device op for:", dev)
        try:
            msg = fn(dev)  # this calls into control_smart_devices.*
            _dbg("EXIT device op for:", dev, "->", msg)
        except Exception as e:
            _dbg("ERROR device op for:", dev, e)
            msg = f"Error: {e}"
        outputs.append(f"{dev}: {msg}")
    return "\n".join(outputs) if outputs else "Sorry, I didn't understand that."

def execute_command(text: str, room: str | None = None) -> str:
    _dbg("input:", repr(text))
    action, value, targets = parse_command(text)
    _dbg("parsed:", action, value, "targets_guess:", targets)

    # Never split for these intents
    if action in {"time", "weather", "math", "launch_app", "clip"}:
        _dbg("final_targets:", targets)
        return _run_action(action, value, targets or [])

    # Multi-clause handling
    clauses = _split_clauses(text)
    if len(clauses) > 1:
        shared_targets = _extract_targets(_normalize(text))
        if not shared_targets and room:
            shared_targets = _all_room_devices(room)

        outputs = []
        for c in clauses:
            a, v, t = parse_command(c)
            if not t:
                t = shared_targets
                if not t and room:
                    t = _all_room_devices(room)
            outputs.append(_run_action(a, v, t))
        return "\n".join(o for o in outputs if o)

    # Single clause fallback
    if not targets:
        targets = _best_device_freeform(text)
        if not targets and room:
            targets = _all_room_devices(room)

    return _run_action(action, value, targets)



# ------- console -------
def start_console_command_listener(room: str) -> threading.Thread:
    def _loop():
        while True:
            try:
                text = input("> ").strip()
                if text:
                    result = execute_command(text=text, room=room)
                    print(result)
            except (EOFError, KeyboardInterrupt):
                break
    th = threading.Thread(target=_loop, daemon=True)
    th.start()
    return th
