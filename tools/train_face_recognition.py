# --- make NVIDIA DLLs discoverable from venv ---
import os, sys
from pathlib import Path

# Path to NVIDIA runtime DLL folders in venv
_nv = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
_bins = [
    "cudnn/bin",
    "cublas/bin",
    "cusolver/bin",
    "cusparse/bin",
    "cuda_runtime/bin",
    "cuda_nvrtc/bin"  # sometimes needed for TensorRT/ONNX
]
# Prepend all existing NVIDIA bin paths to PATH
os.environ["PATH"] = ";".join(str(_nv / sub) for sub in _bins if (_nv / sub).exists()) + ";" + os.environ["PATH"]
# ------------------------------------------------

import glob, json, shutil
import onnxruntime as ort
import numpy as np, cv2
from tqdm import tqdm
from sklearn.cluster import DBSCAN

import insightface
from insightface.app import FaceAnalysis
from insightface.utils import face_align

# --- Paths ---
THIS = Path(__file__).resolve()
BASE = THIS.parents[1]                         # home_ai_assistant/
SRC_DIR = BASE / "training_data" / "andrew"    # your images (solo + groups allowed)
MODELS_DIR = BASE / "models"
CROPS_DIR = MODELS_DIR / "andrew_crops"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
CROPS_DIR.mkdir(parents=True, exist_ok=True)

# --- Face model ---
app = FaceAnalysis(name="buffalo_l")
providers = ort.get_available_providers()
ctx_id = 0 if 'CUDAExecutionProvider' in providers else -1
app.prepare(ctx_id=ctx_id, det_size=(640, 640))
print(f"Using {'GPU' if ctx_id == 0 else 'CPU'} for inference.")

def iter_images(folder: Path):
    exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    for fp in folder.rglob("*"):
        if fp.suffix.lower() in exts:
            yield fp

embs, crops_info = [], []   # embeddings and (src_path, crop_path)

print(f"[1/3] Scanning images in: {SRC_DIR}")
for fp in tqdm(list(iter_images(SRC_DIR))):
    img = cv2.imread(str(fp))
    if img is None:
        continue
    faces = app.get(img)
    for i, f in enumerate(faces):
        # aligned crop using 5-point landmarks
        try:
            crop = face_align.norm_crop(img, landmark=f.kps, image_size=112)
        except Exception:
            # fallback to simple bbox crop if landmarks missing
            x1, y1, x2, y2 = map(int, f.bbox)
            x1, y1 = max(0, x1), max(0, y1)
            crop = img[y1:y2, x1:x2]
            if crop.size == 0:
                continue

        emb = f.embedding
        if emb is None or len(emb) == 0:
            continue

        emb = emb.astype("float32")
        emb = emb / np.linalg.norm(emb)
        embs.append(emb)
        crop_name = f"{fp.stem}_face{i}.jpg"
        crop_path = CROPS_DIR / crop_name
        cv2.imwrite(str(crop_path), crop)
        crops_info.append((str(fp), str(crop_path)))

embs = np.vstack(embs) if embs else np.empty((0, 512), dtype="float32")
if embs.shape[0] == 0:
    print("No faces found. Check your source folder.")
    sys.exit(1)

print(f"[2/3] Clustering to isolate YOU (largest cluster)…")
# DBSCAN on cosine distance (embeddings are L2-normalized)
clu = DBSCAN(eps=0.35, min_samples=5, metric="cosine").fit(embs)
labels = clu.labels_
# Choose largest non-noise cluster
unique, counts = np.unique(labels, return_counts=True)
clusters = {int(k): int(v) for k, v in zip(unique, counts)}
clusters_no_noise = {k: v for k, v in clusters.items() if k != -1}
if not clusters_no_noise:
    # fallback: assume all are you
    target_label = 0
    labels = np.zeros(len(embs), dtype=int)
    print("No dense cluster found; proceeding with all faces as a single identity.")
else:
    target_label = max(clusters_no_noise, key=clusters_no_noise.get)

mask_me = (labels == target_label)
X_me = embs[mask_me]
kept = int(mask_me.sum())
dropped = int((~mask_me).sum())
print(f"Kept {kept} crops as YOU; dropped {dropped} as others/noise.")

# Compute centroid for "is_me" scoring
me_centroid = X_me.mean(axis=0)
me_centroid = me_centroid / np.linalg.norm(me_centroid)

# Save artifacts
np.save(MODELS_DIR / "me_centroid.npy", me_centroid)
np.savez(MODELS_DIR / "andrew_gallery.npz",
         X=X_me, crop_paths=np.array([c[1] for i, c in enumerate(crops_info) if mask_me[i]]))

# Quick threshold suggestion from similarity distribution
sims = (X_me @ me_centroid.T).astype("float32")

# conservative starting threshold ~ 5th percentile of your-true sims
thresh = float(np.percentile(sims, 5)) if len(sims) >= 20 else 0.40
summary = {
    "num_images_scanned": len(list(iter_images(SRC_DIR))),
    "num_face_crops_total": int(len(embs)),
    "num_me_crops": kept,
    "num_non_me_crops": dropped,
    "suggested_threshold": round(thresh, 3),
    "centroid_path": str((MODELS_DIR / "me_centroid.npy").resolve()),
    "gallery_path": str((MODELS_DIR / "andrew_gallery.npz").resolve()),
    "crops_dir": str(CROPS_DIR.resolve())
}
with open(MODELS_DIR / "prepare_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print("[3/3] Saved:")
print(json.dumps(summary, indent=2))
