import os
import cv2
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

EVERY_N_FRAMES = 2
RESIZE_TO = None

folder_path = Path(__file__).resolve().parent / ".." / "training_data"
video_exts = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm"}

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def process_video(vpath: Path):
    outdir = vpath.parent
    ensure_dir(outdir)

    cap = cv2.VideoCapture(str(vpath))
    if not cap.isOpened():
        return f"[skip] cannot open: {vpath.name}"

    frame_idx, saved = 0, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % EVERY_N_FRAMES == 0:
            if RESIZE_TO:
                frame = cv2.resize(frame, RESIZE_TO, interpolation=cv2.INTER_AREA)
            out = outdir / f"{vpath.stem}_f{frame_idx:06d}.png"
            cv2.imwrite(str(out), frame)
            saved += 1
        frame_idx += 1

    cap.release()

    try:
        os.remove(vpath)
        return f"[ok] {vpath.name}: saved {saved} frames (deleted video)"
    except Exception as e:
        return f"Error deleting {vpath.name}: {e}"

# Collect all videos
videos = [Path(root) / f for root, _, files in os.walk(folder_path)
          for f in files if Path(f).suffix.lower() in video_exts]

if not videos:
    print("No videos found.")
else:
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = {executor.submit(process_video, v): v for v in videos}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing videos"):
            print(future.result())

print("Done.")
