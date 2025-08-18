import json, os, time
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import tinytuya

_SWITCH_CODES = ("switch", "switch_led", "switch_1", "led_switch", "switch_main")

# -------------------- File and Device Loading -------------------

def _find_file(fname: str) -> Optional[Path]:
    env = os.getenv("SMART_DEVICES_DIR")
    if env:
        p = Path(env) / fname
        if p.exists():
            return p
    here = Path(__file__).resolve()
    for base in [Path.cwd(), here.parent, here.parent.parent, here.parents[2]]:
        p = base / fname
        if p.exists():
            return p
    return None

DEVICES_JSON = _find_file("devices.json")
SNAPSHOT_JSON = _find_file("snapshot.json")

if not DEVICES_JSON:
    raise FileNotFoundError("devices.json not found. Set SMART_DEVICES_DIR or place it in project root.")

with DEVICES_JSON.open("r", encoding="utf-8") as f:
    DEVICES = json.load(f)

_SNAPSHOT = {}
if SNAPSHOT_JSON and SNAPSHOT_JSON.exists():
    snap = json.load(SNAPSHOT_JSON.open("r", encoding="utf-8"))
    for d in snap.get("devices", []):
        if d.get("id"):
            _SNAPSHOT[d["id"]] = {"ip": d.get("ip"), "ver": d.get("ver") or d.get("version") or "3.3"}

_DEVICES_BY_ID: Dict[str, Dict[str, Any]] = {}
_DEVICES_BY_NAME: Dict[str, Dict[str, Any]] = {}
for d in DEVICES:
    name = d.get("name", "").strip()
    did = d.get("id")
    if not did:
        continue
    entry = {
        "name": name,
        "id": did,
        "key": d.get("key"),
        "ip": d.get("ip"),
        "ver": d.get("version") or "3.3",
        "mapping": d.get("mapping", {}),
    }
    _DEVICES_BY_ID[did] = entry
    if name:
        _DEVICES_BY_NAME[name.lower()] = entry

# -------------------- Device Resolution --------------------

def _resolve_device(name_or_id: str) -> Dict[str, Any]:
    print("[bulb] resolve:", name_or_id, flush=True)
    dev = _DEVICES_BY_NAME.get(name_or_id.lower()) or _DEVICES_BY_ID.get(name_or_id)
    if not dev:
        print("[bulb] resolve FAIL:", name_or_id, flush=True)
        raise ValueError(f"Device '{name_or_id}' not found.")
    snap = _SNAPSHOT.get(dev["id"])
    if not dev.get("ip") and snap:
        dev["ip"] = snap.get("ip")
    if not dev.get("ver") and snap:
        dev["ver"] = snap.get("ver")
    print("[bulb] resolved ->", dev.get("name"), dev.get("ip"), dev.get("ver"), flush=True)
    if not dev.get("ip"):
        raise RuntimeError(f"Device '{dev['name']}' has no IP. Run 'python -m tinytuya scan'.")
    return dev

def _bulb(dev: Dict[str, Any]) -> tinytuya.BulbDevice:
    b = tinytuya.BulbDevice(dev["id"], dev["ip"], dev["key"])
    try:
        b.set_version(float(dev.get("ver", 3.3)))
    except Exception:
        b.set_version(3.3)
    return b

def _dp_for(dev: Dict[str, Any], codes: Tuple[str, ...]) -> Optional[int]:
    print("[bulb] _dp_for ENTER", dev.get("name"), codes, flush=True)

    mapping = dev.get("mapping", {})

    # 1st pass: exact match on code
    for k, meta in mapping.items():
        code = (meta.get("code") or "").lower()
        if code in codes:
            try:
                dp = int(k)
                print("[bulb] _dp_for exact match:", code, "->", dp, flush=True)
                return dp
            except Exception as e:
                print("[bulb] _dp_for exact match error:", e, flush=True)
                continue

    # 2nd pass: startswith
    for k, meta in mapping.items():
        code = (meta.get("code") or "").lower()
        if any(code.startswith(c) for c in codes):
            try:
                dp = int(k)
                print("[bulb] _dp_for prefix match:", code, "->", dp, flush=True)
                return dp
            except Exception as e:
                print("[bulb] _dp_for prefix match error:", e, flush=True)
                continue

    # 3rd pass: fallback guesses
    for guess in (1, 20):
        m = mapping.get(str(guess))
        if isinstance(m, dict) and m.get("type") == "Boolean":
            print("[bulb] _dp_for fallback guess:", guess, flush=True)
            return guess

    print("[bulb] _dp_for EXIT None", flush=True)
    return None


# -------------------- Light State Controls --------------------

