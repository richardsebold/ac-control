import threading

import cv2
import numpy as np
import onnxruntime as ort

from watch_core import BASE, PERSON, VEHICLE, Det

MODEL_PATH = BASE / "models" / "yolo11n.onnx"
SIZE = 640
CONF = 0.35
NMS_IOU = 0.5
# why: ids do COCO que o YOLO pré-treinado devolve; só estes interessam para o vigia
KIND_OF = {0: PERSON, 2: VEHICLE, 3: VEHICLE, 5: VEHICLE, 7: VEHICLE}
CLASS_IDS = sorted(KIND_OF)


class Detector:
    def __init__(self, path=MODEL_PATH):
        have = ort.get_available_providers()
        for providers in (["DmlExecutionProvider", "CPUExecutionProvider"], ["CPUExecutionProvider"]):
            providers = [p for p in providers if p in have]
            try:
                self.session = ort.InferenceSession(str(path), providers=providers)
                break
            except Exception:
                # why: DirectML falha em alguns drivers só na criação da sessão; a CPU dá conta do ritmo baixo
                if providers == ["CPUExecutionProvider"]:
                    raise
        self.provider = self.session.get_providers()[0]
        self.input = self.session.get_inputs()[0].name
        # invariant: o DirectML não aceita dois Run simultâneos na mesma sessão (crash nativo que derruba o app)
        self._run_lock = threading.Lock()

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        scale = SIZE / max(h, w)
        nw, nh = round(w * scale), round(h * scale)
        canvas = np.full((SIZE, SIZE, 3), 114, np.uint8)
        top, left = (SIZE - nh) // 2, (SIZE - nw) // 2
        canvas[top:top + nh, left:left + nw] = cv2.resize(bgr, (nw, nh))
        blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        with self._run_lock:
            out = self.session.run(None, {self.input: blob})[0][0].T  # (N, 4 + classes)
        scores = out[:, 4:][:, CLASS_IDS]
        best = scores.argmax(1)
        conf = scores[np.arange(len(scores)), best]
        keep = conf >= CONF
        if not keep.any():
            return []
        cx, cy, bw, bh = out[keep, 0], out[keep, 1], out[keep, 2], out[keep, 3]
        conf, best = conf[keep], best[keep]
        boxes = np.stack([cx - bw / 2, cy - bh / 2, bw, bh], 1)
        idx = cv2.dnn.NMSBoxes(boxes.tolist(), conf.tolist(), CONF, NMS_IOU)
        dets = []
        for i in np.array(idx).flatten():
            x, y, bw_, bh_ = boxes[i]
            x1, y1 = (x - left) / scale / w, (y - top) / scale / h
            x2, y2 = (x + bw_ - left) / scale / w, (y + bh_ - top) / scale / h
            box = tuple(float(min(1.0, max(0.0, v))) for v in (x1, y1, x2, y2))
            if box[2] > box[0] and box[3] > box[1]:
                dets.append(Det(box, KIND_OF[CLASS_IDS[best[i]]], float(conf[i])))
        return dets
