import os, sys, json, time
from pathlib import Path
import threading

import numpy as np
import cv2
import onnxruntime as ort
from insightface.app import FaceAnalysis
from insightface.utils import face_align

BASE = Path(__file__).resolve().parents[0]
MODELS = BASE / "models"

def load_people():
    people = {}
    for pdir in MODELS.iterdir():
        if not pdir.is_dir():
            continue
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
    print("No trained people found in models/<person>/.")
    sys.exit(1)
print("Loaded:", ", ".join(PEOPLE.keys()))

# Always use CPU for inference
app = FaceAnalysis(name="buffalo_l")
app.prepare(ctx_id=-1, det_size=(640, 640))
print("Using CPU for recognition.")

def classify_embedding(emb):
    emb = emb.astype("float32")
    emb /= (np.linalg.norm(emb) + 1e-9)
    best_name, best_sim = None, -1.0
    for name, d in PEOPLE.items():
        s = float(np.dot(emb, d["centroid"]))
        if s > best_sim:
            best_sim, best_name = s, name
    if best_sim >= PEOPLE[best_name]["thresh"]:
        return best_name, best_sim
    return "unknown", best_sim

def score_frame(frame):
    outs = []
    for f in app.get(frame):
        try:
            _ = face_align.norm_crop(frame, landmark=f.kps, image_size=112)
        except Exception:
            continue
        label, sim = classify_embedding(f.embedding)
        outs.append((label, sim))
    return outs

class FaceRecognitionThread(threading.Thread):
    def __init__(self, result_list, poll_delay=0.05):
        super().__init__(daemon=True)
        self.result_list = result_list
        self.poll_delay = poll_delay
        self._stop_flag = threading.Event()

    def run(self):
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("No camera found.")
            return
        while not self._stop_flag.is_set():
            ok, frame = cap.read()
            if not ok:
                break
            outs = score_frame(frame)
            if outs:
                self.result_list.clear()
                self.result_list.extend(outs)
            time.sleep(self.poll_delay)
        cap.release()

    def stop(self):
        self._stop_flag.set()