def light_on(name_or_id: str):
    print("[bulb] light_on ENTER", name_or_id, flush=True)

    dev = _resolve_device(name_or_id)
    dp = _dp_for(dev, _SWITCH_CODES)

    if dp is None:
        raise RuntimeError(f"No switch DP for '{dev['name']}'")

    bulb = _bulb(dev)
    try:
        res = bulb.set_value(dp, True)
        print("[bulb] light_on EXIT", name_or_id, res, flush=True)
        return res
    except Exception as e:
        print("[bulb] light_on ERROR", e, flush=True)
        raise


def light_off(name_or_id: str):
    print("[bulb] light_off ENTER", name_or_id, flush=True)

    dev = _resolve_device(name_or_id)
    dp = _dp_for(dev, _SWITCH_CODES)

    if dp is None:
        raise RuntimeError(f"No switch DP for '{dev['name']}'")

    bulb = _bulb(dev)
    try:
        res = bulb.set_value(dp, False)
        print("[bulb] light_off EXIT", name_or_id, res, flush=True)
        return res
    except Exception as e:
        print("[bulb] light_off ERROR", e, flush=True)
        raise


def light_toggle(name_or_id: str):
    print("[bulb] light_toggle ENTER", name_or_id, flush=True)

    dev = _resolve_device(name_or_id)
    dp = _dp_for(dev, _SWITCH_CODES)

    if dp is None:
        raise RuntimeError(f"No switch DP for '{dev['name']}'")

    bulb = _bulb(dev)

    try:
        status = bulb.status()
        print("[bulb] current status:", status, flush=True)

        state = status.get("dps", {}).get(str(dp), False)
        print("[bulb] current state for DP", dp, "=", state, flush=True)

        res = bulb.set_value(dp, not state)
        print("[bulb] light_toggle EXIT", name_or_id, "->", not state, res, flush=True)
        return res

    except Exception as e:
        print("[bulb] light_toggle ERROR", e, flush=True)
        raise



# -------------------- Color and Temperature --------------------

def light_color(name_or_id: str, color: Any):
    dev = _resolve_device(name_or_id)
    bulb = _bulb(dev)
    light_on(name_or_id)

    white_presets = {
        "white": 50,
        "warm": 15,
        "warm white": 20,
        "soft white": 30,
        "neutral": 50,
        "cool": 80,
        "cool white": 85,
        "cold": 100,
        "candlelight": 0,
        "candle light": 0,
        "candle": 0,
        "daylight": 0,
        "day light": 0,
        "day": 0,
        "ivory": 100,
        "ivory white": 100,
        "amber": 10,
        "gold": 12,
        "sunset": 8,
        "sunrise": 12,
        "halogen": 25,
        "natural": 55,
        "pure white": 60,
        "bright white": 70,
        "arctic white": 95,
    }

    if isinstance(color, str) and color.strip().lower() in white_presets:
        _set_white_temp(dev, bulb, white_presets[color.strip().lower()])
        return

    r, g, b = _parse_color_input(color)
    _apply_rgb(dev, bulb, r, g, b)


def _set_white_temp(dev: Dict[str, Any], bulb, pct: int):
    """Switch to white while preserving current brightness; pct is colour temp 0–100."""
    pct = max(0, min(100, int(pct)))

    # read current brightness from whichever mode we are in
    v_pct = None
    try:
        st = bulb.state()
        if isinstance(st, dict) and "Error" not in st:
            mode = str(bulb.get_mode(state=st)).lower()
            if mode in ("colour", "color"):
                # take V from HSV
                _, _, v = bulb.colour_hsv(state=st)
                v_pct = int(round(float(v) * 100.0))
            else:
                v_pct = int(round(float(bulb.get_brightness_percentage(state=st))))
    except Exception:
        pass
    if v_pct is None:
        v_pct = 100  # sensible default

    # library handles switching to white + applies brightness and colour temp as percentages
    return bulb.set_white_percentage(brightness=v_pct, colourtemp=pct)


