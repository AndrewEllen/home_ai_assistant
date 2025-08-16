import os, re, subprocess
from pathlib import Path
from difflib import SequenceMatcher
from typing import Dict, Tuple, List, Optional

# ---------- existing pieces (root + libraries + manifests) ----------
def _steam_root_candidates():
    try:
        import winreg
        for hive, subkey in [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        ]:
            try:
                with winreg.OpenKey(hive, subkey) as k:
                    val, _ = winreg.QueryValueEx(k, "SteamPath")
                    if val:
                        yield Path(val)
            except OSError:
                pass
    except ImportError:
        pass
    for p in [
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
        Path(os.getenv("PROGRAMFILES(X86)", "")) / "Steam",
        Path(os.getenv("PROGRAMFILES", "")) / "Steam",
    ]:
        if p.exists():
            yield p

def _parse_libraryfolders(steam_root: Path) -> List[Path]:
    libs = {steam_root}
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        t = vdf.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'"\d+"\s*\{[^}]*?"path"\s*"([^"]+)"', t, re.DOTALL | re.IGNORECASE):
            libs.add(Path(m.group(1)))
        if len(libs) == 1:
            for m in re.finditer(r'"\d+"\s*"([^"]+)"', t):
                libs.add(Path(m.group(1)))
    return [p for p in libs if p.exists()]

