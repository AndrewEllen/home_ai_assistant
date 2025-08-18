import os, requests
from dotenv import load_dotenv
from typing import Optional, Tuple

load_dotenv()
OWM_KEY = os.getenv("OPENWEATHER_API_KEY")

def _ip_loc() -> Tuple[float, float, str]:
    r = requests.get("http://ip-api.com/json/", timeout=5)
    j = r.json()
    return float(j["lat"]), float(j["lon"]), f'{j.get("city","")}, {j.get("countryCode","")}'.strip(", ")

def _geocode_city(q: str) -> Optional[Tuple[float, float, str]]:
    r = requests.get(
        "https://api.openweathermap.org/geo/1.0/direct",
        params={"q": q, "limit": 1, "appid": OWM_KEY},
        timeout=8,
    )
    a = r.json()
    if not a:
        return None
    it = a[0]
    name = it.get("name","")
    cc = it.get("country","")
    st = it.get("state")
    label = ", ".join([x for x in [name, st, cc] if x])
    return float(it["lat"]), float(it["lon"]), label


# --- add/replace helpers ---

def _speakable_place(label: str) -> str:
    parts = [p.strip() for p in label.split(",") if p.strip()]
    omit = {"gb", "great britain", "united kingdom", "scotland", "england", "wales", "northern ireland"}
    parts = [p for p in parts if p.lower() not in omit]
    return ", ".join(p.title() for p in parts) if parts else "your area"

def _humidity_label(h: Optional[float]) -> Optional[str]:
    if h is None: return None
    if h < 30: return "low humidity"
    if h < 60: return "moderate humidity"
    if h < 80: return "high humidity"
    return "very high humidity"

def _wind_label(ms: Optional[float]) -> Optional[str]:
    if ms is None: return None
    if ms < 0.5: return "calm air"
    if ms < 1.5: return "light air"
    if ms < 3.3: return "a light breeze"
    if ms < 5.5: return "a gentle breeze"
    if ms < 7.9: return "a moderate breeze"
    if ms < 10.7: return "a fresh breeze"
    if ms < 13.8: return "a strong breeze"
    if ms < 17.1: return "near gale winds"
    if ms < 20.7: return "gale force winds"
    return "storm force winds"

def _wind_dir_words(deg: Optional[float]) -> Optional[str]:
    if deg is None: return None
    names = ["north","north northeast","northeast","east northeast","east","east southeast",
             "southeast","south southeast","south","south southwest","southwest","west southwest",
             "west","west northwest","northwest","north northwest"]
    idx = int((deg % 360) / 22.5 + 0.5) % 16
    return names[idx]

def _clouds_label(pct: Optional[float]) -> Optional[str]:
    if pct is None: return None
    pct = float(pct)
    if pct <= 5: return "clear skies"
    if pct <= 25: return "mostly clear skies"
    if pct <= 50: return "scattered clouds"
    if pct <= 84: return "mostly cloudy skies"
    return "overcast skies"

def _precip_phrase(kind: str, mm1h: Optional[float], mm3h: Optional[float]) -> Optional[str]:
    amt = mm1h if mm1h is not None else mm3h
    if amt is None: return None
    if amt < 0.2: level = f"a few { 'drops' if kind=='rain' else 'flurries' }"
    elif amt < 1: level = f"light {kind}"
    elif amt < 3: level = f"moderate {kind}"
    else: level = f"heavy {kind}"
    if mm1h is not None:
        return f"{level}, about {mm1h:.1f} millimetres in the last hour"
    return f"{level}, about {mm3h:.1f} millimetres in the last three hours"

def _visibility_label(meters: Optional[float]) -> Optional[str]:
    if meters is None: return None
    km = meters / 1000.0
    if km >= 10: return None
    if km >= 5: return "good visibility"
    if km >= 2: return "reduced visibility"
    if km >= 1: return "poor visibility"
    return "very poor visibility"

def get_weather(place: Optional[str], mode: str = "speak") -> str:
    if not OWM_KEY:
        return "Weather error: OPENWEATHER_API_KEY not set."

    if place:
        geo = _geocode_city(place)
        if not geo:
            return f"No results for '{place}'."
        lat, lon, label = geo
    else:
        lat, lon, label = _ip_loc()

    r = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={"lat": lat, "lon": lon, "units": "metric", "appid": OWM_KEY},
        timeout=8,
    )
    w = r.json()
    if r.status_code != 200:
        return f"Weather error: {w.get('message','unknown')}"

    main = w.get("main", {})
    wind = w.get("wind", {})
    wx = (w.get("weather") or [{}])[0]
    clouds = w.get("clouds", {})
    rain = w.get("rain", {})
    snow = w.get("snow", {})

    temp = main.get("temp")
    feels = main.get("feels_like")
    hum = main.get("humidity")
    desc = (wx.get("description") or "").lower()
    spd = wind.get("speed")
    gust = wind.get("gust")
    wdir_words = _wind_dir_words(wind.get("deg"))
    cloud_pct = clouds.get("all")
    vis = w.get("visibility")

    place_label = _speakable_place(label or w.get("name", "your area"))

    if mode == "compact":
        # still available for screens or logs
        parts = [place_label]
        if temp is not None: parts.append(f"{temp:.0f} C")
        if feels is not None: parts.append(f"feels {feels:.0f} C")
        if hum is not None: parts.append(f"humidity {hum}%")
        if spd is not None: parts.append(f"wind {spd} metres per second")
        if cloud_pct is not None: parts.append(f"clouds {int(cloud_pct)}%")
        if desc: parts.append(desc.capitalize())
        return " | ".join(parts)

    hum_text = _humidity_label(hum)
    wind_text = _wind_label(spd)
    cloud_text = _clouds_label(cloud_pct)
    vis_text = _visibility_label(vis)
    rain_text = _precip_phrase("rain", rain.get("1h"), rain.get("3h"))
    snow_text = _precip_phrase("snow", snow.get("1h"), snow.get("3h"))

    # Sentence 1: temp and place
    if temp is not None:
        out = [f"It is {temp:.0f} degrees Celsius in {place_label}"]
    else:
        out = [f"In {place_label}"]

    # Conditions
    # Prefer API description; fall back to computed clouds
    if desc:
        out.append(f"with {desc}")
        if cloud_text and cloud_pct and cloud_pct >= 85 and "overcast" not in desc:
            out.append(f"({cloud_text})")
    elif cloud_text:
        out.append(f"with {cloud_text}")

    if rain_text:
        out.append(f"and {rain_text}")
    if snow_text:
        joiner = "and" if rain_text else "with"
        out.append(f"{joiner} {snow_text}")

    if hum_text:
        out.append(f"and {hum_text}")

    if wind_text:
        if wdir_words:
            out.append(f"and {wind_text} from the {wdir_words}")
        else:
            out.append(f"and {wind_text}")
        if gust:
            out.append(f"with gusts up to {gust:.1f} metres per second")

    if vis_text:
        out.append(f"and {vis_text}")

    sentence = " ".join(out).replace("  ", " ").strip()
    if not sentence.endswith("."):
        sentence += "."

    # Optional feels-like second sentence
    if temp is not None and feels is not None and abs(feels - temp) >= 2:
        sentence += f" It feels like {feels:.0f} degrees Celsius."

    return sentence