def _parse_color_input(c: Any) -> Tuple[int, int, int]:
    named = {
        # Base
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 0, 255),
        "yellow": (255, 255, 0),
        "purple": (128, 0, 128),
        "pink": (255, 105, 180),
        "orange": (255, 165, 0),
        "cyan": (0, 255, 255),
        "magenta": (255, 0, 255),
        "turquoise": (64, 224, 208),

        # Extended basics
        "lime": (191, 255, 0),
        "teal": (0, 128, 128),
        "violet": (238, 130, 238),
        "indigo": (75, 0, 130),
        "maroon": (128, 0, 0),
        "navy": (0, 0, 128),
        "olive": (128, 128, 0),
        "aqua": (0, 255, 255),
        "coral": (255, 127, 80),
        "crimson": (220, 20, 60),
        "lavender": (230, 230, 250),
        "mint": (189, 252, 201),
        "peach": (255, 218, 185),
        "plum": (221, 160, 221),
        "rose": (255, 228, 225),
        "salmon": (250, 128, 114),
        "scarlet": (255, 36, 0),
        "tan": (210, 180, 140),
        "beige": (245, 245, 220),
        "burgundy": (128, 0, 32),
        "emerald": (80, 200, 120),
        "gold": (255, 215, 0),
        "silver": (192, 192, 192),
        "bronze": (205, 127, 50),
        "charcoal": (54, 69, 79),
        "chocolate": (210, 105, 30),
        "brown": (165, 42, 42),
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "gray": (128, 128, 128),
        "grey": (128, 128, 128),

        # Pastels
        "baby blue": (137, 207, 240),
        "baby pink": (244, 194, 194),
        "powder blue": (176, 224, 230),
        "mint green": (152, 255, 152),
        "pastel yellow": (253, 253, 150),
        "pastel pink": (255, 209, 220),
        "pastel purple": (179, 158, 181),
        "pastel orange": (255, 179, 71),
        "pastel green": (119, 221, 119),
        "pastel blue": (174, 198, 207),
        "pastel red": (255, 105, 97),

        # Neons
        "neon green": (57, 255, 20),
        "neon blue": (77, 77, 255),
        "neon pink": (255, 20, 147),
        "neon yellow": (207, 255, 4),
        "neon orange": (255, 95, 31),
        "neon purple": (177, 13, 201),

        # Warm tones
        "amber": (255, 191, 0),
        "apricot": (251, 206, 177),
        "copper": (184, 115, 51),
        "mustard": (255, 219, 88),
        "ochre": (204, 119, 34),
        "russet": (128, 70, 27),
        "rust": (183, 65, 14),
        "saffron": (244, 196, 48),
        "sepia": (112, 66, 20),

        # Cool tones
        "aquamarine": (127, 255, 212),
        "azure": (0, 127, 255),
        "cobalt": (0, 71, 171),
        "cerulean": (42, 82, 190),
        "seafoam": (159, 226, 191),
        "sky blue": (135, 206, 235),
        "steel blue": (70, 130, 180),

        # Earth tones
        "khaki": (240, 230, 140),
        "sand": (194, 178, 128),
        "mahogany": (192, 64, 0),
        "mocha": (150, 75, 0),
        "coffee": (111, 78, 55),
        "walnut": (119, 63, 26),
        "forest green": (34, 139, 34),
        "hunter green": (53, 94, 59),

        # Miscellaneous
        "fuchsia": (255, 0, 255),
        "chartreuse": (127, 255, 0),
        "periwinkle": (204, 204, 255),
        "blush": (222, 93, 131),
        "ivory": (255, 255, 240),
        "cream": (255, 253, 208),
        "off white": (253, 253, 250),
        "pearl": (234, 224, 200),
        "smoke": (115, 130, 118),
        "slate": (112, 128, 144),
        "gunmetal": (42, 52, 57),
        "midnight blue": (25, 25, 112),
        "midnight": (25, 25, 112),
        "obsidian": (15, 15, 15)
    }

    if isinstance(c, str):
        s = c.strip().lower()
        if s in named:
            return named[s]
        if s.startswith("#") and len(s) in (7, 4):
            if len(s) == 7:
                return int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)
            return int(s[1]*2, 16), int(s[2]*2, 16), int(s[3]*2, 16)
        raise ValueError(f"Unsupported color '{c}'")
    if isinstance(c, (tuple, list)) and len(c) == 3:
        return tuple(max(0, min(255, int(v))) for v in c)
    raise ValueError(f"Unsupported color '{c}'")

def _read_current_hsv(dev: Dict[str, Any], bulb: tinytuya.BulbDevice) -> Optional[Tuple[float, float, float]]:
    """Return current (h,s,v) in 0..1, or None if unavailable."""
    try:
        st = bulb.state()
        if isinstance(st, dict) and "Error" not in st:
            h, s, v = bulb.colour_hsv(state=st)
            return float(h), float(s), float(v)
    except Exception:
        pass
    # Fallback via raw DPS "colour" if state() path failed
    try:
        dps = bulb.status().get("dps", {}) or {}
        dp_colour = getattr(bulb, "dpset", {}).get("colour")
        if dp_colour and dp_colour in dps and isinstance(dps[dp_colour], str):
            h, s, v = tinytuya.BulbDevice.hexvalue_to_hsv(dps[dp_colour], getattr(bulb, "dpset", {}).get("value_hexformat"))
            return float(h), float(s), float(v)
    except Exception:
        pass
    return None

