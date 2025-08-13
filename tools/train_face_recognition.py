import os, sys
from pathlib import Path

_nv = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
_bins = ["cudnn/bin","cublas/bin","cusolver/bin","cusparse/bin","cuda_runtime/bin","cuda_nvrtc/bin"]
os.environ["PATH"] = ";".join(str(_nv / sub) for sub in _bins if (_nv / sub).exists()) + ";" + os.environ["PATH"]

import json
import onnxruntime as ort
import numpy as np, cv2
from tqdm import tqdm
from sklearn.cluster import DBSCAN
from concurrent.futures import ThreadPoolExecutor
import insightface
from insightface.app import FaceAnalysis
from insightface.utils import face_align

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <person_folder>")
    sys.exit(1)

person_name = sys.argv[1]
THIS = Path(__file__).resolve()
BASE = THIS.parents[1]
SRC_DIR = BASE / "training_data" / person_name
PERSON_DIR = BASE / "models" / person_name
CROPS_DIR = PERSON_DIR / f"{person_name}_crops"
PERSON_DIR.mkdir(parents=True, exist_ok=True)
CROPS_DIR.mkdir(parents=True, exist_ok=True)

app = FaceAnalysis(name="buffalo_l")
ctx_id = 0 if 'CUDAExecutionProvider' in ort.get_available_providers() else -1
app.prepare(ctx_id=ctx_id, det_size=(640, 640))
print(f"Using {'GPU' if ctx_id == 0 else 'CPU'} for inference.")

def iter_images(folder: Path):
    exts = {".jpg",".jpeg",".png",".webp",".bmp"}
    for fp in folder.rglob("*"):
        if fp.suffix.lower() in exts:
            yield fp

def process_image(fp: Path):
    img = cv2.imread(str(fp))
    if img is None:
        return []
    faces = app.get(img)
    out = []
    for i, f in enumerate(faces):
        try:
            crop = face_align.norm_crop(img, landmark=f.kps, image_size=112)
        except Exception:
            x1,y1,x2,y2 = map(int, f.bbox)
            x1,y1 = max(0,x1), max(0,y1)
            crop = img[y1:y2, x1:x2]
            if crop.size == 0:
                continue
        emb = f.embedding
        if emb is None or len(emb) == 0:
            continue
        emb = emb.astype("float32")
        emb /= np.linalg.norm(emb)
        crop_path = CROPS_DIR / f"{fp.stem}_face{i}.jpg"
        cv2.imwrite(str(crop_path), crop)
        out.append((emb, str(fp), str(crop_path)))
    return out

files = list(iter_images(SRC_DIR))
embs, crops_info = [], []
print(f"[1/3] Scanning images in: {SRC_DIR}")

with ThreadPoolExecutor(max_workers=os.cpu_count()) as ex:
    for res in tqdm(ex.map(process_image, files), total=len(files)):
        for emb, src, crop in res:
            embs.append(emb); crops_info.append((src, crop))

embs = np.vstack(embs) if embs else np.empty((0,512), dtype="float32")
if embs.shape[0] == 0:
    print("No faces found.")
    sys.exit(1)

print(f"[2/3] Clustering to isolate {person_name} (largest cluster)…")
clu = DBSCAN(eps=0.35, min_samples=5, metric="cosine").fit(embs)
labels = clu.labels_
unique, counts = np.unique(labels, return_counts=True)
clusters_no_noise = {int(k): int(v) for k, v in zip(unique, counts) if k != -1}
if not clusters_no_noise:
    target_label = 0
    labels = np.zeros(len(embs), dtype=int)
    print("No dense cluster found; assuming all faces are target.")
else:
    target_label = max(clusters_no_noise, key=clusters_no_noise.get)

mask = (labels == target_label)
X_me = embs[mask]
kept, dropped = int(mask.sum()), int((~mask).sum())
print(f"Kept {kept} crops; dropped {dropped} others/noise.")

me_centroid = X_me.mean(axis=0); me_centroid /= np.linalg.norm(me_centroid)

np.save(PERSON_DIR / f"{person_name}_centroid.npy", me_centroid)
np.savez(PERSON_DIR / f"{person_name}_gallery.npz",
         X=X_me, crop_paths=np.array([c[1] for i, c in enumerate(crops_info) if mask[i]]))

sims = (X_me @ me_centroid.T).astype("float32")
thresh = float(np.percentile(sims, 5)) if len(sims) >= 20 else 0.40

summary = {
    "person": person_name,
    "num_images_scanned": len(files),
    "num_face_crops_total": int(len(embs)),
    "num_target_crops": kept,
    "num_non_target_crops": dropped,
    "suggested_threshold": round(thresh, 3),
    "centroid_path": str((PERSON_DIR / f"{person_name}_centroid.npy").resolve()),
    "gallery_path": str((PERSON_DIR / f"{person_name}_gallery.npz").resolve()),
    "crops_dir": str(CROPS_DIR.resolve())
}
with open(PERSON_DIR / f"{person_name}_prepare_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print("[3/3] Saved:")
print(json.dumps(summary, indent=2))
