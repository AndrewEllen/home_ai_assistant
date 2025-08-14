# modules/smart_devices/control_smart_devices.py
import json, os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import time
import tinytuya

# -------- path resolver --------
def _find_file(fname: str) -> Optional[Path]:
    env = os.getenv("SMART_DEVICES_DIR")
    if env:
        p = Path(env) / fname
        if p.exists():
            return p

    here = Path(__file__).resolve()
    candidates = [
        Path.cwd(),
        here.parent,
        here.parent.parent,
        here.parents[2],
    ]
    for base in candidates:
        p = base / fname
        if p.exists():
            return p
    return None

# -------- load sources --------
DEVICES_JSON = _find_file("devices.json")
SNAPSHOT_JSON = _find_file("snapshot.json")
TUYA_RAW_JSON = _find_file("tuya-raw.json")

if not DEVICES_JSON:
    raise FileNotFoundError("devices.json not found. Set SMART_DEVICES_DIR or place it in project root.")

with DEVICES_JSON.open("r", encoding="utf-8") as f:
    DEVICES = json.load(f)

def _load_snapshot() -> Dict[str, Dict[str, Any]]:
    m: Dict[str, Dict[str, Any]] = {}
    if SNAPSHOT_JSON and SNAPSHOT_JSON.exists():
        snap = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
        for d in snap.get("devices", []):
            did = d.get("id")
            if did:
                m[did] = {"ip": d.get("ip"), "ver": d.get("ver") or d.get("version") or "3.3"}
    return m