def _read_current_brightness(dev: Dict[str, Any], bulb: tinytuya.BulbDevice) -> Optional[float]:
    """Return current brightness 0..1 from mode-aware state, else None."""
    try:
        st = bulb.state()
        if isinstance(st, dict) and "Error" not in st:
            mode = str(bulb.get_mode(state=st)).lower()
            if mode in ("colour", "color"):
                h, s, v = bulb.colour_hsv(state=st)
                return float(v)
            # white path
            bp = float(bulb.get_brightness_percentage(state=st))
            return max(0.0, min(1.0, bp / 100.0))
    except Exception:
        pass

    # Fallback via raw DPS
    try:
        dps = bulb.status().get("dps", {}) or {}
        dp_b = _dp_for(dev, ("bright_value_v2", "bright_value", "brightness"))
        if dp_b and str(dp_b) in dps:
            meta = dev.get("mapping", {}).get(str(dp_b), {}).get("values", {})
            dmin = int(meta.get("min", 0)); dmax = int(meta.get("max", 1000)) or 1000
            val = int(dps[str(dp_b)])
            return max(0.0, min(1.0, (val - dmin) / float(max(1, dmax - dmin))))
        for code in ("colour_data_v2","color_data_v2","colour_data","color_data"):
            dp_c = _dp_for(dev, (code,))
            if not dp_c or str(dp_c) not in dps or dps[str(dp_c)] is None:
                continue
            raw = dps[str(dp_c)]
            if isinstance(raw, str) and raw.strip().startswith("{"):
                obj = json.loads(raw); v = float(obj.get("v", obj.get("V", 1000)))
            elif isinstance(raw, str):
                m = re.match(r"^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$", raw)
                if not m: continue
                v = float(m.group(3))
            elif isinstance(raw, dict):
                v = float(raw.get("v", raw.get("V", 1000)))
            else:
                continue
            return v/1000.0 if v > 3 else (v/255.0 if v > 1.0 else v)
    except Exception:
        pass
    return None

def _apply_rgb(dev, bulb, r, g, b, saturation: float | None = None, brightness: float | None = None):
    import colorsys

    r = max(0, min(255, int(r))); g = max(0, min(255, int(g))); b = max(0, min(255, int(b)))
    h, s_calc, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)

    s = s_calc if saturation is None else max(0.0, min(1.0, float(saturation)))

    if brightness is None:
        # preserve current brightness regardless of mode
        try:
            st = bulb.state()
            if isinstance(st, dict) and "Error" not in st:
                mode = str(bulb.get_mode(state=st)).lower()
                if mode in ("colour", "color"):
                    _, _, v = bulb.colour_hsv(state=st)
                    v = float(v)
                else:
                    v_pct = float(bulb.get_brightness_percentage(state=st))
                    v = max(0.0, min(1.0, v_pct / 100.0))
            else:
                v = 1.0
        except Exception:
            v = 1.0
    else:
        v = max(0.0, min(1.0, float(brightness)))

    # set_hsv switches to colour mode without resetting v
    bulb.set_hsv(h, s, v)


# ---------------------------------------- Brightness ----------------------------------------


def light_brightness(name_or_id: str, percent: int):
    """0–100%. If mode=colour, keep H/S and change V; else use white brightness."""
    print("[bulb] light_brightness ENTER", name_or_id, percent, flush=True)

    dev = _resolve_device(name_or_id)
    bulb = _bulb(dev)

    # ensure it's on first
    light_on(name_or_id)

    pct = max(0, min(100, int(percent)))
    v_new = pct / 100.0
    print("[bulb] clamped percent:", pct, "v_new:", v_new, flush=True)

    # Read mode
    try:
        st = bulb.state()
        print("[bulb] state:", st, flush=True)
    except Exception as e:
        print("[bulb] state read ERROR", e, flush=True)
        st = None

    try:
        mode = str(bulb.get_mode(state=st)).lower()
    except Exception:
        if isinstance(st, dict):
            mode = str(st.get("mode", "")).lower()
        else:
            mode = ""

    print("[bulb] mode:", mode, flush=True)

    try:
        if mode in ("colour", "color"):
            hsv = _read_current_hsv(dev, bulb)
            print("[bulb] current HSV:", hsv, flush=True)

            if hsv:
                h, s, _ = hsv
                res = bulb.set_hsv(h, s, v_new)  # preserve H/S
                print("[bulb] light_brightness EXIT set_hsv", res, flush=True)
                return res

            res = bulb.set_brightness_percentage(pct)
            print("[bulb] light_brightness EXIT fallback set_brightness_percentage", res, flush=True)
            return res

        # White or unknown
        res = bulb.set_brightness_percentage(pct)
        print("[bulb] light_brightness EXIT set_brightness_percentage", res, flush=True)
        return res

    except Exception as e:
        print("[bulb] light_brightness ERROR", e, flush=True)
        raise