def _scan_manifests(steamapps_dir: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    pat = re.compile(r'"([^"]+)"\s+"([^"]+)"')
    for acf in steamapps_dir.glob("appmanifest_*.acf"):
        data = acf.read_text(encoding="utf-8", errors="ignore")
        appid = name = None
        for k, v in pat.findall(data):
            if k == "appid": appid = v
            elif k == "name": name = v
        if appid and name:
            out[appid] = name
    return out

def get_all_installed_steam_games() -> Dict[str, str]:
    roots = list(_steam_root_candidates())
    if not roots:
        raise FileNotFoundError("Steam root not found.")
    steam_root = roots[0]
    libs = set(_parse_libraryfolders(steam_root))
    for drive in map(lambda d: f"{d}:\\", "CDEFGHIJKLMNOPQRSTUVWXYZ"):
        p = Path(drive) / "SteamLibrary"
        if (p / "steamapps").exists():
            libs.add(p)
    games: Dict[str, str] = {}
    for lib in libs:
        sp = lib / "steamapps"
        if sp.exists():
            games.update(_scan_manifests(sp))
    return games

# ---------- search helpers ----------
_strip_words = {"the","and","edition","definitive","remastered","game","of","to","for","ii","iii","iv","v","vi","vii","online","special","enhanced","ultimate"}

def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[®™©]", "", s)
    s = re.sub(r"[-_:,.()'\\[\\]]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _acronym(s: str) -> str:
    toks = [w for w in re.split(r"\s+", _norm(s)) if w and w not in _strip_words]
    return "".join(w[0] for w in toks)

def _token_set_ratio(a: str, b: str) -> float:
    A = set(_norm(a).split())
    B = set(_norm(b).split())
    if not A or not B:
        return 0.0
    inter = len(A & B)
    union = len(A | B)
    jaccard = inter / union
    sm = SequenceMatcher(None, _norm(a), _norm(b)).ratio()
    return 0.6 * jaccard + 0.4 * sm

def _find_appid_contains(appid_to_name: Dict[str, str], *substrs: str) -> Optional[str]:
    """Return appid whose normalized name contains all substrings."""
    subs = [s for s in (_norm(x) for x in substrs) if s]
    for appid, name in appid_to_name.items():
        n = _norm(name)
        if all(s in n for s in subs):
            return appid
    return None

def build_alias_index(appid_to_name: Dict[str, str]) -> Dict[str, str]:
    """
    Returns alias->appid. Includes:
    - normalized full names
    - acronyms (e.g., 'csgo')
    - manual aliases bound to installed targets when possible
    """
    alias: Dict[str, str] = {}

    # First pass: generate aliases from actual installed names
    name_index: Dict[str, str] = {}  # norm_name -> appid
    for appid, name in appid_to_name.items():
        n = _norm(name)
        name_index[n] = appid
        alias[n] = appid
        ac = _acronym(name)
        if len(ac) >= 2:
            alias[ac] = appid
        # Remove edition fluff
        base = re.sub(r"\b(remastered|definitive|enhanced|special|ultimate)\b", "", n)
        base = re.sub(r"\s+", " ", base).strip()
        if base and base != n:
            alias[base] = appid

    # Deterministic bindings to installed titles when present
    def bind_group(installed_appid: Optional[str], names_fallback: List[List[str]], aliases: List[str]):
        target = None
        if installed_appid and installed_appid in appid_to_name:
            target = installed_appid
        else:
            # try fallbacks by name contains
            for pieces in names_fallback:
                candidate = _find_appid_contains(appid_to_name, *pieces)
                if candidate:
                    target = candidate
                    break
        if target:
            for a in aliases:
                alias[_norm(a)] = target

    # Groups
    bind_group(
        installed_appid="730",
        names_fallback=[["counter", "strike", "2"], ["counter", "strike"]],
        aliases=[
            "cs2","cs 2","counter strike 2","counter-strike 2",
            "csgo","cs:go","counter strike global offensive","counter-strike: global offensive","counter strike","counter-strike","cs",
            "counter-strike", "counter stroke", "counter-stroke"
        ],
    )
    bind_group(
        installed_appid="3240220",
        names_fallback=[["grand","theft","auto","v"],["gta","v"]],
        aliases=["gta v","gta5","gtav","gta","gta online"]
    )
    bind_group(
        installed_appid="570",
        names_fallback=[["dota","2"],["dota"]],
        aliases=["dota 2","dota2","dota"]
    )
    bind_group(
        installed_appid="252950",
        names_fallback=[["rocket","league"]],
        aliases=["rocket league","rl"]
    )
    bind_group(
        installed_appid="489830",
        names_fallback=[["skyrim","special","edition"],["the","elder","scrolls","v","skyrim"]],
        aliases=["skyrim se","skyrim special edition","skyrim"]
    )

    # Generic manual alias list that will be bound via fuzzy to best installed if still unbound
    manual_aliases = {
        "counter strike": None,
        "counter-strike": None,
        "playerunknowns battlegrounds": None,
        "pubg": None,
    }

    # Second pass: wire any remaining manual aliases to the best matching installed title
    for a in list(manual_aliases.keys()):
        na = _norm(a)
        if na in alias:
            continue
        best: Tuple[str, float] | None = None
        for appid, name in appid_to_name.items():
            score = _token_set_ratio(a, name)
            if not best or score > best[1]:
                best = (appid, score)
        if best and best[1] >= 0.55:
            alias[na] = best[0]

    return alias

def search_game(query: str, appid_to_name: Dict[str, str], alias_index: Dict[str, str], min_score: float = 0.58) -> Tuple[str, str, float] | None:
    """
    Returns (appid, display_name, score) or None.
    Tries exact alias hit, then fuzzy across names and aliases.
    """
    qn = _norm(query)

    # Exact alias hit
    if qn in alias_index:
        appid = alias_index[qn]
        return appid, appid_to_name[appid], 1.0

    # Try acronym quick path
    qa = _acronym(qn)
    if qa in alias_index:
        appid = alias_index[qa]
        return appid, appid_to_name[appid], 0.95

    # Fuzzy over names and aliases
    candidates: List[Tuple[str, str]] = []  # (appid, label)
    for appid, name in appid_to_name.items():
        candidates.append((appid, name))
    for al, appid in alias_index.items():
        candidates.append((appid, al))

    # Keep the best per appid
    best_per_app: Dict[str, float] = {}
    best_label: Dict[str, str] = {}
    for appid, label in candidates:
        score = _token_set_ratio(query, label)
        if score > best_per_app.get(appid, -1.0):
            best_per_app[appid] = score
            best_label[appid] = appid_to_name[appid]

    if not best_per_app:
        return None
    appid_best = max(best_per_app.items(), key=lambda x: x[1])[0]
    score_best = best_per_app[appid_best]
    if score_best >= min_score:
        return appid_best, best_label[appid_best], score_best
    return None

# ---------- launcher ----------
def launch_steam_game(appid: str):
    if os.name == "nt":
        os.startfile(f"steam://rungameid/{appid}")  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["steam", f"steam://rungameid/{appid}"])

def launch_game_by_name(query: str) -> str:
    games = get_all_installed_steam_games()
    aliases = build_alias_index(games)
    hit = search_game(query, games, aliases)
    if not hit:
        return False
    appid, name, _ = hit
    #launch_steam_game(appid)
    return f"Launching {name}"

# ---------- example ----------
if __name__ == "__main__":
    games = get_all_installed_steam_games()
    aliases = build_alias_index(games)

    print(f"Installed games: {len(games)}")
    print("Try: cs2, counter strike, dota, gta v, skyrim se")

    for q in ["csgo", "cs2", "counter strike global offensive", "gta v", "rl", "skyrim se", "command and conquer", "soundpad"]:
        hit = search_game(q, games, aliases)
        print(q, "->", hit)

    # launch example:
    # launch_game_by_name("cs2")