def _index_devices():
    by_name: Dict[str, Dict[str, Any]] = {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for d in DEVICES:
        name = (d.get("name") or "").strip()
        did = d.get("id")
        mapping: Dict[str, Any] = d.get("mapping", {})

        dp_switch = None
        dp_brightness = None
        dp_ct = None
        for k, meta in mapping.items():
            code = (meta or {}).get("code", "")
            if code in {"switch_led", "led_switch", "switch", "switch_1"}:
                dp_switch = int(k)
            elif code in {"bright_value", "bright_value_v2"}:
                dp_brightness = int(k)
            elif code in {"temp_value", "temp_value_v2", "colour_temp"}:
                dp_ct = int(k)

        by_id[did] = {
            "name": name,
            "id": did,
            "key": d.get("key"),
            "ip": d.get("ip") or None,
            "ver": d.get("version") or "3.3",
            "dp_switch": dp_switch,
            "dp_brightness": dp_brightness,
            "dp_ct": dp_ct,
            "mapping": mapping,
            "product_name": d.get("product_name"),
        }
        if name:
            by_name[name.lower()] = by_id[did]
    return by_name, by_id

_BY_NAME, _BY_ID = _index_devices()
_SNAP = _load_snapshot()

def _resolve_device(name_or_id: str) -> Dict[str, Any]:
    dev = _BY_NAME.get(name_or_id.lower()) or _BY_ID.get(name_or_id)
    if not dev:
        raise ValueError(f"Device '{name_or_id}' not found in devices.json")

    snap = _SNAP.get(dev["id"])
    if (not dev.get("ip")) and snap and snap.get("ip"):
        dev["ip"] = snap["ip"]
    if (not dev.get("ver")) and snap and snap.get("ver"):
        dev["ver"] = snap["ver"] or "3.3"

    if not dev.get("ip"):
        raise RuntimeError(f"Device '{dev['name']}' has no IP. Run 'python -m tinytuya scan' to populate.")
    if not dev.get("dp_switch"):
        raise RuntimeError(f"Device '{dev['name']}' has no switch DP in mapping.")

    return dev

def _bulb(dev: Dict[str, Any]) -> tinytuya.BulbDevice:
    b = tinytuya.BulbDevice(dev["id"], dev["ip"], dev["key"])
    try:
        b.set_version(float(str(dev.get("ver") or "3.3")))
    except Exception:
        b.set_version(3.3)
    return b

# -------- public API --------
def light_set(name_or_id: str, on: bool):
    dev = _resolve_device(name_or_id)
    return _bulb(dev).set_status(bool(on), dev["dp_switch"])

def light_toggle(name_or_id: str):
    dev = _resolve_device(name_or_id)
    b = _bulb(dev)
    st = b.status()
    cur = bool(((st or {}).get("dps") or {}).get(str(dev["dp_switch"]), False))
    return b.set_status(not cur, dev["dp_switch"])

def light_brightness(name_or_id: str, level: int):
    dev = _resolve_device(name_or_id)
    dp = dev.get("dp_brightness")
    if dp is None:
        raise RuntimeError(f"No brightness DP for '{dev['name']}'")
    meta = dev["mapping"].get(str(dp), {}).get("values", {})
    dmin = int(meta.get("min", 0))
    dmax = int(meta.get("max", 1000))
    pct = max(0, min(100, int(level)))
    val = int(round(dmin + (dmax - dmin) * (pct / 100.0)))
    return _bulb(dev).set_value(dp, val)

def light_temp(name_or_id: str, temp: int):
    dev = _resolve_device(name_or_id)
    dp = dev.get("dp_ct")
    if dp is None:
        raise RuntimeError(f"No color temp DP for '{dev['name']}'")
    meta = dev["mapping"].get(str(dp), {}).get("values", {})
    dmin = int(meta.get("min", 0))
    dmax = int(meta.get("max", 1000))
    pct = max(0, min(100, int(temp)))
    val = int(round(dmin + (dmax - dmin) * (pct / 100.0)))
    b = _bulb(dev)
    b.set_value(dp, val)
    return True

# ---- helpers ----
def _dp_for(dev: Dict[str, Any], codes: Tuple[str, ...]) -> Optional[int]:
    mapping = dev.get("mapping") or {}
    for k, meta in mapping.items():
        if (meta or {}).get("code") in codes:
            try:
                return int(k)
            except Exception:
                continue
    return None

def _device_status(dev: Dict[str, Any]) -> Dict[str, Any]:
    b = _bulb(dev)
    st = b.status() or {}
    return (st.get("dps") or {}) if isinstance(st, dict) else {}

def _pct_from_dps(meta: Dict[str, Any], value: int) -> int:
    dmin = int((meta or {}).get("min", 0))
    dmax = int((meta or {}).get("max", 1000))
    rng = max(1, dmax - dmin)
    pct = int(round((int(value) - dmin) * 100.0 / rng))
    return max(0, min(100, pct))

def _pct_to_dps(meta: Dict[str, Any], pct: int) -> int:
    dmin = int((meta or {}).get("min", 0))
    dmax = int((meta or {}).get("max", 1000))
    p = max(0, min(100, int(pct)))
    return int(round(dmin + (dmax - dmin) * (p / 100.0)))

# ---- state and queries ----
def light_state(name_or_id: str) -> Dict[str, Any]:
    dev = _resolve_device(name_or_id)
    dps = _device_status(dev)
    result: Dict[str, Any] = {"name": dev["name"], "id": dev["id"], "on": None, "brightness": None, "temp": None, "mode": None}

    if dev.get("dp_switch") is not None:
        result["on"] = bool(dps.get(str(dev["dp_switch"]), False))

    if dev.get("dp_brightness") is not None:
        dp = str(dev["dp_brightness"])
        meta = (dev.get("mapping") or {}).get(dp, {}).get("values", {})
        if dp in dps:
            result["brightness"] = _pct_from_dps(meta, int(dps[dp]))

    if dev.get("dp_ct") is not None:
        dp = str(dev["dp_ct"])
        meta = (dev.get("mapping") or {}).get(dp, {}).get("values", {})
        if dp in dps:
            result["temp"] = _pct_from_dps(meta, int(dps[dp]))

    dp_mode = _dp_for(dev, ("work_mode", "colour_mode", "mode"))
    if dp_mode is not None and str(dp_mode) in dps:
        result["mode"] = dps[str(dp_mode)]

    return result

# ---- brightness and temperature helpers ----
def light_brightness_step(name_or_id: str, delta_pct: int):
    dev = _resolve_device(name_or_id)
    dp = dev.get("dp_brightness")
    if dp is None:
        raise RuntimeError(f"No brightness DP for '{dev['name']}'")
    dps = _device_status(dev)
    dp_str = str(dp)
    meta = (dev.get("mapping") or {}).get(dp_str, {}).get("values", {})
    cur = _pct_from_dps(meta, int(dps.get(dp_str, _pct_to_dps(meta, 50))))
    new_pct = max(0, min(100, cur + int(delta_pct)))
    return _bulb(dev).set_value(dp, _pct_to_dps(meta, new_pct))

def light_temp_step(name_or_id: str, delta_pct: int):
    dev = _resolve_device(name_or_id)
    dp = dev.get("dp_ct")
    if dp is None:
        raise RuntimeError(f"No color temp DP for '{dev['name']}'")
    dps = _device_status(dev)
    dp_str = str(dp)
    meta = (dev.get("mapping") or {}).get(dp_str, {}).get("values", {})
    cur = _pct_from_dps(meta, int(dps.get(dp_str, _pct_to_dps(meta, 50))))
    new_pct = max(0, min(100, cur + int(delta_pct)))
    return _bulb(dev).set_value(dp, _pct_to_dps(meta, new_pct))

def light_temp_named(name_or_id: str, preset: str):
    presets = {
        "warm": 15, "warm white": 20, "soft white": 30,
        "neutral": 50, "daylight": 65,
        "cool": 80, "cool white": 85, "cold": 90,
        "white": 50
    }
    pct = presets.get((preset or "").lower())
    if pct is None:
        raise ValueError(f"Unknown preset '{preset}'")
    # switch to white mode if available
    dev = _resolve_device(name_or_id)
    b = _bulb(dev)
    dp_mode = _dp_for(dev, ("work_mode", "colour_mode", "mode"))
    try:
        if dp_mode is not None:
            b.set_value(dp_mode, "white")
    except Exception:
        pass
    return light_temp(name_or_id, pct)

# ---- color (RGB) ----

def light_color(name_or_id: str, color: Any):
    dev = _resolve_device(name_or_id)
    b = _bulb(dev)
    light_set(name_or_id, True)

    # white family = use white mode + temperature, not RGB
    if isinstance(color, str) and color.strip().lower() in {"white", "warm white", "cool white"}:
        return light_temp_named(name_or_id, color.strip().lower())

    # ensure 'colour' work mode before writing HSV
    dp_mode = _dp_for(dev, ("work_mode", "colour_mode", "mode"))
    if dp_mode is not None:
        try:
            b.set_value(dp_mode, "colour")
            time.sleep(0.12)  # small delay so the next DP write takes
        except Exception:
            pass

    named = {
        "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
        "yellow": (255, 255, 0), "purple": (128, 0, 128),
        "pink": (255, 105, 180), "orange": (255, 165, 0), "cyan": (0, 255, 255),
        "magenta": (255, 0, 255), "turquoise": (64, 224, 208)
    }

    def parse_color(c: Any) -> Tuple[int, int, int]:
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
            r, g, b_ = (int(c[0]), int(c[1]), int(c[2]))
            return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b_))
        raise ValueError(f"Unsupported color '{c}'")

    r, g, b_ = parse_color(color)

    # convert to HSV once
    import colorsys
    h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b_/255.0)
    H = int(round(h * 360))

    # Select correct DP and scale. v2 uses 0–1000, legacy uses 0–255.
    dp_v2 = _dp_for(dev, ("colour_data_v2", "color_data_v2"))
    dp_v1 = _dp_for(dev, ("colour_data", "color_data"))

    if dp_v2 is not None:
        S = 1000
        V = 1000
        payload = f"{H:04x}{S:04x}{V:04x}"
        return b.set_value(dp_v2, payload)

    if dp_v1 is not None:
        S = 255
        V = 255
        payload = f"{H:04x}{S:04x}{V:04x}"
        return b.set_value(dp_v1, payload)

    # last resort: library helper
    return b.set_colour(r, g, b_)


# ---- convenience wrappers ----
def lights_set(names_or_ids: list[str], on: bool):
    results = []
    for n in names_or_ids:
        try:
            results.append((n, bool(on), light_set(n, on)))
        except Exception as e:
            results.append((n, bool(on), f"Error: {e}"))
    return results

def lights_brightness(names_or_ids: list[str], level: int):
    results = []
    for n in names_or_ids:
        try:
            results.append((n, int(level), light_brightness(n, level)))
        except Exception as e:
            results.append((n, int(level), f"Error: {e}"))
    return results

def list_devices() -> Dict[str, Dict[str, Any]]:
    return {k: v.copy() for k, v in _BY_NAME.items()}
