import json, os, time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import tinytuya

# -------------------- File and Device Loading --------------------

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
        if meta.get("code") in codes:
            try:
                return int(k)
            except Exception:
                continue
    return None

# -------------------- Light State Controls --------------------

def light_on(name_or_id: str):
    dev = _resolve_device(name_or_id)
    dp = _dp_for(dev, ("switch", "switch_led", "switch_1"))
    if dp is None:
        raise RuntimeError(f"No switch DP for '{dev['name']}'")
    return _bulb(dev).set_value(dp, True)

def light_off(name_or_id: str):
    dev = _resolve_device(name_or_id)
    dp = _dp_for(dev, ("switch", "switch_led", "switch_1"))
    if dp is None:
        raise RuntimeError(f"No switch DP for '{dev['name']}'")
    return _bulb(dev).set_value(dp, False)

def light_toggle(name_or_id: str):
    dev = _resolve_device(name_or_id)
    dp = _dp_for(dev, ("switch", "switch_led", "switch_1"))
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
        "white": 50, "warm": 15, "warm white": 20,
        "soft white": 30, "neutral": 50,
        "cool": 80, "cool white": 85, "cold": 100
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
        "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
        "yellow": (255, 255, 0), "purple": (128, 0, 128),
        "pink": (255, 105, 180), "orange": (255, 165, 0),
        "cyan": (0, 255, 255), "magenta": (255, 0, 255), "turquoise": (64, 224, 208)
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

