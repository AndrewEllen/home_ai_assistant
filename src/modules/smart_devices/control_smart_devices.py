import json, os, time
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
    dev = _DEVICES_BY_NAME.get(name_or_id.lower()) or _DEVICES_BY_ID.get(name_or_id)
    if not dev:
        raise ValueError(f"Device '{name_or_id}' not found.")
    snap = _SNAPSHOT.get(dev["id"])
    if not dev.get("ip") and snap:
        dev["ip"] = snap.get("ip")
    if not dev.get("ver") and snap:
        dev["ver"] = snap.get("ver")
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
    for k, meta in dev.get("mapping", {}).items():
        code = (meta.get("code") or "").lower()
        if code in codes:
            try: return int(k)
            except: continue
    for k, meta in dev.get("mapping", {}).items():
        code = (meta.get("code") or "").lower()
        if any(code.startswith(c) for c in codes):
            try: return int(k)
            except: continue
    for guess in (1, 20):
        m = dev.get("mapping", {}).get(str(guess))
        if isinstance(m, dict) and m.get("type") == "Boolean":
            return guess
    return None


# -------------------- Light State Controls --------------------

def light_on(name_or_id: str):
    dev = _resolve_device(name_or_id)
    dp = _dp_for(dev, _SWITCH_CODES)
    if dp is None: 
        raise RuntimeError(f"No switch DP for '{dev['name']}'")
    return _bulb(dev).set_value(dp, True)

def light_off(name_or_id: str):
    dev = _resolve_device(name_or_id)
    dp = _dp_for(dev, _SWITCH_CODES)
    if dp is None: 
        raise RuntimeError(f"No switch DP for '{dev['name']}'")
    return _bulb(dev).set_value(dp, False)

def light_toggle(name_or_id: str):
    dev = _resolve_device(name_or_id)
    dp = _dp_for(dev, _SWITCH_CODES)
    if dp is None: 
        raise RuntimeError(f"No switch DP for '{dev['name']}'")
    bulb = _bulb(dev)
    state = bulb.status().get("dps", {}).get(str(dp), False)
    return bulb.set_value(dp, not state)


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


def _set_white_temp(dev: Dict[str, Any], bulb: tinytuya.BulbDevice, pct: int):
    dp_mode = _dp_for(dev, ("mode", "work_mode", "colour_mode"))
    if dp_mode:
        try:
            bulb.set_value(dp_mode, "white")
        except Exception:
            pass

    dp_ct = _dp_for(dev, ("temp_value", "temp_value_v2", "colour_temp"))
    if dp_ct is None:
        raise RuntimeError("Device does not support white temperature")

    meta = dev.get("mapping", {}).get(str(dp_ct), {}).get("values", {})
    dmin = int(meta.get("min", 0))
    dmax = int(meta.get("max", 1000))
    val = int(round(dmin + (dmax - dmin) * (pct / 100.0)))
    bulb.set_value(dp_ct, val)


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


def _apply_rgb(dev, bulb, r, g, b):
    import colorsys, time

    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))

    h, _, _ = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)  # 0..1

    try:
        bulb.set_mode("colour")
        time.sleep(0.1)
    except Exception:
        dp_mode = _dp_for(dev, ("mode", "work_mode", "colour_mode"))
        if dp_mode:
            try:
                bulb.set_value(dp_mode, "colour")
                time.sleep(0.1)
            except Exception:
                pass

    # Send one atomic colour command with max saturation and brightness
    bulb.set_hsv(h, 1.0, 1.0)

