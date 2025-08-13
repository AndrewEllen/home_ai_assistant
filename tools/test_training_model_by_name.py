import os, sys
from pathlib import Path

# NVIDIA DLLs (Windows, venv)
_nv = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
_bins = ["cudnn/bin","cublas/bin","cusolver/bin","cusparse/bin","cuda_runtime/bin","cuda_nvrtc/bin"]
os.environ["PATH"] = ";".join(str(_nv / s) for s in _bins if (_nv / s).exists()) + ";" + os.environ["PATH"]

import json
import numpy as np, cv2, onnxruntime as ort
from insightface.app import FaceAnalysis
from insightface.utils import face_align

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <person_folder_name>"); sys.exit(1)

person = sys.argv[1]
BASE = Path(__file__).resolve().parents[1]
PDIR = BASE / "models" / person
centroid = np.load(PDIR / f"{person}_centroid.npy")
with open(PDIR / f"{person}_prepare_summary.json") as f:
    thresh = json.load(f)["suggested_threshold"]

app = FaceAnalysis(name="buffalo_l")
ctx_id = 0 if 'CUDAExecutionProvider' in ort.get_available_providers() else -1
app.prepare(ctx_id=ctx_id, det_size=(640,640))
print(f"Using {'GPU' if ctx_id==0 else 'CPU'}; threshold={thresh:.3f}")

def score_frame(frame):
    outs = []
    for f in app.get(frame):
        try:
            crop = face_align.norm_crop(frame, landmark=f.kps, image_size=112)
        except Exception:
            continue
        emb = f.embedding.astype("float32"); emb /= np.linalg.norm(emb)
        s = float(np.dot(emb, centroid))
        x1,y1,x2,y2 = map(int, f.bbox)
        outs.append((s,(x1,y1,x2,y2)))
    return outs

def draw_and_show(frame, outs, label):
    for s,(x1,y1,x2,y2) in outs:
        ok = s >= thresh
        col = (0,255,0) if ok else (0,0,255)
        txt = f"{person} {s:.2f}" if ok else f"unknown {s:.2f}"
        cv2.rectangle(frame,(x1,y1),(x2,y2),col,2)
        cv2.putText(frame,txt,(x1,max(0,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,0.7,col,2)
    cv2.imshow(label, frame)

def test_camera():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened(): print("No camera."); return
    while True:
        ok, frame = cap.read()
        if not ok: break
        outs = score_frame(frame)
        draw_and_show(frame, outs, "Face Recognition - ESC to quit")
        if cv2.waitKey(1) & 0xFF == 27: break
    cap.release(); cv2.destroyAllWindows()

def test_folder(folder):
    folder = Path(folder)
    outdir = PDIR / f"{person}_tested"
    outdir.mkdir(parents=True, exist_ok=True)
    exts = {".jpg",".jpeg",".png",".webp",".bmp"}
    files = [p for p in folder.rglob("*") if p.suffix.lower() in exts]
    tp=fp=tn=fn=0
    for p in files:
        img = cv2.imread(str(p))
        if img is None: continue
        outs = score_frame(img)
        # basic metrics: if any face passes threshold => positive
        pred_pos = any(s>=thresh for s,_ in outs)
        # heuristic: treat images from this person's folder as positives, others as negatives
        is_pos = (person.lower() in p.parts[-2].lower()) or (person.lower() in p.stem.lower())
        if pred_pos and is_pos: tp+=1
        elif pred_pos and not is_pos: fp+=1
        elif (not pred_pos) and is_pos: fn+=1
        else: tn+=1
        for s,(x1,y1,x2,y2) in outs:
            col = (0,255,0) if s>=thresh else (0,0,255)
            txt = f"{person} {s:.2f}" if s>=thresh else f"unknown {s:.2f}"
            cv2.rectangle(img,(x1,y1),(x2,y2),col,2)
            cv2.putText(img,txt,(x1,max(0,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,0.7,col,2)
        cv2.imwrite(str(outdir / p.name), img)
    total = tp+fp+tn+fn
    if total:
        prec = tp/(tp+fp) if (tp+fp) else 0.0
        rec = tp/(tp+fn) if (tp+fn) else 0.0
        print(f"Tested {total} images → TP:{tp} FP:{fp} TN:{tn} FN:{fn} | precision:{prec:.3f} recall:{rec:.3f}")
        print(f"Annotated outputs: {outdir}")

ans = input("Use camera? [y/n]: ").strip().lower()
if ans in ("y","yes"):
    test_camera()
else:
    folder = input("Folder path to test: ").strip().strip('"')
    test_folder(folder)
