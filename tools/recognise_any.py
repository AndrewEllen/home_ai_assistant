import os, sys, json, time
from pathlib import Path

# NVIDIA DLLs from venv (Windows)
_nv = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
_bins = ["cudnn/bin","cublas/bin","cusolver/bin","cusparse/bin","cuda_runtime/bin","cuda_nvrtc/bin"]
os.environ["PATH"] = ";".join(str(_nv / s) for s in _bins if (_nv / s).exists()) + ";" + os.environ["PATH"]

import numpy as np, cv2, onnxruntime as ort
from insightface.app import FaceAnalysis
from insightface.utils import face_align

BASE = Path(__file__).resolve().parents[1]
MODELS = BASE / "models"

def load_people():
    people = {}
    for pdir in MODELS.iterdir():
        if not pdir.is_dir(): continue
        name = pdir.name
        cnp = pdir / f"{name}_centroid.npy"
        jsn = pdir / f"{name}_prepare_summary.json"
        if cnp.exists() and jsn.exists():
            centroid = np.load(cnp).astype("float32")
            centroid /= (np.linalg.norm(centroid) + 1e-9)
            with open(jsn) as f:
                th = float(json.load(f).get("suggested_threshold", 0.40))
            people[name] = {"centroid": centroid, "thresh": th}
    return people

PEOPLE = load_people()
if not PEOPLE:
    print("No trained people found in models/<person>/."); sys.exit(1)
print("Loaded:", ", ".join(PEOPLE.keys()))

app = FaceAnalysis(name="buffalo_l")
ctx_id = 0 if 'CUDAExecutionProvider' in ort.get_available_providers() else -1
app.prepare(ctx_id=ctx_id, det_size=(640, 640))
print(f"Using {'GPU' if ctx_id==0 else 'CPU'}")

def classify_embedding(emb):
    emb = emb.astype("float32"); emb /= (np.linalg.norm(emb) + 1e-9)
    best_name, best_sim = None, -1.0
    for name, d in PEOPLE.items():
        s = float(np.dot(emb, d["centroid"]))
        if s > best_sim:
            best_sim, best_name = s, name
    # person-specific threshold
    if best_sim >= PEOPLE[best_name]["thresh"]:
        return best_name, best_sim
    return "unknown", best_sim

def score_frame(frame):
    outs = []
    for f in app.get(frame):
        try:
            crop = face_align.norm_crop(frame, landmark=f.kps, image_size=112)
        except Exception:
            continue
        label, sim = classify_embedding(f.embedding)
        x1,y1,x2,y2 = map(int, f.bbox)
        outs.append((label, sim, (x1,y1,x2,y2)))
    return outs

def draw_and_show(frame, outs, win="Recognition"):
    for lab, sim, (x1,y1,x2,y2) in outs:
        ok = lab != "unknown"
        col = (0,255,0) if ok else (0,0,255)
        txt = f"{lab} {sim:.2f}"
        cv2.rectangle(frame,(x1,y1),(x2,y2),col,2)
        cv2.putText(frame,txt,(x1,max(0,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,0.7,col,2)
    cv2.imshow(win, frame)

def test_camera():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened(): print("No camera."); return
    while True:
        ok, frame = cap.read()
        if not ok: break
        outs = score_frame(frame)
        draw_and_show(frame, outs, "ESC to quit")
        if cv2.waitKey(1) & 0xFF == 27: break
    cap.release(); cv2.destroyAllWindows()

def test_folder(folder):
    folder = Path(folder)
    outdir = MODELS / "_runs" / time.strftime("%Y%m%d_%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)
    exts = {".jpg",".jpeg",".png",".webp",".bmp"}
    files = [p for p in folder.rglob("*") if p.suffix.lower() in exts]
    for p in files:
        img = cv2.imread(str(p))
        if img is None: continue
        outs = score_frame(img)
        for lab, sim, (x1,y1,x2,y2) in outs:
            col = (0,255,0) if lab!="unknown" else (0,0,255)
            txt = f"{lab} {sim:.2f}"
            cv2.rectangle(img,(x1,y1),(x2,y2),col,2)
            cv2.putText(img,txt,(x1,max(0,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,0.7,col,2)
        cv2.imwrite(str(outdir / p.name), img)
    print(f"Annotated outputs → {outdir}")

ans = input("Use camera? [y/n]: ").strip().lower()
if ans in ("y","yes"):
    test_camera()
else:
    folder = input("Folder path to test: ").strip().strip('"')
    test_folder(folder)
