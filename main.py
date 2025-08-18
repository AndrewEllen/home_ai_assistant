import configparser, os, sys, runpy
from pathlib import Path

def load_mode(p: Path) -> bool:
    c = configparser.ConfigParser(); c.read(p)
    return c.getboolean("mode", "server", fallback=False)

def main():
    root = Path(__file__).resolve().parent
    cfg = root / "server_client.cfg"
    if not cfg.exists(): sys.exit("server_client.cfg missing")

    is_server = load_mode(cfg)
    target = root / "src" / ("server" if is_server else "client") / "main.py"
    print("Starting As " + ("Server" if is_server else "Client"))
    if not target.exists(): sys.exit(f"Target script not found: {target}")

    # make `import detect_command` work
    sys.path.insert(0, str(target.parent))
    os.chdir(root)
    runpy.run_path(str(target), run_name="__main__")

if __name__ == "__main__":
    main()
